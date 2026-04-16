"""Shared JSON-like payload types used across the CLI and core services."""

from __future__ import annotations

from typing import Any

type JsonValue = Any
type JsonObject = dict[str, Any]
type JsonArray = list[Any]


def as_json_object(value: object) -> JsonObject:
    """Return a JSON object when the runtime value is a dict."""
    return value if isinstance(value, dict) else {}


def as_json_array(value: object) -> JsonArray:
    """Return a JSON array when the runtime value is a list."""
    return value if isinstance(value, list) else []
