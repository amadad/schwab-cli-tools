"""Polymarket probability data for portfolio context."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# Slugs for key macro markets relevant to portfolio policy decisions.
# These are the highest-volume Polymarket markets for Fed/macro topics.
# If a slug goes stale (market closes), the keyword fallback searches
# top-volume open markets for matching terms automatically.
MACRO_SLUGS = {
    "will-there-be-no-change-in-fed-interest-rates-after-the-june-2026-meeting": "Fed holds rates at June meeting",
    "how-many-fed-rate-cuts-in-2026": "Fed rate cuts in 2026 (event)",
    "what-will-the-fed-rate-be-at-the-end-of-2026": "Fed rate at end of 2026 (event)",
    "us-recession-by-end-of-2026": "US recession by end of 2026",
}

GAMMA_API_BASE = "https://gamma-api.polymarket.com"


@dataclass(slots=True)
class PolymarketSignal:
    slug: str
    title: str
    probability: float | None = None
    summary: str | None = None  # for multi-outcome events
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolymarketSignal:
        return cls(
            slug=str(data.get("slug") or ""),
            title=str(data.get("title") or ""),
            probability=(
                float(data["probability"]) if data.get("probability") is not None else None
            ),
            summary=str(data["summary"]) if data.get("summary") is not None else None,
            error=str(data["error"]) if data.get("error") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"slug": self.slug, "title": self.title}
        if self.probability is not None:
            d["probability"] = self.probability
            d["probability_pct"] = f"{self.probability * 100:.0f}%"
        if self.summary:
            d["summary"] = self.summary
        if self.error:
            d["error"] = self.error
        return d


@dataclass(slots=True)
class PolymarketSnapshot:
    signals: list[PolymarketSignal] = field(default_factory=list)
    timestamp: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolymarketSnapshot:
        return cls(
            signals=[PolymarketSignal.from_dict(signal) for signal in data.get("signals", [])],
            timestamp=str(data["timestamp"]) if data.get("timestamp") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signals": [s.to_dict() for s in self.signals],
            "timestamp": self.timestamp,
        }

    def summary_lines(self) -> list[str]:
        """Return human-readable summary lines for embedding in analysis prompts."""
        lines = []
        for s in self.signals:
            if s.probability is not None:
                lines.append(f"- {s.title}: {s.probability * 100:.0f}%")
            elif s.summary:
                lines.append(f"- {s.title}: {s.summary}")
            elif s.error:
                lines.append(f"- {s.title}: unavailable ({s.error})")
        return lines


_HEADERS = {"Accept": "application/json", "User-Agent": "cli-schwab/1.0"}


def _fetch_json(url: str) -> Any:
    """Fetch JSON from a URL with standard headers."""
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=10) as resp:
        return json.loads(resp.read())


def _search_market_by_keyword(keyword: str) -> float | str | None:
    """Fallback: search top-volume open markets by keyword."""
    url = (
        f"{GAMMA_API_BASE}/markets?limit=200&closed=false"
        f"&order=volume&ascending=false"
    )
    data = _fetch_json(url)
    if not data:
        return None

    kw_lower = keyword.lower()
    for m in data:
        if kw_lower in m.get("question", "").lower():
            outcome_prices = m.get("outcomePrices")
            if outcome_prices:
                prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                return float(prices[0]) if prices else None
    return None


def _fetch_market_by_slug(slug: str) -> float | str | None:
    """Fetch current probability or event summary for a Polymarket slug.

    For single-outcome markets, returns a float probability.
    For multi-outcome events, returns a formatted string summary.
    Falls back to keyword search if slug is not found.
    """
    # Try as a market first
    url = f"{GAMMA_API_BASE}/markets?slug={slug}&closed=false&limit=1"
    data = _fetch_json(url)

    if data:
        market = data[0] if isinstance(data, list) else data
        outcome_prices = market.get("outcomePrices")
        if outcome_prices:
            prices = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            return float(prices[0]) if prices else None
        return float(market.get("bestAsk", 0)) or None

    # Try as an event (multi-market container)
    url = f"{GAMMA_API_BASE}/events?slug={slug}&closed=false&limit=1"
    events = _fetch_json(url)

    if events:
        event = events[0] if isinstance(events, list) else events
        markets = event.get("markets", [])
        if markets:
            parts = []
            for m in sorted(markets, key=lambda x: float((json.loads(x.get("outcomePrices", '["0"]')) if isinstance(x.get("outcomePrices"), str) else x.get("outcomePrices", [0]))[0]), reverse=True)[:5]:
                q = m.get("groupItemTitle") or m.get("question", "")
                prices = m.get("outcomePrices")
                if prices:
                    p = json.loads(prices) if isinstance(prices, str) else prices
                    parts.append(f"{q}: {float(p[0])*100:.0f}%")
            if parts:
                return " | ".join(parts)

    # Fallback: keyword search from slug (e.g. "fed-cuts-interest-rates" → "fed cuts interest rates")
    keyword = slug.replace("-", " ").replace("_", " ")
    # Use the most distinctive words
    for kw in [keyword, " ".join(keyword.split()[:3])]:
        result = _search_market_by_keyword(kw)
        if result is not None:
            return result

    return None


def fetch_polymarket_signals(
    slugs: dict[str, str] | None = None,
) -> PolymarketSnapshot:
    """Fetch macro probability signals from Polymarket."""
    from datetime import datetime

    targets = slugs or MACRO_SLUGS
    signals: list[PolymarketSignal] = []

    for slug, title in targets.items():
        try:
            result = _fetch_market_by_slug(slug)
            if isinstance(result, float):
                signals.append(PolymarketSignal(slug=slug, title=title, probability=result))
            elif isinstance(result, str):
                signals.append(PolymarketSignal(slug=slug, title=title, summary=result))
            else:
                signals.append(PolymarketSignal(slug=slug, title=title, error="not found"))
        except Exception as exc:
            signals.append(PolymarketSignal(slug=slug, title=title, error=str(exc)))

    return PolymarketSnapshot(signals=signals, timestamp=datetime.now().isoformat())
