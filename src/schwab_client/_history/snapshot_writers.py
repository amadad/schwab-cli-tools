"""Snapshot table write helpers for the history store."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from src.core.errors import ConfigError
from src.core.json_types import JsonValue
from src.core.models import (
    AccountSnapshot,
    ManualAccount,
    MarketSnapshot,
    PositionSnapshot,
    SnapshotDocument,
)


class HistorySnapshotWriterMixin:
    if TYPE_CHECKING:
        @staticmethod
        def _float(value: object) -> float: ...

        @staticmethod
        def _nullable_float(value: object) -> float | None: ...

        @staticmethod
        def _int(value: object) -> int: ...

        @staticmethod
        def _nullable_int(value: object) -> int | None: ...

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
        account: AccountSnapshot | ManualAccount | dict[str, JsonValue],
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

    def _account_key(self, *, source: str, account: dict[str, JsonValue]) -> str:
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

    def _account_lookup_key(self, account: AccountSnapshot | dict[str, JsonValue]) -> str:
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
        self, account: AccountSnapshot | ManualAccount | dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        if isinstance(account, dict):
            return account
        return account.to_dict()
