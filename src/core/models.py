"""Typed domain models for portfolio snapshots and history storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

from src.core.json_types import JsonValue


class _SerializableModel:
    def to_dict(self) -> dict[str, JsonValue]:  # pragma: no cover - interface only
        raise NotImplementedError


ModelValue = _SerializableModel | list[JsonValue] | dict[str, JsonValue] | JsonValue


def _string(value: JsonValue) -> str | None:
    if value is None:
        return None
    return str(value)


def _float(value: JsonValue, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def _optional_float(value: JsonValue) -> float | None:
    if value is None:
        return None
    return float(value)


def _int(value: JsonValue, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


def _optional_int(value: JsonValue) -> int | None:
    if value is None:
        return None
    return int(value)


def _serialize(value: ModelValue) -> JsonValue:
    if isinstance(value, _SerializableModel):
        return value.to_dict()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items() if item is not None}
    return value


def _compact_dict(data: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {key: _serialize(value) for key, value in data.items() if value is not None}


@dataclass(slots=True)
class SnapshotError(_SerializableModel):
    component: str
    message: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            component=str(data.get("component", "unknown")),
            message=str(data.get("message", "")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {"component": self.component, "message": self.message}


@dataclass(slots=True)
class PositionSnapshot(_SerializableModel):
    symbol: str
    description: str | None = None
    quantity: float = 0.0
    market_value: float = 0.0
    average_price: float = 0.0
    cost_basis: float = 0.0
    unrealized_pl: float | None = None
    day_pl: float | None = None
    day_pl_pct: float | None = None
    percentage: float | None = None
    percentage_of_portfolio: float | None = None
    account: str | None = None
    account_number: str | None = None
    account_alias: str | None = None
    account_number_masked: str | None = None
    account_number_last4: str | None = None
    asset_type: str = "UNKNOWN"
    is_money_market: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            symbol=str(data.get("symbol", "")),
            description=_string(data.get("description")),
            quantity=_float(data.get("quantity")),
            market_value=_float(data.get("market_value")),
            average_price=_float(data.get("average_price")),
            cost_basis=_float(data.get("cost_basis")),
            unrealized_pl=_optional_float(data.get("unrealized_pl")),
            day_pl=_optional_float(data.get("day_pl")),
            day_pl_pct=_optional_float(data.get("day_pl_pct")),
            percentage=_optional_float(data.get("percentage")),
            percentage_of_portfolio=_optional_float(data.get("percentage_of_portfolio")),
            account=_string(data.get("account")),
            account_number=_string(data.get("account_number")),
            account_alias=_string(data.get("account_alias")),
            account_number_masked=_string(data.get("account_number_masked")),
            account_number_last4=_string(data.get("account_number_last4")),
            asset_type=str(data.get("asset_type", "UNKNOWN")),
            is_money_market=bool(data.get("is_money_market")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return _compact_dict(
            {
                "symbol": self.symbol,
                "description": self.description,
                "quantity": self.quantity,
                "market_value": self.market_value,
                "average_price": self.average_price,
                "cost_basis": self.cost_basis,
                "unrealized_pl": self.unrealized_pl,
                "day_pl": self.day_pl,
                "day_pl_pct": self.day_pl_pct,
                "percentage": self.percentage,
                "percentage_of_portfolio": self.percentage_of_portfolio,
                "account": self.account,
                "account_number": self.account_number,
                "account_alias": self.account_alias,
                "account_number_masked": self.account_number_masked,
                "account_number_last4": self.account_number_last4,
                "asset_type": self.asset_type,
                "is_money_market": self.is_money_market,
            }
        )


@dataclass(slots=True)
class AccountBalance(_SerializableModel):
    account: str
    account_name: str
    account_type: str | None = None
    total_value: float = 0.0
    cash_balance: float = 0.0
    money_market_value: float = 0.0
    buying_power: float = 0.0
    invested_amount: float = 0.0

    def to_dict(self) -> dict[str, JsonValue]:
        return _compact_dict(
            {
                "account": self.account,
                "account_name": self.account_name,
                "account_type": self.account_type,
                "total_value": self.total_value,
                "cash_balance": self.cash_balance,
                "money_market_value": self.money_market_value,
                "buying_power": self.buying_power,
                "invested_amount": self.invested_amount,
            }
        )


@dataclass(slots=True)
class AccountSnapshot(_SerializableModel):
    account: str
    account_type: str | None = None
    account_number: str | None = None
    account_alias: str | None = None
    account_number_masked: str | None = None
    account_number_last4: str | None = None
    total_value: float = 0.0
    cash_balance: float = 0.0
    money_market_value: float = 0.0
    total_cash: float = 0.0
    invested_value: float = 0.0
    buying_power: float = 0.0
    position_count: int | None = None
    positions: list[PositionSnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            account=str(data.get("account") or data.get("name") or "Unknown"),
            account_type=_string(data.get("account_type") or data.get("type")),
            account_number=_string(data.get("account_number")),
            account_alias=_string(data.get("account_alias")),
            account_number_masked=_string(data.get("account_number_masked")),
            account_number_last4=_string(data.get("account_number_last4") or data.get("last_four")),
            total_value=_float(data.get("total_value")),
            cash_balance=_float(data.get("cash_balance")),
            money_market_value=_float(data.get("money_market_value")),
            total_cash=_float(data.get("total_cash")),
            invested_value=_float(data.get("invested_value")),
            buying_power=_float(data.get("buying_power")),
            position_count=_optional_int(data.get("position_count")),
            positions=[
                PositionSnapshot.from_dict(position) for position in data.get("positions", [])
            ],
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return _compact_dict(
            {
                "account": self.account,
                "account_type": self.account_type,
                "account_number": self.account_number,
                "account_alias": self.account_alias,
                "account_number_masked": self.account_number_masked,
                "account_number_last4": self.account_number_last4,
                "total_value": self.total_value,
                "cash_balance": self.cash_balance,
                "money_market_value": self.money_market_value,
                "total_cash": self.total_cash,
                "invested_value": self.invested_value,
                "buying_power": self.buying_power,
                "position_count": self.position_count,
                "positions": self.positions,
            }
        )


@dataclass(slots=True)
class ManualAccount(_SerializableModel):
    name: str
    value: float = 0.0
    id: str | None = None
    last_four: str | None = None
    type: str | None = None
    category: str | None = None
    provider: str | None = None
    tax_status: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            id=_string(data.get("id")),
            name=str(data.get("name") or data.get("account") or "Unknown"),
            last_four=_string(data.get("last_four") or data.get("account_number_last4")),
            type=_string(data.get("type") or data.get("account_type")),
            category=_string(data.get("category")),
            provider=_string(data.get("provider")),
            tax_status=_string(data.get("tax_status")),
            value=_float(data.get("value")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return _compact_dict(
            {
                "id": self.id,
                "name": self.name,
                "last_four": self.last_four,
                "type": self.type,
                "category": self.category,
                "provider": self.provider,
                "tax_status": self.tax_status,
                "value": self.value,
            }
        )


@dataclass(slots=True)
class ManualAccountsSummary(_SerializableModel):
    total_value: float = 0.0
    total_cash: float = 0.0
    total_invested: float = 0.0
    account_count: int = 0
    by_category: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            total_value=_float(data.get("total_value")),
            total_cash=_float(data.get("total_cash")),
            total_invested=_float(data.get("total_invested")),
            account_count=_int(data.get("account_count")),
            by_category={
                str(category): _float(value)
                for category, value in (data.get("by_category") or {}).items()
            },
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "total_value": self.total_value,
            "total_cash": self.total_cash,
            "total_invested": self.total_invested,
            "account_count": self.account_count,
            "by_category": dict(self.by_category),
        }


@dataclass(slots=True)
class ManualAccountsPayload(_SerializableModel):
    source_path: str | None = None
    last_updated: str | None = None
    accounts: list[ManualAccount] = field(default_factory=list)
    summary: ManualAccountsSummary = field(default_factory=ManualAccountsSummary)

    @classmethod
    def empty(cls, *, source_path: str | None = None) -> Self:
        return cls(source_path=source_path)

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            source_path=_string(data.get("source_path")),
            last_updated=_string(data.get("last_updated")),
            accounts=[ManualAccount.from_dict(account) for account in data.get("accounts", [])],
            summary=ManualAccountsSummary.from_dict(data.get("summary", {})),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "source_path": self.source_path,
            "last_updated": self.last_updated,
            "accounts": [account.to_dict() for account in self.accounts],
            "summary": self.summary.to_dict(),
        }


@dataclass(slots=True)
class AllocationSlice(_SerializableModel):
    value: float = 0.0
    percentage: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            value=_float(data.get("value")),
            percentage=_float(data.get("percentage")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {"value": self.value, "percentage": self.percentage}


@dataclass(slots=True)
class TopHolding(_SerializableModel):
    symbol: str
    percentage: float = 0.0
    value: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            symbol=str(data.get("symbol", "")),
            percentage=_float(data.get("percentage")),
            value=_float(data.get("value")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "symbol": self.symbol,
            "percentage": self.percentage,
            "value": self.value,
        }


@dataclass(slots=True)
class ConcentrationRisk(_SerializableModel):
    symbol: str
    percentage: float = 0.0
    value: float = 0.0
    risk_level: str = "Unknown"

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            symbol=str(data.get("symbol", "")),
            percentage=_float(data.get("percentage")),
            value=_float(data.get("value")),
            risk_level=str(data.get("risk_level", "Unknown")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "symbol": self.symbol,
            "percentage": self.percentage,
            "value": self.value,
            "risk_level": self.risk_level,
        }


@dataclass(slots=True)
class AllocationAnalysis(_SerializableModel):
    diversification_score: float = 0.0
    by_asset_type: dict[str, AllocationSlice] = field(default_factory=dict)
    concentration_risks: list[ConcentrationRisk] = field(default_factory=list)
    top_holdings_pct: list[TopHolding] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            diversification_score=_float(data.get("diversification_score")),
            by_asset_type={
                str(asset_type): AllocationSlice.from_dict(entry)
                for asset_type, entry in (data.get("by_asset_type") or {}).items()
            },
            concentration_risks=[
                ConcentrationRisk.from_dict(entry) for entry in data.get("concentration_risks", [])
            ],
            top_holdings_pct=[
                TopHolding.from_dict(entry) for entry in data.get("top_holdings_pct", [])
            ],
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "diversification_score": self.diversification_score,
            "by_asset_type": {
                asset_type: entry.to_dict() for asset_type, entry in self.by_asset_type.items()
            },
            "concentration_risks": [risk.to_dict() for risk in self.concentration_risks],
            "top_holdings_pct": [holding.to_dict() for holding in self.top_holdings_pct],
        }


@dataclass(slots=True)
class PortfolioSummary(_SerializableModel):
    total_value: float = 0.0
    total_cash: float = 0.0
    total_invested: float = 0.0
    total_unrealized_pl: float = 0.0
    cash_percentage: float = 0.0
    account_count: int = 0
    position_count: int = 0
    positions: list[PositionSnapshot] = field(default_factory=list)
    api_value: float | None = None
    manual_value: float | None = None
    manual_cash: float | None = None
    api_account_count: int | None = None
    manual_account_count: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            total_value=_float(data.get("total_value")),
            total_cash=_float(data.get("total_cash")),
            total_invested=_float(data.get("total_invested")),
            total_unrealized_pl=_float(data.get("total_unrealized_pl")),
            cash_percentage=_float(data.get("cash_percentage")),
            account_count=_int(data.get("account_count")),
            position_count=_int(data.get("position_count")),
            positions=[
                PositionSnapshot.from_dict(position) for position in data.get("positions", [])
            ],
            api_value=_optional_float(data.get("api_value")),
            manual_value=_optional_float(data.get("manual_value")),
            manual_cash=_optional_float(data.get("manual_cash")),
            api_account_count=_optional_int(data.get("api_account_count")),
            manual_account_count=_optional_int(data.get("manual_account_count")),
        )

    def to_dict(self, *, include_positions: bool = False) -> dict[str, JsonValue]:
        data = _compact_dict(
            {
                "total_value": self.total_value,
                "api_value": self.api_value,
                "manual_value": self.manual_value,
                "total_cash": self.total_cash,
                "manual_cash": self.manual_cash,
                "total_invested": self.total_invested,
                "total_unrealized_pl": self.total_unrealized_pl,
                "cash_percentage": self.cash_percentage,
                "account_count": self.account_count,
                "api_account_count": self.api_account_count,
                "manual_account_count": self.manual_account_count,
                "position_count": self.position_count,
            }
        )
        if include_positions:
            data["positions"] = [position.to_dict() for position in self.positions]
        return data


@dataclass(slots=True)
class MarketSignalDetails(_SerializableModel):
    vix: dict[str, JsonValue] | None = None
    market_sentiment: str | None = None
    sector_rotation: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        vix_payload = data.get("vix")
        return cls(
            vix=dict(vix_payload) if isinstance(vix_payload, dict) else None,
            market_sentiment=_string(data.get("market_sentiment")),
            sector_rotation=_string(data.get("sector_rotation")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return _compact_dict(
            {
                "vix": self.vix,
                "market_sentiment": self.market_sentiment,
                "sector_rotation": self.sector_rotation,
            }
        )


@dataclass(slots=True)
class MarketSignalsSnapshot(_SerializableModel):
    signals: MarketSignalDetails = field(default_factory=MarketSignalDetails)
    overall: str | None = None
    recommendation: str | None = None
    timestamp: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            signals=MarketSignalDetails.from_dict(data.get("signals", {})),
            overall=_string(data.get("overall")),
            recommendation=_string(data.get("recommendation")),
            timestamp=_string(data.get("timestamp")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return _compact_dict(
            {
                "signals": self.signals,
                "overall": self.overall,
                "recommendation": self.recommendation,
                "timestamp": self.timestamp,
            }
        )


@dataclass(slots=True)
class VixSnapshot(_SerializableModel):
    vix: float | None = None
    change: float | None = None
    change_pct: float | None = None
    signal: str | None = None
    interpretation: str | None = None
    timestamp: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            vix=_optional_float(data.get("vix")),
            change=_optional_float(data.get("change")),
            change_pct=_optional_float(data.get("change_pct")),
            signal=_string(data.get("signal")),
            interpretation=_string(data.get("interpretation")),
            timestamp=_string(data.get("timestamp")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return _compact_dict(
            {
                "vix": self.vix,
                "change": self.change,
                "change_pct": self.change_pct,
                "signal": self.signal,
                "interpretation": self.interpretation,
                "timestamp": self.timestamp,
            }
        )


@dataclass(slots=True)
class IndexQuote(_SerializableModel):
    name: str | None = None
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            name=_string(data.get("name")),
            price=_optional_float(data.get("price")),
            change=_optional_float(data.get("change")),
            change_pct=_optional_float(data.get("change_pct")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return _compact_dict(
            {
                "name": self.name,
                "price": self.price,
                "change": self.change,
                "change_pct": self.change_pct,
            }
        )


@dataclass(slots=True)
class IndicesSnapshot(_SerializableModel):
    indices: dict[str, IndexQuote] = field(default_factory=dict)
    sentiment: str | None = None
    timestamp: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            indices={
                str(symbol): IndexQuote.from_dict(entry)
                for symbol, entry in (data.get("indices") or {}).items()
            },
            sentiment=_string(data.get("sentiment")),
            timestamp=_string(data.get("timestamp")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return _compact_dict(
            {
                "indices": {symbol: entry.to_dict() for symbol, entry in self.indices.items()},
                "sentiment": self.sentiment,
                "timestamp": self.timestamp,
            }
        )


@dataclass(slots=True)
class SectorPerformanceEntry(_SerializableModel):
    symbol: str | None = None
    sector: str | None = None
    price: float | None = None
    change_pct: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            symbol=_string(data.get("symbol")),
            sector=_string(data.get("sector")),
            price=_optional_float(data.get("price")),
            change_pct=_optional_float(data.get("change_pct")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return _compact_dict(
            {
                "symbol": self.symbol,
                "sector": self.sector,
                "price": self.price,
                "change_pct": self.change_pct,
            }
        )


@dataclass(slots=True)
class SectorPerformanceSnapshot(_SerializableModel):
    sectors: list[SectorPerformanceEntry] = field(default_factory=list)
    leaders: list[str] = field(default_factory=list)
    laggards: list[str] = field(default_factory=list)
    rotation: str | None = None
    cyclical_avg: float | None = None
    defensive_avg: float | None = None
    timestamp: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            sectors=[SectorPerformanceEntry.from_dict(entry) for entry in data.get("sectors", [])],
            leaders=[str(item) for item in data.get("leaders", [])],
            laggards=[str(item) for item in data.get("laggards", [])],
            rotation=_string(data.get("rotation")),
            cyclical_avg=_optional_float(data.get("cyclical_avg")),
            defensive_avg=_optional_float(data.get("defensive_avg")),
            timestamp=_string(data.get("timestamp")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return _compact_dict(
            {
                "sectors": [entry.to_dict() for entry in self.sectors],
                "leaders": list(self.leaders),
                "laggards": list(self.laggards),
                "rotation": self.rotation,
                "cyclical_avg": self.cyclical_avg,
                "defensive_avg": self.defensive_avg,
                "timestamp": self.timestamp,
            }
        )


@dataclass(slots=True)
class MarketSnapshot(_SerializableModel):
    signals: MarketSignalsSnapshot | None = None
    vix: VixSnapshot | None = None
    indices: IndicesSnapshot | None = None
    sectors: SectorPerformanceSnapshot | None = None

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        signals_payload = data.get("signals")
        vix_payload = data.get("vix")
        indices_payload = data.get("indices")
        sectors_payload = data.get("sectors")
        return cls(
            signals=(
                MarketSignalsSnapshot.from_dict(signals_payload)
                if isinstance(signals_payload, dict)
                else None
            ),
            vix=VixSnapshot.from_dict(vix_payload) if isinstance(vix_payload, dict) else None,
            indices=(
                IndicesSnapshot.from_dict(indices_payload)
                if isinstance(indices_payload, dict)
                else None
            ),
            sectors=(
                SectorPerformanceSnapshot.from_dict(sectors_payload)
                if isinstance(sectors_payload, dict)
                else None
            ),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "signals": self.signals.to_dict() if self.signals else None,
            "vix": self.vix.to_dict() if self.vix else None,
            "indices": self.indices.to_dict() if self.indices else None,
            "sectors": self.sectors.to_dict() if self.sectors else None,
        }


@dataclass(slots=True)
class PortfolioSnapshot(_SerializableModel):
    summary: PortfolioSummary
    api_accounts: list[AccountSnapshot] = field(default_factory=list)
    manual_accounts: ManualAccountsPayload = field(default_factory=ManualAccountsPayload)
    positions: list[PositionSnapshot] = field(default_factory=list)
    allocation: AllocationAnalysis | None = None

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        manual_accounts_payload = data.get("manual_accounts") or {}
        return cls(
            summary=PortfolioSummary.from_dict(data.get("summary", {})),
            api_accounts=[
                AccountSnapshot.from_dict(account) for account in data.get("api_accounts", [])
            ],
            manual_accounts=ManualAccountsPayload.from_dict(manual_accounts_payload),
            positions=[
                PositionSnapshot.from_dict(position) for position in data.get("positions", [])
            ],
            allocation=(
                AllocationAnalysis.from_dict(data["allocation"])
                if isinstance(data.get("allocation"), dict)
                else None
            ),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "summary": self.summary.to_dict(),
            "api_accounts": [account.to_dict() for account in self.api_accounts],
            "manual_accounts": self.manual_accounts.to_dict(),
            "positions": [position.to_dict() for position in self.positions],
            "allocation": self.allocation.to_dict() if self.allocation else None,
        }


@dataclass(slots=True)
class SnapshotDocument(_SerializableModel):
    generated_at: str
    portfolio: PortfolioSnapshot
    market: MarketSnapshot | None = None
    errors: list[SnapshotError] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Self:
        return cls(
            generated_at=str(data.get("generated_at") or data.get("timestamp") or ""),
            portfolio=PortfolioSnapshot.from_dict(data.get("portfolio", {})),
            market=(
                MarketSnapshot.from_dict(data["market"])
                if isinstance(data.get("market"), dict)
                else None
            ),
            errors=[SnapshotError.from_dict(error) for error in data.get("errors", [])],
        )

    def to_dict(self) -> dict[str, JsonValue]:
        data: dict[str, JsonValue] = {
            "generated_at": self.generated_at,
            "portfolio": self.portfolio.to_dict(),
            "market": self.market.to_dict() if self.market else None,
        }
        if self.errors:
            data["errors"] = [error.to_dict() for error in self.errors]
        return data
