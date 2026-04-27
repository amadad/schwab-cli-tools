"""Token path and storage helpers for Schwab OAuth."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path

import httpx
from authlib.deprecate import AuthlibDeprecationWarning
from dotenv import load_dotenv

from src.core.errors import ConfigError
from src.core.json_types import JsonObject
from src.schwab_client.secure_files import (
    ensure_sensitive_dir,
    prepare_sensitive_file,
    restrict_sqlite_permissions,
    write_sensitive_json,
)

load_dotenv()
logger = logging.getLogger(__name__)

DATA_DIR_ENV = "SCHWAB_CLI_DATA_DIR"
TOKEN_PATH_ENV = "SCHWAB_TOKEN_PATH"
TOKEN_DB_FILENAME = "tokens.db"
TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 6.5
TOKEN_LOCK_TIMEOUT_SECONDS = 60.0
AUTH_RECOVERY_ERRORS = (ConfigError, OSError, sqlite3.Error, ValueError, TypeError, RuntimeError)
AUTH_PROBE_ERRORS = (*AUTH_RECOVERY_ERRORS, httpx.HTTPStatusError)


@contextmanager
def suppress_authlib_jose_warning() -> Iterator[None]:
    """Suppress third-party deprecation noise from lazy Schwab/Authlib imports."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="authlib.jose module is deprecated.*",
            category=AuthlibDeprecationWarning,
            module="authlib._joserfc_helpers",
        )
        warnings.filterwarnings(
            "ignore",
            message="websockets\\.legacy is deprecated.*",
            category=DeprecationWarning,
            module="websockets\\.legacy",
        )
        yield


@cache
def schwab_auth_module():
    """Lazy import of ``schwab.auth`` with deprecation warnings suppressed."""
    with suppress_authlib_jose_warning():
        from schwab import auth as schwab_auth
    return schwab_auth


def oauth_error_type() -> type[Exception]:
    """Return Authlib's OAuthError without surfacing Authlib's internal warning."""
    with suppress_authlib_jose_warning():
        from authlib.integrations.base_client.errors import OAuthError
    return OAuthError


def resolve_data_dir() -> Path:
    """Resolve the base data directory."""
    env_dir = os.getenv(DATA_DIR_ENV)
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".cli-schwab"


def resolve_token_path(
    token_path_env: str = TOKEN_PATH_ENV,
    token_filename: str = "schwab_token.json",
) -> Path:
    """Resolve a token path, with env var override."""
    env_path = os.getenv(token_path_env)
    if env_path:
        return Path(env_path).expanduser()
    return resolve_data_dir() / "tokens" / token_filename


def resolve_token_db_path(token_path: str | Path | None = None) -> Path:
    """Resolve the SQLite sidecar used for token metadata and locking."""
    if token_path is None:
        return resolve_data_dir() / "tokens" / TOKEN_DB_FILENAME
    return Path(token_path).expanduser().parent / TOKEN_DB_FILENAME


# Default token locations
DEFAULT_TOKEN_PATH = resolve_token_path()


def _parse_datetime_like(value: object) -> datetime | None:
    """Parse Schwab token timestamps stored as unix seconds or ISO strings."""
    if value is None:
        return None
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value)
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError, OSError):
        return None


def _derive_token_window(tokens: JsonObject) -> tuple[datetime, datetime] | None:
    """Return token creation and effective-expiry timestamps when available."""
    creation_time = _parse_datetime_like(tokens.get("creation_timestamp"))
    token_data = tokens.get("token", {})
    expires_at = token_data.get("expires_at") if isinstance(token_data, dict) else None
    access_expiry = _parse_datetime_like(expires_at)

    if access_expiry is not None:
        created = creation_time or (access_expiry - timedelta(minutes=30))
        has_refresh_token = (
            bool(token_data.get("refresh_token")) if isinstance(token_data, dict) else False
        )
        effective_expiry = created + timedelta(days=7) if has_refresh_token else access_expiry
        return created, effective_expiry

    if creation_time is not None:
        return creation_time, creation_time + timedelta(days=7)

    return None


def _build_token_info(
    *,
    created: datetime,
    expires: datetime,
    db_path: Path,
    warning: str | None = None,
    warning_level: str | None = None,
    cached: bool = False,
) -> JsonObject:
    """Build the standard token info payload from a token window."""
    now = datetime.now()
    time_remaining = expires - now
    hours_remaining = time_remaining.total_seconds() / 3600
    days_remaining = time_remaining.days if hours_remaining > 0 else 0

    computed_warning = warning
    computed_level = warning_level
    if computed_warning is None:
        if hours_remaining <= 0:
            computed_warning = "Token has EXPIRED. Run 'schwab-auth' to re-authenticate."
            computed_level = "critical"
        elif hours_remaining < 24:
            computed_warning = (
                f"Token expires in {hours_remaining:.1f} hours! Run 'schwab-auth' soon."
            )
            computed_level = "critical"
        elif hours_remaining < 48:
            computed_warning = (
                f"Token expires in {days_remaining} days. Consider re-authenticating."
            )
            computed_level = "warning"
        elif hours_remaining < 72:
            computed_warning = f"Token expires in {days_remaining} days."
            computed_level = "notice"

    return {
        "exists": True,
        "valid": hours_remaining > 0,
        "created": created.isoformat(),
        "expires": expires.isoformat(),
        "expires_in_days": days_remaining,
        "expires_in_hours": round(hours_remaining, 1) if hours_remaining > 0 else 0,
        "warning": computed_warning,
        "warning_level": computed_level,
        "db_path": str(db_path),
        "cached": cached,
    }


class TokenManager:
    """Manage Schwab OAuth token files plus SQLite-backed state and locking."""

    def __init__(
        self,
        token_path: Path = DEFAULT_TOKEN_PATH,
        db_path: Path | None = None,
    ):
        self.token_path = Path(token_path)
        self.db_path = Path(db_path) if db_path is not None else resolve_token_db_path(token_path)
        ensure_sensitive_dir(self.token_path.parent)
        prepare_sensitive_file(self.db_path)
        self._ensure_state_db()

    def _connect(self, *, timeout: float = TOKEN_LOCK_TIMEOUT_SECONDS) -> sqlite3.Connection:
        prepare_sensitive_file(self.db_path)
        conn = sqlite3.connect(self.db_path, timeout=timeout, isolation_level=None)
        setattr(conn, "row_factory", sqlite3.Row)  # noqa: B010
        conn.execute("PRAGMA journal_mode=WAL")
        restrict_sqlite_permissions(self.db_path)
        return conn

    def _ensure_state_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_state (
                    token_path TEXT PRIMARY KEY,
                    created_at TEXT,
                    expires_at TEXT,
                    updated_at TEXT NOT NULL,
                    file_mtime REAL
                )
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(token_state)")}
            if "token_json" in cols:
                conn.execute("ALTER TABLE token_state DROP COLUMN token_json")
                orphans = [
                    row[0]
                    for row in conn.execute("SELECT token_path FROM token_state").fetchall()
                    if not Path(row[0]).exists()
                ]
                for orphan in orphans:
                    conn.execute("DELETE FROM token_state WHERE token_path = ?", (orphan,))

    @contextmanager
    def auth_lock(
        self,
        *,
        timeout: float = TOKEN_LOCK_TIMEOUT_SECONDS,
    ) -> Iterator[sqlite3.Connection]:
        """Serialize token reads/writes across local processes with SQLite."""
        conn = self._connect(timeout=timeout)
        committed = False
        try:
            conn.execute("BEGIN EXCLUSIVE")
            yield conn
            conn.commit()
            committed = True
        finally:
            if not committed:
                conn.rollback()
            restrict_sqlite_permissions(self.db_path)
            conn.close()

    def tokens_exist(self) -> bool:
        """Check if the token file exists."""
        return self.token_path.exists()

    def load_tokens(self) -> JsonObject | None:
        """Load tokens from the token JSON file."""
        if not self.tokens_exist():
            return None
        try:
            with self.token_path.open() as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load tokens from %s: %s", self.token_path, exc)
            return None

    def _write_token_file(self, tokens: JsonObject) -> None:
        write_sensitive_json(self.token_path, tokens)

    def _upsert_state(
        self,
        tokens: JsonObject,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        window = _derive_token_window(tokens)
        created_at = window[0].isoformat() if window else None
        expires_at = window[1].isoformat() if window else None
        file_mtime = self.token_path.stat().st_mtime if self.token_path.exists() else None
        target = conn or self._connect()
        try:
            target.execute(
                """
                INSERT INTO token_state (
                    token_path,
                    created_at,
                    expires_at,
                    updated_at,
                    file_mtime
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(token_path) DO UPDATE SET
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at,
                    file_mtime=excluded.file_mtime
                """,
                (
                    str(self.token_path),
                    created_at,
                    expires_at,
                    datetime.now().isoformat(),
                    file_mtime,
                ),
            )
        finally:
            if conn is None:
                target.close()

    def _delete_state(self, *, conn: sqlite3.Connection | None = None) -> None:
        target = conn or self._connect()
        try:
            target.execute(
                "DELETE FROM token_state WHERE token_path = ?",
                (str(self.token_path),),
            )
        finally:
            if conn is None:
                target.close()

    def _load_cached_state(self) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM token_state WHERE token_path = ?",
                (str(self.token_path),),
            ).fetchone()

    def sync_state_from_file(self, *, conn: sqlite3.Connection | None = None) -> JsonObject | None:
        """Sync the sidecar DB from the token file and return the loaded token."""
        tokens = self.load_tokens()
        if tokens is None:
            return None
        self._upsert_state(tokens, conn=conn)
        return tokens

    def read_token_object(self) -> JsonObject:
        """Read a token object for ``client_from_access_functions`` safely."""
        with self.auth_lock() as conn:
            tokens = self.load_tokens()
            if tokens is None:
                raise FileNotFoundError(f"Token file not found or unreadable: {self.token_path}")
            self._upsert_state(tokens, conn=conn)
            return tokens

    def write_token_object(self, tokens: JsonObject, *args: object, **kwargs: object) -> None:
        """Write a refreshed token object atomically and sync the sidecar DB."""
        del args, kwargs
        with self.auth_lock() as conn:
            self._write_token_file(tokens)
            self._upsert_state(tokens, conn=conn)

    def get_token_info(self) -> JsonObject:
        """Get current token status, using cached metadata when needed."""
        if not self.tokens_exist():
            return {
                "exists": False,
                "valid": False,
                "warning": "Token file not found. Run 'schwab-auth' to authenticate.",
                "warning_level": "critical",
                "db_path": str(self.db_path),
            }

        tokens = self.load_tokens()
        if tokens is not None:
            window = _derive_token_window(tokens)
            self._upsert_state(tokens)
            if window is not None:
                created, expires = window
                return _build_token_info(created=created, expires=expires, db_path=self.db_path)

        cached = self._load_cached_state()
        if cached is not None:
            cached_created = _parse_datetime_like(cached["created_at"])
            cached_expires = _parse_datetime_like(cached["expires_at"])
            if cached_created is not None and cached_expires is not None:
                return _build_token_info(
                    created=cached_created,
                    expires=cached_expires,
                    db_path=self.db_path,
                    warning=(
                        "Token file is unreadable; using cached token metadata. "
                        "Run 'schwab-auth --force' if this persists."
                    ),
                    warning_level="warning",
                    cached=True,
                )

        return {
            "exists": True,
            "valid": False,
            "warning": (
                "Cannot determine token expiration. "
                "Run 'schwab-auth --force' to re-authenticate."
            ),
            "warning_level": "warning",
            "db_path": str(self.db_path),
        }

    def get_storage_info(self) -> JsonObject:
        """Describe the local token persistence strategy for diagnostics."""
        return {
            "token_path": str(self.token_path),
            "db_path": str(self.db_path),
            "storage_mode": "file+sqlite_sidecar",
            "locking": "sqlite_begin_exclusive",
        }

    def delete_tokens(self) -> None:
        """Delete the token file and its cached state."""
        with self.auth_lock() as conn:
            if self.token_path.exists():
                self.token_path.unlink()
                logger.info("Deleted token file: %s", self.token_path)
            self._delete_state(conn=conn)


def get_token_manager(
    token_path: Path | None = None,
    db_path: Path | None = None,
) -> TokenManager:
    """Create a token manager using default portfolio token path when omitted."""
    return TokenManager(token_path=token_path or DEFAULT_TOKEN_PATH, db_path=db_path)
