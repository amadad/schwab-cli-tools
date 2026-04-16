"""Typed models for advisor recommendations."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.json_types import JsonObject


@dataclass(slots=True)
class AdvisorRecommendation:
    thesis: str
    rationale: str
    recommendation_type: str
    target_type: str
    target_id: str
    direction: str
    horizon_days: int
    benchmark_symbol: str | None = None
    confidence: float | None = None
    tags: list[str] | None = None

    @classmethod
    def from_dict(cls, data: JsonObject) -> AdvisorRecommendation:
        thesis = str(data.get("thesis") or data.get("summary") or "").strip()
        rationale = str(data.get("rationale") or "").strip()
        recommendation_type = str(data.get("recommendation_type") or "").strip()
        target_type = str(data.get("target_type") or "").strip()
        target_id = str(data.get("target_id") or "").strip()
        direction = str(data.get("direction") or "").strip()
        horizon_raw = data.get("horizon_days")

        required_fields = {
            "thesis": thesis,
            "rationale": rationale,
            "recommendation_type": recommendation_type,
            "target_type": target_type,
            "target_id": target_id,
            "direction": direction,
            "horizon_days": horizon_raw,
        }
        missing = [name for name, value in required_fields.items() if value in (None, "")]
        if missing:
            raise ValueError(f"Missing required recommendation field(s): {', '.join(missing)}")

        if horizon_raw is None:
            raise ValueError("Missing required recommendation field(s): horizon_days")
        horizon_days = int(horizon_raw)
        if horizon_days <= 0:
            raise ValueError("Recommendation horizon_days must be greater than zero")

        return cls(
            thesis=thesis,
            rationale=rationale,
            recommendation_type=recommendation_type,
            target_type=target_type,
            target_id=target_id,
            direction=direction,
            horizon_days=horizon_days,
            benchmark_symbol=data.get("benchmark_symbol"),
            confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
            tags=[str(x) for x in (data.get("tags") or [])],
        )

    def to_dict(self) -> JsonObject:
        return {
            "thesis": self.thesis,
            "rationale": self.rationale,
            "recommendation_type": self.recommendation_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "direction": self.direction,
            "horizon_days": self.horizon_days,
            "benchmark_symbol": self.benchmark_symbol,
            "confidence": self.confidence,
            "tags": self.tags or [],
        }
