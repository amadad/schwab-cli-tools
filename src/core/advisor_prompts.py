"""Prompt templates for the portfolio advisor learning loop.

These templates consume the learning context assembled by advisor.build_learning_prompt()
and produce different outputs: retrospectives, pattern extraction, and scan criteria.
"""

from __future__ import annotations

RETROSPECTIVE_PROMPT = """\
You are a portfolio advisor conducting a retrospective on investment theses. \
Below is the learning loop context: open theses, closed theses with outcomes, \
and the current market environment.

For each thesis that has been evaluated but NOT yet reviewed, produce a \
structured retrospective:

1. **Thesis vs Reality**: What was the thesis? What actually happened?
2. **Regime Alignment**: Was the entry regime favorable for this type of trade? \
   Did regime shifts help or hurt?
3. **Signal Quality**: Which signals at entry were predictive? Which were noise?
4. **Timing Assessment**: Was the entry/exit timing good relative to the regime cycle?
5. **Lesson**: One specific, actionable lesson to improve future selection.

Be brutally honest. The goal is compounding learning, not ego protection. \
Tag each lesson as [KEEP] (repeat this approach), [STOP] (avoid this pattern), \
or [ADJUST] (modify the approach).

---
{context}
---

Current Market:
{market_context}
---
"""

PATTERN_EXTRACTION_PROMPT = """\
You are a quantitative portfolio analyst extracting signal patterns from thesis history. \
Below is the full learning context with all reviewed theses, their outcomes, \
and any previously extracted patterns.

Your task:
1. **Identify New Patterns**: Look for combinations of entry conditions \
   (regime, VIX band, sector rotation, sentiment) that consistently led to \
   good or bad outcomes. Name each pattern clearly.
2. **Validate Existing Patterns**: For patterns already extracted, check if \
   recent data supports or contradicts them. Update confidence levels.
3. **Regime-Specific Insights**: Which strategies worked in risk-on vs risk-off? \
   During VIX spikes vs calm periods? When sector rotation favored cyclicals vs defensives?
4. **Anti-Patterns**: What conditions reliably predicted LOSSES? These are as \
   valuable as win patterns.
5. **Confidence Ranking**: Rank patterns by (hit_rate * avg_return * sqrt(sample_size)). \
   Flag patterns with fewer than 5 samples as tentative.

Output format for each pattern:
- Pattern Name: descriptive_name
- Conditions: regime=X, vix_band=Y, ...
- Hit Rate: X% (N samples)
- Avg Return: X%
- Confidence: HIGH/MEDIUM/LOW
- Regime Affinity: risk_on/risk_off/neutral

The bitter lesson applies: trust the data over narratives. If a pattern \
contradicts conventional wisdom but has sample support, flag it prominently.

---
{context}
---
"""

SCAN_CRITERIA_PROMPT = """\
You are a research analyst generating scan criteria for new investment candidates. \
Below is the full learning context including performance history, extracted patterns, \
and current market conditions.

Based on:
1. What patterns have worked historically (from the pattern leaderboard)
2. The CURRENT market regime and VIX level
3. Lessons from recent thesis reviews (especially [KEEP] items)
4. Anti-patterns to AVOID

Generate specific scan criteria for finding new candidates:

## Scan Output Format:
- **Regime Context**: Current regime and what it implies for selection
- **Primary Criteria**: The top 3-5 conditions a candidate MUST meet, \
  derived from the highest-confidence patterns that match current conditions
- **Secondary Criteria**: Nice-to-haves from medium-confidence patterns
- **Exclusion Criteria**: What to AVOID based on anti-patterns
- **Sector Lean**: Which sectors to favor/avoid given rotation signals
- **Position Sizing Guidance**: Based on conviction level and VIX
- **Candidate Suggestions**: If you can identify specific symbols that match, list them \
  with brief rationale

Remember: the goal is alpha generation through systematic pattern application, \
not gut feel. Every criterion should trace back to a pattern with sample support.

---
{context}
---

Current Market:
{market_context}
---
"""

ADVISOR_TEMPLATES = {
    "retrospective": RETROSPECTIVE_PROMPT,
    "patterns": PATTERN_EXTRACTION_PROMPT,
    "scan": SCAN_CRITERIA_PROMPT,
}


def render_advisor_prompt(
    template_name: str,
    *,
    learning_context: str,
    market_context: str = "Not available",
) -> str:
    """Render an advisor prompt template with learning and market context."""
    template = ADVISOR_TEMPLATES.get(template_name)
    if not template:
        available = ", ".join(ADVISOR_TEMPLATES.keys())
        raise ValueError(f"Unknown advisor template: {template_name}. Available: {available}")
    return template.format(context=learning_context, market_context=market_context)
