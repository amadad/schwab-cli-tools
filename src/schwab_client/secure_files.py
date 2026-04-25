"""Restrictive local-file helpers for Schwab secrets and private stores."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

SENSITIVE_DIR_MODE = 0o700
SENSITIVE_FILE_MODE = 0o600
SENSITIVE_DIR_NAMES = {".cli-schwab", "advisor", "history", "private", "tokens"}


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def ensure_sensitive_dir(path: Path) -> Path:
    """Create a directory intended for local secrets/private data."""
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    if not existed or path.name in SENSITIVE_DIR_NAMES:
        _chmod_best_effort(path, SENSITIVE_DIR_MODE)
    for parent in path.parents:
        if parent.name in SENSITIVE_DIR_NAMES:
            _chmod_best_effort(parent, SENSITIVE_DIR_MODE)
    return path


def prepare_sensitive_file(path: Path) -> Path:
    """Ensure a sensitive file exists with owner-only permissions."""
    ensure_sensitive_dir(path.parent)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SENSITIVE_FILE_MODE)
    except FileExistsError:
        pass
    else:
        os.close(fd)
    _chmod_best_effort(path, SENSITIVE_FILE_MODE)
    return path


def restrict_sqlite_permissions(db_path: Path) -> None:
    """Best-effort owner-only mode for a SQLite DB and common sidecars."""
    for candidate in (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        Path(f"{db_path}-journal"),
    ):
        if candidate.exists():
            _chmod_best_effort(candidate, SENSITIVE_FILE_MODE)


def write_sensitive_json(path: Path, payload: object) -> None:
    """Atomically write JSON with owner-only permissions."""
    ensure_sensitive_dir(path.parent)
    temp_path: Path | None = None
    replaced = False
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            _chmod_best_effort(temp_path, SENSITIVE_FILE_MODE)
            json.dump(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
        replaced = True
        _chmod_best_effort(path, SENSITIVE_FILE_MODE)
    finally:
        if not replaced and temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = [
    "SENSITIVE_DIR_MODE",
    "SENSITIVE_DIR_NAMES",
    "SENSITIVE_FILE_MODE",
    "ensure_sensitive_dir",
    "prepare_sensitive_file",
    "restrict_sqlite_permissions",
    "write_sensitive_json",
]
