"""Tests for Schwab CLI commands."""

import io
import json
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import (
    CLIResult,
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
        import os

        from src.schwab_client.cli.commands.trade import is_live_trading_enabled

        # Ensure env var is not set
        os.environ.pop("SCHWAB_ALLOW_LIVE_TRADES", None)

        assert is_live_trading_enabled() is False

    def test_live_trading_enabled_with_env_var(self):
        """Test live trading enabled with env var."""
        import os

        from src.schwab_client.cli.commands.trade import is_live_trading_enabled

        os.environ["SCHWAB_ALLOW_LIVE_TRADES"] = "true"
        try:
            assert is_live_trading_enabled() is True
        finally:
            os.environ.pop("SCHWAB_ALLOW_LIVE_TRADES", None)

    def test_ensure_trade_blocks_without_env_var(self):
        """Test ensure_trade_confirmation blocks live trades."""
        import os

        from src.core.errors import ConfigError
        from src.schwab_client.cli.commands.trade import ensure_trade_confirmation

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
        import os

        from src.schwab_client.cli.commands.trade import ensure_trade_confirmation

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

        # Capture stdout
        import io
        from contextlib import redirect_stdout

        from src.schwab_client.cli import main

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


class TestAuthRouting:
    """Tests for root auth command routing."""

    @patch("src.schwab_client.cli.cmd_auth")
    def test_auth_defaults_to_status(self, mock_cmd_auth):
        from src.schwab_client.cli import main

        main(["auth"])

        mock_cmd_auth.assert_called_once_with(output_mode="text")

    @patch("src.schwab_client.cli.cmd_auth_login")
    def test_auth_login_routes_to_market_rail(self, mock_cmd_auth_login):
        from src.schwab_client.cli import main

        main(["auth", "login", "--market", "--manual", "--force"])

        mock_cmd_auth_login.assert_called_once_with(
            output_mode="text",
            rail="market",
            force=True,
            manual=True,
            interactive=False,
            browser=None,
            timeout=300.0,
        )


class TestAuthAdminCommands:
    """Tests for auth/doctor diagnostic output."""

    @patch("src.schwab_client.cli.commands.admin.TokenManager")
    def test_auth_json_includes_storage_metadata(self, mock_manager_cls):
        """auth --json should expose sidecar/locking status explicitly."""
        from src.schwab_client.cli.commands.admin import cmd_auth

        mock_manager = MagicMock()
        mock_manager.get_token_info.return_value = {
            "exists": True,
            "valid": True,
            "db_path": "/tmp/tokens.db",
        }
        mock_manager.get_storage_info.return_value = {
            "token_path": "/tmp/token.json",
            "db_path": "/tmp/tokens.db",
            "storage_mode": "token_json+sqlite_sidecar",
            "locking": "sqlite_begin_exclusive",
        }
        mock_manager_cls.return_value = mock_manager

        output = io.StringIO()
        with redirect_stdout(output):
            cmd_auth(output_mode="json")

        payload = json.loads(output.getvalue())
        assert payload["command"] == "auth"
        assert payload["data"]["storage"]["db_path"] == "/tmp/tokens.db"
        assert payload["data"]["storage"]["locking"] == "sqlite_begin_exclusive"

    @patch("src.schwab_client.cli.commands.admin.secure_config")
    @patch("src.schwab_client.cli.commands.admin.TokenManager")
    def test_doctor_text_shows_token_db_paths(self, mock_manager_cls, mock_config):
        """doctor text output should surface the token sidecar database paths."""
        from src.schwab_client.cli.commands.admin import cmd_doctor

        mock_manager = MagicMock()
        mock_manager.get_token_info.return_value = {
            "exists": True,
            "valid": True,
            "expires_in_hours": 48.0,
            "expires_in_days": 2,
        }
        mock_manager.get_storage_info.return_value = {
            "token_path": "/tmp/token.json",
            "db_path": "/tmp/tokens.db",
            "storage_mode": "token_json+sqlite_sidecar",
            "locking": "sqlite_begin_exclusive",
        }
        mock_manager.db_path = "/tmp/tokens.db"
        mock_manager_cls.return_value = mock_manager
        mock_config.get_all_accounts.return_value = {}

        output = io.StringIO()
        with redirect_stdout(output):
            cmd_doctor(output_mode="text")

        text = output.getvalue()
        assert "Token DB:" in text
        assert "/tmp/tokens.db" in text

    @patch("src.schwab_client.cli.commands.admin.secure_config")
    @patch("src.schwab_client.cli.commands.admin.TokenManager")
    def test_doctor_json_includes_storage_metadata(self, mock_manager_cls, mock_config):
        """doctor --json should expose token storage metadata for both auth rails."""
        from src.schwab_client.cli.commands.admin import cmd_doctor

        mock_manager = MagicMock()
        mock_manager.get_token_info.return_value = {
            "exists": True,
            "valid": True,
            "expires_in_hours": 48.0,
            "expires_in_days": 2,
        }
        mock_manager.get_storage_info.return_value = {
            "token_path": "/tmp/token.json",
            "db_path": "/tmp/tokens.db",
            "storage_mode": "token_json+sqlite_sidecar",
            "locking": "sqlite_begin_exclusive",
        }
        mock_manager_cls.return_value = mock_manager
        mock_config.get_all_accounts.return_value = {}

        output = io.StringIO()
        with redirect_stdout(output):
            cmd_doctor(output_mode="json")

        payload = json.loads(output.getvalue())
        assert payload["command"] == "doctor"
        assert payload["data"]["portfolio"]["storage"]["db_path"] == "/tmp/tokens.db"
        assert payload["data"]["market"]["storage"]["locking"] == "sqlite_begin_exclusive"


@patch("src.schwab_client.cli.commands.admin.authenticate_interactive")
@patch("src.schwab_client.cli.commands.admin.TokenManager")
def test_cmd_auth_login_portfolio_reauth(mock_manager_cls, mock_authenticate_interactive):
    from src.schwab_client.cli.commands.admin import cmd_auth_login

    manager = MagicMock()
    manager.get_token_info = MagicMock(
        side_effect=[
            {"exists": True, "valid": False},
            {"exists": True, "valid": True, "expires": "2026-01-01T00:00:00", "expires_in_days": 6},
        ]
    )
    manager.db_path = "/tmp/tokens.db"
    mock_manager_cls.return_value = manager

    output = io.StringIO()
    with redirect_stdout(output):
        cmd_auth_login(output_mode="text", rail="portfolio", manual=False)

    manager.delete_tokens.assert_called_once()
    mock_authenticate_interactive.assert_called_once()
    assert "Authenticated portfolio rail successfully." in output.getvalue()


class TestContextCommand:
    """Tests for the portfolio context command."""

    @patch("src.schwab_client.cli.commands.context_cmd.get_cached_market_client")
    @patch("src.schwab_client.cli.commands.context_cmd.get_client")
    @patch("src.schwab_client.cli.commands.context_cmd.PortfolioContext")
    def test_context_json_envelope(self, mock_context_cls, mock_get_client, mock_get_market_client):
        """Test context --json returns a valid envelope."""
        from src.schwab_client.cli.commands.context_cmd import cmd_context

        mock_client = MagicMock()
        mock_market_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_market_client.return_value = mock_market_client

        ctx = MagicMock()
        ctx.to_dict.return_value = {
            "assembled_at": "2026-04-01T12:00:00",
            "summary": None,
            "accounts": [],
            "vix": None,
            "regime": None,
            "polymarket": None,
            "lynch": None,
            "ytd_distributions": {},
            "policy_delta": None,
            "errors": None,
        }
        mock_context_cls.assemble.return_value = ctx

        output = io.StringIO()
        with redirect_stdout(output):
            cmd_context(output_mode="json")

        payload = json.loads(output.getvalue())
        errors = validate_envelope(payload)
        assert not errors, f"Envelope errors: {errors}"
        assert payload["command"] == "context"
        assert payload["success"] is True
        assert payload["data"] == ctx.to_dict.return_value
        mock_context_cls.assemble.assert_called_once_with(
            mock_client,
            market_client=mock_market_client,
            include_lynch=False,
        )

    @patch("src.schwab_client.cli.commands.context_cmd.get_cached_market_client")
    @patch("src.schwab_client.cli.commands.context_cmd.get_client")
    @patch("src.schwab_client.cli.commands.context_cmd.PortfolioContext")
    def test_context_json_output_writes_file_and_returns_metadata(
        self,
        mock_context_cls,
        mock_get_client,
        mock_get_market_client,
        tmp_path,
    ):
        """context --json --output should export the full payload and return a compact pointer."""
        from src.schwab_client.cli.commands.context_cmd import cmd_context

        mock_client = MagicMock()
        mock_market_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_market_client.return_value = mock_market_client

        ctx = MagicMock()
        ctx.assembled_at = "2026-04-01T12:00:00"
        ctx.market_available = False
        ctx.manual_accounts_included = True
        ctx.history = {"snapshot_id": 50, "db_path": "/tmp/history.db"}
        ctx.to_dict.return_value = {
            "assembled_at": ctx.assembled_at,
            "summary": {"total_value": 100.0},
            "accounts": [{"account": "Trading (...1234)"}],
            "market_available": ctx.market_available,
            "manual_accounts_included": ctx.manual_accounts_included,
            "history": ctx.history,
        }
        mock_context_cls.assemble.return_value = ctx

        output_path = tmp_path / "context.json"
        output = io.StringIO()
        with redirect_stdout(output):
            cmd_context(output_mode="json", output_path=str(output_path))

        payload = json.loads(output.getvalue())
        assert payload["data"] == {
            "output_path": str(output_path),
            "output_type": "json",
            "assembled_at": "2026-04-01T12:00:00",
            "market_available": False,
            "manual_accounts_included": True,
            "history": {"snapshot_id": 50, "db_path": "/tmp/history.db"},
        }
        assert json.loads(output_path.read_text()) == ctx.to_dict.return_value

    @patch("src.schwab_client.cli.commands.context_cmd.get_cached_market_client")
    @patch("src.schwab_client.cli.commands.context_cmd.get_client")
    @patch("src.schwab_client.cli.commands.context_cmd.PortfolioContext")
    def test_context_template_forces_lynch(
        self,
        mock_context_cls,
        mock_get_client,
        mock_get_market_client,
    ):
        """Test memo/review templates force the deeper Lynch analysis path."""
        from src.schwab_client.cli.commands.context_cmd import cmd_context

        mock_client = MagicMock()
        mock_market_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_market_client.return_value = mock_market_client

        ctx = MagicMock()
        ctx.to_prompt_block.return_value = "context block"
        mock_context_cls.assemble.return_value = ctx

        output = io.StringIO()
        with redirect_stdout(output):
            cmd_context(template="memo")

        assert output.getvalue()
        mock_context_cls.assemble.assert_called_once_with(
            mock_client,
            market_client=mock_market_client,
            include_lynch=True,
        )


class TestHistoryCommand:
    """Tests for the history command surface."""

    @patch("src.schwab_client.cli.commands.history.HistoryStore")
    def test_history_snapshot_id_returns_exact_payload(self, mock_store_cls):
        from src.schwab_client.cli.commands.history import cmd_history

        store = MagicMock()
        store.path = "/tmp/history.db"
        store.get_snapshot_payload.return_value = {
            "generated_at": "2026-04-01T12:00:00",
            "portfolio": {"summary": {"total_value": 100.0}},
        }
        mock_store_cls.return_value = store

        output = io.StringIO()
        with redirect_stdout(output):
            cmd_history(output_mode="json", snapshot_id=50)

        payload = json.loads(output.getvalue())
        assert payload["data"] == {
            "db_path": "/tmp/history.db",
            "snapshot_id": 50,
            "snapshot": {
                "generated_at": "2026-04-01T12:00:00",
                "portfolio": {"summary": {"total_value": 100.0}},
            },
        }
        store.get_snapshot_payload.assert_called_once_with(50)

    @patch("src.schwab_client.cli.commands.history.HistoryStore")
    def test_history_snapshot_id_output_writes_file_and_returns_pointer(
        self, mock_store_cls, tmp_path
    ):
        from src.schwab_client.cli.commands.history import cmd_history

        store = MagicMock()
        store.path = "/tmp/history.db"
        store.get_snapshot_payload.return_value = {
            "generated_at": "2026-04-01T12:00:00",
            "portfolio": {"summary": {"total_value": 100.0}},
        }
        mock_store_cls.return_value = store

        output_path = tmp_path / "snapshot-50.json"
        output = io.StringIO()
        with redirect_stdout(output):
            cmd_history(output_mode="json", snapshot_id=50, output_path=str(output_path))

        payload = json.loads(output.getvalue())
        assert payload["data"] == {
            "db_path": "/tmp/history.db",
            "snapshot_id": 50,
            "output_path": str(output_path),
        }
        assert json.loads(output_path.read_text()) == store.get_snapshot_payload.return_value


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

    @patch("src.schwab_client.cli.cmd_context")
    def test_main_parses_context_output_path(self, mock_cmd):
        """context --output should pass the export path through."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["context", "--output", "./context.json", "--no-lynch"])

        mock_cmd.assert_called_once_with(
            output_mode="text",
            include_lynch=False,
            prompt=False,
            template=None,
            output_path="./context.json",
        )

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

    @patch("src.schwab_client.cli.cmd_snapshot")
    def test_main_parses_snapshot_command(self, mock_cmd):
        """Test main function parses snapshot command."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["snapshot", "--output", "./out.json", "--no-market"])

        mock_cmd.assert_called_once_with(
            output_mode="text",
            output_path="./out.json",
            include_market=False,
        )

    @patch("src.schwab_client.cli.cmd_snapshot")
    def test_main_parses_snapshot_command_with_default_output_path(self, mock_cmd):
        """Test snapshot --output with no value uses the default output location."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["snapshot", "--output", "--no-market"])

        mock_cmd.assert_called_once_with(
            output_mode="text",
            output_path="",
            include_market=False,
        )

    @patch("src.schwab_client.cli.cmd_history")
    def test_main_parses_history_command(self, mock_cmd):
        """Test main function parses history command."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["history", "--dataset", "portfolio", "--limit", "5"])

        mock_cmd.assert_called_once_with(
            output_mode="text",
            dataset="portfolio",
            limit=5,
            since=None,
            symbol=None,
            account=None,
            snapshot_id=None,
            output_path=None,
            backfill_paths=None,
        )

    @patch("src.schwab_client.cli.cmd_history")
    def test_main_parses_history_snapshot_read(self, mock_cmd):
        """history --snapshot-id should route to the exact-read path."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["history", "--snapshot-id", "42", "--output", "./snapshot.json"])

        mock_cmd.assert_called_once_with(
            output_mode="text",
            dataset="runs",
            limit=20,
            since=None,
            symbol=None,
            account=None,
            snapshot_id=42,
            output_path="./snapshot.json",
            backfill_paths=None,
        )

    @patch("src.schwab_client.cli.cmd_query")
    def test_main_parses_query_command(self, mock_cmd):
        """Test main function parses query command."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["query", "SELECT 1"])

        mock_cmd.assert_called_once_with("SELECT 1", output_mode="text")

    @patch("src.schwab_client.cli.cmd_history")
    def test_main_parses_history_import_defaults(self, mock_cmd):
        """Test history --import-defaults triggers default backfill."""
        from src.schwab_client.cli import main

        with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
            main(["history", "--import-defaults"])

        mock_cmd.assert_called_once_with(
            output_mode="text",
            dataset="runs",
            limit=20,
            since=None,
            symbol=None,
            account=None,
            snapshot_id=None,
            output_path=None,
            backfill_paths=[],
        )
