"""Typed helper models used by :mod:`src.core.context`."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.json_types import JsonObject


@dataclass(slots=True)
class TransactionRecord:
    """A single transaction from the Schwab API."""

    date: str
    account: str
    type: str
    description: str = ""
    amount: float = 0.0
    symbol: str | None = None
    quantity: float | None = None

    @classmethod
    def from_dict(cls, data: JsonObject) -> TransactionRecord:
        return cls(
            date=str(data.get("date") or ""),
            account=str(data.get("account") or ""),
            type=str(data.get("type") or ""),
            description=str(data.get("description") or ""),
            amount=float(data.get("amount", 0.0) or 0.0),
            symbol=str(data["symbol"]) if data.get("symbol") is not None else None,
            quantity=float(data["quantity"]) if data.get("quantity") is not None else None,
        )

    def to_dict(self) -> JsonObject:
        data: JsonObject = {
            "date": self.date,
            "account": self.account,
            "type": self.type,
            "description": self.description,
            "amount": self.amount,
        }
        if self.symbol:
            data["symbol"] = self.symbol
        if self.quantity is not None:
            data["quantity"] = self.quantity
        return data


@dataclass(slots=True)
class RegimeSnapshot:
    """Market regime data."""

    regime: str = "unknown"
    description: str = ""
    risk_on: bool = False
    rates_rising: bool = False
    signals: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: JsonObject) -> RegimeSnapshot:
        raw_signals = data.get("signals")
        signals = raw_signals if isinstance(raw_signals, dict) else {}
        return cls(
            regime=str(data.get("regime") or "unknown"),
            description=str(data.get("description") or ""),
            risk_on=bool(data.get("risk_on", False)),
            rates_rising=bool(data.get("rates_rising", False)),
            signals={str(key): float(value) for key, value in signals.items() if value is not None},
        )

    def to_dict(self) -> JsonObject:
        return {
            "regime": self.regime,
            "description": self.description,
            "risk_on": self.risk_on,
            "rates_rising": self.rates_rising,
            "signals": dict(self.signals),
        }


@dataclass(slots=True)
class LynchResult:
    """Lynch sell-signal analysis result."""

    total_checked: int = 0
    signals_found: int = 0
    flagged: list[JsonObject] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: JsonObject) -> LynchResult:
        raw_flagged = data.get("flagged")
        flagged = (
            [item for item in raw_flagged if isinstance(item, dict)]
            if isinstance(raw_flagged, list)
            else []
        )
        return cls(
            total_checked=int(data.get("total_checked", 0) or 0),
            signals_found=int(data.get("signals_found", 0) or 0),
            flagged=flagged,
        )

    def to_dict(self) -> JsonObject:
        return {
            "total_checked": self.total_checked,
            "signals_found": self.signals_found,
            "flagged": [dict(item) for item in self.flagged],
        }
