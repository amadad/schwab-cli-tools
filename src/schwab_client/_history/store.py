"""SQLite-backed history store implementation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.core.errors import ConfigError
from src.core.models import (
    AccountSnapshot,
    ManualAccount,
    MarketSnapshot,
    PositionSnapshot,
    SnapshotDocument,
)

from .normalizer import SnapshotNormalizer
from .schema import SCHEMA_STATEMENTS, resolve_history_db_path


class HistoryStore(SnapshotNormalizer):
    """Persist and query canonical snapshot documents."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser() if path else resolve_history_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
            conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if query_only:
            conn.execute("PRAGMA query_only = ON")
        return conn

    def store_snapshot(
        self,
        snapshot: dict[str, Any] | SnapshotDocument,
        *,
        source_command: str,
        source_path: str | None = None,
    ) -> dict[str, Any]:
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

    def list_runs(self, *, limit: int = 20, since: str | None = None) -> list[dict[str, Any]]:
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
        params: list[Any] = []
        if since:
            sql += " WHERE history.observed_at >= ?"
            params.append(since)
        sql += " ORDER BY history.observed_at DESC, history.snapshot_id DESC LIMIT ?"
        params.append(limit)
        return self._fetch_all(sql, params)

    def get_snapshot_payload(self, snapshot_id: int) -> dict[str, Any] | None:
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
    ) -> dict[str, Any] | None:
        """Return the earliest stored snapshot on or after a timestamp."""
        sql = """
            SELECT snapshot_id, observed_at
            FROM portfolio_history
            WHERE observed_at >= ?
        """
        params: list[Any] = [observed_at]
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
    ) -> list[dict[str, Any]]:
        """Return portfolio history rows."""
        sql = "SELECT * FROM portfolio_history"
        params: list[Any] = []
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
    ) -> list[dict[str, Any]]:
        """Return position history rows."""
        sql = "SELECT * FROM position_history"
        clauses: list[str] = []
        params: list[Any] = []

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
    ) -> list[dict[str, Any]]:
        """Return market context history rows."""
        sql = "SELECT * FROM market_history"
        params: list[Any] = []
        if since:
            sql += " WHERE observed_at >= ?"
            params.append(since)
        sql += " ORDER BY observed_at DESC, snapshot_id DESC LIMIT ?"
        params.append(limit)
        return self._fetch_all(sql, params)

    def store_transactions(
        self,
        transactions: list[dict[str, Any]],
        *,
        account_key: str,
    ) -> int:
        """Store transactions, deduplicating by unique constraint.

        Returns the number of new transactions inserted.
        """
        from datetime import datetime

        observed_at = datetime.now().isoformat()
        inserted = 0

        with self._connect() as conn:
            for tx in transactions:
                net_amount = float(tx.get("net_amount", 0) or 0)
                tx_type = tx.get("type", "UNKNOWN")
                description = tx.get("description", "")
                tx_date = tx.get("date", "")
                is_dist = int(tx.get("is_distribution", False))

                try:
                    conn.execute(
                        """
                        INSERT INTO transactions (
                            observed_at, account_key, transaction_date,
                            transaction_type, description, net_amount,
                            symbol, quantity, is_distribution, raw_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            observed_at,
                            account_key,
                            tx_date,
                            tx_type,
                            description,
                            net_amount,
                            tx.get("symbol"),
                            tx.get("quantity"),
                            is_dist,
                            json.dumps(tx.get("raw")) if tx.get("raw") else None,
                        ),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass  # duplicate — already stored

            conn.commit()
        return inserted

    def get_distribution_ytd(self, year: int | None = None) -> list[dict[str, Any]]:
        """Get YTD distribution totals per account."""
        year = year or __import__("datetime").date.today().year
        year_start = f"{year}-01-01"
        return self._fetch_all(
            """
            SELECT
                a.account_label,
                a.account_alias,
                t.account_key,
                SUM(ABS(t.net_amount)) AS ytd_total,
                COUNT(*) AS distribution_count,
                MIN(t.transaction_date) AS first_distribution,
                MAX(t.transaction_date) AS last_distribution
            FROM transactions AS t
            JOIN accounts AS a ON a.account_key = t.account_key
            WHERE t.is_distribution = 1
              AND t.transaction_date >= ?
            GROUP BY t.account_key
            """,
            [year_start],
        )

    def get_distribution_history(
        self, *, account: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get distribution transaction history."""
        sql = """
            SELECT
                t.transaction_date,
                a.account_label,
                t.net_amount,
                t.description
            FROM transactions AS t
            JOIN accounts AS a ON a.account_key = t.account_key
            WHERE t.is_distribution = 1
        """
        params: list[Any] = []
        if account:
            sql += " AND (a.account_label = ? OR a.account_alias = ?)"
            params.extend([account, account])
        sql += " ORDER BY t.transaction_date DESC LIMIT ?"
        params.append(limit)
        return self._fetch_all(sql, params)

    def execute_query(self, sql: str) -> list[dict[str, Any]]:
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

    def import_json_paths(self, paths: list[str] | None = None) -> dict[str, Any]:
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
            except Exception as exc:  # pragma: no cover - defensive wrapper
                failures.append({"path": str(file_path), "message": str(exc)})

        result = {
            "db_path": str(self.path),
            "imported": imported,
            "paths": [str(path) for path in candidate_paths],
        }
        if failures:
            result["failures"] = failures
        return result

    def create_or_update_brief_run(self, **kwargs: Any) -> int:
        snapshot_id = kwargs.get("snapshot_id")
        snapshot_observed_at = kwargs.get("snapshot_observed_at")
        brief_for_date = kwargs.get("brief_for_date")
        if snapshot_id is None or snapshot_observed_at is None or brief_for_date is None:
            raise ConfigError("brief run requires snapshot_id, snapshot_observed_at, and brief_for_date")

        existing = self.get_brief_run_by_snapshot_id(int(snapshot_id))
        fields = [
            "snapshot_observed_at",
            "brief_for_date",
            "status",
            "context_json",
            "scorecard_json",
            "analysis_json",
            "analysis_raw_response",
            "analysis_model_command",
            "analysis_prompt_version",
            "advisor_run_id",
            "advisor_issue_key",
            "briefing_json",
            "email_subject",
            "email_html",
            "email_text",
            "fallback_mode",
            "last_error",
            "sent_at",
        ]
        payload = {
            field: kwargs[field] if field in kwargs else (existing.get(field) if existing else None)
            for field in fields
        }
        for key in ("context_json", "scorecard_json", "analysis_json", "briefing_json"):
            payload[key] = self._json_dumps(payload.get(key))
        payload.setdefault("status", "captured")
        assignments = ",\n                        ".join(f"{field} = excluded.{field}" for field in fields)
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO brief_runs (
                    snapshot_id,
                    {', '.join(fields)}
                ) VALUES (
                    ?,
                    {', '.join(['?'] * len(fields))}
                )
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    {assignments},
                    updated_at = CURRENT_TIMESTAMP
                """,
                [snapshot_id, *[payload[field] for field in fields]],
            )
            conn.commit()
            row = conn.execute(
                "SELECT id FROM brief_runs WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if row is None:
                raise ConfigError("Could not determine brief run id")
            return int(row[0])

    def record_brief_delivery(
        self,
        brief_run_id: int,
        *,
        channel: str,
        recipient_json: dict[str, Any] | list[Any] | None,
        provider: str | None,
        provider_message_id: str | None,
        dry_run: bool,
        status: str,
        error_text: str | None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO brief_deliveries (
                    brief_run_id,
                    channel,
                    recipient_json,
                    provider,
                    provider_message_id,
                    dry_run,
                    status,
                    error_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    brief_run_id,
                    channel,
                    self._json_dumps(recipient_json),
                    provider,
                    provider_message_id,
                    int(bool(dry_run)),
                    status,
                    error_text,
                ),
            )
            conn.commit()
            if cursor.lastrowid is None:
                raise ConfigError("Could not determine brief delivery id")
            return int(cursor.lastrowid)

    def get_brief_run_by_snapshot_id(self, snapshot_id: int) -> dict[str, Any] | None:
        with self._connect(query_only=True) as conn:
            row = conn.execute("SELECT * FROM brief_runs WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
        if row is None:
            return None
        return self.get_brief_run(int(row["id"]))

    def get_brief_run(self, run_id: int) -> dict[str, Any] | None:
        with self._connect(query_only=True) as conn:
            row = conn.execute("SELECT * FROM brief_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            deliveries = [
                dict(delivery)
                for delivery in conn.execute(
                    "SELECT * FROM brief_deliveries WHERE brief_run_id = ? ORDER BY attempted_at DESC, id DESC",
                    (run_id,),
                ).fetchall()
            ]
        data = dict(row)
        for key in ("context_json", "scorecard_json", "analysis_json", "briefing_json"):
            data[key] = self._json_loads(data.get(key))
        for delivery in deliveries:
            delivery["recipient_json"] = self._json_loads(delivery.get("recipient_json"))
            delivery["dry_run"] = bool(delivery.get("dry_run", 0))
        data["deliveries"] = deliveries
        return data

    def find_latest_brief_for_date(self, brief_for_date: str) -> dict[str, Any] | None:
        with self._connect(query_only=True) as conn:
            row = conn.execute(
                "SELECT id FROM brief_runs WHERE brief_for_date = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (brief_for_date,),
            ).fetchone()
        if row is None:
            return None
        return self.get_brief_run(int(row[0]))

    def list_brief_runs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            """
            SELECT
                id,
                snapshot_id,
                snapshot_observed_at,
                brief_for_date,
                status,
                email_subject,
                fallback_mode,
                advisor_run_id,
                sent_at,
                created_at,
                updated_at,
                last_error
            FROM brief_runs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            [limit],
        )
        return rows

    def _json_dumps(self, value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value)

    def _json_loads(self, value: Any) -> Any:
        if value in (None, ""):
            return None
        if isinstance(value, dict | list):
            return value
        return json.loads(value)

    def _fetch_all(self, sql: str, params: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
        with self._connect(query_only=True) as conn:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def _clear_snapshot_children(self, conn: sqlite3.Connection, snapshot_id: int) -> None:
        for table in [
            "snapshot_components",
            "portfolio_snapshots",
            "account_snapshots",
            "position_snapshots",
            "market_snapshots",
            "index_snapshots",
            "sector_snapshots",
        ]:
            conn.execute(f"DELETE FROM {table} WHERE snapshot_id = ?", (snapshot_id,))

    def _insert_components(
        self,
        conn: sqlite3.Connection,
        snapshot_id: int,
        snapshot: SnapshotDocument,
    ) -> None:
        errors_by_component = {
            error.component or "unknown": error.message for error in snapshot.errors
        }
        components = {
            "portfolio.summary": snapshot.portfolio.summary is not None,
            "portfolio.allocation": snapshot.portfolio.allocation is not None,
            "portfolio.positions": snapshot.portfolio.positions is not None,
            "portfolio.manual_accounts": snapshot.portfolio.manual_accounts.accounts is not None,
            "market.signals": snapshot.market.signals is not None if snapshot.market else False,
            "market.vix": snapshot.market.vix is not None if snapshot.market else False,
            "market.indices": snapshot.market.indices is not None if snapshot.market else False,
            "market.sectors": snapshot.market.sectors is not None if snapshot.market else False,
        }

        for component, success in components.items():
            conn.execute(
                """
                INSERT INTO snapshot_components (snapshot_id, component, success, error_message)
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    component,
                    int(success and component not in errors_by_component),
                    errors_by_component.get(component),
                ),
            )

        for component, message in errors_by_component.items():
            if component in components:
                continue
            conn.execute(
                """
                INSERT INTO snapshot_components (snapshot_id, component, success, error_message)
                VALUES (?, ?, 0, ?)
                """,
                (snapshot_id, component, message),
            )

    def _insert_portfolio(
        self,
        conn: sqlite3.Connection,
        snapshot_id: int,
        snapshot: SnapshotDocument,
    ) -> None:
        summary = snapshot.portfolio.summary
        conn.execute(
            """
            INSERT INTO portfolio_snapshots (
                snapshot_id,
                total_value,
                api_value,
                manual_value,
                total_cash,
                manual_cash,
                total_invested,
                total_unrealized_pl,
                cash_percentage,
                account_count,
                api_account_count,
                manual_account_count,
                position_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                self._float(summary.total_value),
                self._float(summary.api_value),
                self._float(summary.manual_value),
                self._float(summary.total_cash),
                self._float(summary.manual_cash),
                self._float(summary.total_invested),
                self._float(summary.total_unrealized_pl),
                self._float(summary.cash_percentage),
                self._int(summary.account_count),
                self._int(summary.api_account_count),
                self._int(summary.manual_account_count),
                self._int(summary.position_count),
            ),
        )

        api_account_keys: dict[str, str] = {}
        for api_account in snapshot.portfolio.api_accounts:
            account_key = self._upsert_account(conn, source="api", account=api_account)
            api_account_keys[self._account_lookup_key(api_account)] = account_key
            conn.execute(
                """
                INSERT INTO account_snapshots (
                    snapshot_id,
                    account_key,
                    total_value,
                    cash_balance,
                    money_market_value,
                    total_cash,
                    invested_value,
                    buying_power,
                    position_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    account_key,
                    self._float(api_account.total_value),
                    self._float(api_account.cash_balance),
                    self._float(api_account.money_market_value),
                    self._float(api_account.total_cash),
                    self._float(api_account.invested_value),
                    self._float(api_account.buying_power),
                    self._nullable_int(api_account.position_count),
                ),
            )

            for position in api_account.positions:
                self._insert_position(conn, snapshot_id, account_key, position)

        for manual_account in snapshot.portfolio.manual_accounts.accounts:
            account_key = self._upsert_account(conn, source="manual", account=manual_account)
            is_cash = manual_account.category == "cash"
            conn.execute(
                """
                INSERT INTO account_snapshots (
                    snapshot_id,
                    account_key,
                    total_value,
                    cash_balance,
                    money_market_value,
                    total_cash,
                    invested_value,
                    buying_power,
                    position_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    account_key,
                    self._float(manual_account.value),
                    self._float(manual_account.value if is_cash else 0),
                    0.0,
                    self._float(manual_account.value if is_cash else 0),
                    self._float(manual_account.value if not is_cash else 0),
                    0.0,
                    None,
                ),
            )

        if not api_account_keys and snapshot.portfolio.positions:
            for position in snapshot.portfolio.positions:
                account_key = self._upsert_account(
                    conn,
                    source="api",
                    account={
                        "account": position.account or "Unknown",
                        "account_alias": position.account_alias,
                        "account_number_last4": position.account_number_last4,
                    },
                )
                self._insert_position(conn, snapshot_id, account_key, position)

    def _insert_market(
        self,
        conn: sqlite3.Connection,
        snapshot_id: int,
        market: MarketSnapshot | None,
    ) -> None:
        if not market:
            return

        signals = market.signals
        vix = market.vix
        indices = market.indices.indices if market.indices else {}
        sectors = market.sectors.sectors if market.sectors else []

        conn.execute(
            """
            INSERT INTO market_snapshots (
                snapshot_id,
                overall,
                recommendation,
                market_sentiment,
                sector_rotation,
                vix_value,
                vix_signal
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                signals.overall if signals else None,
                signals.recommendation if signals else None,
                signals.signals.market_sentiment if signals else None,
                signals.signals.sector_rotation if signals else None,
                self._float(vix.vix if vix else None),
                vix.signal if vix else None,
            ),
        )

        for symbol, index_entry in indices.items():
            conn.execute(
                """
                INSERT INTO index_snapshots (
                    snapshot_id,
                    symbol,
                    name,
                    price,
                    change_value,
                    change_pct
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    symbol,
                    index_entry.name,
                    self._float(index_entry.price),
                    self._float(index_entry.change),
                    self._float(index_entry.change_pct),
                ),
            )

        for rank, sector_entry in enumerate(sectors, start=1):
            conn.execute(
                """
                INSERT INTO sector_snapshots (
                    snapshot_id,
                    symbol,
                    sector,
                    price,
                    change_pct,
                    rank
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    sector_entry.symbol,
                    sector_entry.sector,
                    self._float(sector_entry.price),
                    self._float(sector_entry.change_pct),
                    rank,
                ),
            )

    def _insert_position(
        self,
        conn: sqlite3.Connection,
        snapshot_id: int,
        account_key: str,
        position: PositionSnapshot,
    ) -> None:
        conn.execute(
            """
            INSERT INTO position_snapshots (
                snapshot_id,
                account_key,
                symbol,
                asset_type,
                quantity,
                market_value,
                average_price,
                cost_basis,
                unrealized_pl,
                day_pl,
                day_pl_pct,
                weight_pct,
                is_money_market
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                account_key,
                position.symbol,
                position.asset_type,
                self._float(position.quantity),
                self._float(position.market_value),
                self._float(position.average_price),
                self._float(position.cost_basis),
                self._nullable_float(position.unrealized_pl),
                self._nullable_float(position.day_pl),
                self._nullable_float(position.day_pl_pct),
                self._nullable_float(position.percentage_of_portfolio or position.percentage),
                int(bool(position.is_money_market)),
            ),
        )

    def _upsert_account(
        self,
        conn: sqlite3.Connection,
        *,
        source: str,
        account: AccountSnapshot | ManualAccount | dict[str, Any],
    ) -> str:
        account_data = self._account_data(account)
        account_key = self._account_key(source=source, account=account_data)
        conn.execute(
            """
            INSERT INTO accounts (
                account_key,
                source,
                external_id,
                account_alias,
                account_label,
                account_type,
                tax_status,
                category,
                provider,
                last_four
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_key) DO UPDATE SET
                source = excluded.source,
                external_id = excluded.external_id,
                account_alias = excluded.account_alias,
                account_label = excluded.account_label,
                account_type = excluded.account_type,
                tax_status = excluded.tax_status,
                category = excluded.category,
                provider = excluded.provider,
                last_four = excluded.last_four
            """,
            (
                account_key,
                source,
                account_data.get("id"),
                account_data.get("account_alias"),
                account_data.get("account") or account_data.get("name") or "Unknown",
                account_data.get("account_type") or account_data.get("type"),
                account_data.get("tax_status"),
                account_data.get("category"),
                account_data.get("provider"),
                account_data.get("account_number_last4") or account_data.get("last_four"),
            ),
        )
        return account_key

    def _account_key(self, *, source: str, account: dict[str, Any]) -> str:
        if source == "manual":
            manual_id = account.get("id") or account.get("name") or account.get("account")
            if not manual_id:
                raise ConfigError("Manual account is missing an id/name")
            return f"manual:{manual_id}"

        alias = account.get("account_alias")
        if alias:
            return f"api:{alias}"

        label = account.get("account") or account.get("name") or "Unknown"
        last_four = account.get("account_number_last4") or "na"
        return f"api:{label}:{last_four}"

    def _account_lookup_key(self, account: AccountSnapshot | dict[str, Any]) -> str:
        account_data = self._account_data(account)
        return "|".join(
            [
                str(account_data.get("account_alias") or ""),
                str(account_data.get("account") or account_data.get("name") or ""),
                str(
                    account_data.get("account_number_last4") or account_data.get("last_four") or ""
                ),
            ]
        )

    def _account_data(
        self, account: AccountSnapshot | ManualAccount | dict[str, Any]
    ) -> dict[str, Any]:
        if isinstance(account, dict):
            return account
        return account.to_dict()
