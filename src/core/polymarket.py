"""Polymarket probability data for portfolio context."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from src.core.json_types import JsonObject, JsonValue, as_json_array, as_json_object

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
POLYMARKET_FETCH_ERRORS = (
    OSError,
    TimeoutError,
    ValueError,
    TypeError,
    json.JSONDecodeError,
    urllib.error.URLError,
)


@dataclass(slots=True)
class PolymarketSignal:
    slug: str
    title: str
    probability: float | None = None
    summary: str | None = None  # for multi-outcome events
    error: str | None = None

    @classmethod
    def from_dict(cls, data: JsonObject) -> PolymarketSignal:
        return cls(
            slug=str(data.get("slug") or ""),
            title=str(data.get("title") or ""),
            probability=(
                float(data["probability"]) if data.get("probability") is not None else None
            ),
            summary=str(data["summary"]) if data.get("summary") is not None else None,
            error=str(data["error"]) if data.get("error") is not None else None,
        )

    def to_dict(self) -> JsonObject:
        d: JsonObject = {"slug": self.slug, "title": self.title}
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
    def from_dict(cls, data: JsonObject) -> PolymarketSnapshot:
        return cls(
            signals=[PolymarketSignal.from_dict(signal) for signal in data.get("signals", [])],
            timestamp=str(data["timestamp"]) if data.get("timestamp") is not None else None,
        )

    def to_dict(self) -> JsonObject:
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


def _fetch_json(url: str) -> JsonValue:
    """Fetch JSON from a URL with standard headers."""
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=10) as resp:
        return json.loads(resp.read())


def _search_market_by_keyword(keyword: str) -> float | str | None:
    """Fallback: search top-volume open markets by keyword."""
    url = f"{GAMMA_API_BASE}/markets?limit=200&closed=false" f"&order=volume&ascending=false"
    data = as_json_array(_fetch_json(url))
    if not data:
        return None

    kw_lower = keyword.lower()
    for market in data:
        item = as_json_object(market)
        if kw_lower in str(item.get("question") or "").lower():
            outcome_prices = item.get("outcomePrices")
            if outcome_prices:
                prices = (
                    json.loads(outcome_prices)
                    if isinstance(outcome_prices, str)
                    else outcome_prices
                )
                if isinstance(prices, list) and prices:
                    return float(prices[0])
    return None


def _fetch_market_by_slug(slug: str) -> float | str | None:
    """Fetch current probability or event summary for a Polymarket slug.

    For single-outcome markets, returns a float probability.
    For multi-outcome events, returns a formatted string summary.
    Falls back to keyword search if slug is not found.
    """
    # Try as a market first
    url = f"{GAMMA_API_BASE}/markets?slug={slug}&closed=false&limit=1"
    data = as_json_array(_fetch_json(url))

    if data:
        market = as_json_object(data[0])
        outcome_prices = market.get("outcomePrices")
        if outcome_prices:
            prices = (
                json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            )
            if isinstance(prices, list) and prices:
                return float(prices[0])
        return float(market.get("bestAsk", 0) or 0) or None

    # Try as an event (multi-market container)
    url = f"{GAMMA_API_BASE}/events?slug={slug}&closed=false&limit=1"
    events = as_json_array(_fetch_json(url))

    if events:
        event = as_json_object(events[0])
        markets = [as_json_object(item) for item in as_json_array(event.get("markets"))]
        if markets:
            parts = []
            for market in sorted(
                markets,
                key=lambda item: float(
                    (
                        json.loads(str(item.get("outcomePrices") or '["0"]'))
                        if isinstance(item.get("outcomePrices"), str)
                        else item.get("outcomePrices", [0])
                    )[0]
                ),
                reverse=True,
            )[:5]:
                q = market.get("groupItemTitle") or market.get("question", "")
                prices = market.get("outcomePrices")
                if prices:
                    parsed_prices = json.loads(prices) if isinstance(prices, str) else prices
                    if isinstance(parsed_prices, list) and parsed_prices:
                        parts.append(f"{q}: {float(parsed_prices[0]) * 100:.0f}%")
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
        except POLYMARKET_FETCH_ERRORS as exc:
            signals.append(PolymarketSignal(slug=slug, title=title, error=str(exc)))

    return PolymarketSnapshot(signals=signals, timestamp=datetime.now().isoformat())
