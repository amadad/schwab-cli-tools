"""Advisor learning loop CLI commands.

Commands:
    advisor thesis SYMBOL   Record an investment thesis
    advisor evaluate        Evaluate open theses against current prices
    advisor review          Show thesis history and reviews
    advisor learn           Extract signal patterns from outcomes
    advisor scan            Generate research scan criteria
    advisor status          Show learning loop dashboard
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from src.core.errors import PortfolioError
from src.schwab_client._history.advisor_store import AdvisorStore

from ..context import get_cached_market_client
from ..output import format_header, handle_cli_error, print_json_response


def _get_advisor_store() -> AdvisorStore:
    return AdvisorStore()


def _get_market_context() -> dict[str, Any]:
    """Fetch current market context for advisor operations."""
    ctx: dict[str, Any] = {}
    try:
        market_client = get_cached_market_client()
        from src.core.market_service import get_market_regime, get_market_signals, get_vix

        try:
            vix = get_vix(market_client)
            ctx["vix"] = vix.get("vix") or vix.get("value")
            ctx["vix_signal"] = vix.get("signal")
        except Exception:
            pass

        try:
            regime = get_market_regime(market_client)
            ctx["regime"] = regime.get("regime")
            ctx["risk_on"] = regime.get("risk_on")
        except Exception:
            pass

        try:
            signals = get_market_signals(market_client)
            ctx["sentiment"] = signals.get("overall")
            ctx["sector_rotation"] = (
                signals.get("signals", {}).get("sector_rotation")
                if isinstance(signals.get("signals"), dict)
                else None
            )
        except Exception:
            pass

    except Exception:
        pass
    return ctx


def cmd_advisor_thesis(
    symbol: str,
    *,
    direction: str = "long",
    rationale: str = "",
    horizon: int = 90,
    entry_price: float | None = None,
    target: float | None = None,
    stop_loss: float | None = None,
    tags: list[str] | None = None,
    output_mode: str = "text",
) -> None:
    """Record a new investment thesis.

    Auto-fetches entry price via yfinance if not provided.
    Auto-captures market context (regime, VIX, sentiment) if available.
    """
    command = "advisor-thesis"
    try:
        store = _get_advisor_store()
        market_ctx = _get_market_context()

        from src.core.advisor import record_thesis_with_context

        result = record_thesis_with_context(
            store,
            symbol=symbol,
            direction=direction,
            rationale=rationale,
            time_horizon_days=horizon,
            entry_price=entry_price,
            target_return_pct=target,
            stop_loss_pct=stop_loss,
            market_context=market_ctx if market_ctx else None,
            tags=tags,
        )

        actual_entry = result.get("entry_price", entry_price)

        if output_mode == "json":
            print_json_response(command, data={**result, "market_context": market_ctx})
            return

        print(format_header("THESIS RECORDED"))
        print(f"  ID:        #{result['thesis_id']}")
        print(f"  Symbol:    {result['symbol']}")
        print(f"  Direction: {direction}")
        print(f"  Horizon:   {horizon} days")
        if actual_entry:
            source = "auto-fetched" if entry_price is None else "provided"
            print(f"  Entry:     ${actual_entry:,.2f} ({source})")
        if target:
            print(f"  Target:    +{target}%")
        if stop_loss:
            print(f"  Stop:      -{stop_loss}%")
        if market_ctx:
            print(f"\n  Market Context at Entry:")
            if market_ctx.get("regime"):
                print(f"    Regime:   {market_ctx['regime']}")
            if market_ctx.get("vix"):
                print(f"    VIX:      {market_ctx['vix']:.1f}")
            if market_ctx.get("sentiment"):
                print(f"    Signal:   {market_ctx['sentiment']}")
        if rationale:
            print(f"\n  Rationale: {rationale}")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_advisor_evaluate(
    *,
    output_mode: str = "text",
) -> None:
    """Evaluate all open theses against current market prices.

    Uses Schwab market client if available, falls back to yfinance (no auth).
    Always includes benchmark (SPY) comparison for alpha calculation.
    """
    command = "advisor-evaluate"
    try:
        store = _get_advisor_store()
        open_theses = store.list_theses(status="open")

        if not open_theses:
            if output_mode == "json":
                print_json_response(command, data={"evaluations": [], "message": "No open theses"})
            else:
                print("No open theses to evaluate.")
            return

        # Try Schwab market client for prices, but don't fail if unavailable
        symbols = list({t["symbol"] for t in open_theses})
        price_lookup: dict[str, float] = {}

        try:
            market_client = get_cached_market_client()
            for symbol in symbols:
                try:
                    quote_data = market_client.get_quote(symbol)
                    if hasattr(quote_data, "json"):
                        quote_data = quote_data.json()
                    sym_data = quote_data.get(symbol, {})
                    price = sym_data.get("quote", {}).get("lastPrice")
                    if price is not None:
                        price_lookup[symbol] = float(price)
                except Exception:
                    continue
        except Exception:
            pass  # yfinance fallback happens in evaluate_open_theses

        market_ctx = _get_market_context()

        from src.core.advisor import evaluate_open_theses

        results = evaluate_open_theses(
            store,
            price_lookup=price_lookup if price_lookup else None,
            market_context=market_ctx,
        )

        if output_mode == "json":
            print_json_response(command, data={"evaluations": results, "market_context": market_ctx})
            return

        print(format_header("THESIS EVALUATIONS"))
        for r in results:
            if r.get("status") == "no_price":
                print(f"  #{r['thesis_id']} {r['symbol']}: no price data")
                continue

            ret_str = f"{r['return_pct']:+.1f}%" if r.get("return_pct") is not None else "N/A"
            flags_str = " ".join(f"[{f}]" for f in r.get("flags", []))

            # Format with benchmark comparison
            entry = r.get("entry_price", 0) or 0
            current = r.get("current_price", 0) or 0
            days = r.get("days_open", 0) or 0
            horizon = r.get("horizon_days", 0) or 0

            print(
                f"  #{r['thesis_id']} {r['symbol']} ({r['direction']}): "
                f"${entry:,.2f} → ${current:,.2f} "
                f"= {ret_str}  ({days:.0f}d/{horizon}d) "
                f"{flags_str}"
            )

            # Show alpha vs benchmark
            bench = r.get("benchmark_return_pct")
            alpha = r.get("alpha_pct")
            if bench is not None and alpha is not None:
                alpha_label = "alpha" if alpha >= 0 else "underperform"
                print(f"    vs SPY: {bench:+.1f}% → {alpha_label}: {alpha:+.1f}%")

            if r.get("auto_closed"):
                print(f"    → Auto-closed: {r['auto_closed']}")
            if r.get("regime_at_entry") != r.get("regime_current"):
                print(
                    f"    → Regime shift: {r.get('regime_at_entry', '?')} → "
                    f"{r.get('regime_current', '?')}"
                )
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_advisor_review(
    *,
    thesis_id: int | None = None,
    status: str | None = None,
    limit: int = 20,
    output_mode: str = "text",
) -> None:
    """Show thesis history, reviews, and learning context."""
    command = "advisor-review"
    try:
        store = _get_advisor_store()

        if thesis_id is not None:
            thesis = store.get_thesis_with_history(thesis_id)
            if not thesis:
                if output_mode == "json":
                    print_json_response(
                        command, success=False,
                        error={"type": "NotFound", "message": f"Thesis #{thesis_id} not found"},
                    )
                else:
                    print(f"Thesis #{thesis_id} not found.")
                return

            if output_mode == "json":
                print_json_response(command, data=thesis)
                return

            _print_thesis_detail(thesis)
            return

        # List theses
        theses = store.list_theses(status=status, limit=limit)

        if output_mode == "json":
            print_json_response(command, data={"theses": theses, "count": len(theses)})
            return

        if not theses:
            print("No theses found.")
            return

        print(format_header(f"THESES ({status or 'all'})"))
        for t in theses:
            tags_str = f" [{t['tags']}]" if t.get("tags") else ""
            print(
                f"  #{t['id']} {t['symbol']} ({t['direction']}) — "
                f"{t['status']} — {t['opened_at'][:10]}"
                f"{tags_str}"
            )
            if t.get("rationale"):
                rationale = t["rationale"][:80]
                if len(t["rationale"]) > 80:
                    rationale += "..."
                print(f"    {rationale}")
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_advisor_learn(
    *,
    output_mode: str = "text",
    prompt: bool = False,
    template: str | None = None,
) -> None:
    """Extract signal patterns from thesis outcomes, or generate learning prompts."""
    command = "advisor-learn"
    try:
        store = _get_advisor_store()

        if template or prompt:
            from src.core.advisor import build_learning_prompt
            from src.core.advisor_prompts import render_advisor_prompt

            learning_ctx = build_learning_prompt(store)

            if template:
                market_ctx = _get_market_context()
                market_str = json.dumps(market_ctx, indent=2) if market_ctx else "Not available"
                rendered = render_advisor_prompt(
                    template,
                    learning_context=learning_ctx,
                    market_context=market_str,
                )
                if output_mode == "json":
                    print_json_response(command, data={"prompt": rendered, "template": template})
                else:
                    print(rendered)
            else:
                if output_mode == "json":
                    print_json_response(command, data={"learning_context": learning_ctx})
                else:
                    print(learning_ctx)
            return

        # Compute patterns from data
        from src.core.advisor import compute_pattern_stats

        patterns = compute_pattern_stats(store)

        if output_mode == "json":
            all_patterns = store.get_patterns()
            print_json_response(
                command,
                data={"patterns_updated": len(patterns), "all_patterns": all_patterns},
            )
            return

        if not patterns:
            print("No reviewed theses to learn from yet. Review some theses first.")
            return

        print(format_header("PATTERNS EXTRACTED"))
        print(f"  Updated {len(patterns)} patterns from thesis history.\n")

        leaderboard = store.get_pattern_leaderboard()
        if leaderboard:
            print("  Pattern Leaderboard (sample >= 3):")
            for p in leaderboard:
                hit = f"{p['hit_rate']:.0%}" if p.get("hit_rate") is not None else "?"
                avg = f"{p['avg_return_pct']:.1f}%" if p.get("avg_return_pct") is not None else "?"
                print(
                    f"    {p['pattern_name']}: hit {hit}, avg {avg} (n={p['sample_size']})"
                )
        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_advisor_status(
    *,
    output_mode: str = "text",
) -> None:
    """Show the learning loop dashboard."""
    command = "advisor-status"
    try:
        store = _get_advisor_store()
        perf = store.get_performance_summary()
        open_theses = store.get_open_theses()
        patterns = store.get_patterns(min_sample_size=0)

        if output_mode == "json":
            print_json_response(
                command,
                data={
                    "performance": perf,
                    "open_theses": open_theses,
                    "pattern_count": len(patterns),
                },
            )
            return

        print(format_header("ADVISOR LEARNING LOOP"))

        print(f"\n  Theses:   {perf['total_theses']} total "
              f"({perf['open']} open, {perf['closed']} closed)")
        print(f"  Reviewed: {perf['reviewed']}")
        if perf.get("win_rate") is not None:
            print(f"  Win Rate: {perf['win_rate']:.0%}")
        if perf.get("avg_return_pct") is not None:
            print(f"  Avg Return: {perf['avg_return_pct']:.1f}%")
        print(f"  Patterns: {perf['patterns_extracted']}")

        if perf.get("by_regime"):
            print(format_header("BY REGIME"))
            for rs in perf["by_regime"]:
                wins = rs.get("wins", 0) or 0
                total = rs["thesis_count"]
                avg_ret = f"{rs['avg_return']:.1f}%" if rs.get("avg_return") is not None else "N/A"
                print(f"  {rs['regime']}: {wins}/{total} wins, avg {avg_ret}")

        if open_theses:
            print(format_header("OPEN THESES"))
            for t in open_theses:
                ret = (
                    f"{t['latest_return_pct']:+.1f}%"
                    if t.get("latest_return_pct") is not None
                    else "no data"
                )
                days = f"{t['days_open']:.0f}d" if t.get("days_open") is not None else "?"
                print(
                    f"  #{t['id']} {t['symbol']} ({t['direction']}): "
                    f"{ret} ({days}/{t['time_horizon_days']}d) "
                    f"regime@entry: {t.get('regime_at_entry', '?')}"
                )

        print()

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_advisor_close(
    thesis_id: int,
    *,
    reason: str = "manual",
    output_mode: str = "text",
) -> None:
    """Close an open thesis."""
    command = "advisor-close"
    try:
        store = _get_advisor_store()
        result = store.close_thesis(thesis_id, reason=reason)

        if output_mode == "json":
            print_json_response(command, data=result)
            return

        print(f"Thesis #{thesis_id} closed (reason: {reason}).")

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def _print_thesis_detail(thesis: dict[str, Any]) -> None:
    """Print detailed thesis view with price trajectory and checkpoint history."""
    print(format_header(f"THESIS #{thesis['id']}: {thesis['symbol']}"))
    print(f"  Direction:  {thesis['direction']}")
    print(f"  Status:     {thesis['status']}")
    print(f"  Opened:     {thesis['opened_at']}")
    if thesis.get("closed_at"):
        print(f"  Closed:     {thesis['closed_at']} ({thesis.get('close_reason', '?')})")
    print(f"  Horizon:    {thesis['time_horizon_days']} days")
    if thesis.get("entry_price"):
        print(f"  Entry:      ${thesis['entry_price']:,.2f}")
    if thesis.get("target_return_pct"):
        print(f"  Target:     +{thesis['target_return_pct']}%")
    if thesis.get("stop_loss_pct"):
        print(f"  Stop:       -{thesis['stop_loss_pct']}%")

    print(f"\n  Entry Context:")
    print(f"    Regime:   {thesis.get('regime_at_entry', 'N/A')}")
    print(f"    VIX:      {thesis.get('vix_at_entry', 'N/A')}")
    print(f"    Sentiment: {thesis.get('sentiment_at_entry', 'N/A')}")

    if thesis.get("rationale"):
        print(f"\n  Rationale:\n    {thesis['rationale']}")

    # Price trajectory (fetched live via yfinance)
    try:
        from src.core.advisor import enrich_thesis_trajectory

        store = _get_advisor_store()
        trajectory = enrich_thesis_trajectory(store, thesis["id"])
        if trajectory and trajectory.get("return_pct") is not None:
            print(format_header("PRICE TRAJECTORY"))
            print(
                f"  Return:        {trajectory['return_pct']:+.1f}% "
                f"(${trajectory['entry_price']:,.2f} → ${trajectory['current_price']:,.2f})"
            )
            print(f"  Max Drawdown:  {trajectory.get('max_drawdown_pct', 0):.1f}%")
            print(f"  Max Gain:      {trajectory.get('max_gain_pct', 0):+.1f}%")
            print(f"  Peak→Trough:   {trajectory.get('peak_trough_drawdown_pct', 0):.1f}%")
            if trajectory.get("benchmark_return_pct") is not None:
                print(f"  SPY Return:    {trajectory['benchmark_return_pct']:+.1f}%")
                print(f"  Alpha:         {trajectory.get('alpha_pct', 0):+.1f}%")
            print(f"  Trading Days:  {trajectory.get('trading_days', 0)}")

            path = trajectory.get("path", [])
            if path:
                print(f"\n  Price Path:")
                for p in path:
                    print(f"    {p['date']}: ${p['close']:,.2f} ({p['return_pct']:+.1f}%)")
    except Exception:
        pass  # Don't break thesis view if trajectory fails

    checkpoints = thesis.get("checkpoints", [])
    if checkpoints:
        print(format_header("CHECKPOINTS"))
        for cp in checkpoints:
            ret = f"{cp['return_pct']:+.1f}%" if cp.get("return_pct") is not None else "N/A"
            price = f"${cp['current_price']:,.2f}" if cp.get("current_price") else "N/A"
            print(f"  {cp['checked_at'][:10]}: {price} ({ret}) regime={cp.get('regime_current', '?')}")

    review = thesis.get("review")
    if review:
        print(format_header("REVIEW"))
        if review.get("final_return_pct") is not None:
            print(f"  Final Return: {review['final_return_pct']:+.1f}%")
        correct = "Yes" if review.get("was_correct") else "No" if review.get("was_correct") is not None else "N/A"
        print(f"  Correct: {correct}")
        if review.get("what_worked"):
            print(f"  What Worked: {review['what_worked']}")
        if review.get("what_failed"):
            print(f"  What Failed: {review['what_failed']}")
        if review.get("lessons"):
            print(f"  Lessons: {review['lessons']}")

    print()
