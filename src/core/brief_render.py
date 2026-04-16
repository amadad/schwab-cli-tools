"""Rendering and delivery helpers for portfolio briefs."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime

from src.core.brief_types import JsonDict
from src.core.json_types import JsonObject


def _split_csv_env(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def email_settings() -> JsonObject:
    return {
        "from": os.environ.get("PORTFOLIO_BRIEF_EMAIL_FROM", "agent@orb.scty.org"),
        "to": _split_csv_env("PORTFOLIO_BRIEF_EMAIL_TO", ["amadad@gmail.com"]),
        "reply_to": _split_csv_env("PORTFOLIO_BRIEF_EMAIL_REPLY_TO", ["agent@scty.org"]),
    }


def _alert_level(status: str) -> str:
    return {
        "urgent": "urgent",
        "attention": "warning",
        "warning": "warning",
        "watch": "info",
        "on_track": "info",
    }.get(status, "info")


def brief_subject(date_str: str, primary_alert: str, one_thing: str) -> str:
    lead = one_thing or primary_alert or "No action needed today"
    if lead == "None":
        lead = primary_alert or "No action needed today"
    lead = lead.replace("\n", " ").strip().rstrip(".")
    if len(lead) > 90:
        lead = lead[:87].rstrip() + "..."
    try:
        short_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d")
    except ValueError:
        short_date = date_str
    return f"Brief • {short_date} • {lead}"


def build_briefing(
    *,
    brief_date: str,
    analysis: JsonObject,
    scorecard: JsonObject,
    context_signals: JsonObject | None = None,
) -> JsonObject:
    primary_alert = analysis.get("primary_alert") or "None"
    summary = analysis.get("summary") or "Portfolio check complete."
    one_thing = analysis.get("one_thing") or "No action needed today."
    context_signals = context_signals or {}

    alerts: list[JsonDict] = []
    for alert in scorecard.get("alerts", [])[:4]:
        alerts.append(
            {
                "level": alert.get("level", "info"),
                "bucket": alert.get("bucket", ""),
                "issue": alert.get("issue", ""),
                "action": alert.get("action", ""),
            }
        )

    if not alerts:
        for item in analysis.get("bucket_narrative", []):
            status = item.get("status", "on_track")
            if status == "on_track":
                continue
            alerts.append(
                {
                    "level": _alert_level(status),
                    "bucket": item.get("bucket", ""),
                    "issue": item.get("note", ""),
                    "action": "",
                }
            )
            if len(alerts) >= 4:
                break

    what_changed: list[str] = []
    for item in analysis.get("bucket_narrative", []):
        status = item.get("status", "on_track")
        if status == "on_track":
            continue
        bucket = item.get("bucket", "")
        note = item.get("note", "")
        what_changed.append(f"{bucket}: {note}" if bucket else note)
        if len(what_changed) >= 4:
            break
    if not what_changed and primary_alert and primary_alert != "None":
        what_changed = [primary_alert]
    if not what_changed:
        what_changed = ["No material changes from policy posture."]

    top_actions: list[JsonDict] = []
    for rec in analysis.get("recommendations", [])[:4]:
        top_actions.append(
            {
                "priority": rec.get("priority", len(top_actions) + 1),
                "action": rec.get("action", ""),
                "detail": rec.get("rationale", ""),
                "bucket": rec.get("bucket", ""),
            }
        )
    if not top_actions:
        top_actions = [{"priority": 1, "action": one_thing, "detail": "", "bucket": ""}]

    market_context = analysis.get("market_context", {})
    market_note_parts = [
        market_context.get("vix_signal", ""),
        market_context.get("polymarket_summary", ""),
        market_context.get("relevance", ""),
    ]
    market_note = " ".join(part.strip() for part in market_note_parts if part).strip()

    alert_count = len(scorecard.get("alerts", []))
    if alert_count and primary_alert == "None":
        primary_alert = f"{alert_count} policy alerts"

    return {
        "subject": brief_subject(brief_date, primary_alert, one_thing),
        "bottom_line": summary,
        "what_changed": what_changed,
        "alerts": alerts,
        "alert_count": alert_count,
        "top_3": top_actions,
        "one_thing": one_thing,
        "market_note": market_note,
        "leave_alone": analysis.get("leave_alone", []),
        "context_signals": context_signals,
        "fallback_mode": analysis.get("fallback_reason"),
    }


def _build_advisor_section_html(advisor: JsonObject | None) -> str:
    if not advisor:
        return ""
    confidence = advisor.get("confidence")
    conf_text = f"{confidence:.2f}" if isinstance(confidence, int | float) else "N/A"
    meta = [
        f"Run #{advisor.get('id')}",
        f"{advisor.get('recommendation_type', 'recommendation').title()} call",
        f"{advisor.get('direction', 'hold').title()} {advisor.get('target_id', 'portfolio')}",
        f"{advisor.get('horizon_days', '?')}d horizon",
        f"Confidence {conf_text}",
    ]
    rationale = str(advisor.get("rationale") or "").strip()
    tags = advisor.get("tags") or []
    tags_html = ""
    if tags:
        chips = "".join(
            f"<span style='display:inline-block;background:#f3f4f6;border-radius:999px;padding:4px 8px;margin:0 6px 6px 0;font-size:12px;color:#4b5563'>{tag}</span>"
            for tag in tags[:5]
        )
        tags_html = f"<div style='margin-top:10px'>{chips}</div>"
    return (
        '<p style="font-size:11px;font-weight:600;color:#7c3aed;letter-spacing:1px;text-transform:uppercase;margin:24px 0 12px 0">Advisor Call</p>'
        + f"<p style='font-size:15px;line-height:1.6;color:#111827;margin:0 0 8px 0'><strong>{advisor.get('thesis','')}</strong></p>"
        + f"<p style='font-size:13px;color:#6b7280;margin:0 0 10px 0'>{' • '.join(meta)}</p>"
        + (
            f"<p style='font-size:14px;line-height:1.7;color:#3a3a3a;margin:0'>{rationale}</p>"
            if rationale
            else ""
        )
        + tags_html
    )


def _build_advisor_section_text(advisor: JsonObject | None) -> list[str]:
    if not advisor:
        return []
    confidence = advisor.get("confidence")
    conf_text = f"{confidence:.2f}" if isinstance(confidence, int | float) else "N/A"
    lines = [
        "ADVISOR CALL",
        f"Run #{advisor.get('id')} • {advisor.get('direction','hold')} {advisor.get('target_id','portfolio')} • {advisor.get('horizon_days','?')}d • confidence {conf_text}",
        str(advisor.get("thesis") or ""),
    ]
    if advisor.get("rationale"):
        lines += ["", str(advisor["rationale"])]
    return lines


def _format_signed_percent(value: object) -> str:
    if not isinstance(value, int | float):
        return "—"
    return f"{value:+.1f}%"


def _build_bucket_strip_html(scorecard: JsonObject) -> str:
    rows = scorecard.get("buckets", [])
    if not rows:
        return ""
    groups = {
        "⚠️ Needs Attention": [],
        "Inherited IRAs": ["Inherited IRA (Dad)", "Inherited IRA (Mom)", "Inherited Roth (Mom)"],
        "Retirement": ["Trad IRA (Ali)", "Roth (Ali)", "Roth (Syra)"],
        "Taxable": ["Trading", "Index", "Business"],
        "Education": [
            "Education (Ammar)",
            "Education (Hasan)",
            "Education (Laila)",
            "Education (Noora)",
        ],
        "Other": ["Cash / Bank", "DAF"],
    }
    bucket_map = {bucket["bucket"]: bucket for bucket in rows}
    groups["⚠️ Needs Attention"] = [
        bucket["bucket"]
        for bucket in rows
        if bucket.get("status") in ("urgent", "warning", "attention")
    ]

    td = "padding:5px 8px;font-size:13px;color:#374151;border-bottom:1px solid #f0ebff"
    th = "padding:4px 8px;font-size:10px;font-weight:700;color:#7c3aed;letter-spacing:1px;text-transform:uppercase;border-bottom:2px solid #e9d5ff"
    html = '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:8px">'
    html += f'<tr><th style="{th}" align="left">Bucket</th><th style="{th}" align="right">Value</th><th style="{th}" align="right">Cash</th><th style="{th}" align="right">WoW</th></tr>'

    for group_name, bucket_names in groups.items():
        buckets_in_group = [bucket_map[name] for name in bucket_names if name in bucket_map]
        if not buckets_in_group:
            continue
        html += f'<tr><td colspan="4" style="padding:8px 8px 2px;font-size:10px;font-weight:700;color:#9ca3af;letter-spacing:1px;text-transform:uppercase;border-top:1px solid #f0ebff">{group_name}</td></tr>'
        for bucket in buckets_in_group:
            status = bucket.get("status", "on_track")
            dot = (
                "🔴" if status == "urgent" else "🟡" if status in ("warning", "attention") else "🟢"
            )
            name_color = (
                "#dc2626"
                if status == "urgent"
                else "#d97706" if status in ("warning", "attention") else "#111827"
            )
            cash_pct = bucket.get("cash_pct", 0)
            cash_color = "#dc2626" if cash_pct > 40 else "#d97706" if cash_pct > 20 else "#6b7280"
            wow_pct = bucket.get("wow_pct")
            wow_color = (
                "#059669" if isinstance(wow_pct, int | float) and wow_pct >= 0 else "#dc2626"
            )
            value = bucket.get("value") or 0
            html += (
                f'<tr><td style="{td}"><span style="color:{name_color}">{dot} {bucket["bucket"]}</span></td>'
                f'<td style="{td};text-align:right">${value/1000:.0f}k</td>'
                f'<td style="{td};text-align:right"><span style="color:{cash_color}">{cash_pct:.0f}%</span></td>'
                f'<td style="{td};text-align:right"><span style="color:{wow_color}">{_format_signed_percent(wow_pct)}</span></td></tr>'
            )
    html += "</table>"
    return html


def _build_context_strip_html(context_signals: JsonObject) -> str:
    parts: list[str] = []
    regime = context_signals.get("regime")
    if regime:
        color = "#059669" if "risk_on" in regime.lower() else "#d97706"
        parts.append(
            f"<span style='color:{color};font-weight:600'>{regime.upper().replace('_', ' ')}</span>"
        )
    for pacing in context_signals.get("distribution_pacing", []):
        pct = pacing.get("pacing_pct", 0)
        color = "#059669" if pacing.get("on_track", True) else "#dc2626"
        parts.append(f"<span style='color:{color}'>{pacing.get('account', '')}: {pct:.0f}%</span>")
    for signal in context_signals.get("polymarket", [])[:1]:
        if signal.get("probability") is not None:
            parts.append(
                f"<span style='color:#6b6b6b'>{signal['title']}: {signal['probability'] * 100:.0f}%</span>"
            )
    if not parts:
        return ""
    return (
        '<p style="font-size:11px;font-weight:600;color:#6b6b6b;letter-spacing:1px;text-transform:uppercase;margin:16px 0 8px 0">Signals</p>'
        + '<p style="font-size:13px;line-height:1.8;margin:0 0 12px 0">'
        + "  •  ".join(parts)
        + "</p>"
    )


def render_html(
    *,
    briefing: JsonObject,
    snapshot: JsonObject,
    scorecard: JsonObject,
    advisor: JsonObject | None,
) -> str:
    portfolio = snapshot.get("portfolio") or {}
    summary = portfolio.get("summary") or {}
    market = snapshot.get("market") or {}
    vix = market.get("vix") or {}
    total = summary.get("total_value", 0)
    cash_pct = summary.get("cash_percentage", 0)
    vix_val = vix.get("vix") if isinstance(vix, dict) else None
    send_date = datetime.now().strftime("%b %d, %Y")

    subject = briefing.get("subject", "")
    alert_count = briefing.get("alert_count", len(briefing.get("alerts", [])))
    has_high_alert = any(
        alert.get("level") in ("urgent", "warning") for alert in briefing.get("alerts", [])
    )
    urgency_keywords = [
        "action",
        "attention",
        "penalty",
        "risk",
        "deadline",
        "urgent",
        "required",
        "alert",
    ]
    is_urgent = (
        has_high_alert
        or alert_count > 0
        or any(
            word in (subject + briefing.get("one_thing", "")).lower() for word in urgency_keywords
        )
    )
    status = "ATTENTION NEEDED" if is_urgent else "ALL CLEAR"
    status_color = "#dc2626" if is_urgent else "#059669"

    alerts_html = ""
    for alert in briefing.get("alerts", []):
        level = alert.get("level", "info")
        color = "#dc2626" if level == "urgent" else "#d97706" if level == "warning" else "#2563eb"
        alerts_html += f"<p style='font-size:13px;line-height:1.6;color:{color};margin:0 0 4px 0'><strong>[{level.upper()}] {alert.get('bucket','')}</strong> — {alert.get('issue','')}</p>"
        if alert.get("action"):
            alerts_html += f"<p style='font-size:13px;color:#6b6b6b;margin:0 0 8px 8px'>→ {alert['action']}</p>"
    alerts_section = (
        (
            '<p style="font-size:11px;font-weight:600;color:#dc2626;letter-spacing:1px;text-transform:uppercase;margin:0 0 12px 0">Alerts</p>'
            + alerts_html
            + '<div style="height:16px"></div>'
        )
        if alerts_html
        else ""
    )

    vix_header = (
        f' <span style="color:#9a9a9a;font-size:13px">— VIX {vix_val}</span>'
        if isinstance(vix_val, int | float)
        else ""
    )
    changes_html = "".join(
        f"<p style='font-size:14px;line-height:1.7;color:#3a3a3a;margin:0'>• {item}</p>"
        for item in briefing.get("what_changed", [])
    )
    top_html = ""
    for index, item in enumerate(briefing.get("top_3", []), start=1):
        top_html += f"<p style='font-size:14px;line-height:1.7;color:#3a3a3a;margin:0'>{index}. {item.get('action','')}</p>"
        if item.get("detail"):
            top_html += f"<p style='font-size:13px;line-height:1.6;color:#9a9a9a;margin:0 0 8px 14px'>{item['detail']}</p>"

    market_note_html = (
        f"<p style='font-size:14px;color:#3a3a3a;margin:16px 0 0 0'>{briefing['market_note']}</p>"
        if briefing.get("market_note")
        else ""
    )
    context_strip_html = _build_context_strip_html(briefing.get("context_signals", {}))
    bucket_strip_html = _build_bucket_strip_html(scorecard)
    bucket_status_section = (
        (
            '<p style="font-size:11px;font-weight:600;color:#7c3aed;letter-spacing:1px;text-transform:uppercase;margin:0 0 12px 0">Bucket Status</p>'
            + bucket_strip_html
        )
        if bucket_strip_html
        else ""
    )
    fallback_note = ""
    if briefing.get("fallback_mode"):
        fallback_note = f"<p style='font-size:12px;color:#9a3412;margin:0 0 16px 0'>Rendered from deterministic fallback: {briefing['fallback_mode']}</p>"

    return f"""<!DOCTYPE html>
<html lang=\"en\"><head><meta charset=\"UTF-8\"/></head>
<body style=\"background-color:#f8f8f8;font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:0;padding:0\">
<div style=\"display:none\">Morning Brief — {send_date} — {status}</div>
<table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background-color:#f8f8f8\"><tr><td style=\"padding:40px 20px\">
<table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"max-width:560px;margin:0 auto\"><tr><td>
<table width=\"100%\" style=\"margin-bottom:24px\"><tr><td><span style=\"font-size:32px\">🌙</span></td><td style=\"text-align:right;color:#6b6b6b;font-size:13px\">{send_date}</td></tr></table>
<table width=\"100%\" style=\"background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,0.08);padding:32px\"><tr><td>
<p style=\"margin:0 0 4px 0\"><strong style=\"color:{status_color}\">{status}</strong>{vix_header}</p>
<p style=\"font-size:32px;font-weight:700;margin:8px 0 4px 0\">${total/1e6:.2f}M</p>
<p style=\"color:#6b6b6b;margin:0\">Cash {cash_pct:.1f}%</p>
</td></tr></table>
<div style=\"height:16px\"></div>
<table width=\"100%\" style=\"background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,0.08);padding:32px\"><tr><td>
{alerts_section}
{fallback_note}
{context_strip_html}
{bucket_status_section}
{_build_advisor_section_html(advisor)}
<p style=\"font-size:11px;font-weight:600;color:#7c3aed;letter-spacing:1px;text-transform:uppercase;margin:24px 0 12px 0\">Bottom Line</p>
<p style=\"font-size:14px;line-height:1.7;color:#3a3a3a;margin:0\">{briefing.get('bottom_line','')}</p>
<p style=\"font-size:11px;font-weight:600;color:#7c3aed;letter-spacing:1px;text-transform:uppercase;margin:24px 0 12px 0\">What Changed</p>
{changes_html}
<p style=\"font-size:11px;font-weight:600;color:#7c3aed;letter-spacing:1px;text-transform:uppercase;margin:24px 0 12px 0\">Top 3 Today</p>
{top_html}
<p style=\"font-size:11px;font-weight:600;color:#f59e0b;letter-spacing:1px;text-transform:uppercase;margin:24px 0 12px 0\">If You Do One Thing</p>
<p style=\"font-size:14px;line-height:1.7;color:#1e40af;font-weight:500;margin:0\">{briefing.get('one_thing','')}</p>
{market_note_html}
<p style=\"font-size:13px;color:#9a9a9a;margin:32px 0 0 0\">— min</p>
</td></tr></table>
<p style=\"font-size:12px;color:#b0b0b0;text-align:center;margin-top:24px\">🌙 Morning Brief</p>
</td></tr></table>
</td></tr></table></body></html>"""


def render_text(
    *,
    briefing: JsonObject,
    snapshot: JsonObject,
    advisor: JsonObject | None,
) -> str:
    portfolio = snapshot.get("portfolio") or {}
    summary = portfolio.get("summary") or {}
    total = summary.get("total_value", 0)
    cash_pct = summary.get("cash_percentage", 0)
    send_date = datetime.now().strftime("%b %d, %Y")
    lines = [
        f"MORNING BRIEF • {send_date}",
        "=" * 40,
        f"${total/1e6:.2f}M  Cash {cash_pct:.1f}%",
        "",
        "BOTTOM LINE",
        briefing.get("bottom_line", ""),
        "",
        "WHAT CHANGED",
        *[f"• {item}" for item in briefing.get("what_changed", [])],
        "",
        f"ALERTS ({briefing.get('alert_count', len(briefing.get('alerts', [])))})",
        *[
            f"- [{alert.get('level','info').upper()}] {alert.get('bucket','')}: {alert.get('issue','')}"
            for alert in briefing.get("alerts", [])
        ],
        "",
        "TOP ACTIONS",
        *[
            f"{index}. {item.get('action','')}"
            for index, item in enumerate(briefing.get("top_3", []), start=1)
        ],
        "",
        "IF YOU DO ONE THING",
        briefing.get("one_thing", ""),
    ]
    if briefing.get("fallback_mode"):
        lines.extend(["", f"Fallback mode: {briefing['fallback_mode']}"])
    advisor_lines = _build_advisor_section_text(advisor)
    if advisor_lines:
        lines += ["", *advisor_lines]
    if briefing.get("market_note"):
        lines += ["", briefing["market_note"]]
    lines.append(f"\n—\n🌙 Morning Brief • {datetime.now().strftime('%I:%M %p')}")
    return "\n".join(lines)


def send_email(subject: str, html: str, text: str) -> JsonObject:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return {"error": "No RESEND_API_KEY"}
    settings = email_settings()
    payload = {
        "from": settings["from"],
        "to": settings["to"],
        "reply_to": settings["reply_to"],
        "subject": subject,
        "html": html,
        "text": text,
    }
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "cli-schwab/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code} {exc.reason}"}
    except (
        urllib.error.URLError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:  # pragma: no cover - network wrapper
        return {"error": str(exc)}


__all__ = [
    "brief_subject",
    "build_briefing",
    "email_settings",
    "render_html",
    "render_text",
    "send_email",
]
