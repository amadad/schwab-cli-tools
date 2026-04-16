"""PortfolioContext — single assembler for all portfolio state.

Every tool, brief, review, and analysis reads from this object instead of
making independent API calls. The context gathers:

- Positions and account balances (Schwab API)
- Transactions / distributions (Schwab API + SQLite history)
- Market data: VIX, regime, indices, sectors (Market API)
- Signals: Polymarket macro probabilities
- Lynch sell signals
- Policy evaluation: distribution pacing, cash levels, calendar alerts

Usage:
    ctx = PortfolioContext.assemble(client, market_client=mc)
    print(ctx.policy_delta.summary_lines())
    print(ctx.to_prompt_block())
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, cast

from src.core.context_models import LynchResult, RegimeSnapshot, TransactionRecord
from src.core.errors import ConfigError, PortfolioError
from src.core.json_types import JsonObject, as_json_array, as_json_object
from src.core.models import AccountSnapshot, MarketSnapshot, PortfolioSummary, VixSnapshot
from src.schwab_client.history import HistoryStore

from .market_service import get_market_regime, get_vix
from .policy import PolicyDelta, evaluate_policy, load_policy_config
from .polymarket import PolymarketSnapshot, fetch_polymarket_signals


class PortfolioContextClient(Protocol):
    def get_all_accounts_full(self) -> list[dict]: ...

    def get_account_numbers(self) -> list[dict[str, str]]: ...

    def get_transactions(
        self,
        account_hash: str,
        start_date: str | None = None,
        end_date: str | None = None,
        transaction_type: str = "TRADE",
    ) -> list[dict]: ...


class MarketContextClient(Protocol):
    def get_quote(self, symbol: str) -> object: ...


CONTEXT_COMPONENT_ERRORS = (
    ConfigError,
    PortfolioError,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    ImportError,
    LookupError,
    RuntimeError,
    sqlite3.Error,
)


@dataclass(slots=True)
class PortfolioContext:
    """Complete assembled portfolio context — the single source of truth."""

    # Core portfolio
    summary: PortfolioSummary | None = None
    accounts: list[AccountSnapshot] = field(default_factory=list)

    # Market
    vix: VixSnapshot | None = None
    regime: RegimeSnapshot | None = None
    market: MarketSnapshot | None = None
    market_available: bool = False

    # Signals
    polymarket: PolymarketSnapshot | None = None
    lynch: LynchResult | None = None

    # Transactions / distributions
    ytd_distributions: dict[str, float] = field(default_factory=dict)
    recent_transactions: list[TransactionRecord] = field(default_factory=list)

    # Policy evaluation
    policy_delta: PolicyDelta | None = None

    # Meta
    assembled_at: str = ""
    history: JsonObject | None = None
    manual_accounts_included: bool = False
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: JsonObject) -> PortfolioContext:
        accounts_payload = as_json_array(data.get("accounts"))
        transactions_payload = as_json_array(data.get("recent_transactions"))
        distributions_payload = as_json_object(data.get("ytd_distributions"))
        errors_payload = as_json_array(data.get("errors"))
        return cls(
            summary=(
                PortfolioSummary.from_dict(data["summary"])
                if isinstance(data.get("summary"), dict)
                else None
            ),
            accounts=[
                AccountSnapshot.from_dict(account)
                for account in accounts_payload
                if isinstance(account, dict)
            ],
            vix=VixSnapshot.from_dict(data["vix"]) if isinstance(data.get("vix"), dict) else None,
            regime=(
                RegimeSnapshot.from_dict(data["regime"])
                if isinstance(data.get("regime"), dict)
                else None
            ),
            market=(
                MarketSnapshot.from_dict(data["market"])
                if isinstance(data.get("market"), dict)
                else None
            ),
            market_available=bool(data.get("market_available", False)),
            polymarket=(
                PolymarketSnapshot.from_dict(data["polymarket"])
                if isinstance(data.get("polymarket"), dict)
                else None
            ),
            lynch=(
                LynchResult.from_dict(data["lynch"])
                if isinstance(data.get("lynch"), dict)
                else None
            ),
            ytd_distributions={
                str(key): float(value)
                for key, value in distributions_payload.items()
                if value is not None
            },
            recent_transactions=[
                TransactionRecord.from_dict(item)
                for item in transactions_payload
                if isinstance(item, dict)
            ],
            policy_delta=(
                PolicyDelta.from_dict(data["policy_delta"])
                if isinstance(data.get("policy_delta"), dict)
                else None
            ),
            assembled_at=str(data.get("assembled_at") or ""),
            history=as_json_object(data.get("history")) or None,
            manual_accounts_included=bool(data.get("manual_accounts_included", False)),
            errors=[str(item) for item in errors_payload],
        )

    @staticmethod
    def _normalize_ytd_distributions_payload(payload: JsonObject | None) -> dict[str, float]:
        if not isinstance(payload, dict):
            return {}
        return {str(key): float(value) for key, value in payload.items() if value is not None}

    @staticmethod
    def _stringify_snapshot_errors(errors: object) -> list[str]:
        result: list[str] = []
        if not isinstance(errors, list):
            return result
        for error in errors:
            if isinstance(error, dict):
                component = str(error.get("component") or "unknown")
                message = str(error.get("message") or "")
                result.append(f"{component}: {message}" if message else component)
            else:
                result.append(str(error))
        return result

    @staticmethod
    def _alias_for_snapshot_account(account: JsonObject) -> str | None:
        from config.secure_account_config import secure_config

        alias = account.get("account_alias")
        if alias:
            return str(alias)

        account_number = account.get("account_number")
        if account_number:
            info = secure_config.get_account_info_by_number(str(account_number))
            if info:
                return info.alias

        last4 = str(account.get("account_number_last4") or account.get("last_four") or "")
        if last4:
            for info in secure_config.get_all_accounts().values():
                if info.account_number.endswith(last4):
                    return info.alias

        label = account.get("account") or account.get("name")
        return str(label) if label else None

    @classmethod
    def from_snapshot_payload(
        cls,
        snapshot: JsonObject,
        *,
        ytd_distributions: JsonObject | None = None,
        supplemental: JsonObject | None = None,
    ) -> tuple[PortfolioContext, str | None]:
        portfolio = as_json_object(snapshot.get("portfolio"))
        summary = as_json_object(portfolio.get("summary")) or as_json_object(
            snapshot.get("summary")
        )
        if not summary:
            context = cls(
                assembled_at=str(snapshot.get("generated_at") or datetime.now().isoformat())
            )
            context.errors.append("policy: invalid_snapshot_summary")
            return context, "invalid_snapshot_summary"

        accounts = [
            dict(account)
            for account in as_json_array(
                portfolio.get("api_accounts") or snapshot.get("api_accounts")
            )
            if isinstance(account, dict)
        ]
        manual_accounts_payload = as_json_object(portfolio.get("manual_accounts"))
        manual_accounts = as_json_array(manual_accounts_payload.get("accounts"))
        market = as_json_object(snapshot.get("market")) or None
        supplemental = supplemental or {}
        normalized_ytd = cls._normalize_ytd_distributions_payload(ytd_distributions)

        account_balances: dict[str, dict[str, float]] = {}
        for account in accounts:
            key = cls._alias_for_snapshot_account(account)
            if not key:
                continue
            account_balances[key] = {
                "total_value": float(account.get("total_value", 0.0) or 0.0),
                "cash": float(account.get("total_cash", 0.0) or 0.0),
            }

        missing_reason: str | None = None
        policy_delta = None
        policy_config = load_policy_config()
        tracked_accounts = policy_config.tracked_distribution_accounts() & set(account_balances)
        missing_distribution_accounts = sorted(
            account for account in tracked_accounts if account not in normalized_ytd
        )
        if missing_distribution_accounts:
            missing_reason = "missing_distribution_history:" + ",".join(
                missing_distribution_accounts
            )
        else:
            policy_delta = evaluate_policy(
                account_balances=account_balances,
                ytd_distributions=normalized_ytd,
                total_cash_pct=float(summary.get("cash_percentage", 0.0) or 0.0),
                policy_config=policy_config,
            )

        errors = cls._stringify_snapshot_errors(snapshot.get("errors"))
        errors.extend(str(error) for error in as_json_array(supplemental.get("errors")))
        if missing_reason:
            errors.append(f"policy: {missing_reason}")

        context = cls.from_dict(
            {
                "assembled_at": str(
                    supplemental.get("assembled_at") or snapshot.get("generated_at") or ""
                ),
                "summary": dict(summary),
                "accounts": accounts,
                "vix": market.get("vix") if market is not None else None,
                "regime": supplemental.get("regime"),
                "market": market,
                "market_available": bool(
                    market is not None
                    and any(
                        market.get(component) is not None
                        for component in ("signals", "vix", "indices", "sectors")
                    )
                ),
                "polymarket": supplemental.get("polymarket"),
                "lynch": supplemental.get("lynch"),
                "ytd_distributions": normalized_ytd,
                "recent_transactions": as_json_array(supplemental.get("recent_transactions")),
                "policy_delta": policy_delta.to_dict() if policy_delta else None,
                "history": as_json_object(snapshot.get("history")),
                "manual_accounts_included": bool(manual_accounts),
                "errors": errors or None,
            }
        )
        return context, missing_reason

    @classmethod
    def assemble(
        cls,
        client: PortfolioContextClient,
        *,
        market_client: MarketContextClient | None = None,
        include_polymarket: bool = True,
        include_lynch: bool = False,
        include_transactions: bool = True,
        distribution_overrides: dict[str, float] | None = None,
    ) -> PortfolioContext:
        """Assemble complete portfolio context from all data sources.

        Args:
            client: Authenticated SchwabClientWrapper
            market_client: Authenticated market data client
            include_polymarket: Fetch Polymarket macro signals
            include_lynch: Run Lynch sell signal analysis
            include_transactions: Fetch recent transactions for distribution tracking
            distribution_overrides: Manual YTD distribution amounts by account alias
        """
        ctx = cls(assembled_at=datetime.now().isoformat())

        # --- Core portfolio data ---
        ctx._assemble_portfolio(client)

        # --- Market data ---
        if market_client:
            ctx._assemble_market(market_client)

        # --- Polymarket ---
        if include_polymarket:
            ctx._assemble_polymarket()

        # --- Lynch ---
        if include_lynch and market_client:
            ctx._assemble_lynch(market_client)

        # --- Transactions / distributions ---
        if include_transactions:
            ctx._assemble_transactions(client, overrides=distribution_overrides)
        elif distribution_overrides:
            ctx.ytd_distributions = dict(distribution_overrides)

        # --- History provenance ---
        ctx._assemble_history_metadata()

        # --- Policy evaluation ---
        ctx._evaluate_policy()

        return ctx

    def _assemble_portfolio(self, client: PortfolioContextClient) -> None:
        """Fetch positions and account balances."""
        try:
            from config.secure_account_config import secure_config
            from src.core.portfolio_service import (
                build_account_snapshots_model,
                build_portfolio_summary_model,
            )
            from src.schwab_client.client import MONEY_MARKET_SYMBOLS
            from src.schwab_client.snapshot import get_account_display_name

            accounts_raw = client.get_all_accounts_full()
            self.summary = build_portfolio_summary_model(
                accounts_raw, get_account_display_name, MONEY_MARKET_SYMBOLS
            )
            self.accounts = build_account_snapshots_model(
                accounts_raw, get_account_display_name, MONEY_MARKET_SYMBOLS
            )
            for account in self.accounts:
                if account.account_number:
                    account.account_number_last4 = str(account.account_number)[-4:]
                    info = secure_config.get_account_info_by_number(str(account.account_number))
                    if info and not account.account_alias:
                        account.account_alias = info.alias
                    for position in account.positions:
                        position.account_number_last4 = str(account.account_number)[-4:]
                        if info and not position.account_alias:
                            position.account_alias = info.alias
        except CONTEXT_COMPONENT_ERRORS as exc:
            self.errors.append(f"portfolio: {exc}")

    def _assemble_market(self, market_client: object) -> None:
        """Fetch VIX, regime, and full market snapshot."""
        from .market_service import get_market_indices, get_market_signals, get_sector_performance
        from .models import IndicesSnapshot, MarketSignalsSnapshot, SectorPerformanceSnapshot

        signals = None
        indices = None
        sectors = None

        try:
            signals = MarketSignalsSnapshot.from_dict(get_market_signals(market_client))
        except CONTEXT_COMPONENT_ERRORS as exc:
            self.errors.append(f"market.signals: {exc}")

        try:
            vix_data = get_vix(market_client)
            self.vix = VixSnapshot.from_dict(vix_data)
        except CONTEXT_COMPONENT_ERRORS as exc:
            self.errors.append(f"vix: {exc}")

        try:
            regime_data = get_market_regime(market_client)
            self.regime = RegimeSnapshot(
                regime=regime_data.get("regime", "unknown"),
                description=regime_data.get("description", ""),
                risk_on=regime_data.get("risk_on", False),
                rates_rising=regime_data.get("rates_rising", False),
                signals=regime_data.get("signals", {}),
            )
        except CONTEXT_COMPONENT_ERRORS as exc:
            self.errors.append(f"regime: {exc}")

        try:
            indices = IndicesSnapshot.from_dict(get_market_indices(market_client))
        except CONTEXT_COMPONENT_ERRORS as exc:
            self.errors.append(f"market.indices: {exc}")

        try:
            sectors = SectorPerformanceSnapshot.from_dict(get_sector_performance(market_client))
        except CONTEXT_COMPONENT_ERRORS as exc:
            self.errors.append(f"market.sectors: {exc}")

        self.market = MarketSnapshot(
            signals=signals,
            vix=self.vix,
            indices=indices,
            sectors=sectors,
        )
        self.market_available = any(
            component is not None for component in (signals, self.vix, indices, sectors)
        )

    def _assemble_polymarket(self) -> None:
        """Fetch macro probability signals from Polymarket."""
        try:
            self.polymarket = fetch_polymarket_signals()
        except CONTEXT_COMPONENT_ERRORS as exc:
            self.errors.append(f"polymarket: {exc}")

    def _assemble_lynch(
        self,
        market_client: MarketContextClient,
    ) -> None:
        """Run Lynch sell signal analysis on current holdings."""
        try:
            from src.core.lynch_service import HoldingInput, analyze_holdings_lynch

            positions = self.summary.positions if self.summary else []
            equity_symbols = [
                p.symbol
                for p in positions
                if p.asset_type in ("EQUITY", "ETF") and not p.is_money_market
            ]

            if not equity_symbols:
                self.lynch = LynchResult(total_checked=0)
                return

            holdings_data: list[HoldingInput] = []
            for symbol in equity_symbols[:50]:  # cap to avoid API overload
                try:
                    quote_payload = market_client.get_quote(symbol)
                    if hasattr(quote_payload, "json"):
                        quote_payload = quote_payload.json()
                    quote_data = as_json_object(quote_payload)
                    symbol_data = as_json_object(quote_data.get(symbol))
                    fundamentals = as_json_object(symbol_data.get("fundamental"))
                    quote = as_json_object(symbol_data.get("quote"))
                    fundamentals.update(
                        {
                            "lastPrice": quote.get("lastPrice"),
                            "high52": quote.get("52WkHigh"),
                            "low52": quote.get("52WkLow"),
                        }
                    )
                    holdings_data.append({"symbol": symbol, "fundamentals": fundamentals})
                except CONTEXT_COMPONENT_ERRORS:
                    continue

            results = analyze_holdings_lynch(holdings_data)
            flagged = [cast(JsonObject, dict(result)) for result in results if result["signals"]]
            self.lynch = LynchResult(
                total_checked=len(results),
                signals_found=len(flagged),
                flagged=flagged,
            )
        except CONTEXT_COMPONENT_ERRORS as exc:
            self.errors.append(f"lynch: {exc}")

    def _assemble_transactions(
        self,
        client: PortfolioContextClient,
        *,
        overrides: dict[str, float] | None = None,
    ) -> None:
        """Fetch YTD transactions and compute distribution totals."""
        self.ytd_distributions = dict(overrides or {})

        try:
            from config.secure_account_config import secure_config

            policy_config = load_policy_config()
            tracked_distribution_accounts = policy_config.tracked_distribution_accounts()
            today = date.today()
            year_start = date(today.year, 1, 1)

            account_numbers = client.get_account_numbers()
            for account_info in account_numbers:
                account_number = account_info["accountNumber"]
                account_hash = account_info["hashValue"]
                resolved_account = secure_config.get_account_info_by_number(account_number)
                if not resolved_account:
                    continue
                alias = resolved_account.alias
                label = alias

                if alias not in tracked_distribution_accounts:
                    continue

                # Skip if we already have an override
                if alias in self.ytd_distributions:
                    continue

                try:
                    # Fetch all transaction types to catch distributions
                    for tx_type in ["JOURNAL", "TRADE"]:
                        txns = client.get_transactions(
                            account_hash,
                            start_date=year_start.isoformat(),
                            end_date=today.isoformat(),
                            transaction_type=tx_type,
                        )
                        for tx in txns:
                            amount = float(tx.get("netAmount", 0) or 0)
                            tx_date = tx.get("transactionDate", tx.get("tradeDate", ""))
                            description = tx.get("description", "")

                            self.recent_transactions.append(
                                TransactionRecord(
                                    date=tx_date[:10] if tx_date else "",
                                    account=label,
                                    type=tx_type,
                                    description=description,
                                    amount=amount,
                                )
                            )

                            # Distributions show as negative netAmount (cash out)
                            if amount < 0 and tx_type == "JOURNAL":
                                self.ytd_distributions[label] = self.ytd_distributions.get(
                                    label, 0
                                ) + abs(amount)
                except CONTEXT_COMPONENT_ERRORS as exc:
                    self.errors.append(f"transactions:{label}: {exc}")

        except CONTEXT_COMPONENT_ERRORS as exc:
            self.errors.append(f"transactions: {exc}")

    def _assemble_history_metadata(self) -> None:
        """Attach latest history DB provenance for downstream tools."""
        try:
            store = HistoryStore()
            rows = store.list_runs(limit=1)
            latest = rows[0] if rows else None
            self.history = {
                "snapshot_id": latest.get("snapshot_id") if latest else None,
                "db_path": str(store.path),
            }
        except (ConfigError, OSError, sqlite3.Error) as exc:
            self.errors.append(f"history: {exc}")

    def _policy_account_key(self, account: AccountSnapshot) -> str:
        if account.account_alias:
            return account.account_alias
        if account.account_number:
            from config.secure_account_config import secure_config

            info = secure_config.get_account_info_by_number(str(account.account_number))
            if info:
                return info.alias
        return account.account

    def _evaluate_policy(self) -> None:
        """Run policy engine against current state."""
        try:
            account_balances: dict[str, dict[str, float]] = {}
            for account in self.accounts:
                account_balances[self._policy_account_key(account)] = {
                    "total_value": account.total_value,
                    "cash": account.total_cash,
                }

            total_cash_pct = self.summary.cash_percentage if self.summary else 0

            self.policy_delta = evaluate_policy(
                account_balances=account_balances,
                ytd_distributions=self.ytd_distributions,
                total_cash_pct=total_cash_pct,
            )
        except CONTEXT_COMPONENT_ERRORS as exc:
            self.errors.append(f"policy: {exc}")

    def to_dict(self) -> JsonObject:
        """Serialize full context for JSON output."""
        return {
            "assembled_at": self.assembled_at,
            "summary": self.summary.to_dict() if self.summary else None,
            "accounts": [a.to_dict() for a in self.accounts],
            "vix": self.vix.to_dict() if self.vix else None,
            "regime": self.regime.to_dict() if self.regime else None,
            "market": self.market.to_dict() if self.market else None,
            "market_available": self.market_available,
            "polymarket": self.polymarket.to_dict() if self.polymarket else None,
            "lynch": self.lynch.to_dict() if self.lynch else None,
            "ytd_distributions": self.ytd_distributions,
            "recent_transactions": [txn.to_dict() for txn in self.recent_transactions],
            "policy_delta": self.policy_delta.to_dict() if self.policy_delta else None,
            "history": self.history,
            "manual_accounts_included": self.manual_accounts_included,
            "errors": self.errors if self.errors else None,
        }

    def to_prompt_block(self) -> str:
        """Render context as a text block suitable for embedding in LLM prompts.

        This is the key method — it produces the structured context that the
        finance analyst prompt, morning brief, and weekly review all consume.
        """
        lines: list[str] = []

        # --- Portfolio summary ---
        if self.summary:
            lines.append("## Portfolio Summary")
            lines.append(f"Total Value: ${self.summary.total_value:,.0f}")
            lines.append(
                f"Total Cash: ${self.summary.total_cash:,.0f} ({self.summary.cash_percentage:.1f}%)"
            )
            lines.append(f"Invested: ${self.summary.total_invested:,.0f}")
            lines.append(f"Unrealized P&L: ${self.summary.total_unrealized_pl:,.0f}")
            lines.append(
                f"Accounts: {self.summary.account_count} | Positions: {self.summary.position_count}"
            )
            lines.append("")

        # --- Account breakdown ---
        if self.accounts:
            lines.append("## Accounts")
            for account_snapshot in self.accounts:
                cash_pct = (
                    account_snapshot.total_cash / account_snapshot.total_value * 100
                    if account_snapshot.total_value > 0
                    else 0
                )
                lines.append(
                    f"- {account_snapshot.account}: ${account_snapshot.total_value:,.0f} "
                    f"(cash ${account_snapshot.total_cash:,.0f} = {cash_pct:.0f}%)"
                )
            lines.append("")

        # --- Market context ---
        lines.append("## Market Context")
        if not self.market_available and not (self.vix or self.regime):
            lines.append("Market data unavailable.")
        if self.vix:
            lines.append(f"VIX: {self.vix.vix:.1f} ({self.vix.signal}) — {self.vix.interpretation}")
        if self.regime:
            lines.append(f"Regime: {self.regime.regime.upper()} — {self.regime.description}")
        lines.append("")

        # --- Polymarket ---
        if self.polymarket and self.polymarket.signals:
            lines.append("## Macro Probabilities (Polymarket)")
            lines.extend(self.polymarket.summary_lines())
            lines.append("")

        # --- Distribution pacing ---
        if self.policy_delta and self.policy_delta.distribution_pacing:
            lines.append("## Distribution Pacing (2026)")
            for p in self.policy_delta.distribution_pacing:
                status = "ON TRACK" if p.on_track else "BEHIND"
                lines.append(
                    f"- {p.account}: ${p.ytd_distributions:,.0f} / ${p.annual_floor:,.0f} "
                    f"({p.pacing_pct:.0f}%) — {status} "
                    f"[{p.years_remaining}yr to {p.deadline.isoformat()}]"
                )
            lines.append("")

        # --- Policy alerts ---
        if self.policy_delta and self.policy_delta.alerts:
            lines.append("## Policy Alerts")
            for alert in self.policy_delta.alerts:
                icon = {"critical": "!!!", "warning": "!!", "info": "!"}.get(alert.severity, "!")
                lines.append(f"[{icon}] {alert.bucket}: {alert.message}")
            lines.append("")

        # --- Calendar ---
        if self.policy_delta and self.policy_delta.calendar_actions:
            lines.append("## Calendar Actions")
            for c in self.policy_delta.calendar_actions:
                lines.append(f"- {c}")
            lines.append("")

        # --- Lynch ---
        if self.lynch:
            lines.append("## Lynch Sell Signals")
            if self.lynch.signals_found == 0:
                lines.append(f"0 signals across {self.lynch.total_checked} positions checked.")
            else:
                lines.append(
                    f"{self.lynch.signals_found} signals across "
                    f"{self.lynch.total_checked} positions:"
                )
                for f in self.lynch.flagged:
                    for s in f.get("signals", []):
                        lines.append(f"- {f['symbol']}: {s['trigger']} ({s['detail']})")
            lines.append("")

        # --- Errors ---
        if self.errors:
            lines.append("## Context Errors")
            for e in self.errors:
                lines.append(f"- {e}")
            lines.append("")

        return "\n".join(lines)
