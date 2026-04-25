"""Filesystem and environment-based path resolution helpers."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from .auth_tokens import resolve_data_dir

HISTORY_DB_ENV_VAR = "SCHWAB_HISTORY_DB_PATH"
REPORT_DIR_ENV_VAR = "SCHWAB_REPORT_DIR"
MANUAL_ACCOUNTS_ENV_VAR = "SCHWAB_MANUAL_ACCOUNTS_PATH"


def resolve_private_dir() -> Path | None:
    """Return the repo-local ``private`` directory when running inside the repo."""
    private_dir = Path.cwd() / "private"
    return private_dir if private_dir.exists() else None


def resolve_history_db_path() -> Path:
    """Resolve the SQLite history database path."""
    env_path = os.getenv(HISTORY_DB_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser()

    private_dir = resolve_private_dir()
    if private_dir is not None:
        return private_dir / "history" / "schwab_history.db"

    return resolve_data_dir() / "history" / "schwab_history.db"


def resolve_report_dir() -> Path:
    """Resolve the directory where report JSON artifacts are stored."""
    env_dir = os.getenv(REPORT_DIR_ENV_VAR)
    if env_dir:
        return Path(env_dir).expanduser()

    private_dir = resolve_private_dir()
    if private_dir is not None:
        return private_dir / "reports"

    return resolve_data_dir() / "reports"


def resolve_report_path(
    output_path: str | Path | None, *, timestamp: datetime | None = None
) -> Path:
    """Resolve a report output path."""
    if output_path:
        path = Path(output_path).expanduser()
    else:
        ts = timestamp or datetime.now()
        path = resolve_report_dir() / f"report-{ts.strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resolve_manual_accounts_path() -> Path | None:
    """Resolve the manual accounts file path.

    Preference order:
    1. ``SCHWAB_MANUAL_ACCOUNTS_PATH``
    2. ``./private/notes/manual_accounts.json`` when running inside this repo
    3. ``<data_dir>/manual_accounts.json``
    """
    env_path = os.getenv(MANUAL_ACCOUNTS_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser()

    private_dir = resolve_private_dir()
    if private_dir is not None:
        repo_path = private_dir / "notes" / "manual_accounts.json"
        if repo_path.exists():
            return repo_path

    data_path = resolve_data_dir() / "manual_accounts.json"
    if data_path.exists():
        return data_path

    return None


def default_history_import_roots() -> list[Path]:
    """Return default JSON import roots for history backfill."""
    paths: list[Path] = []

    private_dir = resolve_private_dir()
    if private_dir is not None:
        paths.extend([private_dir / "snapshots", private_dir / "reports"])

    data_dir = resolve_data_dir()
    paths.extend([data_dir / "snapshots", data_dir / "reports"])
    return paths


__all__ = [
    "HISTORY_DB_ENV_VAR",
    "MANUAL_ACCOUNTS_ENV_VAR",
    "REPORT_DIR_ENV_VAR",
    "default_history_import_roots",
    "resolve_history_db_path",
    "resolve_manual_accounts_path",
    "resolve_private_dir",
    "resolve_report_dir",
    "resolve_report_path",
]
