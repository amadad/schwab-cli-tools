"""Prompt templates for portfolio analysis.

These templates consume PortfolioContext.to_prompt_block() output and produce
different depth levels of analysis: brief, review, and memo.
"""

from __future__ import annotations

BRIEF_PROMPT = """\
You are a financial advisor reviewing a client's portfolio. Below is the current \
portfolio context with positions, market data, macro signals, distribution pacing, \
and policy alerts.

Produce a concise morning brief (5-10 bullet points) covering:
1. Portfolio status: total value, cash level, any notable changes
2. Market context: VIX level, regime, what it means for this portfolio
3. Macro signals: Polymarket probabilities and their implications for deployment pacing
4. Policy alerts: any items that need action, ranked by urgency
5. Distribution pacing: are inherited IRAs on track?
6. One actionable recommendation for the week

Be direct. Lead with what needs attention. Skip anything that's fine.

---
{context}
---
"""

WEEKLY_REVIEW_PROMPT = """\
You are a financial advisor producing a weekly portfolio review. Below is the \
complete portfolio context.

Produce a structured weekly review with these sections:

## Portfolio Summary
Total value, week-over-week change context, cash position vs policy targets.

## Bucket Scorecard
For each account: value, cash %, status vs policy, any flags.

## Inherited IRA Pacing
Distribution progress against annual floors. Specific dollar amounts needed. \
Timeline recommendations given current pacing and market conditions.

## Market Assessment
VIX, regime, and Polymarket signals. How these should influence deployment \
pacing for inherited-IRA excess cash and any rebalancing decisions.

## Lynch Signals
Any sell signals flagged. If none, state that clearly.

## Priority Actions
Numbered list of specific actions for the coming week, ordered by urgency. \
Include dollar amounts and account names.

## Strategic Alignment
Check current state against policy: cash bands, distribution pace, \
inherited IRA combined % of total.

---
{context}
---
"""

MEMO_PROMPT = """\
You are a senior financial advisor writing an investment memo for a client. \
Below is the complete portfolio context with positions, market data, macro \
signals, and policy evaluation.

Write a decision-ready memo that reasons like a financial advisor, not a data dump.

Requirements:
- Start with the single most important thing the client needs to know right now
- For inherited IRAs: compute exact deployment schedules (monthly amounts, \
  start dates, what to buy) given the current regime and horizon
- For cash levels: compare to policy, explain whether deviations are justified \
  by current market conditions
- Connect Polymarket probabilities to specific portfolio decisions \
  (e.g., "36% recession probability at VIX 31 argues for pacing inherited IRA \
  deployment at $60k/month rather than lump sum")
- Provide tax-aware reasoning (bracket headroom, withholding, Roth conversion)
- End with a decision matrix: action / account / amount / timing / rationale

Tag assertions as [Fact] (from data), [Analysis] (derived), or [Recommendation].

---
{context}
---
"""


def render_prompt(template: str, context_block: str) -> str:
    """Render a prompt template with the portfolio context block."""
    return template.format(context=context_block)


TEMPLATES = {
    "brief": BRIEF_PROMPT,
    "review": WEEKLY_REVIEW_PROMPT,
    "memo": MEMO_PROMPT,
}
