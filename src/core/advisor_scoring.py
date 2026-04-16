"""Deterministic scoring for advisor recommendation outcomes."""

from __future__ import annotations

from collections.abc import Mapping

from src.core.context import PortfolioContext


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _mapping_from_context(
    context: PortfolioContext | Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if context is None:
        return None
    if isinstance(context, PortfolioContext):
        return context.to_dict()
    return context


def _policy_delta_from_context(
    context: PortfolioContext | Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    context_mapping = _mapping_from_context(context)
    if context_mapping is None:
        return None
    if "policy_delta" in context_mapping:
        policy_delta = context_mapping.get("policy_delta")
        return policy_delta if isinstance(policy_delta, Mapping) else None
    if any(
        key in context_mapping
        for key in ("alerts", "distribution_pacing", "calendar_actions", "checked_at")
    ):
        return context_mapping
    return None


def compute_policy_health_score(
    context: PortfolioContext | Mapping[str, object] | None,
) -> float | None:
    context_mapping = _mapping_from_context(context)
    policy = _policy_delta_from_context(context)
    if policy is None:
        return None

    raw_alerts = policy.get("alerts")
    alerts = raw_alerts if isinstance(raw_alerts, list) else []
    total = 100.0
    for alert in alerts:
        if not isinstance(alert, Mapping):
            continue
        severity = str(alert.get("severity") or alert.get("level") or "info").lower()
        if severity in {"critical", "urgent"}:
            total -= 25
        elif severity == "warning":
            total -= 10
        else:
            total -= 3

    raw_distribution_pacing = policy.get("distribution_pacing")
    distribution_pacing = (
        raw_distribution_pacing if isinstance(raw_distribution_pacing, list) else []
    )
    for pacing in distribution_pacing:
        if not isinstance(pacing, Mapping):
            continue
        if not pacing.get("on_track", True):
            total -= 15

    portfolio_cash = None
    summary = context_mapping.get("summary") if isinstance(context_mapping, Mapping) else None
    if isinstance(summary, Mapping):
        portfolio_cash = summary.get("cash_percentage")
    pct = _coerce_float(portfolio_cash)
    if pct is not None:
        if pct > 30:
            total -= min(15.0, pct - 30.0)
        elif pct < 15:
            total -= min(10.0, 15.0 - pct)
    return max(total, 0.0)


def classify_outcome(before: float, after: float) -> tuple[float, str]:
    delta = after - before
    if delta > 5:
        return delta, "improved"
    if delta < -5:
        return delta, "worsened"
    return delta, "neutral"
