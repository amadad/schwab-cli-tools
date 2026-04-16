import subprocess
import sys
from pathlib import Path


def run_advisor_cli(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "src.schwab_client.advisor_cli", *args],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,
        timeout=30,
    )


def test_advisor_help_runs():
    result = run_advisor_cli("--help")
    assert result.returncode == 0
    assert "schwab-advisor" in result.stdout
