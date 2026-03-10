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

    defensive_sectors = [s for s in sectors if s["symbol"] in defensive]
    cyclical_sectors = [s for s in sectors if s["symbol"] in cyclical]

    defensive_avg = (
        sum(s["change_pct"] for s in defensive_sectors) / len(defensive_sectors)
        if defensive_sectors
        else 0
    )
    cyclical_avg = (
        sum(s["change_pct"] for s in cyclical_sectors) / len(cyclical_sectors)
        if cyclical_sectors
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


def _cumulative_return(candles: list[dict], days: int) -> float:
    """Calculate cumulative return over the last N trading days from price candles."""
    if len(candles) < days + 1:
        return 0.0
    recent = candles[-(days + 1):]
    start_price = recent[0].get("close", 0)
    end_price = recent[-1].get("close", 0)
    if start_price <= 0:
        return 0.0
    return (end_price - start_price) / start_price * 100


def get_market_regime(client) -> dict[str, Any]:
    """Detect market regime using bond/equity relative strength.

    Uses AGG vs BIL (60-day) for risk-on/risk-off determination,
    and TLT vs BIL (20-day) for rate direction within risk-off.

    Regimes:
      - risk_on: AGG 60d return > BIL 60d return (credit expanding)
      - risk_off_falling_rates: TLT 20d return > BIL 20d return
      - risk_off_rising_rates: TLT 20d return < BIL 20d return
    """
    symbols = ["AGG", "BIL", "TLT"]
    candles_by_symbol: dict[str, list] = {}

    for symbol in symbols:
        resp = client.get_price_history_every_day(symbol)
        data = resp.json() if hasattr(resp, "json") else resp
        candles_by_symbol[symbol] = data.get("candles", [])

    agg_60 = _cumulative_return(candles_by_symbol.get("AGG", []), 60)
    bil_60 = _cumulative_return(candles_by_symbol.get("BIL", []), 60)
    tlt_20 = _cumulative_return(candles_by_symbol.get("TLT", []), 20)
    bil_20 = _cumulative_return(candles_by_symbol.get("BIL", []), 20)

    if agg_60 > bil_60:
        regime = "risk_on"
        description = "Credit expanding — conditions favor equity exposure"
    elif tlt_20 < bil_20:
        regime = "risk_off_rising_rates"
        description = "Risk-off with rising rates — favor dollar strength, short bonds"
    else:
        regime = "risk_off_falling_rates"
        description = "Risk-off with falling rates — favor treasuries, gold, defensives"

    return {
        "regime": regime,
        "description": description,
        "signals": {
            "agg_60d_return": round(agg_60, 2),
            "bil_60d_return": round(bil_60, 2),
            "tlt_20d_return": round(tlt_20, 2),
            "bil_20d_return": round(bil_20, 2),
        },
        "risk_on": agg_60 > bil_60,
        "rates_rising": tlt_20 < bil_20,
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


def get_implied_volatility(client, symbol: str) -> dict[str, Any]:
    """Fetch implied volatility from option chain for a symbol.

    Uses the ANALYTICAL strategy to get IV data from near-term ATM options.
    Returns current IV, percentile context, and signal interpretation.
    """
    symbol_upper = symbol.upper()

    resp = client.get_option_chain(
        symbol_upper,
        contract_type=client.Options.ContractType.CALL,
        strike_count=1,
        strategy=client.Options.Strategy.ANALYTICAL,
    )
    data = resp.json() if hasattr(resp, "json") else resp

    underlying = data.get("underlying") or {}
    mark = underlying.get("mark") or underlying.get("last") or 0

    # Fall back to regular quote if underlying price not in option chain
    if not mark:
        quote_data = _ensure_ok(client.get_quote(symbol_upper), f"quote:{symbol_upper}")
        quote = quote_data.get(symbol_upper, {}).get("quote", {})
        mark = quote.get("lastPrice") or quote.get("closePrice") or 0

    # Extract IV from the volatility field or from near-term options
    iv = data.get("volatility", 0)

    # If top-level volatility not available, compute from nearest expiry
    if not iv:
        call_map = data.get("callExpDateMap", {})
        if call_map:
            # Take first expiration
            first_exp = next(iter(call_map.values()), {})
            if first_exp:
                # Take the strike closest to ATM
                first_strike_options = next(iter(first_exp.values()), [])
                if first_strike_options:
                    opt = first_strike_options[0] if isinstance(first_strike_options, list) else first_strike_options
                    iv = opt.get("volatility", 0)

    # Normalize to percentage if needed (API sometimes returns decimal)
    if iv and iv < 5:
        iv = iv * 100

    # Interpret IV level
    if iv < 15:
        signal = "very_low"
        interpretation = "Unusually calm — options cheap, consider buying protection"
    elif iv < 25:
        signal = "low"
        interpretation = "Below average volatility"
    elif iv < 35:
        signal = "normal"
        interpretation = "Normal implied volatility range"
    elif iv < 50:
        signal = "elevated"
        interpretation = "Elevated — market pricing significant move"
    elif iv < 75:
        signal = "high"
        interpretation = "High IV — potential opportunity for sellers"
    else:
        signal = "extreme"
        interpretation = "Extreme IV — crisis or event-driven"

    # Days to expiration from nearest chain
    dte = 0
    call_map = data.get("callExpDateMap", {})
    if call_map:
        first_exp_key = next(iter(call_map), "")
        # Key format is typically "2026-03-14:4"
        if ":" in first_exp_key:
            try:
                dte = int(first_exp_key.split(":")[1])
            except (ValueError, IndexError):
                pass

    return {
        "symbol": symbol_upper,
        "implied_volatility": round(iv, 2) if iv else None,
        "mark_price": mark,
        "dte": dte,
        "signal": signal,
        "interpretation": interpretation,
        "timestamp": datetime.now().isoformat(),
    }


def get_market_hours(client, date_str: str | None = None) -> dict[str, Any]:
    """Check if the equity market is open on a given date.

    Args:
        client: Authenticated market client
        date_str: Date to check (YYYY-MM-DD). Defaults to today.

    Returns:
        Dict with is_open, session_hours, and market status details.
    """
    from datetime import date as date_type

    check_date = (
        date_type.fromisoformat(date_str) if date_str
        else datetime.now().date()
    )

    resp = client.get_market_hours(
        client.MarketHours.Market.EQUITY,
        date=check_date,
    )
    data = resp.json() if hasattr(resp, "json") else resp

    # Response structure: {"equity": {"EQ": {...}}} or {"equity": {"equity": {...}}}
    equity_data = data.get("equity", {})
    # Get the first (and usually only) market entry
    market_info = next(iter(equity_data.values()), {})

    is_open = market_info.get("isOpen", False)
    market_date = market_info.get("date", str(check_date))
    product_name = market_info.get("productName", "US Equity")

    session_hours = {}
    if is_open:
        for session_name, hours_list in market_info.get("sessionHours", {}).items():
            if hours_list:
                session_hours[session_name] = {
                    "start": hours_list[0].get("start", ""),
                    "end": hours_list[0].get("end", ""),
                }

    return {
        "date": market_date,
        "is_open": is_open,
        "product": product_name,
        "session_hours": session_hours,
        "timestamp": datetime.now().isoformat(),
    }
