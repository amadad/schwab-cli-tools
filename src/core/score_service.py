"""Compounding Quality 15-point stock scoring framework."""

from __future__ import annotations

from typing import Any

# 15 dimensions, scored 1-5. Max score = 75.
# PASS >= 60, WATCH 45-59, SELL < 45
DIMENSIONS = [
    "business_model",
    "management",
    "competitive_advantage",
    "industry_attractiveness",
    "main_risks",
    "balance_sheet",
    "capital_intensity",
    "capital_allocation",
    "profitability",
    "historical_growth",
    "stock_based_compensation",
    "outlook",
    "valuation",
    "owners_earnings",
    "historical_value_creation",
]


def score_from_fundamentals(symbol: str, fundamentals: dict[str, Any]) -> dict[str, Any]:
    """Score a stock on quantifiable dimensions using fundamentals data.

    Returns scored dimensions with values 1-5, and marks qualitative ones
    as requiring manual review (score=None).
    """
    scores: dict[str, dict[str, Any]] = {}

    pe = fundamentals.get("peRatio") or 0
    eps_growth_5y = fundamentals.get("epsTTMGrowthRate5Y") or 0
    rev_growth_5y = fundamentals.get("revenueGrowthRate5Y") or 0
    profit_margin = fundamentals.get("netProfitMarginTTM") or 0
    roe = fundamentals.get("returnOnEquity") or 0
    roic = fundamentals.get("returnOnInvestment") or 0
    div_yield = fundamentals.get("dividendYield") or 0
    debt_equity = fundamentals.get("totalDebtToEquity") or 0

    # Qualitative dimensions — need manual review
    for dim in [
        "business_model",
        "management",
        "competitive_advantage",
        "industry_attractiveness",
        "main_risks",
        "outlook",
    ]:
        scores[dim] = {"score": None, "note": "Requires qualitative analysis"}

    # Balance Sheet (quantifiable)
    if debt_equity <= 0.3:
        bs_score = 5
    elif debt_equity <= 0.6:
        bs_score = 4
    elif debt_equity <= 1.0:
        bs_score = 3
    elif debt_equity <= 2.0:
        bs_score = 2
    else:
        bs_score = 1
    scores["balance_sheet"] = {"score": bs_score, "note": f"D/E: {debt_equity:.2f}"}

    # Capital Intensity (approximated by profit margin)
    if profit_margin > 25:
        ci_score = 5
    elif profit_margin > 15:
        ci_score = 4
    elif profit_margin > 10:
        ci_score = 3
    elif profit_margin > 5:
        ci_score = 2
    else:
        ci_score = 1
    scores["capital_intensity"] = {"score": ci_score, "note": f"Net margin: {profit_margin:.1f}%"}

    # Capital Allocation (ROIC)
    if roic > 20:
        ca_score = 5
    elif roic > 15:
        ca_score = 4
    elif roic > 10:
        ca_score = 3
    elif roic > 5:
        ca_score = 2
    else:
        ca_score = 1
    scores["capital_allocation"] = {"score": ca_score, "note": f"ROIC: {roic:.1f}%"}

    # Profitability (profit margin + ROE)
    avg_profit = (profit_margin + roe) / 2 if roe else profit_margin
    if avg_profit > 25:
        p_score = 5
    elif avg_profit > 18:
        p_score = 4
    elif avg_profit > 12:
        p_score = 3
    elif avg_profit > 5:
        p_score = 2
    else:
        p_score = 1
    scores["profitability"] = {
        "score": p_score,
        "note": f"Margin: {profit_margin:.1f}%, ROE: {roe:.1f}%",
    }

    # Historical Growth
    if rev_growth_5y > 15 and eps_growth_5y > 15:
        hg_score = 5
    elif rev_growth_5y > 10 and eps_growth_5y > 10:
        hg_score = 4
    elif rev_growth_5y > 5 and eps_growth_5y > 7:
        hg_score = 3
    elif rev_growth_5y > 0:
        hg_score = 2
    else:
        hg_score = 1
    scores["historical_growth"] = {
        "score": hg_score,
        "note": f"Rev growth: {rev_growth_5y:.1f}%, EPS growth: {eps_growth_5y:.1f}%",
    }

    # SBC (approximated — no direct data, use share dilution proxy)
    # Without share count data, mark as needing review
    scores["stock_based_compensation"] = {"score": None, "note": "Check share count trend"}

    # Valuation
    if pe <= 0:
        v_score = 1
        v_note = "Negative earnings"
    elif pe < 15:
        v_score = 5
        v_note = f"P/E: {pe:.1f} (cheap)"
    elif pe < 20:
        v_score = 4
        v_note = f"P/E: {pe:.1f} (fair)"
    elif pe < 30:
        v_score = 3
        v_note = f"P/E: {pe:.1f} (moderate)"
    elif pe < 50:
        v_score = 2
        v_note = f"P/E: {pe:.1f} (expensive)"
    else:
        v_score = 1
        v_note = f"P/E: {pe:.1f} (very expensive)"
    scores["valuation"] = {"score": v_score, "note": v_note}

    # Owner's Earnings (EPS growth + dividend yield)
    owners_return = eps_growth_5y + div_yield
    if owners_return > 15:
        oe_score = 5
    elif owners_return > 10:
        oe_score = 4
    elif owners_return > 7:
        oe_score = 3
    elif owners_return > 3:
        oe_score = 2
    else:
        oe_score = 1
    scores["owners_earnings"] = {
        "score": oe_score,
        "note": f"EPS growth {eps_growth_5y:.1f}% + div yield {div_yield:.1f}% = {owners_return:.1f}%",
    }

    # Historical Value Creation (ROE as proxy)
    if roe > 25:
        hvc_score = 5
    elif roe > 18:
        hvc_score = 4
    elif roe > 12:
        hvc_score = 3
    elif roe > 5:
        hvc_score = 2
    else:
        hvc_score = 1
    scores["historical_value_creation"] = {"score": hvc_score, "note": f"ROE: {roe:.1f}%"}

    # Calculate totals
    scored_dims = {k: v for k, v in scores.items() if v["score"] is not None}
    unscored_dims = {k: v for k, v in scores.items() if v["score"] is None}

    quantitative_total = sum(v["score"] for v in scored_dims.values())
    quantitative_max = len(scored_dims) * 5

    # Project full score assuming unscored dimensions average same ratio
    if scored_dims:
        avg_score = quantitative_total / len(scored_dims)
        projected_total = round(avg_score * 15)
    else:
        projected_total = 0

    if projected_total >= 60:
        signal = "PASS"
    elif projected_total >= 45:
        signal = "WATCH"
    else:
        signal = "SELL"

    return {
        "symbol": symbol,
        "dimensions": scores,
        "quantitative_total": quantitative_total,
        "quantitative_max": quantitative_max,
        "scored_count": len(scored_dims),
        "unscored_count": len(unscored_dims),
        "projected_total": projected_total,
        "signal": signal,
    }
