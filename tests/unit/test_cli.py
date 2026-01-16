"""Tests for Schwab CLI commands."""

from unittest.mock import MagicMock, patch


class TestPortfolioCommand:
    """Tests for portfolio command output."""

    @patch("src.schwab_client.cli.get_authenticated_client")
    @patch("src.schwab_client.cli.secure_config")
    def test_portfolio_command_calls_api(self, mock_config, mock_get_client):
        """Test portfolio command uses Schwab client correctly."""
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
        mock_get_client.return_value = mock_raw_client

        # Create wrapper
        wrapper = SchwabClientWrapper(mock_raw_client)
        summary = wrapper.get_portfolio_summary()

        assert summary["total_value"] == 100000
        assert summary["total_cash"] == 10000
        assert summary["total_invested"] == 90000
        assert summary["account_count"] == 1


class TestAccountsCommand:
    """Tests for accounts list command."""

    @patch("src.schwab_client.cli.secure_config")
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


class TestCLIArgParsing:
    """Tests for CLI argument parsing."""

    def test_main_parses_portfolio_command(self):
        """Test main function parses portfolio command."""
        from unittest.mock import patch

        with patch("src.schwab_client.cli.print_portfolio") as mock_print:
            from src.schwab_client.cli import main

            with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
                main(["portfolio"])

            mock_print.assert_called_once_with(include_positions=False, output_mode="text")

    def test_main_parses_portfolio_with_positions(self):
        """Test main function parses portfolio -p flag."""
        from unittest.mock import patch

        with patch("src.schwab_client.cli.print_portfolio") as mock_print:
            from src.schwab_client.cli import main

            with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
                main(["portfolio", "-p"])

            mock_print.assert_called_once_with(include_positions=True, output_mode="text")

    def test_main_parses_balance_command(self):
        """Test main function parses balance command."""
        from unittest.mock import patch

        with patch("src.schwab_client.cli.print_balances") as mock_print:
            from src.schwab_client.cli import main

            with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
                main(["balance"])

            mock_print.assert_called_once_with(output_mode="text")

    def test_main_parses_accounts_command(self):
        """Test main function parses accounts command."""
        from unittest.mock import patch

        with patch("src.schwab_client.cli.list_accounts") as mock_list:
            from src.schwab_client.cli import main

            with patch.dict("os.environ", {"SCHWAB_OUTPUT": "text"}):
                main(["accounts"])

            mock_list.assert_called_once_with(output_mode="text")
