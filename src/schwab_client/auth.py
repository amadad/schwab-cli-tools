"""Authentication helpers for ``schwab-py`` with token-state persistence.

The underlying ``schwab-py`` client still uses the normal token JSON file for
OAuth compatibility. This module adds a small SQLite sidecar database beside the
token file to:

- serialize token reads/writes across local processes
- keep cached token metadata for diagnostics
- support atomic token file writes during refreshes
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from schwab import auth

from src.core.errors import ConfigError

load_dotenv()
logger = logging.getLogger(__name__)

DATA_DIR_ENV = "SCHWAB_CLI_DATA_DIR"
TOKEN_PATH_ENV = "SCHWAB_TOKEN_PATH"
TOKEN_DB_FILENAME = "tokens.db"
TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 6.5
TOKEN_LOCK_TIMEOUT_SECONDS = 60.0


def resolve_data_dir() -> Path:
    """Resolve the base data directory."""
    env_dir = os.getenv(DATA_DIR_ENV)
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".schwab-cli-tools"


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
DEFAULT_TOKEN_DB_PATH = resolve_token_db_path(DEFAULT_TOKEN_PATH)


def _parse_datetime_like(value: Any) -> datetime | None:
    """Parse Schwab token timestamps stored as unix seconds or ISO strings."""
    if value is None:
        return None
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value)
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError, OSError):
        return None


def _derive_token_window(tokens: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Return token creation and refresh-expiry timestamps when available."""
    creation_time = _parse_datetime_like(tokens.get("creation_timestamp"))
    token_data = tokens.get("token", {})
    expires_at = token_data.get("expires_at") if isinstance(token_data, dict) else None
    access_expiry = _parse_datetime_like(expires_at)

    if access_expiry is not None:
        created = creation_time or (access_expiry - timedelta(minutes=30))
        return created, created + timedelta(days=7)

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
) -> dict[str, Any]:
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
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_state_db()

    def _connect(self, *, timeout: float = TOKEN_LOCK_TIMEOUT_SECONDS) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=timeout, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_state_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_state (
                    token_path TEXT PRIMARY KEY,
                    token_json TEXT NOT NULL,
                    created_at TEXT,
                    expires_at TEXT,
                    updated_at TEXT NOT NULL,
                    file_mtime REAL
                )
                """
            )

    @contextmanager
    def auth_lock(
        self,
        *,
        timeout: float = TOKEN_LOCK_TIMEOUT_SECONDS,
    ) -> Iterator[sqlite3.Connection]:
        """Serialize token reads/writes across local processes with SQLite."""
        conn = self._connect(timeout=timeout)
        try:
            conn.execute("BEGIN EXCLUSIVE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def tokens_exist(self) -> bool:
        """Check if the token file exists."""
        return self.token_path.exists()

    def load_tokens(self) -> dict[str, Any] | None:
        """Load tokens from the token JSON file."""
        if not self.tokens_exist():
            return None
        try:
            with self.token_path.open() as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load tokens from %s: %s", self.token_path, exc)
            return None

    def _write_token_file(self, tokens: dict[str, Any]) -> None:
        temp_path = self.token_path.with_suffix(f"{self.token_path.suffix}.tmp")
        temp_path.write_text(json.dumps(tokens))
        temp_path.replace(self.token_path)

    def _upsert_state(
        self,
        tokens: dict[str, Any],
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
                    token_json,
                    created_at,
                    expires_at,
                    updated_at,
                    file_mtime
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_path) DO UPDATE SET
                    token_json=excluded.token_json,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    updated_at=excluded.updated_at,
                    file_mtime=excluded.file_mtime
                """,
                (
                    str(self.token_path),
                    json.dumps(tokens),
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

    def sync_state_from_file(self, *, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
        """Sync the sidecar DB from the token file and return the loaded token."""
        tokens = self.load_tokens()
        if tokens is None:
            return None
        self._upsert_state(tokens, conn=conn)
        return tokens

    def read_token_object(self) -> dict[str, Any]:
        """Read a token object for ``client_from_access_functions`` safely."""
        with self.auth_lock() as conn:
            tokens = self.load_tokens()
            if tokens is None:
                raise FileNotFoundError(f"Token file not found or unreadable: {self.token_path}")
            self._upsert_state(tokens, conn=conn)
            return tokens

    def write_token_object(self, tokens: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        """Write a refreshed token object atomically and sync the sidecar DB."""
        del args, kwargs
        with self.auth_lock() as conn:
            self._write_token_file(tokens)
            self._upsert_state(tokens, conn=conn)

    def get_token_info(self) -> dict[str, Any]:
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

    def get_storage_info(self) -> dict[str, Any]:
        """Describe the local token persistence strategy for diagnostics."""
        return {
            "token_path": str(self.token_path),
            "db_path": str(self.db_path),
            "storage_mode": "token_json+sqlite_sidecar",
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


def _build_locked_client(
    *,
    api_key: str,
    app_secret: str,
    manager: TokenManager,
    asyncio: bool = False,
):
    return auth.client_from_access_functions(
        api_key=api_key,
        app_secret=app_secret,
        token_read_func=manager.read_token_object,
        token_write_func=manager.write_token_object,
        asyncio=asyncio,
    )


def _get_or_create_locked_client(
    *,
    api_key: str,
    app_secret: str,
    callback_url: str,
    token_path: Path,
    asyncio: bool = False,
):
    manager = get_token_manager(token_path=token_path)
    client = None

    if manager.tokens_exist():
        try:
            client = _build_locked_client(
                api_key=api_key,
                app_secret=app_secret,
                manager=manager,
                asyncio=asyncio,
            )
            if client.token_age() >= TOKEN_MAX_AGE_SECONDS:
                logger.info("Token too old, proactively re-authenticating")
                manager.delete_tokens()
                client = None
        except Exception as exc:
            logger.warning("Failed to load managed token state, re-authenticating: %s", exc)
            manager.delete_tokens()
            client = None

    if client is None:
        with manager.auth_lock() as conn:
            bootstrap_client = auth.easy_client(
                api_key=api_key,
                app_secret=app_secret,
                callback_url=callback_url,
                token_path=str(token_path),
                asyncio=asyncio,
            )
            manager.sync_state_from_file(conn=conn)

        if not manager.tokens_exist():
            return bootstrap_client

        client = _build_locked_client(
            api_key=api_key,
            app_secret=app_secret,
            manager=manager,
            asyncio=asyncio,
        )

    return client


def get_authenticated_client(
    api_key: str | None = None,
    app_secret: str | None = None,
    callback_url: str = "https://127.0.0.1:8001",
    token_path: Path | None = None,
    asyncio: bool = False,
):
    """Get an authenticated Schwab client backed by managed token storage."""
    api_key = api_key or os.getenv("SCHWAB_INTEL_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_INTEL_CLIENT_SECRET")
    token_path = token_path or DEFAULT_TOKEN_PATH

    if not api_key or not app_secret:
        raise ConfigError(
            "Missing Schwab credentials. Set SCHWAB_INTEL_APP_KEY and "
            "SCHWAB_INTEL_CLIENT_SECRET environment variables."
        )

    Path(token_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        client = _get_or_create_locked_client(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=callback_url,
            token_path=Path(token_path),
            asyncio=asyncio,
        )
        logger.info("Schwab client authenticated successfully")
        return client
    except Exception as exc:
        logger.error("Authentication failed: %s", exc)
        raise


def authenticate_interactive(
    api_key: str | None = None,
    app_secret: str | None = None,
    callback_url: str = "https://127.0.0.1:8001",
    token_path: Path | None = None,
    interactive: bool = False,
    requested_browser: str | None = None,
    callback_timeout: float | None = 300.0,
):
    """Run the browser-based authentication flow and return a managed client."""
    api_key = api_key or os.getenv("SCHWAB_INTEL_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_INTEL_CLIENT_SECRET")
    token_path = token_path or DEFAULT_TOKEN_PATH

    if not api_key or not app_secret:
        raise ConfigError(
            "Missing Schwab credentials. Set SCHWAB_INTEL_APP_KEY and "
            "SCHWAB_INTEL_CLIENT_SECRET environment variables."
        )

    manager = get_token_manager(token_path=token_path)
    Path(token_path).parent.mkdir(parents=True, exist_ok=True)

    print("Opening browser for Schwab authentication...")
    print("Complete the login and authorize the application.")
    print(f"Callback URL: {callback_url}")
    print()

    with manager.auth_lock() as conn:
        auth.client_from_login_flow(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=callback_url,
            token_path=str(token_path),
            callback_timeout=callback_timeout,
            interactive=interactive,
            requested_browser=requested_browser,
        )
        manager.sync_state_from_file(conn=conn)

    print()
    print(f"Authentication successful! Tokens saved to {token_path}")
    print("Tokens are valid for 7 days before re-authentication is required.")
    return _build_locked_client(
        api_key=api_key,
        app_secret=app_secret,
        manager=manager,
    )


def authenticate_manual(
    api_key: str | None = None,
    app_secret: str | None = None,
    callback_url: str = "https://127.0.0.1:8001",
    token_path: Path | None = None,
):
    """Run the manual authentication flow and return a managed client."""
    api_key = api_key or os.getenv("SCHWAB_INTEL_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_INTEL_CLIENT_SECRET")
    token_path = token_path or DEFAULT_TOKEN_PATH

    if not api_key or not app_secret:
        raise ConfigError(
            "Missing Schwab credentials. Set SCHWAB_INTEL_APP_KEY and "
            "SCHWAB_INTEL_CLIENT_SECRET environment variables."
        )

    manager = get_token_manager(token_path=token_path)
    Path(token_path).parent.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 60)
    print("MANUAL AUTHENTICATION FLOW")
    print("=" * 60)
    print()
    print("This flow works on headless/remote machines.")
    print()
    print("Steps:")
    print("  1. Copy the URL printed below")
    print("  2. Open it in ANY browser (local machine, phone, etc.)")
    print("  3. Log into Schwab and authorize the app")
    print()
    print("  4. Your browser will show 'Can't connect to server' or similar")
    print("     THIS IS EXPECTED - don't worry!")
    print()
    print("  5. Copy the FULL URL from your browser's address bar")
    print("     (starts with https://127.0.0.1:8001/?code=...)")
    print("  6. Paste it back here")
    print()

    with manager.auth_lock() as conn:
        auth.client_from_manual_flow(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=callback_url,
            token_path=str(token_path),
        )
        manager.sync_state_from_file(conn=conn)

    print()
    print(f"Authentication successful! Tokens saved to {token_path}")
    print("Tokens are valid for 7 days before re-authentication is required.")
    return _build_locked_client(
        api_key=api_key,
        app_secret=app_secret,
        manager=manager,
    )


def main():
    """CLI entry point for authentication."""
    try:
        client = authenticate_interactive()

        response = client.get_account_numbers()
        if response.status_code == 200:
            accounts = response.json()
            print(f"Found {len(accounts)} accounts")
            print("Authentication complete!")
        else:
            print(f"Warning: API test returned {response.status_code}")

    except Exception as exc:
        print(f"Authentication failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
