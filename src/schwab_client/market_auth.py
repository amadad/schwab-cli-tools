"""
Authentication for Schwab Market Data API

Separate auth flow for market data (quotes, VIX, sectors).
Uses different credentials and token file from portfolio API.

Usage:
    uv run schwab-market-auth
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from schwab import auth

from .auth import TokenManager, get_token_manager, resolve_token_path

load_dotenv()

MARKET_TOKEN_PATH_ENV = "SCHWAB_MARKET_TOKEN_PATH"


def resolve_market_token_path() -> Path:
    return resolve_token_path(
        token_path_env=MARKET_TOKEN_PATH_ENV,
        token_filename="schwab_market_token.json",
    )


# Separate token file for market data
MARKET_TOKEN_PATH = resolve_market_token_path()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Schwab Market Data OAuth")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-authenticate even if a valid token exists.",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Use manual flow for headless/SSH (copy-paste URL).",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Require ENTER before opening the browser.",
    )
    parser.add_argument(
        "--browser",
        help="Browser name for webbrowser (e.g., chrome, firefox).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Callback timeout in seconds (0 or None waits forever).",
    )
    return parser.parse_args()


def authenticate_market_data(args: argparse.Namespace | None = None):
    """
    Run interactive authentication for Market Data API.

    Uses SCHWAB_MARKET_* credentials (separate from portfolio API).
    """
    args = args or parse_args()
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

    manager = get_token_manager(token_path=MARKET_TOKEN_PATH)
    info = manager.get_token_info()
    if info.get("exists"):
        if not info.get("valid", True):
            print("Existing token expired or invalid. Removing it...")
            manager.delete_tokens()
        elif not args.force:
            print("Existing valid token found.")
            print("Use --force to re-authenticate.")
            return None
        else:
            print("Re-authenticating (forced).")

    # Use manual flow if requested (for headless/SSH)
    if args.manual:
        return authenticate_market_data_manual(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=callback_url,
            manager=manager,
        )

    print("Opening browser for Schwab login...")
    print("Complete the login and authorize the application.\n")

    try:
        client = auth.client_from_login_flow(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=callback_url,
            token_path=str(MARKET_TOKEN_PATH),
            callback_timeout=args.timeout,
            interactive=args.interactive,
            requested_browser=args.browser,
        )

        print("\nAuthentication successful!")
        print(f"Tokens saved to {MARKET_TOKEN_PATH}")
        token_info = manager.get_token_info()
        if token_info.get("expires"):
            print(
                "Token expires: "
                f"{token_info['expires']} "
                f"({token_info.get('expires_in_days', 0)} days)"
            )

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


def authenticate_market_data_manual(
    api_key: str,
    app_secret: str,
    callback_url: str,
    manager: TokenManager,
):
    """
    Run manual authentication flow for headless/remote environments.

    This flow prints a URL that you can open on ANY browser (even a different machine),
    then prompts you to paste the callback URL after authorization.

    Use this when:
    - Running on a headless server
    - Running remotely via SSH
    - Running in a container/cloud environment
    """
    print()
    print("=" * 60)
    print("MANUAL AUTHENTICATION FLOW")
    print("=" * 60)
    print()
    print("This flow works on headless/remote machines.")
    print()
    print("Steps:")
    print("  1. Copy the URL printed below")
    print("  2. Open it in ANY browser (local machine, phone, etc.)")
    print("  3. Log into Schwab and authorize the app")
    print()
    print("  4. Your browser will show 'Can't connect to server' or similar")
    print("     THIS IS EXPECTED - don't worry!")
    print()
    print(f"  5. Copy the FULL URL from your browser's address bar")
    print(f"     (starts with {callback_url}/?code=...)")
    print("  6. Paste it back here")
    print()

    try:
        client = auth.client_from_manual_flow(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=callback_url,
            token_path=str(MARKET_TOKEN_PATH),
        )

        print()
        print("Authentication successful!")
        print(f"Tokens saved to {MARKET_TOKEN_PATH}")
        token_info = manager.get_token_info()
        if token_info.get("expires"):
            print(
                "Token expires: "
                f"{token_info['expires']} "
                f"({token_info.get('expires_in_days', 0)} days)"
            )

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
