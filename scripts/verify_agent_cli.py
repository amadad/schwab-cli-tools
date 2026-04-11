#!/usr/bin/env python3
"""Smoke-test the installed Schwab CLI from outside the source tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"Command failed ({result.returncode}): {' '.join(command)}\n\n"
            f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
        )
    return result


def parse_json(stdout: str) -> dict:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Expected JSON output, got:\n{stdout}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", help="Account alias for dry-run trade verification")
    parser.add_argument("--symbol", default="AAPL", help="Symbol for dry-run trade verification")
    parser.add_argument("--qty", default="1", help="Quantity for dry-run trade verification")
    args = parser.parse_args()

    cli = shutil.which("schwab")
    if not cli:
        raise SystemExit("`schwab` is not on PATH. Install it first with `uv tool install -e .` or `pipx install .`.")

    account = args.account or os.getenv("SCHWAB_DEFAULT_ACCOUNT")
    if not account:
        raise SystemExit(
            "Set --account or SCHWAB_DEFAULT_ACCOUNT so the dry-run trade preview can be verified."
        )

    with tempfile.TemporaryDirectory(prefix="schwab-agent-cli-") as temp_dir:
        cwd = Path(temp_dir)

        run([cli, "--help"], cwd=cwd)

        doctor = parse_json(run([cli, "doctor", "--json"], cwd=cwd).stdout)
        assert doctor["success"] is True

        history = parse_json(run([cli, "history", "--json", "--limit", "1"], cwd=cwd).stdout)
        assert history["success"] is True

        output_path = cwd / "snapshot.json"
        snapshot = parse_json(
            run([cli, "snapshot", "--json", "--output", str(output_path)], cwd=cwd).stdout
        )
        assert snapshot["success"] is True
        assert output_path.exists()

        trade = parse_json(
            run(
                [cli, "buy", account, args.symbol, args.qty, "--dry-run", "--json"],
                cwd=cwd,
            ).stdout
        )
        assert trade["success"] is True

        print("schwab agent CLI verification passed")
        print(f"verified from: {cwd}")
        print(f"snapshot artifact: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
