"""Context command: assemble and display the full portfolio context."""

from __future__ import annotations

import httpx

from src.core.context import PortfolioContext
from src.core.errors import PortfolioError

from ..context import get_cached_market_client, get_client
from ..output import format_header, handle_cli_error, print_json_response


def cmd_context(
    *,
    output_mode: str = "text",
    include_lynch: bool = False,
    prompt: bool = False,
    template: str | None = None,
) -> None:
    """Assemble and display the full portfolio context.

    Args:
        output_mode: "text" or "json"
        include_lynch: Include Lynch sell signal analysis (slower)
        prompt: Output as an LLM-ready prompt block instead of human text
        template: Prompt template to use ("brief", "review", "memo")
    """
    command = "context"
    try:
        client = get_client()

        market_client = None
        try:
            market_client = get_cached_market_client()
        except Exception:
            pass

        # If a template is specified, enable lynch for review/memo depth
        if template in ("review", "memo") and not include_lynch:
            include_lynch = True

        ctx = PortfolioContext.assemble(
            client,
            market_client=market_client,
            include_lynch=include_lynch,
        )

        if output_mode == "json":
            print_json_response(command, data=ctx.to_dict())
            return

        if template:
            from src.core.prompts import TEMPLATES, render_prompt

            tmpl = TEMPLATES.get(template)
            if not tmpl:
                print(f"Unknown template: {template}. Available: {', '.join(TEMPLATES)}")
                return
            print(render_prompt(tmpl, ctx.to_prompt_block()))
            return

        if prompt:
            print(ctx.to_prompt_block())
            return

        # Human-readable text output
        _print_text_context(ctx)

    except (PortfolioError, httpx.HTTPStatusError) as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def _print_text_context(ctx: PortfolioContext) -> None:
    """Print context in human-readable format."""
    print(format_header("PORTFOLIO CONTEXT"))
    print(f"  Assembled: {ctx.assembled_at}")

    if ctx.summary:
        print(f"\n  Total Value:  ${ctx.summary.total_value:,.0f}")
        print(f"  Total Cash:   ${ctx.summary.total_cash:,.0f} ({ctx.summary.cash_percentage:.1f}%)")
        print(f"  Invested:     ${ctx.summary.total_invested:,.0f}")
        print(f"  Unrealized:   ${ctx.summary.total_unrealized_pl:+,.0f}")

    if ctx.accounts:
        print(format_header("ACCOUNTS"))
        for account_snapshot in ctx.accounts:
            cash_pct = (
                account_snapshot.total_cash / account_snapshot.total_value * 100
                if account_snapshot.total_value > 0
                else 0
            )
            print(
                f"  {account_snapshot.account:<15} ${account_snapshot.total_value:>12,.0f}  "
                f"cash ${account_snapshot.total_cash:>10,.0f} ({cash_pct:>4.0f}%)"
            )

    print(format_header("MARKET"))
    if ctx.vix:
        print(f"  VIX:    {ctx.vix.vix:.1f} ({ctx.vix.signal})")
    if ctx.regime:
        print(f"  Regime: {ctx.regime.regime.upper()}")
        print(f"          {ctx.regime.description}")

    if ctx.polymarket and ctx.polymarket.signals:
        print(format_header("POLYMARKET"))
        for s in ctx.polymarket.signals:
            if s.probability is not None:
                print(f"  {s.title}: {s.probability * 100:.0f}%")
            elif s.error:
                print(f"  {s.title}: error ({s.error})")

    if ctx.policy_delta:
        delta = ctx.policy_delta
        if delta.distribution_pacing:
            print(format_header("DISTRIBUTION PACING"))
            for p in delta.distribution_pacing:
                status = "ON TRACK" if p.on_track else "** BEHIND **"
                print(
                    f"  {p.account:<10} ${p.ytd_distributions:>10,.0f} / "
                    f"${p.annual_floor:>10,.0f} ({p.pacing_pct:>4.0f}%)  "
                    f"{status}  [{p.years_remaining}yr → {p.deadline}]"
                )

        if delta.alerts:
            print(
                format_header(
                    f"POLICY ALERTS ({delta.critical_count} critical, {delta.warning_count} warning)"
                )
            )
            for alert in delta.alerts:
                icon = {"critical": "!!!", "warning": " ! ", "info": " - "}.get(
                    alert.severity, " - "
                )
                print(f"  [{icon}] {alert.bucket}: {alert.message}")

        if delta.calendar_actions:
            print(format_header("CALENDAR"))
            for c in delta.calendar_actions:
                print(f"  - {c}")

    if ctx.lynch:
        print(format_header("LYNCH SELL SIGNALS"))
        if ctx.lynch.signals_found == 0:
            print(f"  0 signals across {ctx.lynch.total_checked} positions")
        else:
            print(f"  {ctx.lynch.signals_found} signals found:")
            for f in ctx.lynch.flagged:
                for s in f.get("signals", []):
                    print(f"    {f['symbol']}: {s['trigger']}")

    if ctx.errors:
        print(format_header("ERRORS"))
        for e in ctx.errors:
            print(f"  - {e}")

    print()
