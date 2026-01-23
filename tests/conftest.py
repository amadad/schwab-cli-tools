"""Shared pytest fixtures for test suite"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


# JSON Schema for CLI response envelope
ENVELOPE_SCHEMA = {
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
    errors = []

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


def assert_json_success(result: CLIResult, command: str | None = None) -> dict[str, Any]:
    """Assert CLI result is successful JSON response.

    Args:
        result: CLIResult from run_cli()
        command: Expected command name (optional)

    Returns:
        The parsed JSON data dict
    """
    assert result.json_data is not None, f"Expected JSON output, got: {result.stdout[:200]}"

    errors = validate_envelope(result.json_data)
    assert not errors, f"Envelope validation failed: {errors}"

    assert result.json_data["success"] is True, f"Expected success=True: {result.json_data}"

    if command:
        assert result.json_data["command"] == command

    return result.json_data


def assert_json_error(
    result: CLIResult, expected_type: str | None = None
) -> dict[str, Any]:
    """Assert CLI result is an error JSON response.

    Args:
        result: CLIResult from run_cli()
        expected_type: Expected error type (e.g., "ConfigError")

    Returns:
        The error dict from the response
    """
    assert result.json_data is not None, f"Expected JSON output, got: {result.stdout[:200]}"

    errors = validate_envelope(result.json_data)
    assert not errors, f"Envelope validation failed: {errors}"

    assert result.json_data["success"] is False, f"Expected success=False: {result.json_data}"
    assert result.json_data.get("error") is not None, "Expected error field"

    if expected_type:
        assert result.json_data["error"].get("type") == expected_type

    return result.json_data["error"]


@pytest.fixture
def cli_runner():
    """Fixture providing CLI runner function."""
    return run_cli


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock required environment variables"""
    monkeypatch.setenv("SCHWAB_INTEL_APP_KEY", "test_app_key")
    monkeypatch.setenv("SCHWAB_INTEL_CLIENT_SECRET", "test_client_secret")
    monkeypatch.setenv("SCHWAB_INTEL_CALLBACK_URL", "https://127.0.0.1:8001")
    monkeypatch.setenv("ADJACENT_NEWS_API_KEY", "test_adjacent_key")
    monkeypatch.setenv("OPENAI_API_KEY", "test_openai_key")


@pytest.fixture
def mock_token_data():
    """Mock token data for authentication tests"""
    return {
        "access_token": "mock_access_token_12345",
        "refresh_token": "mock_refresh_token_67890",
        "expires_in": 1800,
        "token_type": "Bearer",
        "scope": "api",
        "expires_at": 9999999999,  # Far future timestamp
    }


@pytest.fixture
def mock_account_data():
    """Mock account data from Schwab API"""
    return [
        {
            "accountNumber": "12345678",
            "hashValue": "ABCD1234EFGH5678",
        },
        {
            "accountNumber": "87654321",
            "hashValue": "WXYZ9876STUV4321",
        },
    ]


@pytest.fixture
def mock_positions_data():
    """Mock positions data from Schwab API"""
    return [
        {
            "symbol": "AAPL",
            "quantity": 100,
            "averagePrice": 150.00,
            "marketValue": 17500.00,
            "unrealizedProfitLoss": 2500.00,
        },
        {
            "symbol": "GOOGL",
            "quantity": 50,
            "averagePrice": 2800.00,
            "marketValue": 145000.00,
            "unrealizedProfitLoss": 5000.00,
        },
        {
            "symbol": "SWVXX",  # Money market fund
            "quantity": 10000,
            "averagePrice": 1.00,
            "marketValue": 10000.00,
            "unrealizedProfitLoss": 0.00,
        },
    ]


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create temporary config directory for tests"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def temp_tokens_dir(tmp_path):
    """Create temporary tokens directory for tests"""
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    return tokens_dir
