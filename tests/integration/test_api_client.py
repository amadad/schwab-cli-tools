"""Integration tests for Schwab API client wrapper"""

from unittest.mock import Mock, patch

import pytest

from src.schwab_client import MONEY_MARKET_SYMBOLS, SchwabClientWrapper


class TestSchwabClientWrapper:
    """Tests for SchwabClientWrapper"""

    @pytest.fixture
    def mock_raw_client(self):
        """Create mock schwab-py client"""
        client = Mock()
        client.Account = Mock()
        client.Account.Fields = Mock()
        client.Account.Fields.POSITIONS = "POSITIONS"
        return client

    @pytest.fixture
    def wrapper(self, mock_raw_client):
        """Create SchwabClientWrapper with mock client"""
        return SchwabClientWrapper(mock_raw_client)

    def test_raw_client_accessible(self, wrapper, mock_raw_client):
        """Test raw client is accessible"""
        assert wrapper.raw_client == mock_raw_client

    def test_get_account_numbers(self, wrapper, mock_raw_client):
        """Test get_account_numbers returns account data"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {"accountNumber": "12345678", "hashValue": "ABC123"},
            {"accountNumber": "87654321", "hashValue": "XYZ789"},
        ]
        mock_response.raise_for_status = Mock()
        mock_raw_client.get_account_numbers.return_value = mock_response

        accounts = wrapper.get_account_numbers()

        assert len(accounts) == 2
        assert accounts[0]["accountNumber"] == "12345678"
        assert accounts[0]["hashValue"] == "ABC123"

    def test_get_account_hash_caches_values(self, wrapper, mock_raw_client):
        """Test get_account_hash caches and returns hash"""
        mock_response = Mock()
        mock_response.json.return_value = [{"accountNumber": "12345678", "hashValue": "ABC123"}]
        mock_response.raise_for_status = Mock()
        mock_raw_client.get_account_numbers.return_value = mock_response

        # First call should fetch
        hash_value = wrapper.get_account_hash("12345678")
        assert hash_value == "ABC123"

        # Second call should use cache (no additional API call)
        hash_value2 = wrapper.get_account_hash("12345678")
        assert hash_value2 == "ABC123"
        assert mock_raw_client.get_account_numbers.call_count == 1

    def test_get_account_hash_returns_none_for_unknown(self, wrapper, mock_raw_client):
        """Test get_account_hash returns None for unknown account"""
        mock_response = Mock()
        mock_response.json.return_value = [{"accountNumber": "12345678", "hashValue": "ABC123"}]
        mock_response.raise_for_status = Mock()
        mock_raw_client.get_account_numbers.return_value = mock_response

        hash_value = wrapper.get_account_hash("99999999")
        assert hash_value is None

    def test_get_all_accounts_full(self, wrapper, mock_raw_client):
        """Test get_all_accounts_full returns account data"""
        mock_response = Mock()
        mock_response.json.return_value = [{"securitiesAccount": {"accountNumber": "12345678"}}]
        mock_response.raise_for_status = Mock()
        mock_raw_client.get_accounts.return_value = mock_response

        accounts = wrapper.get_all_accounts_full()

        assert len(accounts) == 1
        mock_raw_client.get_accounts.assert_called_once()

    def test_get_portfolio_summary_basic(self, wrapper, mock_raw_client):
        """Test get_portfolio_summary aggregates data correctly"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                "securitiesAccount": {
                    "accountNumber": "12345678",
                    "currentBalances": {"liquidationValue": 100000, "cashBalance": 10000},
                    "positions": [
                        {
                            "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                            "longQuantity": 100,
                            "marketValue": 50000,
                            "averagePrice": 450,
                            "unrealizedProfitLoss": 5000,
                            "unrealizedProfitLossPercentage": 10,
                            "currentDayProfitLoss": 500,
                            "currentDayProfitLossPercentage": 1,
                        }
                    ],
                }
            }
        ]
        mock_response.raise_for_status = Mock()
        mock_raw_client.get_accounts.return_value = mock_response

        summary = wrapper.get_portfolio_summary()

        assert summary["total_value"] == 100000
        assert summary["total_cash"] == 10000
        assert summary["total_invested"] == 90000
        assert summary["account_count"] == 1
        assert summary["position_count"] == 1
        assert len(summary["positions"]) == 1
        assert summary["positions"][0]["symbol"] == "AAPL"

    def test_get_portfolio_summary_money_market_as_cash(self, wrapper, mock_raw_client):
        """Test money market funds are counted as cash"""
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                "securitiesAccount": {
                    "accountNumber": "12345678",
                    "currentBalances": {"liquidationValue": 100000, "cashBalance": 5000},
                    "positions": [
                        {
                            "instrument": {"symbol": "SWVXX", "assetType": "MUTUAL_FUND"},
                            "longQuantity": 15000,
                            "marketValue": 15000,
                            "averagePrice": 1,
                            "unrealizedProfitLoss": 0,
                            "currentDayProfitLoss": 0,
                        },
                        {
                            "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                            "longQuantity": 100,
                            "marketValue": 50000,
                            "averagePrice": 450,
                            "unrealizedProfitLoss": 5000,
                            "currentDayProfitLoss": 500,
                        },
                    ],
                }
            }
        ]
        mock_response.raise_for_status = Mock()
        mock_raw_client.get_accounts.return_value = mock_response

        summary = wrapper.get_portfolio_summary()

        # Cash should be 5000 (base) + 15000 (SWVXX) = 20000
        assert summary["total_cash"] == 20000
        # Only AAPL should be in positions, not SWVXX
        assert summary["position_count"] == 1
        assert summary["positions"][0]["symbol"] == "AAPL"

    def test_money_market_symbols_defined(self):
        """Test all expected money market symbols are defined"""
        expected = {"SWGXX", "SWVXX", "SNOXX", "SNSXX", "SNVXX"}
        assert MONEY_MARKET_SYMBOLS == expected

    def test_get_quote(self, wrapper, mock_raw_client):
        """Test get_quote returns quote data"""
        mock_response = Mock()
        mock_response.json.return_value = {"AAPL": {"lastPrice": 150.00}}
        mock_response.raise_for_status = Mock()
        mock_raw_client.get_quote.return_value = mock_response

        quote = wrapper.get_quote("AAPL")

        assert quote["AAPL"]["lastPrice"] == 150.00
        mock_raw_client.get_quote.assert_called_once_with("AAPL")

    def test_get_quotes_multiple(self, wrapper, mock_raw_client):
        """Test get_quotes returns multiple quotes"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "AAPL": {"lastPrice": 150.00},
            "MSFT": {"lastPrice": 350.00},
        }
        mock_response.raise_for_status = Mock()
        mock_raw_client.get_quotes.return_value = mock_response

        quotes = wrapper.get_quotes(["AAPL", "MSFT"])

        assert len(quotes) == 2
        assert quotes["AAPL"]["lastPrice"] == 150.00
        assert quotes["MSFT"]["lastPrice"] == 350.00

    def test_get_account_with_positions(self, wrapper, mock_raw_client):
        """Test get_account with positions included"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "securitiesAccount": {
                "accountNumber": "12345678",
                "positions": [{"instrument": {"symbol": "AAPL"}}],
            }
        }
        mock_response.raise_for_status = Mock()
        mock_raw_client.get_account.return_value = mock_response

        account = wrapper.get_account("ABC123", include_positions=True)

        assert "positions" in account["securitiesAccount"]
        mock_raw_client.get_account.assert_called_once()

    def test_get_account_without_positions(self, wrapper, mock_raw_client):
        """Test get_account without positions"""
        mock_response = Mock()
        mock_response.json.return_value = {"securitiesAccount": {"accountNumber": "12345678"}}
        mock_response.raise_for_status = Mock()
        mock_raw_client.get_account.return_value = mock_response

        account = wrapper.get_account("ABC123", include_positions=False)

        assert account is not None
        mock_raw_client.get_account.assert_called_once_with("ABC123")

    @patch("src.schwab_client.client.secure_config")
    def test_buy_market_dry_run(self, mock_config, wrapper):
        """Test buy_market dry-run preview payload."""
        mock_config.get_account_number.return_value = "12345678"
        account_info = Mock()
        account_info.label = "Trading"
        mock_config.get_account_info.return_value = account_info
        wrapper.get_account_hash = Mock(return_value="ABC123")

        preview = wrapper.buy_market("acct_trading", "aapl", 10, dry_run=True)

        assert preview["dry_run"] is True
        assert preview["action"] == "BUY"
        assert preview["order_type"] == "MARKET"
        assert preview["symbol"] == "AAPL"
        assert preview["quantity"] == 10
        assert preview["account"] == "Trading"
        assert preview["account_number_masked"] == "...5678"
        assert "limit_price" not in preview

    @patch("src.schwab_client.client.secure_config")
    def test_sell_limit_dry_run_includes_limit_price(self, mock_config, wrapper):
        """Test sell_limit dry-run includes limit price and expected metadata."""
        mock_config.get_account_number.return_value = "12345678"
        account_info = Mock()
        account_info.label = "Trading"
        mock_config.get_account_info.return_value = account_info
        wrapper.get_account_hash = Mock(return_value="ABC123")

        preview = wrapper.sell_limit("acct_trading", "msft", 5, 320.5, dry_run=True)

        assert preview["dry_run"] is True
        assert preview["action"] == "SELL"
        assert preview["order_type"] == "LIMIT"
        assert preview["symbol"] == "MSFT"
        assert preview["quantity"] == 5
        assert preview["limit_price"] == 320.5
        assert preview["account"] == "Trading"
        assert preview["account_number_masked"] == "...5678"

    @patch("src.schwab_client.client.secure_config")
    def test_cancel_order_returns_unknown_account_error(self, mock_config, wrapper):
        """Test cancel_order keeps unknown-account error behavior."""
        mock_config.get_account_number.return_value = None

        result = wrapper.cancel_order("missing_alias", "123")

        assert result == {"success": False, "error": "Unknown account alias: missing_alias"}
