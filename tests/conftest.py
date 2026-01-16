"""Shared pytest fixtures for test suite"""

import pytest


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
