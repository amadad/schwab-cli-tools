"""Shared types for the portfolio brief pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.context import PortfolioContext
from src.core.json_types import JsonObject

type JsonDict = JsonObject
type PortfolioContextLike = PortfolioContext | JsonObject | None


@dataclass(slots=True)
class ModelRunResult:
    payload: JsonDict | None
    raw_response: str
    error: str | None
    command: str
