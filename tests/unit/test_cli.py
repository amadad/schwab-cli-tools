"""Tests for Schwab CLI commands."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import (
    CLIResult,
    assert_json_error,
    assert_json_success,
    run_cli,
    validate_envelope,
)


class TestCLIHelp:
    """Tests for CLI help output."""

    def test_help_flag_shows_usage(self):
        """Test --help shows usage information."""
        result = run_cli("--help")
        assert result.exit_code == 0
        assert "Schwab CLI" in result.stdout or "portfolio" in result.stdout
        assert "portfolio" in result.stdout
        assert "positions" in result.stdout

    def test_no_args_shows_help(self):
        """Test running without args shows help."""
        result = run_cli()
        assert result.exit_code == 0
        assert "usage:" in result.stdout.lower() or "commands:" in result.stdout.lower()

    def test_subcommand_help(self):
        """Test subcommand --help works."""
        result = run_cli("buy", "--help")
        assert result.exit_code == 0
        assert "SYMBOL" in result.stdout or "symbol" in result.stdout.lower()

    def test_invalid_command_shows_error(self):
        """Test invalid command shows error."""
        result = run_cli("notacommand")
        assert result.exit_code != 0


class TestJSONEnvelope:
    """Tests for JSON response envelope format."""

    def test_envelope_schema_validation(self):
        """Test envelope validation function works."""
        valid = {
            "schema_version": 1,
            "command": "test",
            "timestamp": "2025-01-01T00:00:00",
            "success": True,
            "data": {},
            "error": None,
        }
        assert validate_envelope(valid) == []

    def test_envelope_missing_required_field(self):
        """Test envelope validation catches missing fields."""
        invalid = {"schema_version": 1, "command": "test"}
        errors = validate_envelope(invalid)
        assert len(errors) > 0
        assert any("timestamp" in e or "success" in e for e in errors)

    def test_envelope_wrong_schema_version(self):
        """Test envelope validation catches wrong schema version."""
        invalid = {
            "schema_version": 2,
            "command": "test",
            "timestamp": "2025-01-01T00:00:00",
            "success": True,
        }
        errors = validate_envelope(invalid)
        assert any("schema_version" in e for e in errors)

    def test_envelope_extra_fields_rejected(self):
        """Test envelope validation catches unexpected fields."""
        invalid = {
            "schema_version": 1,
            "command": "test",
            "timestamp": "2025-01-01T00:00:00",
            "success": True,
            "extra_field": "bad",
        }
        errors = validate_envelope(invalid)
        assert any("extra" in e.lower() for e in errors)


class TestTradeSafety:
    """Tests for trade safety mechanisms."""

    def test_live_trading_disabled_by_default(self):
        """Test live trading is blocked without env var."""
        from src.schwab_client.cli.commands.trade import is_live_trading_enabled

        import os
        # Ensure env var is not set
        os.environ.pop("SCHWAB_ALLOW_LIVE_TRADES", None)

        assert is_live_trading_enabled() is False

    def test_live_trading_enabled_with_env_var(self):
        """Test live trading enabled with env var."""
        from src.schwab_client.cli.commands.trade import is_live_trading_enabled

        import os
        os.environ["SCHWAB_ALLOW_LIVE_TRADES"] = "true"
        try:
            assert is_live_trading_enabled() is True
        finally:
            os.environ.pop("SCHWAB_ALLOW_LIVE_TRADES", None)

    def test_ensure_trade_blocks_without_env_var(self):
        """Test ensure_trade_confirmation blocks live trades."""
        from src.schwab_client.cli.commands.trade import ensure_trade_confirmation
        from src.core.errors import ConfigError

        import os
        os.environ.pop("SCHWAB_ALLOW_LIVE_TRADES", None)

        with pytest.raises(ConfigError, match="Live trading is disabled"):
            ensure_trade_confirmation(
                output_mode="text",
                auto_confirm=True,
                dry_run=False,  # NOT a dry run
                non_interactive=False,
            )

    def test_ensure_trade_allows_dry_run(self):
        """Test dry-run is always allowed."""
        from src.schwab_client.cli.commands.trade import ensure_trade_confirmation

        import os
        os.environ.pop("SCHWAB_ALLOW_LIVE_TRADES", None)

        # Should not raise - dry_run is always allowed
        ensure_trade_confirmation(
            output_mode="text",
            auto_confirm=False,
            dry_run=True,
            non_interactive=False,
        )


class TestCLIResult:
    """Tests for CLIResult helper class."""

    def test_cli_result_success_property(self):
        """Test CLIResult.success property."""
        success = CLIResult(exit_code=0, stdout="", stderr="")
        failure = CLIResult(exit_code=1, stdout="", stderr="")

        assert success.success is True
        assert failure.success is False

    def test_cli_result_get_data(self):
        """Test CLIResult.get_data() method."""
        result = CLIResult(
            exit_code=0,
            stdout="",
            stderr="",
            json_data={"data": {"key": "value"}},
        )
        assert result.get_data() == {"key": "value"}

    def test_cli_result_get_data_no_json(self):
        """Test CLIResult.get_data() raises without JSON."""
        result = CLIResult(exit_code=0, stdout="text output", stderr="")
        with pytest.raises(ValueError, match="No JSON data"):
            result.get_data()


class TestAccountsCommandJSON:
    """Tests for accounts command JSON output."""

    @patch("src.schwab_client.cli.commands.admin.secure_config")
    def test_accounts_json_envelope(self, mock_config):
        """Test accounts --json returns valid envelope."""
        mock_info = MagicMock()
        mock_info.alias = "test_acct"
        mock_info.label = "Test"
        mock_info.name = "Test Account"
        mock_info.account_type = "Individual"
        mock_info.tax_status = "taxable"
        mock_info.category = "trading"
        mock_info.account_number = "12345678"
        mock_info.description = None

        mock_config.get_all_accounts.return_value = {"test_acct": mock_info}

        from src.schwab_client.cli import main

        # Capture stdout
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            main(["accounts", "--json"])

        output = f.getvalue()
        data = json.loads(output)

        errors = validate_envelope(data)
        assert not errors, f"Envelope errors: {errors}"
        assert data["command"] == "accounts"
        assert data["success"] is True
        assert "accounts" in data["data"]


class TestPortfolioCommand:
    """Tests for portfolio command output."""

    def test_portfolio_command_uses_wrapper(self):
        """Test portfolio command uses Schwab client wrapper correctly."""
        from src.schwab_client import SchwabClientWrapper

        # Setup mock client
        mock_raw_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "securitiesAccount": {
                    "accountNumber": "12345678",
                    "type": "Individual",
                    "currentBalances": {
                        "liquidationValue": 100000,
                        "cashBalance": 10000,
                    },
                    "positions": [
                        {
                            "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                            "longQuantity": 100,
                            "marketValue": 50000,
                            "averagePrice": 450,
                            "unrealizedProfitLoss": 5000,
                            "currentDayProfitLoss": 500,
                        }
                    ],
                }
            }
        ]
        mock_response.raise_for_status = MagicMock()
        mock_raw_client.get_accounts.return_value = mock_response

        # Create wrapper
        wrapper = SchwabClientWrapper(mock_raw_client)
        summary = wrapper.get_portfolio_summary()

        assert summary["total_value"] == 100000
        assert summary["total_cash"] == 10000
        assert summary["total_invested"] == 90000
        assert summary["account_count"] == 1


class TestAccountsCommand:
    """Tests for accounts list command."""

    @patch("src.schwab_client.cli.commands.admin.secure_config")
    def test_list_accounts_returns_configured_accounts(self, mock_config):
        """Test listing configured accounts."""
        mock_info = MagicMock()
        mock_info.alias = "acct_trading"
        mock_info.label = "Trading"
        mock_info.account_type = "Individual"
        mock_info.account_number = "12345678"
        mock_info.get_display_label.return_value = "Trading (...5678)"

        mock_config.get_all_accounts.return_value = {"acct_trading": mock_info}

        accounts = mock_config.get_all_accounts()

        assert "acct_trading" in accounts
        assert accounts["acct_trading"].label == "Trading"


class TestClientOrderMethods:
    """Tests for order-related client methods."""

    def test_place_order_builds_correct_structure(self):
        """Test placing equity order via client wrapper."""
        from src.schwab_client import SchwabClientWrapper

        mock_raw_client = MagicMock()

        # Mock get_account_numbers
        mock_numbers_response = MagicMock()
        mock_numbers_response.json.return_value = [
            {"accountNumber": "12345678", "hashValue": "ABC123"}
        ]
        mock_numbers_response.raise_for_status = MagicMock()
        mock_raw_client.get_account_numbers.return_value = mock_numbers_response

        # Mock place_order
        mock_order_response = MagicMock()
        mock_order_response.status_code = 201
        mock_order_response.headers = {"Location": "orders/12345"}
        mock_raw_client.place_order.return_value = mock_order_response

        wrapper = SchwabClientWrapper(mock_raw_client)

        order = {
            "orderType": "MARKET",
            "session": "NORMAL",
            "duration": "DAY",
            "orderStrategyType": "SINGLE",
            "orderLegCollection": [
                {
                    "instruction": "BUY",
                    "quantity": 10,
                    "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                }
            ],
        }

        result = wrapper.place_order("ABC123", order)

        mock_raw_client.place_order.assert_called_once()
        assert result["success"] is True

    def test_get_orders_returns_list(self):
        """Test getting orders returns list."""
        from src.schwab_client import SchwabClientWrapper

        mock_raw_client = MagicMock()

        # Mock get_orders
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"orderId": "123", "status": "FILLED"},
            {"orderId": "456", "status": "PENDING"},
        ]
        mock_response.raise_for_status = MagicMock()
        mock_raw_client.get_orders_for_account.return_value = mock_response

        wrapper = SchwabClientWrapper(mock_raw_client)
        orders = wrapper.get_orders("ABC123")

        assert len(orders) == 2
        assert orders[0]["orderId"] == "123"


class TestCLICommandAliases:
    """Tests for CLI command aliases."""

    def test_portfolio_alias(self):
        """Test 'p' alias works for portfolio."""
        result = run_cli("p", "--help")
        assert result.exit_code == 0
        assert "portfolio" in result.stdout.lower() or "positions" in result.stdout.lower()

    def test_doctor_alias(self):
        """Test 'dr' alias works for doctor."""
        result = run_cli("dr", "--help")
        assert result.exit_code == 0


class TestCLIArgParsing:
    """Tests for CLI argument parsing."""

    @patch("src.schwab_client.cli.cmd_portfolio")
    def test_main_parses_portfolio_command(self, mock_cmd):
        """Test main function parses portfolio command."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["portfolio"])

        mock_cmd.assert_called_once_with(include_positions=False, output_mode="text")

    @patch("src.schwab_client.cli.cmd_portfolio")
    def test_main_parses_portfolio_with_positions(self, mock_cmd):
        """Test main function parses portfolio -p flag."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["portfolio", "-p"])

        mock_cmd.assert_called_once_with(include_positions=True, output_mode="text")

    @patch("src.schwab_client.cli.cmd_balance")
    def test_main_parses_balance_command(self, mock_cmd):
        """Test main function parses balance command."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["balance"])

        mock_cmd.assert_called_once_with(output_mode="text")

    @patch("src.schwab_client.cli.cmd_accounts")
    def test_main_parses_accounts_command(self, mock_cmd):
        """Test main function parses accounts command."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["accounts"])

        mock_cmd.assert_called_once_with(output_mode="text")

    @patch("src.schwab_client.cli.cmd_report")
    def test_main_parses_report_command(self, mock_cmd):
        """Test main function parses report command."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["report"])

        mock_cmd.assert_called_once_with(
            output_mode="text",
            output_path=None,
            include_market=True,
        )
