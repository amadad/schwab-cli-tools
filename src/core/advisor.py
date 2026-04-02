"""Portfolio Advisor Learning Loop — core service.

Orchestrates the thesis → evaluate → review → learn → scan cycle:

1. THESIS: Record investment decisions with full market context at entry
2. EVALUATE: Measure outcomes at checkpoints against current market state
3. REVIEW: Generate retrospective analysis comparing thesis vs reality
4. LEARN: Extract signal patterns from reviewed outcomes
5. SCAN: Use learned patterns to screen for new candidates

The "bitter lesson" approach: let accumulated data drive selection criteria
rather than hand-coded heuristics. The LLM synthesizes patterns from outcomes;
the system just records everything faithfully.
"""

from __future__ import annotations

import json
from datetime import datetime
from statistics import mean, median
from typing import Any

from src.schwab_client._history.advisor_store import AdvisorStore


def record_thesis_with_context(
    store: AdvisorStore,
    *,
    symbol: str,
    direction: str = "long",
    rationale: str,
    time_horizon_days: int = 90,
    entry_price: float | None = None,
    target_return_pct: float | None = None,
    stop_loss_pct: float | None = None,
    market_context: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Record a thesis, extracting regime/signals from market context if provided."""
    regime = None
    vix = None
    sentiment = None
    sector_rotation = None
    signals = None

    if market_context:
        regime = market_context.get("regime")
        vix_data = market_context.get("vix")
        if isinstance(vix_data, dict):
            vix = vix_data.get("vix") or vix_data.get("value")
        elif isinstance(vix_data, (int, float)):
            vix = float(vix_data)
        sentiment = market_context.get("sentiment")
        sector_rotation = market_context.get("sector_rotation")
        signals = {
            k: v
            for k, v in market_context.items()
            if k not in ("regime", "vix", "sentiment", "sector_rotation")
        }

    return store.record_thesis(
        symbol=symbol,
        direction=direction,
        rationale=rationale,
        time_horizon_days=time_horizon_days,
        entry_price=entry_price,
        target_return_pct=target_return_pct,
        stop_loss_pct=stop_loss_pct,
        regime=regime,
        vix=vix,
        sentiment=sentiment,
        sector_rotation=sector_rotation,
        signals=signals if signals else None,
        tags=tags,
    )


def evaluate_open_theses(
    store: AdvisorStore,
    *,
    price_lookup: dict[str, float],
    market_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate all open theses against current prices.

    Args:
        store: AdvisorStore instance
        price_lookup: Dict of symbol -> current price
        market_context: Current market state (regime, vix, etc.)

    Returns:
        List of evaluation results with return calculations and status flags.
    """
    open_theses = store.list_theses(status="open")
    results: list[dict[str, Any]] = []

    regime = market_context.get("regime") if market_context else None
    vix = None
    sentiment = None
    if market_context:
        vix_data = market_context.get("vix")
        if isinstance(vix_data, dict):
            vix = vix_data.get("vix") or vix_data.get("value")
        elif isinstance(vix_data, (int, float)):
            vix = float(vix_data)
        sentiment = market_context.get("sentiment")

    for thesis in open_theses:
        symbol = thesis["symbol"]
        current_price = price_lookup.get(symbol)
        if current_price is None:
            results.append({
                "thesis_id": thesis["id"],
                "symbol": symbol,
                "status": "no_price",
                "message": f"No price data for {symbol}",
            })
            continue

        entry_price = thesis.get("entry_price")
        return_pct = None
        if entry_price and entry_price > 0:
            if thesis["direction"] == "long":
                return_pct = ((current_price - entry_price) / entry_price) * 100
            else:
                return_pct = ((entry_price - current_price) / entry_price) * 100

        # Record checkpoint
        store.record_checkpoint(
            thesis["id"],
            current_price=current_price,
            return_pct=return_pct,
            regime=regime,
            vix=vix,
            sentiment=sentiment,
        )

        # Check if thesis has hit target or stop
        days_open = thesis.get("days_open", 0) or 0
        horizon = thesis.get("time_horizon_days", 90)
        target = thesis.get("target_return_pct")
        stop = thesis.get("stop_loss_pct")

        flags: list[str] = []
        auto_close_reason = None

        if return_pct is not None:
            if target and return_pct >= target:
                flags.append("TARGET_HIT")
                auto_close_reason = "target_hit"
            if stop and return_pct <= -abs(stop):
                flags.append("STOP_HIT")
                auto_close_reason = "stop_hit"
        if days_open >= horizon:
            flags.append("HORIZON_EXPIRED")
            if not auto_close_reason:
                auto_close_reason = "horizon_expired"

        # Regime shift detection
        if thesis.get("regime_at_entry") and regime:
            if thesis["regime_at_entry"] != regime:
                flags.append("REGIME_SHIFTED")

        result = {
            "thesis_id": thesis["id"],
            "symbol": symbol,
            "direction": thesis["direction"],
            "entry_price": entry_price,
            "current_price": current_price,
            "return_pct": round(return_pct, 2) if return_pct is not None else None,
            "days_open": days_open,
            "horizon_days": horizon,
            "regime_at_entry": thesis.get("regime_at_entry"),
            "regime_current": regime,
            "flags": flags,
        }

        # Auto-close if criteria met
        if auto_close_reason:
            store.close_thesis(thesis["id"], reason=auto_close_reason)
            result["auto_closed"] = auto_close_reason

        results.append(result)

    return results


def compute_pattern_stats(
    store: AdvisorStore,
) -> list[dict[str, Any]]:
    """Extract signal patterns from reviewed theses.

    Groups theses by entry conditions (regime, VIX band, sentiment) and
    computes aggregate performance statistics for each combination.
    This is the "learning" step — data-driven pattern discovery.
    """
    reviews = store._fetch_all(
        """
        SELECT
            t.id,
            t.symbol,
            t.direction,
            t.regime_at_entry,
            t.vix_at_entry,
            t.sentiment_at_entry,
            t.sector_rotation_at_entry,
            t.time_horizon_days,
            t.tags,
            r.final_return_pct,
            r.was_correct,
            r.regime_aligned,
            julianday(t.closed_at) - julianday(t.opened_at) AS holding_days
        FROM theses t
        JOIN thesis_reviews r ON r.thesis_id = t.id
        WHERE r.final_return_pct IS NOT NULL
        """
    )

    if not reviews:
        return []

    # Group by regime
    regime_groups: dict[str, list[dict[str, Any]]] = {}
    for r in reviews:
        regime = r.get("regime_at_entry") or "unknown"
        regime_groups.setdefault(regime, []).append(r)

    # Group by VIX band
    vix_groups: dict[str, list[dict[str, Any]]] = {}
    for r in reviews:
        vix = r.get("vix_at_entry")
        if vix is None:
            band = "unknown"
        elif vix < 15:
            band = "low_vix"
        elif vix < 20:
            band = "normal_vix"
        elif vix < 30:
            band = "elevated_vix"
        else:
            band = "high_vix"
        vix_groups.setdefault(band, []).append(r)

    # Group by direction
    direction_groups: dict[str, list[dict[str, Any]]] = {}
    for r in reviews:
        direction_groups.setdefault(r["direction"], []).append(r)

    # Combine: regime + vix band patterns
    combined_groups: dict[str, list[dict[str, Any]]] = {}
    for r in reviews:
        regime = r.get("regime_at_entry") or "unknown"
        vix = r.get("vix_at_entry")
        if vix is None:
            band = "unknown"
        elif vix < 20:
            band = "low"
        else:
            band = "high"
        key = f"{regime}_{band}_vix"
        combined_groups.setdefault(key, []).append(r)

    patterns_upserted: list[dict[str, Any]] = []

    all_groups = {
        **{f"regime:{k}": v for k, v in regime_groups.items()},
        **{f"vix_band:{k}": v for k, v in vix_groups.items()},
        **{f"direction:{k}": v for k, v in direction_groups.items()},
        **{f"combo:{k}": v for k, v in combined_groups.items()},
    }

    for pattern_name, group in all_groups.items():
        returns = [r["final_return_pct"] for r in group if r["final_return_pct"] is not None]
        correct = [r for r in group if r.get("was_correct")]
        holding = [r["holding_days"] for r in group if r.get("holding_days") is not None]

        if not returns:
            continue

        conditions = _extract_conditions(pattern_name, group)

        result = store.upsert_pattern(
            pattern_name=pattern_name,
            description=f"Pattern based on {pattern_name} ({len(group)} theses)",
            conditions=conditions,
            sample_size=len(group),
            hit_rate=len(correct) / len(group) if group else None,
            avg_return_pct=mean(returns),
            median_return_pct=median(returns) if returns else None,
            best_return_pct=max(returns),
            worst_return_pct=min(returns),
            avg_holding_days=mean(holding) if holding else None,
            regime_affinity=conditions.get("regime"),
        )
        patterns_upserted.append(result)

    return patterns_upserted


def _extract_conditions(pattern_name: str, group: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract the common conditions that define a pattern group."""
    conditions: dict[str, Any] = {"pattern_type": pattern_name.split(":")[0]}

    if pattern_name.startswith("regime:"):
        conditions["regime"] = pattern_name.split(":", 1)[1]
    elif pattern_name.startswith("vix_band:"):
        conditions["vix_band"] = pattern_name.split(":", 1)[1]
    elif pattern_name.startswith("direction:"):
        conditions["direction"] = pattern_name.split(":", 1)[1]
    elif pattern_name.startswith("combo:"):
        parts = pattern_name.split(":", 1)[1]
        conditions["combo"] = parts

    return conditions


def build_learning_prompt(store: AdvisorStore) -> str:
    """Build an LLM-ready prompt with the full learning context.

    This is the key integration point: it assembles all thesis history,
    reviews, patterns, and performance data into a structured block
    that an LLM can use to generate retrospectives, extract patterns,
    and recommend research directions.
    """
    ctx = store.get_learning_context()
    perf = ctx["performance"]
    lines: list[str] = []

    lines.append("## Advisor Learning Loop Context")
    lines.append("")

    # Performance summary
    lines.append("### Performance Summary")
    lines.append(f"Total theses: {perf['total_theses']} (open: {perf['open']}, closed: {perf['closed']})")
    lines.append(f"Reviewed: {perf['reviewed']}")
    if perf.get("win_rate") is not None:
        lines.append(f"Win rate: {perf['win_rate']:.0%}")
    if perf.get("avg_return_pct") is not None:
        lines.append(f"Avg return: {perf['avg_return_pct']:.1f}%")
    lines.append("")

    # By regime
    if perf.get("by_regime"):
        lines.append("### Performance by Regime")
        for rs in perf["by_regime"]:
            win_rate = (
                f"{rs['wins']}/{rs['thesis_count']}"
                if rs.get("wins") is not None
                else "N/A"
            )
            avg_ret = f"{rs['avg_return']:.1f}%" if rs.get("avg_return") is not None else "N/A"
            lines.append(f"- {rs['regime']}: {win_rate} wins, avg return {avg_ret}")
        lines.append("")

    # Open theses
    if ctx["open_theses"]:
        lines.append("### Open Theses")
        for t in ctx["open_theses"]:
            ret = f"{t['latest_return_pct']:.1f}%" if t.get("latest_return_pct") is not None else "no data"
            days = f"{t['days_open']:.0f}d" if t.get("days_open") is not None else "?"
            lines.append(
                f"- [{t['id']}] {t['symbol']} ({t['direction']}) — "
                f"{days} open, return: {ret}, "
                f"regime@entry: {t.get('regime_at_entry', '?')}"
            )
        lines.append("")

    # Recent reviews (lessons learned)
    if ctx["recent_reviews"]:
        lines.append("### Recent Lessons (from reviewed theses)")
        for r in ctx["recent_reviews"]:
            correct = "correct" if r.get("was_correct") else "incorrect"
            ret = f"{r['final_return_pct']:.1f}%" if r.get("final_return_pct") is not None else "?"
            lines.append(f"- {r['symbol']} ({r['direction']}): {correct}, {ret}")
            if r.get("lessons"):
                lines.append(f"  Lesson: {r['lessons']}")
        lines.append("")

    # Patterns
    if ctx["patterns"]:
        lines.append("### Extracted Signal Patterns")
        for p in ctx["patterns"]:
            hit = f"{p['hit_rate']:.0%}" if p.get("hit_rate") is not None else "?"
            avg = f"{p['avg_return_pct']:.1f}%" if p.get("avg_return_pct") is not None else "?"
            lines.append(
                f"- {p['pattern_name']}: hit rate {hit}, avg return {avg} "
                f"(n={p['sample_size']})"
            )
        lines.append("")

    return "\n".join(lines)
