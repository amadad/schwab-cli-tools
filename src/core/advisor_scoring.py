"""Deterministic scoring for advisor recommendation outcomes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _policy_delta_from_context(context: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if context is None:
        return None
    if "policy_delta" in context:
        policy_delta = context.get("policy_delta")
        return policy_delta if isinstance(policy_delta, Mapping) else None
    if any(key in context for key in ("alerts", "distribution_pacing", "calendar_actions", "checked_at")):
        return context
    return None


def compute_policy_health_score(context: Mapping[str, Any] | None) -> float | None:
    policy = _policy_delta_from_context(context)
    if policy is None:
        return None

    alerts = policy.get("alerts") or []
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
    for pacing in policy.get("distribution_pacing") or []:
        if not isinstance(pacing, Mapping):
            continue
        if not pacing.get("on_track", True):
            total -= 15
    portfolio_cash = None
    summary = context.get('summary') if isinstance(context, Mapping) else None
    if isinstance(summary, Mapping):
        portfolio_cash = summary.get('cash_percentage')
    try:
        if portfolio_cash is not None:
            pct = float(portfolio_cash)
            if pct > 30:
                total -= min(15.0, pct - 30.0)
            elif pct < 15:
                total -= min(10.0, 15.0 - pct)
    except (TypeError, ValueError):
        pass
    return max(total, 0.0)


def classify_outcome(before: float, after: float) -> tuple[float, str]:
    delta = after - before
    if delta > 5:
        return delta, "improved"
    if delta < -5:
        return delta, "worsened"
    return delta, "neutral"
