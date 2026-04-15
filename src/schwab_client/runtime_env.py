"""Explicit runtime environment loading for CLI entrypoints."""

from __future__ import annotations

import os
import re
from pathlib import Path

_EXPORT_LINE_RE = re.compile(r'^export\s+(\w+)=["\']?([^"\']+)["\']?')


def load_bash_secrets(path: str | Path | None = None) -> None:
    """Load exported secrets from ``~/.bash_secrets`` into the current process.

    This is intended for CLI/process entrypoints only. It avoids hidden import-time
    environment mutation inside library modules while still supporting cron setups
    that rely on a shell secrets file.
    """
    secrets_path = Path(path).expanduser() if path else Path.home() / ".bash_secrets"
    if not secrets_path.exists():
        return

    for line in secrets_path.read_text().splitlines():
        match = _EXPORT_LINE_RE.match(line)
        if not match:
            continue
        key, value = match.groups()
        os.environ.setdefault(key, value)
