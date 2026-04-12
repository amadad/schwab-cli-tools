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

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from src.core.models import (
    AccountSnapshot,
    MarketSnapshot,
    PortfolioSummary,
    VixSnapshot,
)
from src.schwab_client.history import HistoryStore

from .market_service import get_market_regime, get_vix
from .policy import PolicyDelta, evaluate_policy, load_policy_config
from .polymarket import PolymarketSnapshot, fetch_polymarket_signals


@dataclass(slots=True)
class TransactionRecord:
    """A single transaction from the Schwab API."""

    date: str
    account: str
    type: str  # JOURNAL, TRADE, DIVIDEND, etc.
    description: str = ""
    amount: float = 0.0
    symbol: str | None = None
    quantity: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransactionRecord:
        return cls(
            date=str(data.get("date") or ""),
            account=str(data.get("account") or ""),
            type=str(data.get("type") or ""),
            description=str(data.get("description") or ""),
            amount=float(data.get("amount", 0.0) or 0.0),
            symbol=str(data["symbol"]) if data.get("symbol") is not None else None,
            quantity=float(data["quantity"]) if data.get("quantity") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "date": self.date,
            "account": self.account,
            "type": self.type,
            "description": self.description,
            "amount": self.amount,
        }
        if self.symbol:
            d["symbol"] = self.symbol
        if self.quantity is not None:
            d["quantity"] = self.quantity
        return d


@dataclass(slots=True)
class RegimeSnapshot:
    """Market regime data."""

    regime: str = "unknown"
    description: str = ""
    risk_on: bool = False
    rates_rising: bool = False
    signals: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegimeSnapshot:
        return cls(
            regime=str(data.get("regime") or "unknown"),
            description=str(data.get("description") or ""),
            risk_on=bool(data.get("risk_on", False)),
            rates_rising=bool(data.get("rates_rising", False)),
            signals={
                str(key): float(value)
                for key, value in (data.get("signals") or {}).items()
                if value is not None
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "description": self.description,
            "risk_on": self.risk_on,
            "rates_rising": self.rates_rising,
            "signals": self.signals,
        }


@dataclass(slots=True)
class LynchResult:
    """Lynch sell signal analysis result."""

    total_checked: int = 0
    signals_found: int = 0
    flagged: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LynchResult:
        return cls(
            total_checked=int(data.get("total_checked", 0) or 0),
            signals_found=int(data.get("signals_found", 0) or 0),
            flagged=[dict(item) for item in data.get("flagged", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_checked": self.total_checked,
            "signals_found": self.signals_found,
            "flagged": self.flagged,
        }


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
    history: dict[str, Any] | None = None
    manual_accounts_included: bool = False
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PortfolioContext:
        return cls(
            summary=(
                PortfolioSummary.from_dict(data["summary"])
                if isinstance(data.get("summary"), dict)
                else None
            ),
            accounts=[
                AccountSnapshot.from_dict(account) for account in (data.get("accounts") or [])
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
                for key, value in (data.get("ytd_distributions") or {}).items()
                if value is not None
            },
            recent_transactions=[
                TransactionRecord.from_dict(item)
                for item in (data.get("recent_transactions") or [])
            ],
            policy_delta=(
                PolicyDelta.from_dict(data["policy_delta"])
                if isinstance(data.get("policy_delta"), dict)
                else None
            ),
            assembled_at=str(data.get("assembled_at") or ""),
            history=dict(data["history"]) if isinstance(data.get("history"), dict) else None,
            manual_accounts_included=bool(data.get("manual_accounts_included", False)),
            errors=[str(item) for item in (data.get("errors") or [])],
        )

    @classmethod
    def assemble(
        cls,
        client: Any,
        *,
        market_client: Any | None = None,
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
            ctx._assemble_lynch(client, market_client)

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

    def _assemble_portfolio(self, client: Any) -> None:
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
        except Exception as exc:
            self.errors.append(f"portfolio: {exc}")

    def _assemble_market(self, market_client: Any) -> None:
        """Fetch VIX, regime, and full market snapshot."""
        from .market_service import get_market_indices, get_market_signals, get_sector_performance
        from .models import IndicesSnapshot, MarketSignalsSnapshot, SectorPerformanceSnapshot

        signals = None
        indices = None
        sectors = None

        try:
            signals = MarketSignalsSnapshot.from_dict(get_market_signals(market_client))
        except Exception as exc:
            self.errors.append(f"market.signals: {exc}")

        try:
            vix_data = get_vix(market_client)
            self.vix = VixSnapshot.from_dict(vix_data)
        except Exception as exc:
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
        except Exception as exc:
            self.errors.append(f"regime: {exc}")

        try:
            indices = IndicesSnapshot.from_dict(get_market_indices(market_client))
        except Exception as exc:
            self.errors.append(f"market.indices: {exc}")

        try:
            sectors = SectorPerformanceSnapshot.from_dict(get_sector_performance(market_client))
        except Exception as exc:
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
        except Exception as exc:
            self.errors.append(f"polymarket: {exc}")

    def _assemble_lynch(self, client: Any, market_client: Any) -> None:
        """Run Lynch sell signal analysis on current holdings."""
        try:
            from src.core.lynch_service import analyze_holdings_lynch

            positions = self.summary.positions if self.summary else []
            equity_symbols = [
                p.symbol
                for p in positions
                if p.asset_type in ("EQUITY", "ETF") and not p.is_money_market
            ]

            if not equity_symbols:
                self.lynch = LynchResult(total_checked=0)
                return

            holdings_data = []
            for symbol in equity_symbols[:50]:  # cap to avoid API overload
                try:
                    quote_data = market_client.get_quote(symbol)
                    if hasattr(quote_data, "json"):
                        quote_data = quote_data.json()
                    symbol_data = quote_data.get(symbol, {})
                    fundamentals = symbol_data.get("fundamental", {})
                    quote = symbol_data.get("quote", {})
                    fundamentals.update(
                        {
                            "lastPrice": quote.get("lastPrice"),
                            "high52": quote.get("52WkHigh"),
                            "low52": quote.get("52WkLow"),
                        }
                    )
                    holdings_data.append({"symbol": symbol, "fundamentals": fundamentals})
                except Exception:
                    continue

            results = analyze_holdings_lynch(holdings_data)
            flagged = [r for r in results if r.get("signals")]
            self.lynch = LynchResult(
                total_checked=len(results),
                signals_found=len(flagged),
                flagged=flagged,
            )
        except Exception as exc:
            self.errors.append(f"lynch: {exc}")

    def _assemble_transactions(
        self,
        client: Any,
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
                account_info = secure_config.get_account_info_by_number(account_number)
                if not account_info:
                    continue
                alias = account_info.alias
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
                                self.ytd_distributions[label] = (
                                    self.ytd_distributions.get(label, 0) + abs(amount)
                                )
                except Exception as exc:
                    self.errors.append(f"transactions:{label}: {exc}")

        except Exception as exc:
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
        except Exception as exc:
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
        except Exception as exc:
            self.errors.append(f"policy: {exc}")

    def to_dict(self) -> dict[str, Any]:
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
            lines.append(f"Total Cash: ${self.summary.total_cash:,.0f} ({self.summary.cash_percentage:.1f}%)")
            lines.append(f"Invested: ${self.summary.total_invested:,.0f}")
            lines.append(f"Unrealized P&L: ${self.summary.total_unrealized_pl:,.0f}")
            lines.append(f"Accounts: {self.summary.account_count} | Positions: {self.summary.position_count}")
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
                icon = {"critical": "!!!", "warning": "!!", "info": "!"}.get(
                    alert.severity, "!"
                )
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
