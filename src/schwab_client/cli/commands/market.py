"""
Market commands: vix, indices, sectors, market, movers, futures, fundamentals, dividends.
"""

from datetime import datetime, timedelta

from schwab.client.base import BaseClient

from config.secure_account_config import secure_config
from src.core.market_service import (
    get_market_indices,
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

    except Exception as exc:
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

    except Exception as exc:
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
                f"  {sector['symbol']:4s} {sector['sector']:24s} "
                f"{sector['change_pct']:+.2f}%"
            )

        print(f"\n  Rotation: {data.get('rotation')}")
        print(f"  Leaders:  {', '.join(data.get('leaders', []))}")
        print(f"  Laggards: {', '.join(data.get('laggards', []))}")
        print()

    except Exception as exc:
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

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_movers(
    *,
    output_mode: str = "text",
    gainers_only: bool = False,
    losers_only: bool = False,
    count: int = 5,
) -> None:
    """Show top market movers (gainers/losers)."""
    command = "movers"
    try:
        client = get_cached_market_client()
        Movers = BaseClient.Movers

        resp_g = client.get_movers(
            Movers.Index.SPX,
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
            Movers.Index.SPX,
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
        true_gainers = [g for g in gainers_list if g.get("netPercentChange", 0) > 0]
        true_losers = [l for l in losers_list if l.get("netPercentChange", 0) < 0]

        data = {
            "gainers": [
                {"symbol": g.get("symbol"), "change_pct": g.get("netPercentChange")}
                for g in true_gainers[:count]
            ],
            "losers": [
                {"symbol": l.get("symbol"), "change_pct": l.get("netPercentChange")}
                for l in true_losers[:count]
            ],
        }

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        if not losers_only:
            print("\nTOP GAINERS")
            for g in data["gainers"][:count]:
                pct = g["change_pct"] * 100 if g["change_pct"] else 0
                print(f"  {g['symbol']:8} +{pct:.2f}%")

        if not gainers_only:
            print("\nTOP LOSERS")
            for l in data["losers"][:count]:
                pct = l["change_pct"] * 100 if l["change_pct"] else 0
                print(f"  {l['symbol']:8} {pct:.2f}%")

        print()

    except Exception as exc:
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

    except Exception as exc:
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

    except Exception as exc:
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
                    ex_date = datetime(now.year, ex_cal["ex_month"], ex_cal["day"])
                    if now <= ex_date <= now + timedelta(days=30):
                        shares = p.get("quantity", 0)
                        total = shares * ex_cal["amount"]
                        upcoming_divs.append({
                            "symbol": sym,
                            "ex_date": ex_date.strftime("%b %d"),
                            "amount_per_share": ex_cal["amount"],
                            "total": total,
                            "shares": shares,
                        })

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
                all_dividends.extend([
                    t for t in transactions
                    if t.get("transactionType") in ["DIVIDEND", "INTEREST"]
                ])

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

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)
