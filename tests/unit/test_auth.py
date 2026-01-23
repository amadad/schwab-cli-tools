"""Tests for Schwab authentication and token management"""

import json
from unittest.mock import Mock, patch

import pytest

from src.core.errors import ConfigError
from src.schwab_client.auth import TokenManager, get_authenticated_client


class TestTokenManager:
    """Tests for TokenManager"""

    def test_tokens_exist_false_when_missing(self, tmp_path):
        """Test tokens_exist returns False when file missing"""
        manager = TokenManager(token_path=tmp_path / "nonexistent.json")
        assert not manager.tokens_exist()

    def test_tokens_exist_true_when_present(self, tmp_path):
        """Test tokens_exist returns True when file exists"""
        token_file = tmp_path / "token.json"
        token_file.write_text('{"access_token": "test"}')
        manager = TokenManager(token_path=token_file)
        assert manager.tokens_exist()

    def test_load_tokens_returns_none_when_missing(self, tmp_path):
        """Test load_tokens returns None when file missing"""
        manager = TokenManager(token_path=tmp_path / "nonexistent.json")
        assert manager.load_tokens() is None

    def test_load_tokens_returns_data_when_present(self, tmp_path):
        """Test load_tokens returns data when file exists"""
        token_file = tmp_path / "token.json"
        token_data = {"access_token": "test123", "refresh_token": "refresh456"}
        token_file.write_text(json.dumps(token_data))

        manager = TokenManager(token_path=token_file)
        loaded = manager.load_tokens()

        assert loaded is not None
        assert loaded["access_token"] == "test123"
        assert loaded["refresh_token"] == "refresh456"

    def test_load_tokens_handles_invalid_json(self, tmp_path):
        """Test load_tokens handles corrupted file"""
        token_file = tmp_path / "token.json"
        token_file.write_text("not valid json {{{")

        manager = TokenManager(token_path=token_file)
        assert manager.load_tokens() is None

    def test_get_token_info_no_file(self, tmp_path):
        """Test get_token_info when no token file"""
        manager = TokenManager(token_path=tmp_path / "nonexistent.json")
        info = manager.get_token_info()

        assert info["exists"] is False
        assert info["valid"] is False

    def test_delete_tokens(self, tmp_path):
        """Test delete_tokens removes file"""
        token_file = tmp_path / "token.json"
        token_file.write_text('{"access_token": "test"}')

        manager = TokenManager(token_path=token_file)
        assert manager.tokens_exist()

        manager.delete_tokens()
        assert not manager.tokens_exist()

    def test_delete_tokens_no_file(self, tmp_path):
        """Test delete_tokens handles missing file"""
        manager = TokenManager(token_path=tmp_path / "nonexistent.json")
        # Should not raise
        manager.delete_tokens()


class TestTokenExpiration:
    """Tests for token expiration warnings."""

    def test_token_info_includes_hours_remaining(self, tmp_path):
        """Test token info includes hours remaining."""
        from datetime import datetime, timedelta

        # Create a token that expires in 2 days
        token_path = tmp_path / "test_token.json"
        created = datetime.now() - timedelta(days=5)  # 5 days old, 2 days left
        token_data = {
            "access_token": "test",
            "creation_timestamp": created.isoformat(),
        }
        token_path.write_text(json.dumps(token_data))

        manager = TokenManager(token_path=token_path)
        info = manager.get_token_info()

        assert info["exists"] is True
        assert info["valid"] is True
        assert "expires_in_hours" in info
        assert info["expires_in_hours"] > 0
        assert info["expires_in_hours"] < 72  # Less than 3 days

    def test_token_critical_warning_under_24h(self, tmp_path):
        """Test critical warning when token expires in < 24 hours."""
        from datetime import datetime, timedelta

        # Create a token that expires in 12 hours
        token_path = tmp_path / "test_token.json"
        created = datetime.now() - timedelta(days=7) + timedelta(hours=12)
        token_data = {
            "access_token": "test",
            "creation_timestamp": created.isoformat(),
        }
        token_path.write_text(json.dumps(token_data))

        manager = TokenManager(token_path=token_path)
        info = manager.get_token_info()

        assert info["warning_level"] == "critical"
        assert "hours" in info["warning"].lower()

    def test_token_warning_under_48h(self, tmp_path):
        """Test warning when token expires in 24-48 hours."""
        from datetime import datetime, timedelta

        # Create a token that expires in 36 hours
        token_path = tmp_path / "test_token.json"
        created = datetime.now() - timedelta(days=7) + timedelta(hours=36)
        token_data = {
            "access_token": "test",
            "creation_timestamp": created.isoformat(),
        }
        token_path.write_text(json.dumps(token_data))

        manager = TokenManager(token_path=token_path)
        info = manager.get_token_info()

        assert info["warning_level"] == "warning"

    def test_expired_token_detected(self, tmp_path):
        """Test expired token is detected."""
        from datetime import datetime, timedelta

        # Create an expired token (8 days old)
        token_path = tmp_path / "test_token.json"
        created = datetime.now() - timedelta(days=8)
        token_data = {
            "access_token": "test",
            "creation_timestamp": created.isoformat(),
        }
        token_path.write_text(json.dumps(token_data))

        manager = TokenManager(token_path=token_path)
        info = manager.get_token_info()

        assert info["valid"] is False
        assert info["warning_level"] == "critical"
        assert "expired" in info["warning"].lower()

    def test_missing_token_warning(self, tmp_path):
        """Test missing token gives critical warning."""
        token_path = tmp_path / "nonexistent.json"
        manager = TokenManager(token_path=token_path)
        info = manager.get_token_info()

        assert info["exists"] is False
        assert info["valid"] is False
        assert info["warning_level"] == "critical"


class TestGetAuthenticatedClient:
    """Tests for get_authenticated_client"""

    def test_raises_without_credentials(self, monkeypatch):
        """Test raises ConfigError without credentials"""
        monkeypatch.delenv("SCHWAB_INTEL_APP_KEY", raising=False)
        monkeypatch.delenv("SCHWAB_INTEL_CLIENT_SECRET", raising=False)

        with pytest.raises(ConfigError, match="Missing Schwab credentials"):
            get_authenticated_client()

    def test_raises_with_partial_credentials(self, monkeypatch):
        """Test raises ConfigError with only one credential"""
        monkeypatch.setenv("SCHWAB_INTEL_APP_KEY", "test_key")
        monkeypatch.delenv("SCHWAB_INTEL_CLIENT_SECRET", raising=False)

        with pytest.raises(ConfigError, match="Missing Schwab credentials"):
            get_authenticated_client()

    @patch("src.schwab_client.auth.auth.easy_client")
    def test_returns_client_with_valid_creds(self, mock_easy, monkeypatch, tmp_path):
        """Test returns client when credentials valid"""
        monkeypatch.setenv("SCHWAB_INTEL_APP_KEY", "test_key")
        monkeypatch.setenv("SCHWAB_INTEL_CLIENT_SECRET", "test_secret")

        mock_client = Mock()
        mock_easy.return_value = mock_client

        result = get_authenticated_client(token_path=tmp_path / "token.json")

        assert result == mock_client
        mock_easy.assert_called_once()

    @patch("src.schwab_client.auth.auth.easy_client")
    def test_uses_env_credentials(self, mock_easy, monkeypatch, tmp_path):
        """Test uses credentials from environment"""
        monkeypatch.setenv("SCHWAB_INTEL_APP_KEY", "env_key")
        monkeypatch.setenv("SCHWAB_INTEL_CLIENT_SECRET", "env_secret")

        mock_easy.return_value = Mock()

        get_authenticated_client(token_path=tmp_path / "token.json")

        call_kwargs = mock_easy.call_args[1]
        assert call_kwargs["api_key"] == "env_key"
        assert call_kwargs["app_secret"] == "env_secret"

    @patch("src.schwab_client.auth.auth.easy_client")
    def test_uses_explicit_credentials_over_env(self, mock_easy, monkeypatch, tmp_path):
        """Test explicit credentials override environment"""
        monkeypatch.setenv("SCHWAB_INTEL_APP_KEY", "env_key")
        monkeypatch.setenv("SCHWAB_INTEL_CLIENT_SECRET", "env_secret")

        mock_easy.return_value = Mock()

        get_authenticated_client(
            api_key="explicit_key", app_secret="explicit_secret", token_path=tmp_path / "token.json"
        )

        call_kwargs = mock_easy.call_args[1]
        assert call_kwargs["api_key"] == "explicit_key"
        assert call_kwargs["app_secret"] == "explicit_secret"

    @patch("src.schwab_client.auth.auth.easy_client")
    def test_creates_token_directory(self, mock_easy, monkeypatch, tmp_path):
        """Test creates token directory if needed"""
        monkeypatch.setenv("SCHWAB_INTEL_APP_KEY", "test_key")
        monkeypatch.setenv("SCHWAB_INTEL_CLIENT_SECRET", "test_secret")

        mock_easy.return_value = Mock()

        nested_path = tmp_path / "nested" / "dir" / "token.json"
        get_authenticated_client(token_path=nested_path)

        assert nested_path.parent.exists()
