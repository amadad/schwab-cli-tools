"""Peter Lynch sell-signal analysis for portfolio holdings."""

from __future__ import annotations

from typing import TypedDict

LynchSignal = TypedDict(  # noqa: UP013
    "LynchSignal",
    {
        "trigger": str,
        "detail": str,
        "severity": str,
    },
)

type HoldingFundamentals = dict[str, object]

HoldingInput = TypedDict(  # noqa: UP013
    "HoldingInput",
    {
        "symbol": str,
        "fundamentals": HoldingFundamentals,
    },
)

HoldingAnalysis = TypedDict(  # noqa: UP013
    "HoldingAnalysis",
    {
        "symbol": str,
        "company_type": str,
        "signals": list[LynchSignal],
        "pe_ratio": object,
        "eps_growth": object,
        "dividend_yield": object,
    },
)


def _as_float(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


# Lynch company type classification based on fundamentals
def classify_company_type(fundamentals: HoldingFundamentals) -> str:
    """Classify a company into Lynch categories based on fundamentals."""
    pe = _as_float(fundamentals.get("peRatio"))
    eps_growth = _as_float(fundamentals.get("epsTTMGrowthRate5Y"))
    div_yield = _as_float(fundamentals.get("dividendYield"))

    if eps_growth > 20:
        return "fast_grower"
    if pe > 0 and pe < 10 and div_yield > 3:
        return "slow_grower"
    if 10 <= eps_growth <= 20:
        return "stalwart"
    if pe == 0 or pe < 0:
        return "turnaround"
    return "stalwart"


def check_sell_signals(company_type: str, fundamentals: HoldingFundamentals) -> list[LynchSignal]:
    """Check Lynch sell signals for a given company type and fundamentals."""
    signals: list[LynchSignal] = []
    pe = _as_float(fundamentals.get("peRatio"))
    eps_growth = _as_float(fundamentals.get("epsTTMGrowthRate5Y"))
    payout_ratio = _as_float(fundamentals.get("dividendPayoutRatio"))
    high52 = _as_float(fundamentals.get("high52"))
    low52 = _as_float(fundamentals.get("low52"))
    price = _as_float(fundamentals.get("lastPrice"))

    if company_type == "stalwart":
        if pe > 0 and eps_growth > 0 and pe > eps_growth * 2:
            signals.append(
                {
                    "trigger": "P/E well above earnings growth",
                    "detail": f"P/E {pe:.1f} vs growth {eps_growth:.1f}%",
                    "severity": "warning",
                }
            )

    elif company_type == "fast_grower":
        if pe > 0 and eps_growth > 0 and pe > eps_growth:
            signals.append(
                {
                    "trigger": "P/E exceeds projected earnings growth (PEG > 1)",
                    "detail": f"P/E {pe:.1f} vs growth {eps_growth:.1f}%",
                    "severity": "warning",
                }
            )

    elif company_type == "slow_grower":
        if payout_ratio > 60:
            signals.append(
                {
                    "trigger": "Dividend payout ratio exceeds 60%",
                    "detail": f"Payout ratio: {payout_ratio:.1f}%",
                    "severity": "warning",
                }
            )

    elif company_type == "turnaround":
        if high52 > 0 and price > 0 and price > high52 * 0.9:
            signals.append(
                {
                    "trigger": "Price near 52-week high — turnaround widely recognized",
                    "detail": f"Price ${price:.2f} vs 52wk high ${high52:.2f}",
                    "severity": "info",
                }
            )

    # Universal signals
    if high52 > 0 and low52 > 0 and price > 0:
        range_pct = (price - low52) / (high52 - low52) * 100 if high52 != low52 else 50
        if range_pct > 95:
            signals.append(
                {
                    "trigger": "Trading at 52-week high",
                    "detail": f"At {range_pct:.0f}% of 52-week range",
                    "severity": "info",
                }
            )

    return signals


def analyze_holdings_lynch(holdings_fundamentals: list[HoldingInput]) -> list[HoldingAnalysis]:
    """Analyze a list of holdings with Lynch sell-signal framework.

    Each entry should have 'symbol' and 'fundamentals' keys.
    Returns analysis with classification and signals per holding.
    """
    results: list[HoldingAnalysis] = []
    for holding in holdings_fundamentals:
        symbol = str(holding.get("symbol") or "")
        raw_fund = holding.get("fundamentals")
        fund = raw_fund if isinstance(raw_fund, dict) else {}

        company_type = classify_company_type(fund)
        signals = check_sell_signals(company_type, fund)

        results.append(
            {
                "symbol": symbol,
                "company_type": company_type,
                "signals": signals,
                "pe_ratio": fund.get("peRatio"),
                "eps_growth": fund.get("epsTTMGrowthRate5Y"),
                "dividend_yield": fund.get("dividendYield"),
            }
        )

    return results
