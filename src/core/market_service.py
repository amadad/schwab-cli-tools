"""Market data helpers for Schwab CLI tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.core.errors import PortfolioError

# Sector ETFs for market breadth
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLE": "Energy",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

# Major indices
INDICES = {
    "$SPX": "S&P 500",
    "$COMPX": "Nasdaq Composite",
    "$DJI": "Dow Jones",
    "$VIX": "VIX (Fear Index)",
    "$RUT": "Russell 2000",
}


def _ensure_ok(response, context: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise PortfolioError(f"Market data API error ({context}): {response.status_code}")
    return response.json()


def get_vix(client) -> dict[str, Any]:
    """Fetch VIX data and interpretation."""
    data = _ensure_ok(client.get_quote("$VIX"), "vix")
    vix_data = data.get("$VIX", {})
    quote = vix_data.get("quote", {})

    vix_value = quote.get("lastPrice", 0)

    if vix_value < 15:
        signal = "low_fear"
        interpretation = "Market complacent - consider hedging"
    elif vix_value < 20:
        signal = "normal"
        interpretation = "Normal market conditions"
    elif vix_value < 30:
        signal = "elevated"
        interpretation = "Elevated uncertainty - be cautious"
    elif vix_value < 40:
        signal = "high_fear"
        interpretation = "High fear - potential opportunity"
    else:
        signal = "extreme_fear"
        interpretation = "Extreme fear - crisis levels"

    return {
        "vix": vix_value,
        "change": quote.get("netChange", 0),
        "change_pct": quote.get("netPercentChange", 0),
        "signal": signal,
        "interpretation": interpretation,
        "timestamp": datetime.now().isoformat(),
    }


def get_market_indices(client) -> dict[str, Any]:
    """Fetch major index quotes and sentiment."""
    symbols = list(INDICES.keys())
    data = _ensure_ok(client.get_quotes(symbols), "indices")

    results: dict[str, Any] = {}
    for symbol, name in INDICES.items():
        if symbol in data:
            quote = data[symbol].get("quote", {})
            results[symbol] = {
                "name": name,
                "price": quote.get("lastPrice", 0),
                "change": quote.get("netChange", 0),
                "change_pct": quote.get("netPercentChange", 0),
            }

    spx_change = results.get("$SPX", {}).get("change_pct", 0)
    vix_value = results.get("$VIX", {}).get("price", 20)

    if spx_change > 1 and vix_value < 20:
        sentiment = "risk_on"
    elif spx_change < -1 or vix_value > 25:
        sentiment = "risk_off"
    else:
        sentiment = "neutral"

    return {
        "indices": results,
        "sentiment": sentiment,
        "timestamp": datetime.now().isoformat(),
    }


def get_sector_performance(client) -> dict[str, Any]:
    """Fetch sector ETF performance and rotation signals."""
    symbols = list(SECTOR_ETFS.keys())
    data = _ensure_ok(client.get_quotes(symbols), "sectors")

    sectors = []
    for symbol, name in SECTOR_ETFS.items():
        if symbol in data:
            quote = data[symbol].get("quote", {})
            sectors.append(
                {
                    "symbol": symbol,
                    "sector": name,
                    "price": quote.get("lastPrice", 0),
                    "change_pct": quote.get("netPercentChange", 0),
                }
            )

    sectors.sort(key=lambda x: x["change_pct"], reverse=True)

    leaders = sectors[:3]
    laggards = sectors[-3:]

    defensive = {"XLU", "XLP", "XLV"}
    cyclical = {"XLY", "XLK", "XLF"}

    defensive_avg = (
        sum(s["change_pct"] for s in sectors if s["symbol"] in defensive) / 3
        if sectors
        else 0
    )
    cyclical_avg = (
        sum(s["change_pct"] for s in sectors if s["symbol"] in cyclical) / 3
        if sectors
        else 0
    )

    if cyclical_avg > defensive_avg + 0.5:
        rotation = "risk_on"
    elif defensive_avg > cyclical_avg + 0.5:
        rotation = "risk_off"
    else:
        rotation = "neutral"

    return {
        "sectors": sectors,
        "leaders": [s["sector"] for s in leaders],
        "laggards": [s["sector"] for s in laggards],
        "rotation": rotation,
        "cyclical_avg": round(cyclical_avg, 2),
        "defensive_avg": round(defensive_avg, 2),
        "timestamp": datetime.now().isoformat(),
    }


def get_market_signals(client) -> dict[str, Any]:
    """Combine VIX, indices, and sector rotation into actionable signals."""
    vix_data = get_vix(client)
    indices_data = get_market_indices(client)
    sector_data = get_sector_performance(client)

    signals = {
        "vix": {"value": vix_data.get("vix", 0), "signal": vix_data.get("signal")},
        "market_sentiment": indices_data.get("sentiment"),
        "sector_rotation": sector_data.get("rotation"),
    }

    vix_signal = vix_data.get("signal", "normal")
    sentiment = indices_data.get("sentiment", "neutral")
    rotation = sector_data.get("rotation", "neutral")

    risk_on_count = sum(
        [
            vix_signal in {"low_fear", "normal"},
            sentiment == "risk_on",
            rotation == "risk_on",
        ]
    )

    if risk_on_count >= 2:
        overall = "favorable"
        recommendation = "Market conditions support equity exposure"
    elif risk_on_count == 0:
        overall = "cautious"
        recommendation = "Consider reducing risk exposure"
    else:
        overall = "mixed"
        recommendation = "Mixed signals - maintain current allocation"

    return {
        "signals": signals,
        "overall": overall,
        "recommendation": recommendation,
        "timestamp": datetime.now().isoformat(),
    }
