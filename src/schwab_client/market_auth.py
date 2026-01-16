"""
Authentication for Schwab Market Data API

Separate auth flow for market data (quotes, VIX, sectors).
Uses different credentials and token file from portfolio API.

Usage:
    uv run schwab-market-auth
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from schwab import auth

load_dotenv()

DATA_DIR_ENV = "SCHWAB_CLI_DATA_DIR"
MARKET_TOKEN_PATH_ENV = "SCHWAB_MARKET_TOKEN_PATH"


def resolve_data_dir() -> Path:
    env_dir = os.getenv(DATA_DIR_ENV)
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".schwab-cli-tools"


def resolve_market_token_path() -> Path:
    env_path = os.getenv(MARKET_TOKEN_PATH_ENV)
    if env_path:
        return Path(env_path).expanduser()
    return resolve_data_dir() / "tokens" / "schwab_market_token.json"


# Separate token file for market data
MARKET_TOKEN_PATH = resolve_market_token_path()


def authenticate_market_data():
    """
    Run interactive authentication for Market Data API.

    Uses SCHWAB_MARKET_* credentials (separate from portfolio API).
    """
    api_key = os.getenv("SCHWAB_MARKET_APP_KEY")
    app_secret = os.getenv("SCHWAB_MARKET_CLIENT_SECRET")
    callback_url = os.getenv("SCHWAB_MARKET_CALLBACK_URL", "https://127.0.0.1:8002")

    if not api_key or not app_secret:
        print("ERROR: Missing market data credentials.", file=sys.stderr)
        print("Set SCHWAB_MARKET_APP_KEY and SCHWAB_MARKET_CLIENT_SECRET in .env")
        sys.exit(1)

    MARKET_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("SCHWAB MARKET DATA AUTHENTICATION")
    print("=" * 60)
    print(f"\nCallback URL: {callback_url}")
    print("Opening browser for Schwab login...")
    print("Complete the login and authorize the application.\n")

    try:
        client = auth.client_from_login_flow(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=callback_url,
            token_path=str(MARKET_TOKEN_PATH),
        )

        print("\nAuthentication successful!")
        print(f"Tokens saved to {MARKET_TOKEN_PATH}")
        print("Tokens are valid for 7 days before re-authentication is required.")

        # Test with a simple quote request
        print("\nTesting market data access...")
        response = client.get_quote("$SPX")
        if response.status_code == 200:
            print("Market data API working!")
        else:
            print(f"Warning: Quote request returned {response.status_code}")

        return client

    except Exception as e:
        print(f"\nAuthentication failed: {e}", file=sys.stderr)
        sys.exit(1)


def get_market_client():
    """
    Get authenticated market data client.

    Returns existing client if tokens valid, otherwise runs auth flow.
    """
    api_key = os.getenv("SCHWAB_MARKET_APP_KEY")
    app_secret = os.getenv("SCHWAB_MARKET_CLIENT_SECRET")
    callback_url = os.getenv("SCHWAB_MARKET_CALLBACK_URL", "https://127.0.0.1:8002")

    if not api_key or not app_secret:
        raise ValueError(
            "Missing market data credentials. "
            "Set SCHWAB_MARKET_APP_KEY and SCHWAB_MARKET_CLIENT_SECRET."
        )

    MARKET_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)

    return auth.easy_client(
        api_key=api_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=str(MARKET_TOKEN_PATH),
    )


def main():
    """CLI entry point"""
    authenticate_market_data()
    return 0


if __name__ == "__main__":
    sys.exit(main())
