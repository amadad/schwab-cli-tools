"""Prompt templates for structured advisor recommendations."""

RECOMMEND_PROMPT = """You are generating a concise investment recommendation journal entry.
Return JSON only.

Focus on one materially useful recommendation.
Do not overengineer. Do not give 5 ideas. Give the clearest one.

Required JSON shape:
{{
  "thesis": "one-sentence recommendation",
  "rationale": "why this is interesting or actionable now",
  "recommendation_type": "market|portfolio|security",
  "target_type": "portfolio|account|bucket|symbol",
  "target_id": "what the recommendation applies to",
  "direction": "buy|trim|hold|deploy|wait|de-risk|review",
  "horizon_days": 5,
  "benchmark_symbol": "optional benchmark like SPY or VT",
  "confidence": 0.0,
  "tags": ["optional", "keywords"]
}}

Context:
---
{context}
---
"""
