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


# =============================================================================
# Mock Client Fixtures
# =============================================================================

@pytest.fixture
def mock_portfolio_summary():
    """Sample portfolio summary data."""
    return {
        "total_value": 172500.00,
        "total_cash": 10000.00,
        "total_invested": 162500.00,
        "cash_percentage": 5.8,
        "account_count": 2,
        "position_count": 3,
        "positions": [
            {
                "symbol": "AAPL",
                "quantity": 100,
                "market_value": 17500.00,
                "day_gain_percent": 1.5,
                "account_name": "Trading",
            },
            {
                "symbol": "GOOGL",
                "quantity": 50,
                "market_value": 145000.00,
                "day_gain_percent": -0.3,
                "account_name": "Trading",
            },
        ],
    }


@pytest.fixture
def mock_market_signals():
    """Sample market signals data."""
    return {
        "signals": {
            "vix": {"value": 15.5, "signal": "low_volatility"},
            "market_sentiment": "bullish",
            "sector_rotation": "defensive_to_cyclical",
        },
        "overall": "bullish",
        "recommendation": "favorable for equities",
    }


@pytest.fixture
def mock_vix_data():
    """Sample VIX data."""
    return {
        "vix": 15.5,
        "change": -0.5,
        "change_pct": -3.1,
        "signal": "low_volatility",
        "interpretation": "Market calm, low fear",
    }


@pytest.fixture
def mock_schwab_client(mocker, mock_portfolio_summary, mock_market_signals):
    """Mock SchwabClientWrapper for unit tests.

    Usage:
        def test_portfolio(mock_schwab_client):
            # Client is already patched into context
            from src.schwab_client.cli import main
            main(["portfolio", "--json"])
    """
    from src.schwab_client.client import SchwabClientWrapper

    mock_client = mocker.Mock(spec=SchwabClientWrapper)
    mock_client.get_portfolio_summary.return_value = mock_portfolio_summary
    mock_client.get_positions.return_value = mock_portfolio_summary["positions"]
    mock_client.get_account_balances.return_value = [
        {"account_name": "Trading", "total_value": 172500.00, "cash_balance": 10000.00}
    ]
    mock_client.analyze_allocation.return_value = {
        "by_asset_class": {"equities": {"percentage": 94.2, "value": 162500}},
        "top_holdings": [{"symbol": "GOOGL", "percentage": 84.0, "value": 145000}],
        "concentration_warnings": ["GOOGL exceeds 10% concentration"],
    }
    mock_client.get_portfolio_performance.return_value = {
        "total_value": 172500.00,
        "day_change": 1250.00,
        "day_change_percent": 0.73,
        "top_gainers": [{"symbol": "AAPL", "day_gain_percent": 1.5}],
        "top_losers": [{"symbol": "GOOGL", "day_gain_percent": -0.3}],
    }
    mock_client.get_all_accounts_full.return_value = []
    mock_client.raw_client = mocker.Mock()

    # Patch the context module to return our mock
    mocker.patch(
        "src.schwab_client.cli.context.get_client",
        return_value=mock_client,
    )

    return mock_client


@pytest.fixture
def mock_market_client(mocker, mock_vix_data, mock_market_signals):
    """Mock market client for unit tests."""
    mock_client = mocker.Mock()

    # Patch context module
    mocker.patch(
        "src.schwab_client.cli.context.get_cached_market_client",
        return_value=mock_client,
    )

    # Also patch the service functions
    mocker.patch(
        "src.schwab_client.cli.commands.market.get_vix",
        return_value=mock_vix_data,
    )
    mocker.patch(
        "src.schwab_client.cli.commands.market.get_market_signals",
        return_value=mock_market_signals,
    )
    mocker.patch(
        "src.schwab_client.cli.commands.market.get_market_indices",
        return_value={
            "indices": {
                "$SPX": {"name": "S&P 500", "price": 5000.00, "change_pct": 0.5},
            },
            "sentiment": "bullish",
        },
    )
    mocker.patch(
        "src.schwab_client.cli.commands.market.get_sector_performance",
        return_value={
            "sectors": [{"symbol": "XLK", "sector": "Technology", "change_pct": 1.2}],
            "rotation": "risk_on",
            "leaders": ["XLK"],
            "laggards": ["XLU"],
        },
    )

    return mock_client


@pytest.fixture
def reset_cli_context():
    """Reset cached clients between tests."""
    from src.schwab_client.cli.context import reset_clients

    yield
    reset_clients()
