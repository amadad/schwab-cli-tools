"""
Market commands: vix, indices, sectors, market, movers, futures, fundamentals, dividends.
"""

from datetime import datetime, timedelta
from typing import Any

import httpx
from schwab.client.base import BaseClient  # for Movers enum

from config.secure_account_config import secure_config
from src.core.errors import PortfolioError
from src.core.lynch_service import analyze_holdings_lynch
from src.core.market_service import (
    get_implied_volatility,
    get_market_hours,
    get_market_indices,
    get_market_regime,
    get_market_signals,
    get_sector_performance,
    get_vix,
)

from ..context import get_cached_market_client, get_client
from ..output import format_header, handle_cli_error, print_json_response


def cmd_vix(*, output_mode: str = "text") -> None:
    """Show VIX data."""
    command = "vix"
    try:
        client = get_cached_market_client()
        data = get_vix(client)

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        print(format_header("VIX"))
        print(f"  Value:          {data['vix']:.2f}")
        print(f"  Change:         {data['change']:+.2f} ({data['change_pct']:+.2f}%)")
        print(f"  Signal:         {data['signal']}")
        print(f"  Interpretation: {data['interpretation']}")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_indices(*, output_mode: str = "text") -> None:
    """Show major index quotes."""
    command = "indices"
    try:
        client = get_cached_market_client()
        data = get_market_indices(client)

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        print(format_header("MARKET INDICES"))
        for symbol, info in data.get("indices", {}).items():
            print(
                f"  {symbol:6s} {info['name']:18s} {info['price']:>10,.2f} "
                f"({info['change_pct']:+.2f}%)"
            )
        print(f"\n  Sentiment: {data.get('sentiment')}")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_sectors(*, output_mode: str = "text") -> None:
    """Show sector performance."""
    command = "sectors"
    try:
        client = get_cached_market_client()
        data = get_sector_performance(client)

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        print(format_header("SECTOR PERFORMANCE"))
        for sector in data.get("sectors", []):
            print(
                f"  {sector['symbol']:4s} {sector['sector']:24s} " f"{sector['change_pct']:+.2f}%"
            )

        print(f"\n  Rotation: {data.get('rotation')}")
        print(f"  Leaders:  {', '.join(data.get('leaders', []))}")
        print(f"  Laggards: {', '.join(data.get('laggards', []))}")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_market(*, output_mode: str = "text") -> None:
    """Show aggregated market signals."""
    command = "market"
    try:
        client = get_cached_market_client()
        data = get_market_signals(client)

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        signals = data.get("signals", {})
        print(format_header("MARKET SIGNALS"))
        vix_data = signals.get("vix", {})
        print(f"  VIX:             {vix_data.get('value', 0):.2f} ({vix_data.get('signal')})")
        print(f"  Sentiment:       {signals.get('market_sentiment')}")
        print(f"  Sector Rotation: {signals.get('sector_rotation')}")
        print(f"  Overall:         {data.get('overall')}")
        print(f"  Recommendation:  {data.get('recommendation')}")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_movers(
    *,
    output_mode: str = "text",
    gainers_only: bool = False,
    losers_only: bool = False,
    count: int = 5,
    index: str = "SPX",
) -> None:
    """Show top market movers (gainers/losers)."""
    command = "movers"
    try:
        client = get_cached_market_client()
        Movers = BaseClient.Movers

        # Resolve index name to enum
        index_map = {
            "SPX": Movers.Index.SPX,
            "NASDAQ": Movers.Index.NASDAQ,
            "NYSE": Movers.Index.NYSE,
            "DJI": Movers.Index.DJI,
        }
        movers_index = index_map.get(index.upper(), Movers.Index.SPX)

        resp_g = client.get_movers(
            movers_index,
            sort_order=Movers.SortOrder.PERCENT_CHANGE_UP,
            frequency=Movers.Frequency.ONE,
        )
        gainers_data = resp_g.json() if hasattr(resp_g, "json") else resp_g
        gainers_list = (
            gainers_data.get("screeners", [])
            if isinstance(gainers_data, dict)
            else (gainers_data or [])
        )

        resp_l = client.get_movers(
            movers_index,
            sort_order=Movers.SortOrder.PERCENT_CHANGE_DOWN,
            frequency=Movers.Frequency.ONE,
        )
        losers_data = resp_l.json() if hasattr(resp_l, "json") else resp_l
        losers_list = (
            losers_data.get("screeners", [])
            if isinstance(losers_data, dict)
            else (losers_data or [])
        )

        # Filter to actual gainers/losers
        true_gainers = [gainer for gainer in gainers_list if gainer.get("netPercentChange", 0) > 0]
        true_losers = [loser for loser in losers_list if loser.get("netPercentChange", 0) < 0]

        gainers: list[dict[str, Any]] = [
            {
                "symbol": gainer.get("symbol"),
                "change_pct": gainer.get("netPercentChange"),
            }
            for gainer in true_gainers[:count]
        ]
        losers: list[dict[str, Any]] = [
            {
                "symbol": loser.get("symbol"),
                "change_pct": loser.get("netPercentChange"),
            }
            for loser in true_losers[:count]
        ]
        data: dict[str, Any] = {
            "gainers": gainers,
            "losers": losers,
            "index": index.upper(),
        }

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        if not losers_only:
            print(f"\nTOP GAINERS ({index.upper()})")
            for g in data["gainers"][:count]:
                pct = g["change_pct"] * 100 if g["change_pct"] else 0
                print(f"  {g['symbol']:8} +{pct:.2f}%")

        if not gainers_only:
            print(f"\nTOP LOSERS ({index.upper()})")
            for loser in data["losers"][:count]:
                pct = loser["change_pct"] * 100 if loser["change_pct"] else 0
                print(f"  {loser['symbol']:8} {pct:.2f}%")

        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_futures(*, output_mode: str = "text") -> None:
    """Show pre-market futures for /ES and /NQ."""
    command = "futures"
    try:
        now = datetime.now().time()
        rth_start = datetime.strptime("09:30", "%H:%M").time()
        rth_end = datetime.strptime("16:00", "%H:%M").time()
        is_rth = rth_start <= now <= rth_end

        if is_rth and output_mode == "text":
            print("\nFutures only available outside regular trading hours (9:30 AM - 4:00 PM ET)")
            print("Markets are currently open. Use 'schwab indices' for current market data.")
            return

        client = get_cached_market_client()
        resp = client.get_quotes(["/ES", "/NQ"])
        quotes = resp.json() if hasattr(resp, "json") else resp

        data = {}
        for sym in ["/ES", "/NQ"]:
            if sym in quotes:
                q = quotes[sym]
                data[sym] = {
                    "price": q.get("askPrice") or q.get("lastPrice"),
                    "change": q.get("netChange"),
                    "change_pct": q.get("netPercentChange"),
                }

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        print("\nPRE-MARKET FUTURES")
        for sym, d in data.items():
            name = "S&P 500 (/ES)" if sym == "/ES" else "Nasdaq (/NQ)"
            change_pct = d.get("change_pct", 0) or 0
            sign = "+" if change_pct >= 0 else ""
            price = d.get("price", 0) or 0
            print(f"  {name:20} ${price:,.0f}  {sign}{change_pct * 100:.2f}%")

        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_hours(*, date: str | None = None, output_mode: str = "text") -> None:
    """Check if the market is open today (or on a given date)."""
    command = "hours"
    try:
        client = get_cached_market_client()
        data = get_market_hours(client, date)

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        status = "OPEN" if data["is_open"] else "CLOSED"
        print(format_header("MARKET HOURS"))
        print(f"  Date:    {data['date']}")
        print(f"  Status:  {status}")

        if data["is_open"] and data.get("session_hours"):
            for session, hours in data["session_hours"].items():
                label = (
                    session.replace("regularMarket", "Regular")
                    .replace("preMarket", "Pre-Market")
                    .replace("postMarket", "Post-Market")
                )
                print(f"  {label:14s} {hours['start']} → {hours['end']}")

        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_fundamentals(symbol: str, *, output_mode: str = "text") -> None:
    """Show fundamentals for a symbol."""
    command = "fundamentals"
    try:
        client = get_cached_market_client()

        Instrument = client.Instrument.Projection
        resp = client.get_instruments([symbol], Instrument.FUNDAMENTAL)
        data = resp.json() if hasattr(resp, "json") else resp

        instruments = data.get("instruments", []) if isinstance(data, dict) else []
        inst = instruments[0].get("fundamental", {}) if instruments else {}

        if not inst:
            if output_mode == "json":
                print_json_response(command, data={"symbol": symbol, "error": "No data"})
            else:
                print(f"No data for {symbol}")
            return

        fund_data = {
            "symbol": symbol,
            "pe_ratio": inst.get("peRatio"),
            "eps": inst.get("eps"),
            "dividend_yield": inst.get("dividendYield"),
            "dividend_amount": inst.get("dividendAmount"),
            "52wk_high": inst.get("high52"),
            "52wk_low": inst.get("low52"),
            "market_cap": inst.get("marketCap"),
        }

        if output_mode == "json":
            print_json_response(command, data=fund_data)
            return

        print(f"\n{symbol} FUNDAMENTALS")
        print(f"  P/E:        {fund_data['pe_ratio'] or 'N/A'}")
        print(f"  EPS:        {fund_data['eps'] or 'N/A'}")
        print(f"  Div Yield:  {fund_data['dividend_yield'] or 'N/A'}")
        print(f"  Div Amount: ${fund_data['dividend_amount'] or 'N/A'}")
        print(f"  52wk High:  ${fund_data['52wk_high'] or 'N/A'}")
        print(f"  52wk Low:   ${fund_data['52wk_low'] or 'N/A'}")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_dividends(
    *,
    days: int = 30,
    output_mode: str = "text",
    upcoming: bool = False,
) -> None:
    """Show recent dividend/interest transactions or upcoming ex-dates."""
    command = "dividends"
    try:
        client = get_client()

        if upcoming:
            positions = client.get_positions(None)

            # Approximate ex-date calendar for common dividend payers
            ex_date_calendar = {
                "VTI": {"ex_month": 1, "day": 28, "amount": 0.89},
                "SCHD": {"ex_month": 2, "day": 3, "amount": 0.72},
                "VOO": {"ex_month": 3, "day": 22, "amount": 1.85},
                "QQQ": {"ex_month": 3, "day": 20, "amount": 1.12},
            }

            upcoming_divs = []
            now = datetime.now()
            for p in positions:
                sym = p.get("symbol")
                if sym in ex_date_calendar:
                    ex_cal = ex_date_calendar[sym]
                    ex_date = datetime(now.year, int(ex_cal["ex_month"]), int(ex_cal["day"]))
                    if now <= ex_date <= now + timedelta(days=30):
                        shares = p.get("quantity", 0)
                        total = shares * ex_cal["amount"]
                        upcoming_divs.append(
                            {
                                "symbol": sym,
                                "ex_date": ex_date.strftime("%b %d"),
                                "amount_per_share": ex_cal["amount"],
                                "total": total,
                                "shares": shares,
                            }
                        )

            if output_mode == "json":
                print_json_response(command, data={"upcoming": upcoming_divs})
                return

            if upcoming_divs:
                print("\nUPCOMING EX-DATES (next 30 days)")
                for d in upcoming_divs:
                    print(
                        f"  {d['symbol']:6} ex-div {d['ex_date']} "
                        f"(${d['amount_per_share']:.2f}/share) - ${d['total']:.2f} est."
                    )
            else:
                print("\nNo dividend ex-dates in the next 30 days")
            return

        # Historical dividends
        raw_client = client.raw_client
        TransactionType = raw_client.Transactions.TransactionType

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        all_dividends = []
        for alias in secure_config.get_all_accounts():
            account_number = secure_config.get_account_number(alias)
            if not account_number:
                continue
            account_hash = client.get_account_hash(account_number)
            if not account_hash:
                continue

            resp = raw_client.get_transactions(
                account_hash,
                start_date=start_date,
                end_date=end_date,
                transaction_types=[TransactionType.DIVIDEND_OR_INTEREST],
            )
            transactions = resp.json() if hasattr(resp, "json") else resp
            if isinstance(transactions, list):
                all_dividends.extend(
                    [
                        t
                        for t in transactions
                        if t.get("transactionType") in ["DIVIDEND", "INTEREST"]
                    ]
                )

        data = {
            "transactions": [
                {
                    "date": t.get("tradeDate"),
                    "symbol": t.get("symbol"),
                    "description": t.get("description"),
                    "amount": t.get("amount"),
                }
                for t in all_dividends
            ]
        }

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        total = sum(t.get("amount", 0) for t in all_dividends)
        print(f"\nDIVIDENDS ({days} days)")
        if all_dividends:
            for t in all_dividends:
                print(
                    f"  {t.get('tradeDate'):10} {t.get('symbol', 'N/A'):8} "
                    f"${t.get('amount', 0):>10,.2f}"
                )
            print(f"\n  TOTAL: ${total:,.2f}")
        else:
            print("  No dividends received.")
            print("\n  Use --upcoming to see ex-dates for your holdings")

        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_regime(*, output_mode: str = "text") -> None:
    """Show market regime (risk-on/risk-off) based on bond relative strength."""
    command = "regime"
    try:
        client = get_cached_market_client()
        data = get_market_regime(client)

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        signals = data.get("signals", {})
        regime = data.get("regime", "unknown")
        regime_display = regime.replace("_", " ").upper()

        print(format_header("MARKET REGIME"))
        print(f"  Regime:      {regime_display}")
        print(f"  Description: {data.get('description', '')}")
        print()
        print("  Signals:")
        print(f"    AGG 60d return:  {signals.get('agg_60d_return', 0):+.2f}%")
        print(f"    BIL 60d return:  {signals.get('bil_60d_return', 0):+.2f}%")
        print(f"    TLT 20d return:  {signals.get('tlt_20d_return', 0):+.2f}%")
        print(f"    BIL 20d return:  {signals.get('bil_20d_return', 0):+.2f}%")
        print()
        print(f"  Risk-On:       {'Yes' if data.get('risk_on') else 'No'} (AGG > BIL 60d)")
        print(f"  Rates Rising:  {'Yes' if data.get('rates_rising') else 'No'} (TLT < BIL 20d)")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_lynch(*, output_mode: str = "text") -> None:
    """Check Lynch sell signals on portfolio holdings."""
    command = "lynch"
    try:
        portfolio_client = get_client()
        market_client = get_cached_market_client()

        # Get top holdings
        positions = portfolio_client.get_positions(None)
        # Take top 15 by value, skip money market
        from ...client import MONEY_MARKET_SYMBOLS

        positions = [p for p in positions if p.get("symbol") not in MONEY_MARKET_SYMBOLS]
        positions.sort(key=lambda p: p.get("market_value", 0), reverse=True)
        top_positions = positions[:15]

        if not top_positions:
            if output_mode == "json":
                print_json_response(command, data={"holdings": [], "signals_count": 0})
            else:
                print("No positions found.")
            return

        # Fetch fundamentals for each
        symbols = [p["symbol"] for p in top_positions]

        Instrument = market_client.Instrument.Projection
        resp = market_client.get_instruments(symbols, Instrument.FUNDAMENTAL)
        fund_data = resp.json() if hasattr(resp, "json") else resp
        instruments = fund_data.get("instruments", []) if isinstance(fund_data, dict) else []

        fund_by_symbol = {}
        for inst in instruments:
            sym = inst.get("symbol", "")
            fund = inst.get("fundamental", {})
            # Also get quote data for price
            fund["lastPrice"] = inst.get("lastPrice", 0)
            fund_by_symbol[sym] = fund

        holdings_data = []
        for pos in top_positions:
            sym = pos["symbol"]
            holdings_data.append(
                {
                    "symbol": sym,
                    "fundamentals": fund_by_symbol.get(sym, {}),
                }
            )

        results = analyze_holdings_lynch(holdings_data)

        total_signals = sum(len(r["signals"]) for r in results)

        if output_mode == "json":
            print_json_response(command, data={"holdings": results, "signals_count": total_signals})
            return

        print(format_header("LYNCH SELL-SIGNAL CHECK"))

        for r in results:
            symbol = r["symbol"]
            ctype = r["company_type"].replace("_", " ").title()
            pe = r.get("pe_ratio")
            pe_str = f"P/E {pe:.1f}" if pe else "P/E N/A"

            if r["signals"]:
                print(f"\n  {symbol:8s} [{ctype}] {pe_str}")
                for sig in r["signals"]:
                    severity = sig["severity"].upper()
                    print(f"    [{severity}] {sig['trigger']}")
                    print(f"           {sig['detail']}")
            else:
                print(f"  {symbol:8s} [{ctype}] {pe_str} - No sell signals")

        print(f"\n  Total signals: {total_signals}")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_score(symbol: str, *, output_mode: str = "text") -> None:
    """Score a stock using Compounding Quality 15-point framework."""
    from src.core.score_service import score_from_fundamentals

    command = "score"
    try:
        client = get_cached_market_client()

        Instrument = client.Instrument.Projection
        resp = client.get_instruments([symbol.upper()], Instrument.FUNDAMENTAL)
        data = resp.json() if hasattr(resp, "json") else resp

        instruments = data.get("instruments", []) if isinstance(data, dict) else []
        if not instruments:
            raise PortfolioError(f"No fundamentals data found for {symbol}")

        fund = instruments[0].get("fundamental", {})
        fund["lastPrice"] = instruments[0].get("lastPrice", 0)

        result = score_from_fundamentals(symbol.upper(), fund)

        if output_mode == "json":
            print_json_response(command, data=result)
            return

        signal = result["signal"]
        projected = result["projected_total"]

        print(format_header(f"QUALITY SCORE: {symbol.upper()}"))
        print(f"  Signal: {signal} (projected {projected}/75)")
        print(
            f"  Scored: {result['quantitative_total']}/{result['quantitative_max']} ({result['scored_count']} dimensions)"
        )
        print(f"  Needs review: {result['unscored_count']} qualitative dimensions")
        print()

        for dim_name, dim_data in result["dimensions"].items():
            label = dim_name.replace("_", " ").title()
            score = dim_data["score"]
            note = dim_data["note"]
            if score is not None:
                bar = "*" * score + "." * (5 - score)
                print(f"  {label:28s} [{bar}] {score}/5  {note}")
            else:
                print(f"  {label:28s} [?????] ?/5  {note}")

        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_iv(symbol: str, *, output_mode: str = "text") -> None:
    """Show implied volatility for a symbol from option chain data."""
    command = "iv"
    try:
        client = get_cached_market_client()
        data = get_implied_volatility(client, symbol)

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        iv = data.get("implied_volatility")
        if iv is None:
            print(f"\n  No IV data available for {symbol.upper()}")
            print("  (Symbol may not have listed options)")
            return

        print(format_header(f"IMPLIED VOLATILITY: {data['symbol']}"))
        print(f"  IV:             {iv:.1f}%")
        print(f"  Mark Price:     ${data['mark_price']:,.2f}")
        if data.get("dte"):
            print(f"  Nearest Exp:    {data['dte']} DTE")
        print(f"  Signal:         {data['signal']}")
        print(f"  Interpretation: {data['interpretation']}")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)
