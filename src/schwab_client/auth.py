"""
Authentication wrapper for schwab-py

Provides simplified authentication using the official schwab-py package.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from schwab import auth

from src.core.errors import ConfigError

load_dotenv()
logger = logging.getLogger(__name__)

DATA_DIR_ENV = "SCHWAB_CLI_DATA_DIR"
TOKEN_PATH_ENV = "SCHWAB_TOKEN_PATH"


def resolve_data_dir() -> Path:
    """Resolve the base data directory."""
    env_dir = os.getenv(DATA_DIR_ENV)
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".schwab-cli-tools"


def resolve_token_path() -> Path:
    """Resolve the token path for the portfolio API."""
    env_path = os.getenv(TOKEN_PATH_ENV)
    if env_path:
        return Path(env_path).expanduser()
    return resolve_data_dir() / "tokens" / "schwab_token.json"


# Default token file location
DEFAULT_TOKEN_PATH = resolve_token_path()


class TokenManager:
    """
    Manages Schwab OAuth tokens.

    Note: With schwab-py, token refresh is handled automatically by the client.
    This class provides utilities for checking token status and expiration.
    """

    def __init__(self, token_path: Path = DEFAULT_TOKEN_PATH):
        self.token_path = Path(token_path)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)

    def tokens_exist(self) -> bool:
        """Check if token file exists"""
        return self.token_path.exists()

    def load_tokens(self) -> dict[str, Any] | None:
        """Load tokens from file"""
        if not self.tokens_exist():
            return None
        try:
            with open(self.token_path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load tokens: {e}")
            return None

    def get_token_info(self) -> dict[str, Any]:
        """Get information about current token status"""
        tokens = self.load_tokens()
        if not tokens:
            return {"exists": False, "valid": False}

        # Check if token has creation timestamp
        creation_time = tokens.get("creation_timestamp")
        if creation_time:
            try:
                created = datetime.fromisoformat(creation_time)
                expires = created + timedelta(days=7)
                now = datetime.now()

                return {
                    "exists": True,
                    "valid": now < expires,
                    "created": created.isoformat(),
                    "expires": expires.isoformat(),
                    "expires_in_days": (expires - now).days if now < expires else 0,
                }
            except (ValueError, TypeError):
                pass

        return {"exists": True, "valid": True, "note": "Cannot determine expiration"}

    def delete_tokens(self):
        """Delete token file (for re-authentication)"""
        if self.token_path.exists():
            self.token_path.unlink()
            logger.info(f"Deleted token file: {self.token_path}")


def get_authenticated_client(
    api_key: str | None = None,
    app_secret: str | None = None,
    callback_url: str = "https://127.0.0.1:8001",
    token_path: Path | None = None,
    asyncio: bool = False,
):
    """
    Get an authenticated Schwab client using official schwab-py.

    This function uses schwab-py's easy_client which:
    - Loads existing tokens if available
    - Opens browser for authentication if needed
    - Automatically refreshes tokens as needed

    Args:
        api_key: Schwab API key (defaults to SCHWAB_INTEL_APP_KEY env var)
        app_secret: Schwab app secret (defaults to SCHWAB_INTEL_CLIENT_SECRET env var)
        callback_url: OAuth callback URL
        token_path: Path to token file (defaults to ~/.schwab-cli-tools/tokens/schwab_token.json)
        asyncio: Whether to use async client

    Returns:
        Authenticated schwab.Client instance

    Raises:
        ConfigError: If credentials are missing
    """
    api_key = api_key or os.getenv("SCHWAB_INTEL_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_INTEL_CLIENT_SECRET")
    token_path = token_path or DEFAULT_TOKEN_PATH

    if not api_key or not app_secret:
        raise ConfigError(
            "Missing Schwab credentials. Set SCHWAB_INTEL_APP_KEY and "
            "SCHWAB_INTEL_CLIENT_SECRET environment variables."
        )

    # Ensure token directory exists
    Path(token_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        # Use easy_client which handles token file creation/loading
        client = auth.easy_client(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=callback_url,
            token_path=str(token_path),
            asyncio=asyncio,
        )
        logger.info("Schwab client authenticated successfully")
        return client
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        raise


def authenticate_interactive(
    api_key: str | None = None,
    app_secret: str | None = None,
    callback_url: str = "https://127.0.0.1:8001",
    token_path: Path | None = None,
    interactive: bool = False,
    requested_browser: str | None = None,
    callback_timeout: float | None = 300.0,
):
    """
    Run interactive authentication flow (opens browser).

    Use this for initial setup or when refresh token has expired.
    After 7 days, refresh tokens expire and this must be run again.
    """
    api_key = api_key or os.getenv("SCHWAB_INTEL_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_INTEL_CLIENT_SECRET")
    token_path = token_path or DEFAULT_TOKEN_PATH

    if not api_key or not app_secret:
        raise ConfigError(
            "Missing Schwab credentials. Set SCHWAB_INTEL_APP_KEY and "
            "SCHWAB_INTEL_CLIENT_SECRET environment variables."
        )

    Path(token_path).parent.mkdir(parents=True, exist_ok=True)

    print("Opening browser for Schwab authentication...")
    print("Complete the login and authorize the application.")
    print(f"Callback URL: {callback_url}")
    print()

    client = auth.client_from_login_flow(
        api_key=api_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=str(token_path),
        callback_timeout=callback_timeout,
        interactive=interactive,
        requested_browser=requested_browser,
    )

    print()
    print(f"Authentication successful! Tokens saved to {token_path}")
    print("Tokens are valid for 7 days before re-authentication is required.")
    return client


def main():
    """CLI entry point for authentication"""
    try:
        client = authenticate_interactive()

        # Test the connection
        response = client.get_account_numbers()
        if response.status_code == 200:
            accounts = response.json()
            print(f"Found {len(accounts)} accounts")
            print("Authentication complete!")
        else:
            print(f"Warning: API test returned {response.status_code}")

    except Exception as e:
        print(f"Authentication failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
