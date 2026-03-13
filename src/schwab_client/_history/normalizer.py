"""Snapshot normalization and import helpers for history storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.errors import ConfigError
from src.core.models import SnapshotDocument
from src.core.snapshot_service import summarize_manual_accounts

from ..paths import default_history_import_roots


class SnapshotNormalizer:
    """Normalize canonical and legacy snapshot documents into one internal shape."""

    def _resolve_import_paths(self, paths: list[str] | None) -> list[Path]:
        if paths:
            candidates = [Path(path).expanduser() for path in paths]
        else:
            candidates = default_history_import_roots()

        files: list[Path] = []
        for path in candidates:
            if path.is_file() and path.suffix == ".json":
                files.append(path)
            elif path.is_dir():
                files.extend(sorted(path.glob("*.json")))
        return sorted({file.resolve() for file in files})

    def _infer_source_command(self, path: Path) -> str:
        if "snapshots" in path.parts:
            return "import_snapshot"
        if "reports" in path.parts:
            return "import_report"
        return "import_json"

    def _normalize_document(self, document: dict[str, Any]) -> SnapshotDocument:
        payload = document
        if {
            "schema_version",
            "command",
            "timestamp",
            "success",
        }.issubset(
            payload.keys()
        ) and isinstance(payload.get("data"), dict):
            payload = payload["data"]

        if "portfolio" in payload and isinstance(payload["portfolio"], dict):
            return self._normalize_report_like_document(payload)

        if {"summary", "api_accounts", "manual_accounts"}.issubset(payload.keys()):
            return self._normalize_legacy_snapshot_document(payload)

        raise ConfigError("Unsupported snapshot JSON format")

    def _normalize_report_like_document(self, payload: dict[str, Any]) -> SnapshotDocument:
        generated_at = payload.get("generated_at") or payload.get("timestamp")
        portfolio = dict(payload.get("portfolio", {}))
        summary = dict(portfolio.get("summary", {}))
        positions = portfolio.get("positions") or summary.pop("positions", [])

        api_accounts = portfolio.get("api_accounts")
        if api_accounts is None:
            api_accounts = self._accounts_from_balances_and_positions(
                portfolio.get("balances", []),
                positions,
            )

        manual_accounts = portfolio.get("manual_accounts")
        if manual_accounts is None:
            manual_accounts = {
                "source_path": None,
                "last_updated": None,
                "accounts": [],
                "summary": summarize_manual_accounts([]),
            }
        elif isinstance(manual_accounts, list):
            manual_accounts = {
                "source_path": None,
                "last_updated": None,
                "accounts": manual_accounts,
                "summary": summarize_manual_accounts(manual_accounts),
            }
        else:
            manual_accounts = dict(manual_accounts)
            manual_accounts.setdefault(
                "summary",
                summarize_manual_accounts(manual_accounts.get("accounts", [])),
            )
            manual_accounts.setdefault("source_path", None)
            manual_accounts.setdefault("last_updated", None)

        manual_accounts_list = manual_accounts.get("accounts", [])
        summary.setdefault("api_value", summary.get("total_value", 0))
        summary.setdefault("manual_value", manual_accounts["summary"].get("total_value", 0))
        summary.setdefault("manual_cash", manual_accounts["summary"].get("total_cash", 0))
        summary.setdefault("api_account_count", len(api_accounts))
        summary.setdefault("manual_account_count", len(manual_accounts_list))
        summary.setdefault(
            "account_count",
            int(summary.get("api_account_count", 0) or 0)
            + int(summary.get("manual_account_count", 0) or 0),
        )
        summary.setdefault("position_count", len(positions))
        total_value = float(summary.get("total_value", 0) or 0)
        total_cash = float(summary.get("total_cash", 0) or 0)
        summary.setdefault(
            "cash_percentage",
            total_cash / total_value * 100 if total_value > 0 else 0,
        )

        market = payload.get("market")
        if market and not {"signals", "vix", "indices", "sectors"}.intersection(market.keys()):
            market = {
                "signals": market,
                "vix": None,
                "indices": None,
                "sectors": None,
            }

        normalized = {
            "generated_at": generated_at,
            "portfolio": {
                "summary": summary,
                "api_accounts": api_accounts,
                "manual_accounts": manual_accounts,
                "positions": positions,
                "allocation": portfolio.get("allocation"),
            },
            "market": market,
        }
        if payload.get("errors"):
            normalized["errors"] = payload["errors"]
        return SnapshotDocument.from_dict(normalized)

    def _normalize_legacy_snapshot_document(self, payload: dict[str, Any]) -> SnapshotDocument:
        api_accounts = [
            self._normalize_legacy_api_account(account)
            for account in payload.get("api_accounts", [])
        ]
        manual_accounts_list = payload.get("manual_accounts", [])
        manual_accounts = {
            "source_path": None,
            "last_updated": payload.get("date"),
            "accounts": manual_accounts_list,
            "summary": summarize_manual_accounts(manual_accounts_list),
        }

        positions: list[dict[str, Any]] = []
        for account in api_accounts:
            for position in account.get("positions", []):
                entry = dict(position)
                entry.setdefault("account", account.get("account"))
                entry.setdefault("account_number_last4", account.get("account_number_last4"))
                positions.append(entry)

        summary = dict(payload.get("summary", {}))
        if "account_count" not in summary:
            summary["account_count"] = summary.get(
                "api_account_count", len(api_accounts)
            ) + summary.get(
                "manual_account_count",
                len(manual_accounts_list),
            )
        if "cash_percentage" not in summary:
            total_value = float(summary.get("total_value", 0) or 0)
            total_cash = float(summary.get("total_cash", 0) or 0)
            summary["cash_percentage"] = total_cash / total_value * 100 if total_value > 0 else 0
        summary.setdefault("api_account_count", len(api_accounts))
        summary.setdefault("manual_account_count", len(manual_accounts_list))
        summary.setdefault(
            "position_count",
            len([position for position in positions if not position.get("is_money_market")]),
        )
        summary.setdefault(
            "total_unrealized_pl",
            sum(float(position.get("unrealized_pl", 0) or 0) for position in positions),
        )
        summary.setdefault("manual_cash", manual_accounts["summary"].get("total_cash", 0))

        return SnapshotDocument.from_dict(
            {
                "generated_at": payload.get("timestamp") or payload.get("date"),
                "portfolio": {
                    "summary": summary,
                    "api_accounts": api_accounts,
                    "manual_accounts": manual_accounts,
                    "positions": positions,
                    "allocation": None,
                },
                "market": None,
            }
        )

    def _normalize_legacy_api_account(self, account: dict[str, Any]) -> dict[str, Any]:
        account_label = (
            account.get("account") or f"Account (...{account.get('account_number_last4', '????')})"
        )
        positions = []
        for position in account.get("positions", []):
            positions.append(
                {
                    "symbol": position.get("symbol"),
                    "quantity": position.get("quantity"),
                    "market_value": position.get("market_value"),
                    "average_price": None,
                    "cost_basis": position.get("cost_basis"),
                    "unrealized_pl": position.get("unrealized_pnl"),
                    "asset_type": position.get("asset_type"),
                    "account": account_label,
                    "account_number_last4": account.get("account_number_last4"),
                    "is_money_market": bool(position.get("is_money_market")),
                }
            )

        return {
            "account": account_label,
            "account_type": account.get("account_type"),
            "account_number_last4": account.get("account_number_last4"),
            "total_value": account.get("liquidation_value"),
            "cash_balance": account.get("cash_balance"),
            "money_market_value": account.get("money_market_value"),
            "total_cash": account.get("total_cash"),
            "invested_value": account.get("invested_value"),
            "buying_power": account.get("buying_power", 0),
            "position_count": account.get("position_count"),
            "positions": positions,
        }

    def _accounts_from_balances_and_positions(
        self,
        balances: list[dict[str, Any]],
        positions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        accounts_by_label: dict[str, dict[str, Any]] = {}

        for balance in balances:
            label = balance.get("account") or balance.get("account_name") or "Unknown"
            accounts_by_label[label] = {
                "account": label,
                "account_alias": balance.get("account_alias"),
                "account_type": balance.get("account_type"),
                "account_number_last4": balance.get("account_number_last4"),
                "total_value": balance.get("total_value"),
                "cash_balance": balance.get("cash_balance"),
                "money_market_value": balance.get("money_market_value", 0),
                "total_cash": balance.get("total_cash", balance.get("cash_balance", 0)),
                "invested_value": balance.get(
                    "invested_value",
                    balance.get("invested_amount", 0),
                ),
                "buying_power": balance.get("buying_power", 0),
                "position_count": 0,
                "positions": [],
            }

        for position in positions:
            label = position.get("account") or "Unknown"
            account = accounts_by_label.setdefault(
                label,
                {
                    "account": label,
                    "account_alias": position.get("account_alias"),
                    "account_number_last4": position.get("account_number_last4"),
                    "account_type": None,
                    "total_value": 0,
                    "cash_balance": 0,
                    "money_market_value": 0,
                    "total_cash": 0,
                    "invested_value": 0,
                    "buying_power": 0,
                    "position_count": 0,
                    "positions": [],
                },
            )
            account["positions"].append(position)
            account["position_count"] = len(
                [entry for entry in account["positions"] if not entry.get("is_money_market")]
            )

        return sorted(
            accounts_by_label.values(),
            key=lambda account: float(account.get("total_value", 0) or 0),
            reverse=True,
        )

    @staticmethod
    def _float(value: Any) -> float:
        return float(value or 0)

    @staticmethod
    def _nullable_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _int(value: Any) -> int:
        return int(value or 0)

    @staticmethod
    def _nullable_int(value: Any) -> int | None:
        if value is None:
            return None
        return int(value)
