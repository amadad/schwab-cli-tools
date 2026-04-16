"""Recommendation-store helpers (legacy `_advisor/` package name retained)."""

from .schema import ADVISOR_DB_ENV_VAR, resolve_advisor_db_path

__all__ = ["ADVISOR_DB_ENV_VAR", "resolve_advisor_db_path"]
