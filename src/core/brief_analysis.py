"""Narrative analysis for portfolio briefs."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import datetime
from typing import Any

from src.core.context import PortfolioContext
from src.core.policy import resolve_policy_path
from src.schwab_client.history import HistoryStore

DEFAULT_ANALYSIS_COMMAND = "claude -p"
ANALYSIS_PROMPT_VERSION = "brief-analysis-v1"
ACCOUNT_CONTEXT = """
Account Categories:
- Personal: Taxable brokerage accounts
- Retirement: Traditional/Roth IRAs (Ali's)
- Inherited IRA: Must be depleted within 10 years of inheritance
- Business: Business accounts
- Education: Kids' ESA accounts

Key Targets:
- Cash target: 15% of total portfolio
- Bond target: 20% of total portfolio
- Inherited IRAs have distribution deadlines

RMD Rules:
- Inherited Traditional IRAs require annual RMDs
- Track RMD satisfaction status for each inherited account
""".strip()


def snapshot_date_from_snapshot(snapshot: dict[str, Any]) -> str:
    generated_at = snapshot.get("generated_at")
    if isinstance(generated_at, str) and len(generated_at) >= 10:
        return generated_at[:10]
    return datetime.now().strftime("%Y-%m-%d")


def load_portfolio_history(history_store: HistoryStore, *, limit: int = 7) -> list[dict[str, Any]]:
    return history_store.get_portfolio_history(limit=limit)


def _context_to_dict(context: PortfolioContext | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(context, PortfolioContext):
        return context.to_dict()
    return dict(context or {})


def format_context_signals(context: PortfolioContext | dict[str, Any] | None) -> str:
    payload = _context_to_dict(context)
    if not payload:
        return "  (context unavailable)"

    lines: list[str] = []
    regime = payload.get("regime") or {}
    if regime:
        lines.append(f"  Regime: {regime.get('regime', 'unknown').upper()} — {regime.get('description', '')}")

    polymarket = payload.get("polymarket") or {}
    for signal in (polymarket.get("signals") or [])[:3]:
        if signal.get("probability") is not None:
            lines.append(f"  Polymarket: {signal['title']}: {signal['probability'] * 100:.0f}%")
        elif signal.get("summary"):
            lines.append(f"  Polymarket: {signal['title']}: {signal['summary']}")

    for account, ytd in sorted((payload.get("ytd_distributions") or {}).items()):
        lines.append(f"  Distribution ({account}): ${float(ytd):,.0f} YTD")

    lynch = payload.get("lynch") or {}
    if lynch:
        flagged = lynch.get("flagged") or []
        symbols = ", ".join(item.get("symbol", "?") for item in flagged[:5] if item.get("symbol"))
        signals = lynch.get("signals_found", 0)
        total = lynch.get("total_checked", 0)
        suffix = f" — {symbols}" if signals > 0 and symbols else ""
        lines.append(
            f"  Lynch: {signals} sell signals out of {total} holdings{suffix}"
            if signals > 0
            else f"  Lynch: {total} holdings checked, 0 sell signals"
        )

    delta = payload.get("policy_delta") or {}
    for alert in (delta.get("alerts") or [])[:5]:
        lines.append(
            f"  Policy: [{str(alert.get('severity', 'info')).upper()}] {alert.get('bucket', '')}: {alert.get('message', '')}"
        )
    for action in (delta.get("calendar_actions") or [])[:3]:
        lines.append(f"  Calendar: {action}")

    return "\n".join(lines) if lines else "  No additional signals."


def build_prompt(
    *,
    scorecard: dict[str, Any],
    snapshot: dict[str, Any],
    portfolio_history: list[dict[str, Any]],
    policy_text: str,
    context: PortfolioContext | dict[str, Any] | None,
) -> str:
    vix = ((snapshot.get("market") or {}).get("vix") or {})
    vix_val = vix.get("vix") if isinstance(vix, dict) else "N/A"
    vix_signal = vix.get("signal", "") if isinstance(vix, dict) else ""
    total = scorecard.get("total_portfolio_value", 0)

    history_text = "\n".join(
        f"  {(row.get('observed_at') or '')[:10]}: ${(row.get('total_value') or 0):,.0f}  cash {(row.get('cash_percentage') or 0):.1f}%"
        for row in portfolio_history
    ) or "  No history yet."
    alerts_text = "".join(
        f"  [{alert['level'].upper()}] {alert['bucket']}: {alert['issue']} → {alert['action']}\n"
        for alert in scorecard.get("alerts", [])
    )

    bucket_lines = []
    for bucket in scorecard.get("buckets", []):
        dod_pct = bucket.get("dod_pct")
        wow_pct = bucket.get("wow_pct")
        dod = f"{dod_pct:+.1f}%" if isinstance(dod_pct, int | float) else "—"
        wow = f"{wow_pct:+.1f}%" if isinstance(wow_pct, int | float) else "—"
        bucket_lines.append(
            f"  {bucket['bucket']:<28} ${bucket['value']:>10,.0f} ({bucket['pct_of_portfolio']:.1f}%) "
            f"cash {bucket['cash_pct']:.0f}% dod {dod} wow {wow} [{bucket['status']}]"
        )

    return f"""You are a portfolio analyst. The hard numbers are already computed — your job is interpretation.

{ACCOUNT_CONTEXT}

## Today ({snapshot_date_from_snapshot(snapshot)})
Total portfolio: ${total:,.0f}
VIX: {vix_val} ({vix_signal})

## Deterministic Bucket Scorecard (computed in Python — trust these numbers)
{chr(10).join(bucket_lines)}

## Deterministic Alerts (policy rules checked in Python)
{alerts_text if alerts_text else '  No alerts triggered.'}

## Enriched Signals
{format_context_signals(context)}

## Portfolio-Level History (SQLite)
{history_text}

## Policy Context
{policy_text[:1800] if policy_text else '(No policy file.)'}

## Your job
Interpret the deterministic scorecard above. Do not recalculate the numbers — use them.
Use the enriched signals to add depth to your interpretation.
Keep it tight. Exception-based. No stock essays. No market newsletters.

## Output JSON only
{{
  "summary": "One sentence bottom line",
  "primary_alert": "Most important issue right now, or: None",
  "bucket_narrative": [{{"bucket": "...", "status": "on_track|watch|attention|urgent", "note": "brief reason"}}],
  "recommendations": [{{"priority": 1, "action": "...", "rationale": "...", "urgency": "today|this_week|this_month", "bucket": "..."}}],
  "market_context": {{"vix_signal": "...", "regime": "...", "polymarket_summary": "...", "relevance": "..."}},
  "distribution_pacing": {{"dad_ira": {{"ytd": 0, "floor": 0, "pct": 0, "status": "on_track|behind"}}, "mom_ira": {{"ytd": 0, "floor": 0, "pct": 0, "status": "on_track|behind"}}}},
  "one_thing": "One action, or: No action needed today.",
  "leave_alone": ["bucket names that should not be touched"]
}}"""


def _distribution_pacing_summary(context: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    pacing_items = (context.get("policy_delta") or {}).get("distribution_pacing") or []
    for item in pacing_items:
        account = str(item.get("account") or "").lower()
        key = account.replace(" ", "_").replace("(", "").replace(")", "")
        result[key] = {
            "ytd": round(float(item.get("ytd_distributions") or 0), 2),
            "floor": round(float(item.get("annual_floor") or 0), 2),
            "pct": round(float(item.get("pacing_pct") or 0), 1),
            "status": "on_track" if item.get("on_track", False) else "behind",
        }
    return result


def build_deterministic_fallback(
    *,
    snapshot: dict[str, Any],
    scorecard: dict[str, Any],
    context: PortfolioContext | dict[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    payload = _context_to_dict(context)
    alerts = list(scorecard.get("alerts", []))
    buckets = list(scorecard.get("buckets", []))
    first_alert = alerts[0] if alerts else None

    bucket_narrative = []
    for bucket in buckets:
        status = bucket.get("status") or "on_track"
        if status == "on_track":
            continue
        note = ""
        matching = next((alert for alert in alerts if alert.get("bucket") == bucket.get("bucket")), None)
        if matching:
            note = matching.get("issue") or ""
        elif isinstance(bucket.get("wow_pct"), int | float):
            note = f"Weekly move {bucket['wow_pct']:+.1f}%"
        else:
            note = "Requires review"
        mapped_status = "attention" if status == "warning" else status
        bucket_narrative.append(
            {
                "bucket": bucket.get("bucket"),
                "status": mapped_status,
                "note": note,
            }
        )

    recommendations = []
    for index, alert in enumerate(alerts[:4], start=1):
        urgency = "today" if alert.get("level") == "urgent" else "this_week"
        recommendations.append(
            {
                "priority": index,
                "action": alert.get("action") or f"Review {alert.get('bucket', 'portfolio')}",
                "rationale": alert.get("issue") or "Policy posture changed.",
                "urgency": urgency,
                "bucket": alert.get("bucket") or "portfolio",
            }
        )

    regime = (payload.get("regime") or {}).get("regime")
    polymarket = (payload.get("polymarket") or {}).get("signals") or []
    polymarket_summary = ""
    if polymarket:
        first = polymarket[0]
        if first.get("probability") is not None:
            polymarket_summary = f"{first.get('title', '')}: {first['probability'] * 100:.0f}%"
        else:
            polymarket_summary = str(first.get("summary") or "")

    if first_alert:
        summary = f"Primary attention item: {first_alert.get('bucket')}: {first_alert.get('issue')}"
        primary_alert = first_alert.get("issue") or "None"
        one_thing = first_alert.get("action") or f"Review {first_alert.get('bucket', 'portfolio')}"
    else:
        summary = "No material policy alerts today; maintain current posture unless a specific bucket changed."
        primary_alert = "None"
        one_thing = "No action needed today."

    return {
        "summary": summary,
        "primary_alert": primary_alert,
        "bucket_narrative": bucket_narrative[:6],
        "recommendations": recommendations,
        "market_context": {
            "vix_signal": str(((snapshot.get("market") or {}).get("vix") or {}).get("signal") or ""),
            "regime": regime or "unknown",
            "polymarket_summary": polymarket_summary,
            "relevance": reason,
        },
        "distribution_pacing": _distribution_pacing_summary(payload),
        "one_thing": one_thing,
        "leave_alone": [bucket.get("bucket") for bucket in buckets if bucket.get("status") == "on_track"],
        "parse_error": True,
        "fallback_reason": reason,
    }


def _normalize_analysis_payload(payload: dict[str, Any], *, fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(fallback)
    for key, value in payload.items():
        if value is not None:
            merged[key] = value
    merged["parse_error"] = bool(payload.get("parse_error", False))
    if payload.get("fallback_reason"):
        merged["fallback_reason"] = payload["fallback_reason"]
    return merged


def run_model(prompt: str, *, model_command: str | None = None) -> tuple[dict[str, Any] | None, str, str | None, str]:
    command = model_command or os.environ.get("PORTFOLIO_ANALYSIS_COMMAND", DEFAULT_ANALYSIS_COMMAND)
    result = subprocess.run(
        shlex.split(command),
        input=prompt,
        capture_output=True,
        text=True,
        timeout=300,
        env={key: value for key, value in os.environ.items() if key not in {"CLAUDECODE", "CLAUDE_CODE"}},
    )
    if result.returncode != 0:
        return None, (result.stdout or "").strip(), (result.stderr or result.stdout).strip(), command

    content = result.stdout.strip()
    candidate = content
    if not content.startswith("{") and "{" in content:
        start = content.find("{")
        end = content.rfind("}") + 1
        candidate = content[start:end]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, content, str(exc), command
    if not isinstance(payload, dict):
        return None, content, "model did not return a JSON object", command
    return payload, content, None, command


def extract_context_signals(context: PortfolioContext | dict[str, Any] | None) -> dict[str, Any]:
    payload = _context_to_dict(context)
    if not payload:
        return {}
    regime = payload.get("regime") or {}
    polymarket = payload.get("polymarket") or {}
    lynch = payload.get("lynch") or {}
    delta = payload.get("policy_delta") or {}
    return {
        "regime": regime.get("regime", "unknown"),
        "regime_description": regime.get("description", ""),
        "polymarket": [
            {
                "title": signal.get("title"),
                "probability": signal.get("probability"),
                "summary": signal.get("summary"),
            }
            for signal in (polymarket.get("signals") or [])[:3]
        ],
        "ytd_distributions": payload.get("ytd_distributions", {}),
        "lynch_signals": {
            "total_checked": lynch.get("total_checked", 0),
            "signals_found": lynch.get("signals_found", 0),
            "flagged_symbols": [
                item.get("symbol") for item in (lynch.get("flagged") or [])[:5] if item.get("symbol")
            ],
        },
        "distribution_pacing": delta.get("distribution_pacing", []),
        "policy_alerts": [
            {
                "bucket": alert.get("bucket"),
                "severity": alert.get("severity"),
                "message": alert.get("message"),
            }
            for alert in (delta.get("alerts") or [])[:5]
        ],
        "calendar_actions": (delta.get("calendar_actions") or [])[:3],
    }


def analyze_brief(
    *,
    snapshot: dict[str, Any],
    scorecard: dict[str, Any],
    context: PortfolioContext | dict[str, Any] | None,
    history_store: HistoryStore,
    model_command: str | None = None,
) -> dict[str, Any]:
    policy_path = resolve_policy_path()
    policy_text = policy_path.read_text() if policy_path and policy_path.exists() else ""
    fallback = build_deterministic_fallback(
        snapshot=snapshot,
        scorecard=scorecard,
        context=context,
        reason="deterministic fallback",
    )
    prompt = build_prompt(
        scorecard=scorecard,
        snapshot=snapshot,
        portfolio_history=load_portfolio_history(history_store, limit=7),
        policy_text=policy_text,
        context=context,
    )
    payload, raw_response, error, resolved_command = run_model(prompt, model_command=model_command)
    if error or payload is None:
        analysis = dict(fallback)
        analysis["fallback_reason"] = error or "model call failed"
        analysis["parse_error"] = True
        return {
            "analysis": analysis,
            "raw_response": raw_response,
            "fallback_mode": "deterministic",
            "model_command": resolved_command,
            "prompt_version": ANALYSIS_PROMPT_VERSION,
            "context_signals": extract_context_signals(context),
        }

    normalized = _normalize_analysis_payload(payload, fallback=fallback)
    normalized["parse_error"] = False
    normalized.pop("fallback_reason", None)
    return {
        "analysis": normalized,
        "raw_response": raw_response,
        "fallback_mode": None,
        "model_command": resolved_command,
        "prompt_version": ANALYSIS_PROMPT_VERSION,
        "context_signals": extract_context_signals(context),
    }


__all__ = [
    "ACCOUNT_CONTEXT",
    "ANALYSIS_PROMPT_VERSION",
    "DEFAULT_ANALYSIS_COMMAND",
    "analyze_brief",
    "build_deterministic_fallback",
    "build_prompt",
    "extract_context_signals",
    "format_context_signals",
    "snapshot_date_from_snapshot",
]
