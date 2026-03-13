"""Peter Lynch sell-signal analysis for portfolio holdings."""

from __future__ import annotations

from typing import Any


# Lynch company type classification based on fundamentals
def classify_company_type(fundamentals: dict[str, Any]) -> str:
    """Classify a company into Lynch categories based on fundamentals."""
    pe = fundamentals.get("peRatio") or 0
    eps_growth = fundamentals.get("epsTTMGrowthRate5Y") or 0
    div_yield = fundamentals.get("dividendYield") or 0

    if eps_growth > 20:
        return "fast_grower"
    if pe > 0 and pe < 10 and div_yield > 3:
        return "slow_grower"
    if 10 <= eps_growth <= 20:
        return "stalwart"
    if pe == 0 or pe < 0:
        return "turnaround"
    return "stalwart"


def check_sell_signals(company_type: str, fundamentals: dict[str, Any]) -> list[dict[str, str]]:
    """Check Lynch sell signals for a given company type and fundamentals."""
    signals = []
    pe = fundamentals.get("peRatio") or 0
    eps_growth = fundamentals.get("epsTTMGrowthRate5Y") or 0
    payout_ratio = fundamentals.get("dividendPayoutRatio") or 0
    high52 = fundamentals.get("high52") or 0
    low52 = fundamentals.get("low52") or 0
    price = fundamentals.get("lastPrice") or 0

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


def analyze_holdings_lynch(holdings_fundamentals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Analyze a list of holdings with Lynch sell-signal framework.

    Each entry should have 'symbol' and 'fundamentals' keys.
    Returns analysis with classification and signals per holding.
    """
    results = []
    for holding in holdings_fundamentals:
        symbol = holding["symbol"]
        fund = holding.get("fundamentals", {})

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
