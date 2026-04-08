"""Price data service using yfinance.

Provides auth-free price lookup, historical series, and benchmark comparison.
This is the backbone for the advisor learning loop -- it works without
Schwab market auth, so the loop never breaks due to expired tokens.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


def get_current_price(symbol: str) -> float | None:
    """Fetch the current/last price for a symbol. Returns None on failure."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = getattr(info, "last_price", None)
        if price is not None:
            return float(price)
        # Fallback: get from recent history
        hist = ticker.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def get_prices_bulk(symbols: list[str]) -> dict[str, float]:
    """Fetch current prices for multiple symbols at once."""
    result: dict[str, float] = {}
    if not symbols:
        return result
    try:
        import yfinance as yf

        tickers = yf.Tickers(" ".join(symbols))
        for symbol in symbols:
            try:
                ticker = tickers.tickers.get(symbol)
                if ticker is None:
                    continue
                info = ticker.fast_info
                price = getattr(info, "last_price", None)
                if price is not None:
                    result[symbol] = float(price)
            except Exception:
                continue
    except Exception:
        # Fallback: fetch one by one
        for symbol in symbols:
            price = get_current_price(symbol)
            if price is not None:
                result[symbol] = price
    return result


def get_price_at_date(symbol: str, target_date: str | date) -> float | None:
    """Get the closing price on or near a specific date."""
    try:
        import yfinance as yf

        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date[:10])

        start = target_date - timedelta(days=5)
        end = target_date + timedelta(days=1)

        ticker = yf.Ticker(symbol)
        hist = ticker.history(start=start.isoformat(), end=end.isoformat())
        if hist.empty:
            return None

        # Get the closest date <= target
        hist.index = hist.index.tz_localize(None)
        target_dt = datetime(target_date.year, target_date.month, target_date.day)
        valid = hist[hist.index <= target_dt]
        if not valid.empty:
            return float(valid["Close"].iloc[-1])
        return float(hist["Close"].iloc[0])
    except Exception:
        return None


def get_price_series(
    symbol: str,
    start_date: str | date,
    end_date: str | date | None = None,
) -> list[dict[str, Any]]:
    """Get daily price history between two dates.

    Returns list of {date, open, high, low, close, volume}.
    """
    try:
        import yfinance as yf

        if isinstance(start_date, str):
            start_date = date.fromisoformat(start_date[:10])
        if end_date is None:
            end_date = date.today()
        elif isinstance(end_date, str):
            end_date = date.fromisoformat(end_date[:10])

        ticker = yf.Ticker(symbol)
        hist = ticker.history(
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
        )

        if hist.empty:
            return []

        series = []
        for idx, row in hist.iterrows():
            series.append({
                "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10],
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row["Volume"]),
            })
        return series
    except Exception:
        return []


def compute_benchmark_return(
    start_date: str | date,
    end_date: str | date | None = None,
    benchmark: str = "SPY",
) -> float | None:
    """Compute the benchmark return over a period.

    Returns percentage return (e.g., 5.2 for 5.2%).
    """
    start_price = get_price_at_date(benchmark, start_date)
    if start_price is None or start_price <= 0:
        return None

    if end_date:
        end_price = get_price_at_date(benchmark, end_date)
    else:
        end_price = get_current_price(benchmark)

    if end_price is None:
        return None

    return ((end_price - start_price) / start_price) * 100


def compute_price_trajectory(
    symbol: str,
    start_date: str | date,
    end_date: str | date | None = None,
) -> dict[str, Any]:
    """Compute trajectory statistics for a position over a period.

    Returns: entry_price, current_price, return_pct, max_drawdown_pct,
    max_gain_pct, volatility, and a simplified price path.
    """
    series = get_price_series(symbol, start_date, end_date)
    if not series:
        return {}

    entry_price = series[0]["close"]
    current_price = series[-1]["close"]
    return_pct = ((current_price - entry_price) / entry_price) * 100

    # Drawdown and gain from entry
    closes = [s["close"] for s in series]
    returns_from_entry = [((c - entry_price) / entry_price) * 100 for c in closes]
    max_drawdown = min(returns_from_entry)
    max_gain = max(returns_from_entry)

    # Peak-to-trough drawdown
    peak = closes[0]
    worst_peak_trough = 0.0
    for c in closes:
        if c > peak:
            peak = c
        drawdown = ((c - peak) / peak) * 100
        if drawdown < worst_peak_trough:
            worst_peak_trough = drawdown

    # Simplified path: sample ~10 points for display
    path_points = []
    step = max(1, len(series) // 10)
    for i in range(0, len(series), step):
        s = series[i]
        path_points.append({
            "date": s["date"],
            "close": s["close"],
            "return_pct": round(returns_from_entry[i], 2),
        })
    # Always include the last point
    if path_points[-1]["date"] != series[-1]["date"]:
        path_points.append({
            "date": series[-1]["date"],
            "close": series[-1]["close"],
            "return_pct": round(returns_from_entry[-1], 2),
        })

    return {
        "symbol": symbol,
        "entry_price": round(entry_price, 2),
        "current_price": round(current_price, 2),
        "return_pct": round(return_pct, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "max_gain_pct": round(max_gain, 2),
        "peak_trough_drawdown_pct": round(worst_peak_trough, 2),
        "trading_days": len(series),
        "path": path_points,
    }
