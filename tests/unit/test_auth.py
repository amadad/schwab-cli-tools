"""Tests for Schwab authentication and token management"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.core.errors import ConfigError
from src.schwab_client.auth import TokenManager, get_authenticated_client, resolve_data_dir


class TestPathResolution:
    """Tests for public/default auth path resolution."""

    def test_default_data_dir_is_public_and_generic(self, monkeypatch):
        """Default data dir should not leak a user-specific local path."""
        monkeypatch.delenv("SCHWAB_CLI_DATA_DIR", raising=False)

        path = resolve_data_dir()

        assert path.name == ".cli-schwab"
        assert "Madad" not in str(path)


class TestTokenManager:
    """Tests for TokenManager"""

    def test_creates_sidecar_db(self, tmp_path):
        """Token manager should create the SQLite sidecar on init."""
        manager = TokenManager(token_path=tmp_path / "token.json")

        assert manager.db_path == tmp_path / "tokens.db"
        assert manager.db_path.exists()

    def test_get_token_info_syncs_sidecar_db(self, tmp_path):
        """Reading token info should persist derived metadata to SQLite."""
        token_file = tmp_path / "token.json"
        token_file.write_text(
            json.dumps({"access_token": "test", "creation_timestamp": datetime.now().isoformat()})
        )

        manager = TokenManager(token_path=token_file)
        info = manager.get_token_info()

        assert info["exists"] is True
        with sqlite3.connect(manager.db_path) as conn:
            row = conn.execute(
                "SELECT token_path, created_at, expires_at FROM token_state WHERE token_path = ?",
                (str(token_file),),
            ).fetchone()
        assert row is not None
        assert row[0] == str(token_file)
        assert row[1] is not None
        assert row[2] is not None

    def test_get_token_info_falls_back_to_cached_metadata_when_file_corrupted(self, tmp_path):
        """Corrupted token files should still expose cached metadata from SQLite."""
        token_file = tmp_path / "token.json"
        token_file.write_text(
            json.dumps({"access_token": "test", "creation_timestamp": datetime.now().isoformat()})
        )

        manager = TokenManager(token_path=token_file)
        initial = manager.get_token_info()

        token_file.write_text("not valid json {{{")
        info = manager.get_token_info()

        assert info["exists"] is True
        assert info["cached"] is True
        assert info["valid"] == initial["valid"]
        assert "cached token metadata" in info["warning"].lower()

    def test_delete_tokens_clears_sidecar_state(self, tmp_path):
        """Deleting a token should also remove its cached SQLite metadata."""
        token_file = tmp_path / "token.json"
        token_file.write_text(
            json.dumps({"access_token": "test", "creation_timestamp": datetime.now().isoformat()})
        )

        manager = TokenManager(token_path=token_file)
        manager.get_token_info()
        manager.delete_tokens()

        with sqlite3.connect(manager.db_path) as conn:
            row = conn.execute(
                "SELECT token_path FROM token_state WHERE token_path = ?",
                (str(token_file),),
            ).fetchone()
        assert row is None


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

    def test_access_only_token_uses_access_expiry_window(self, tmp_path):
        """Tokens without refresh tokens should expire at access-token expiry."""
        from datetime import datetime, timedelta

        token_path = tmp_path / "access_only_token.json"
        created = datetime.now() - timedelta(minutes=5)
        access_expires = datetime.now() + timedelta(minutes=25)
        token_data = {
            "creation_timestamp": created.isoformat(),
            "token": {
                "access_token": "test",
                "expires_at": access_expires.timestamp(),
            },
        }
        token_path.write_text(json.dumps(token_data))

        manager = TokenManager(token_path=token_path)
        info = manager.get_token_info()

        assert info["exists"] is True
        assert info["valid"] is True
        assert info["expires_in_hours"] < 1
        assert info["expires_in_days"] == 0

    def test_refreshable_token_uses_refresh_expiry_window(self, tmp_path):
        """Tokens with refresh tokens should still use the 7-day refresh window."""
        from datetime import datetime, timedelta

        token_path = tmp_path / "refreshable_token.json"
        created = datetime.now() - timedelta(minutes=5)
        access_expires = datetime.now() + timedelta(minutes=25)
        token_data = {
            "creation_timestamp": created.isoformat(),
            "token": {
                "access_token": "test",
                "refresh_token": "refresh",
                "expires_at": access_expires.timestamp(),
            },
        }
        token_path.write_text(json.dumps(token_data))

        manager = TokenManager(token_path=token_path)
        info = manager.get_token_info()

        assert info["exists"] is True
        assert info["valid"] is True
        assert info["expires_in_hours"] > 24 * 6
        assert info["expires_in_days"] >= 6

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
    @patch("src.schwab_client.auth.auth.client_from_access_functions")
    def test_creates_token_directory(self, mock_client_from_access, mock_easy, monkeypatch, tmp_path):
        """Test creates token directory if needed"""
        monkeypatch.setenv("SCHWAB_INTEL_APP_KEY", "test_key")
        monkeypatch.setenv("SCHWAB_INTEL_CLIENT_SECRET", "test_secret")

        mock_client = Mock()
        mock_client.token_age.return_value = 0
        mock_client_from_access.return_value = mock_client

        def write_token(**kwargs):
            Path(kwargs["token_path"]).write_text(
                json.dumps(
                    {
                        "creation_timestamp": datetime.now().isoformat(),
                        "token": {"access_token": "test", "expires_at": datetime.now().timestamp()},
                    }
                )
            )
            return Mock()

        mock_easy.side_effect = write_token

        nested_path = tmp_path / "nested" / "dir" / "token.json"
        get_authenticated_client(token_path=nested_path)

        assert nested_path.parent.exists()

    @patch("src.schwab_client.auth.auth.easy_client")
    @patch("src.schwab_client.auth.auth.client_from_access_functions")
    def test_get_authenticated_client_updates_sidecar_state(
        self,
        mock_client_from_access,
        mock_easy,
        monkeypatch,
        tmp_path,
    ):
        """Managed client creation should persist token metadata to SQLite."""
        monkeypatch.setenv("SCHWAB_INTEL_APP_KEY", "test_key")
        monkeypatch.setenv("SCHWAB_INTEL_CLIENT_SECRET", "test_secret")

        managed_client = Mock()
        managed_client.token_age.return_value = 0
        mock_client_from_access.return_value = managed_client

        token_path = tmp_path / "token.json"

        def write_token(**kwargs):
            Path(kwargs["token_path"]).write_text(
                json.dumps(
                    {
                        "creation_timestamp": datetime.now().isoformat(),
                        "token": {"access_token": "test", "expires_at": datetime.now().timestamp()},
                    }
                )
            )
            return Mock()

        mock_easy.side_effect = write_token

        result = get_authenticated_client(token_path=token_path)

        assert result == managed_client
        manager = TokenManager(token_path=token_path)
        info = manager.get_token_info()
        assert info["exists"] is True
        with sqlite3.connect(manager.db_path) as conn:
            row = conn.execute(
                "SELECT token_path FROM token_state WHERE token_path = ?",
                (str(token_path),),
            ).fetchone()
        assert row is not None
