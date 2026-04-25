"""SQLite-backed history store implementation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.core.errors import ConfigError
from src.core.json_types import JsonValue
from src.core.models import SnapshotDocument
from src.schwab_client.secure_files import prepare_sensitive_file, restrict_sqlite_permissions

from .brief_store import HistoryBriefStoreMixin
from .normalizer import SnapshotNormalizer
from .schema import SCHEMA_STATEMENTS, resolve_history_db_path
from .snapshot_writers import HistorySnapshotWriterMixin


class HistoryStore(HistoryBriefStoreMixin, HistorySnapshotWriterMixin, SnapshotNormalizer):
    """Persist and query canonical snapshot documents."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path else resolve_history_db_path()
        prepare_sensitive_file(self.path)
        self.initialize()

    def initialize(self) -> None:
        """Create tables and views if they do not already exist."""
        with self._connect() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            conn.commit()

    def _connect(self, *, query_only: bool = False) -> sqlite3.Connection:
        if query_only and self.path.exists():
            conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        else:
            prepare_sensitive_file(self.path)
            conn = sqlite3.connect(self.path)
        setattr(conn, "row_factory", sqlite3.Row)  # noqa: B010
        conn.execute("PRAGMA foreign_keys = ON")
        if query_only:
            conn.execute("PRAGMA query_only = ON")
        restrict_sqlite_permissions(self.path)
        return conn

    def store_snapshot(
        self,
        snapshot: dict[str, JsonValue] | SnapshotDocument,
        *,
        source_command: str,
        source_path: str | None = None,
    ) -> dict[str, JsonValue]:
        """Persist a canonical snapshot document and return storage metadata."""
        canonical = (
            snapshot
            if isinstance(snapshot, SnapshotDocument)
            else self._normalize_document(snapshot)
        )
        raw_json = json.dumps(canonical.to_dict(), indent=2, sort_keys=True)
        observed_at = canonical.generated_at
        if not observed_at:
            raise ConfigError("Snapshot document is missing generated_at")

        includes_manual_accounts = bool(canonical.portfolio.manual_accounts.accounts)
        includes_market = canonical.market is not None
        errors = canonical.errors

        with self._connect() as conn:
            if source_path:
                conn.execute(
                    """
                    INSERT INTO snapshot_runs (
                        observed_at,
                        source_command,
                        source_path,
                        includes_manual_accounts,
                        includes_market,
                        error_count,
                        raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_path) DO UPDATE SET
                        observed_at = excluded.observed_at,
                        source_command = excluded.source_command,
                        includes_manual_accounts = excluded.includes_manual_accounts,
                        includes_market = excluded.includes_market,
                        error_count = excluded.error_count,
                        raw_json = excluded.raw_json
                    """,
                    (
                        observed_at,
                        source_command,
                        source_path,
                        int(includes_manual_accounts),
                        int(includes_market),
                        len(errors),
                        raw_json,
                    ),
                )
                snapshot_id = conn.execute(
                    "SELECT id FROM snapshot_runs WHERE source_path = ?",
                    (source_path,),
                ).fetchone()[0]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO snapshot_runs (
                        observed_at,
                        source_command,
                        source_path,
                        includes_manual_accounts,
                        includes_market,
                        error_count,
                        raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observed_at,
                        source_command,
                        None,
                        int(includes_manual_accounts),
                        int(includes_market),
                        len(errors),
                        raw_json,
                    ),
                )
                row_id = cursor.lastrowid
                if row_id is None:
                    raise ConfigError("Could not determine snapshot_id for stored snapshot")
                snapshot_id = int(row_id)

            self._clear_snapshot_children(conn, snapshot_id)
            self._insert_components(conn, snapshot_id, canonical)
            self._insert_portfolio(conn, snapshot_id, canonical)
            self._insert_market(conn, snapshot_id, canonical.market)
            conn.commit()

        return {
            "snapshot_id": snapshot_id,
            "db_path": str(self.path),
            "source_command": source_command,
            "source_path": source_path,
        }

    def list_runs(self, *, limit: int = 20, since: str | None = None) -> list[dict[str, JsonValue]]:
        """Return recent snapshot runs with portfolio summary context."""
        sql = """
            SELECT
                history.snapshot_id,
                history.observed_at,
                history.source_command,
                history.source_path,
                history.total_value,
                history.api_value,
                history.manual_value,
                history.total_cash,
                history.total_invested,
                history.cash_percentage,
                history.account_count,
                history.position_count,
                history.error_count,
                market.overall AS market_overall,
                market.vix_value,
                market.market_sentiment
            FROM portfolio_history AS history
            LEFT JOIN market_history AS market ON market.snapshot_id = history.snapshot_id
        """
        params: list[JsonValue] = []
        if since:
            sql += " WHERE history.observed_at >= ?"
            params.append(since)
        sql += " ORDER BY history.observed_at DESC, history.snapshot_id DESC LIMIT ?"
        params.append(limit)
        return self._fetch_all(sql, params)

    def get_snapshot_payload(self, snapshot_id: int) -> dict[str, JsonValue] | None:
        """Return the raw canonical snapshot payload for a snapshot id."""
        with self._connect(query_only=True) as conn:
            row = conn.execute(
                "SELECT raw_json FROM snapshot_runs WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None or not row[0]:
            return None
        return json.loads(row[0])

    def find_first_run_on_or_after(
        self,
        observed_at: str,
        *,
        exclude_snapshot_id: int | None = None,
    ) -> dict[str, JsonValue] | None:
        """Return the earliest stored snapshot on or after a timestamp."""
        sql = """
            SELECT snapshot_id, observed_at
            FROM portfolio_history
            WHERE observed_at >= ?
        """
        params: list[JsonValue] = [observed_at]
        if exclude_snapshot_id is not None:
            sql += " AND snapshot_id != ?"
            params.append(exclude_snapshot_id)
        sql += " ORDER BY observed_at ASC, snapshot_id ASC LIMIT 1"
        rows = self._fetch_all(sql, params)
        return rows[0] if rows else None

    def get_portfolio_history(
        self,
        *,
        limit: int = 20,
        since: str | None = None,
    ) -> list[dict[str, JsonValue]]:
        """Return portfolio history rows."""
        sql = "SELECT * FROM portfolio_history"
        params: list[JsonValue] = []
        if since:
            sql += " WHERE observed_at >= ?"
            params.append(since)
        sql += " ORDER BY observed_at DESC, snapshot_id DESC LIMIT ?"
        params.append(limit)
        return self._fetch_all(sql, params)

    def get_position_history(
        self,
        *,
        symbol: str | None = None,
        account: str | None = None,
        limit: int = 50,
        since: str | None = None,
    ) -> list[dict[str, JsonValue]]:
        """Return position history rows."""
        sql = "SELECT * FROM position_history"
        clauses: list[str] = []
        params: list[JsonValue] = []

        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if account:
            clauses.append("(account_label = ? OR account_alias = ? OR account_key = ?)")
            params.extend([account, account, account])
        if since:
            clauses.append("observed_at >= ?")
            params.append(since)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        sql += " ORDER BY observed_at DESC, market_value DESC LIMIT ?"
        params.append(limit)
        return self._fetch_all(sql, params)

    def get_market_history(
        self,
        *,
        limit: int = 20,
        since: str | None = None,
    ) -> list[dict[str, JsonValue]]:
        """Return market context history rows."""
        sql = "SELECT * FROM market_history"
        params: list[JsonValue] = []
        if since:
            sql += " WHERE observed_at >= ?"
            params.append(since)
        sql += " ORDER BY observed_at DESC, snapshot_id DESC LIMIT ?"
        params.append(limit)
        return self._fetch_all(sql, params)

    def execute_query(self, sql: str) -> list[dict[str, JsonValue]]:
        """Execute a read-only SQL query against the history database."""
        statement = sql.strip()
        if not statement:
            raise ConfigError("SQL query cannot be empty")
        statement = statement.rstrip(";")
        if ";" in statement:
            raise ConfigError("Only a single SQL statement is allowed")

        first_token = statement.split(None, 1)[0].lower()
        if first_token not in {"select", "with", "pragma", "explain"}:
            raise ConfigError("Only read-only SQL statements are allowed")

        with self._connect(query_only=True) as conn:
            cursor = conn.execute(statement)
            return [dict(row) for row in cursor.fetchall()]

    def import_json_paths(self, paths: list[str] | None = None) -> dict[str, JsonValue]:
        """Import legacy or canonical JSON snapshots from disk."""
        candidate_paths = self._resolve_import_paths(paths)
        imported = 0
        failures: list[dict[str, str]] = []

        for file_path in candidate_paths:
            try:
                with file_path.open() as handle:
                    payload = json.load(handle)
                source_command = self._infer_source_command(file_path)
                self.store_snapshot(
                    payload,
                    source_command=source_command,
                    source_path=str(file_path.resolve()),
                )
                imported += 1
            except (
                ConfigError,
                OSError,
                json.JSONDecodeError,
                sqlite3.Error,
                ValueError,
            ) as exc:  # pragma: no cover - import wrapper
                failures.append({"path": str(file_path), "message": str(exc)})

        result = {
            "db_path": str(self.path),
            "imported": imported,
            "paths": [str(path) for path in candidate_paths],
        }
        if failures:
            result["failures"] = failures
        return result

    def _fetch_all(
        self, sql: str, params: list[JsonValue] | tuple[JsonValue, ...]
    ) -> list[dict[str, JsonValue]]:
        with self._connect(query_only=True) as conn:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
