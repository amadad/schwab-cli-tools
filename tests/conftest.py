"""Shared pytest fixtures for test suite"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# JSON Schema for CLI response envelope
ENVELOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["schema_version", "command", "timestamp", "success"],
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "command": {"type": "string", "minLength": 1},
        "timestamp": {"type": "string"},
        "success": {"type": "boolean"},
        "data": {"type": ["object", "null"]},
        "error": {"type": ["object", "null"]},
    },
    "additionalProperties": False,
}


@dataclass
class CLIResult:
    """Result from running the CLI."""

    exit_code: int
    stdout: str
    stderr: str
    json_data: dict[str, Any] | None = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def get_data(self) -> dict[str, Any]:
        """Get the 'data' field from JSON response."""
        if self.json_data is None:
            raise ValueError("No JSON data available - did you use --json flag?")
        return self.json_data.get("data", {})


def run_cli(*args: str, timeout: int = 30) -> CLIResult:
    """Run the schwab CLI with given arguments.

    Args:
        *args: CLI arguments (e.g., "portfolio", "--json")
        timeout: Command timeout in seconds

    Returns:
        CLIResult with exit_code, stdout, stderr, and parsed json_data
    """
    cmd = [sys.executable, "-m", "src.schwab_client.cli", *args]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=Path(__file__).parent.parent,
    )

    json_data = None
    if "--json" in args:
        try:
            json_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass

    return CLIResult(
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        json_data=json_data,
    )


def validate_envelope(data: dict[str, Any]) -> list[str]:
    """Validate JSON response against envelope schema.

    Returns list of validation errors (empty if valid).
    """
    errors: list[str] = []

    # Check required fields
    for field in ENVELOPE_SCHEMA["required"]:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    # Check schema_version
    if "schema_version" in data:
        if data["schema_version"] != 1:
            errors.append(f"Invalid schema_version: {data['schema_version']} (expected 1)")

    # Check command is non-empty string
    if "command" in data:
        if not isinstance(data["command"], str) or not data["command"]:
            errors.append(f"Invalid command: {data['command']}")

    # Check success is boolean
    if "success" in data:
        if not isinstance(data["success"], bool):
            errors.append(f"Invalid success type: {type(data['success'])}")

    # Check no extra fields
    allowed = set(ENVELOPE_SCHEMA["properties"].keys())
    extra = set(data.keys()) - allowed
    if extra:
        errors.append(f"Unexpected fields: {extra}")

    return errors


# =============================================================================
# Mock Client Fixtures
# =============================================================================
