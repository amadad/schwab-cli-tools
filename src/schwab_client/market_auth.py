"""
Authentication for Schwab Market Data API

Auth flow for market data (quotes, VIX, sectors).
Uses a separate token only when market data uses a separate OAuth app.

Usage:
    uv run schwab-market-auth
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.core.errors import ConfigError
from src.schwab_client.auth_tokens import (
    AUTH_PROBE_ERRORS,
    AUTH_RECOVERY_ERRORS,
    TOKEN_MAX_AGE_SECONDS,
    TokenManager,
    get_token_manager,
    oauth_error_type,
    resolve_token_path,
    schwab_auth_module,
)
from src.schwab_client.secure_files import ensure_sensitive_dir

load_dotenv()

MARKET_TOKEN_PATH_ENV = "SCHWAB_MARKET_TOKEN_PATH"


def _market_uses_portfolio_oauth_app() -> bool:
    portfolio_key = os.getenv("SCHWAB_INTEL_APP_KEY")
    portfolio_secret = os.getenv("SCHWAB_INTEL_CLIENT_SECRET")
    market_key = os.getenv("SCHWAB_MARKET_APP_KEY")
    market_secret = os.getenv("SCHWAB_MARKET_CLIENT_SECRET")
    return bool(
        portfolio_key
        and portfolio_secret
        and market_key == portfolio_key
        and market_secret == portfolio_secret
    )


def resolve_market_token_path() -> Path:
    if os.getenv(MARKET_TOKEN_PATH_ENV):
        return resolve_token_path(
            token_path_env=MARKET_TOKEN_PATH_ENV,
            token_filename="schwab_market_token.json",
        )
    if _market_uses_portfolio_oauth_app():
        return resolve_token_path()
    return resolve_token_path(
        token_path_env=MARKET_TOKEN_PATH_ENV,
        token_filename="schwab_market_token.json",
    )


def resolve_market_callback_url() -> str:
    callback_url = os.getenv("SCHWAB_MARKET_CALLBACK_URL")
    if callback_url:
        return callback_url
    if _market_uses_portfolio_oauth_app():
        return os.getenv("SCHWAB_INTEL_CALLBACK_URL", "https://127.0.0.1:8001")
    return "https://127.0.0.1:8002"


def verify_market_token_live() -> tuple[bool, str | None]:
    """Probe the Schwab Market API with the current market token.

    Returns (success, error_message).
    """
    api_key = os.getenv("SCHWAB_MARKET_APP_KEY")
    app_secret = os.getenv("SCHWAB_MARKET_CLIENT_SECRET")
    if not api_key or not app_secret:
        return False, "credentials_missing"

    manager = get_token_manager(token_path=resolve_market_token_path())
    if not manager.tokens_exist():
        return False, "token_file_missing"

    try:
        client = _build_managed_market_client(api_key, app_secret, manager)
        resp = client.get_quote("$SPX")
        resp.raise_for_status()
        return True, None
    except (*AUTH_PROBE_ERRORS, oauth_error_type()) as exc:
        return False, str(exc)


def _build_managed_market_client(
    api_key: str,
    app_secret: str,
    manager: TokenManager,
):
    return schwab_auth_module().client_from_access_functions(
        api_key=api_key,
        app_secret=app_secret,
        token_read_func=manager.read_token_object,
        token_write_func=manager.write_token_object,
    )


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
    """Run interactive authentication for Market Data API."""
    args = args or parse_args()
    api_key = os.getenv("SCHWAB_MARKET_APP_KEY")
    app_secret = os.getenv("SCHWAB_MARKET_CLIENT_SECRET")
    callback_url = resolve_market_callback_url()
    token_path = resolve_market_token_path()

    if not api_key or not app_secret:
        print("ERROR: Missing market data credentials.", file=sys.stderr)
        print("Set SCHWAB_MARKET_APP_KEY and SCHWAB_MARKET_CLIENT_SECRET in .env")
        sys.exit(1)

    ensure_sensitive_dir(token_path.parent)

    print("\n" + "=" * 60)
    print("SCHWAB MARKET DATA AUTHENTICATION")
    print("=" * 60)
    print(f"\nCallback URL: {callback_url}")

    manager = get_token_manager(token_path=token_path)
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
        with manager.auth_lock() as conn:
            schwab_auth_module().client_from_login_flow(
                api_key=api_key,
                app_secret=app_secret,
                callback_url=callback_url,
                token_path=str(token_path),
                callback_timeout=args.timeout,
                interactive=args.interactive,
                requested_browser=args.browser,
            )
            manager.sync_state_from_file(conn=conn)

        if not manager.tokens_exist():
            raise ConfigError(
                f"OAuth bootstrap completed but no token was written to {token_path}"
            )

        client = _build_managed_market_client(api_key, app_secret, manager)

        print("\nAuthentication successful!")
        print(f"Tokens saved to {token_path}")
        token_info = manager.get_token_info()
        if token_info.get("expires"):
            print(
                "Token expires: "
                f"{token_info['expires']} "
                f"({token_info.get('expires_in_days', 0)} days)"
            )

        print("\nTesting market data access...")
        response = client.get_quote("$SPX")
        if response.status_code == 200:
            print("Market data API working!")
        else:
            print(f"Warning: Quote request returned {response.status_code}")

        return client

    except AUTH_RECOVERY_ERRORS as e:
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
    print("  5. Copy the FULL URL from your browser's address bar")
    print(f"     (starts with {callback_url}/?code=...)")
    print("  6. Paste it back here")
    print()

    try:
        with manager.auth_lock() as conn:
            schwab_auth_module().client_from_manual_flow(
                api_key=api_key,
                app_secret=app_secret,
                callback_url=callback_url,
                token_path=str(manager.token_path),
            )
            manager.sync_state_from_file(conn=conn)

        if not manager.tokens_exist():
            raise ConfigError(
                "OAuth bootstrap completed but no token was written to "
                f"{manager.token_path}"
            )

        client = _build_managed_market_client(api_key, app_secret, manager)

        print()
        print("Authentication successful!")
        print(f"Tokens saved to {manager.token_path}")
        token_info = manager.get_token_info()
        if token_info.get("expires"):
            print(
                "Token expires: "
                f"{token_info['expires']} "
                f"({token_info.get('expires_in_days', 0)} days)"
            )

        print("\nTesting market data access...")
        response = client.get_quote("$SPX")
        if response.status_code == 200:
            print("Market data API working!")
        else:
            print(f"Warning: Quote request returned {response.status_code}")

        return client

    except AUTH_RECOVERY_ERRORS as e:
        print(f"\nAuthentication failed: {e}", file=sys.stderr)
        sys.exit(1)


def get_market_client():
    """
    Get authenticated market data client.

    Returns existing client if tokens valid, otherwise runs auth flow.
    """
    api_key = os.getenv("SCHWAB_MARKET_APP_KEY")
    app_secret = os.getenv("SCHWAB_MARKET_CLIENT_SECRET")
    callback_url = resolve_market_callback_url()
    token_path = resolve_market_token_path()

    if not api_key or not app_secret:
        raise ValueError(
            "Missing market data credentials. "
            "Set SCHWAB_MARKET_APP_KEY and SCHWAB_MARKET_CLIENT_SECRET."
        )

    manager = get_token_manager(token_path=token_path)
    ensure_sensitive_dir(token_path.parent)

    client = None
    if manager.tokens_exist():
        try:
            client = _build_managed_market_client(api_key, app_secret, manager)
            if client.token_age() >= TOKEN_MAX_AGE_SECONDS:
                manager.delete_tokens()
                client = None
        except AUTH_RECOVERY_ERRORS:
            manager.delete_tokens()
            client = None

    if client is None:
        with manager.auth_lock() as conn:
            schwab_auth_module().easy_client(
                api_key=api_key,
                app_secret=app_secret,
                callback_url=callback_url,
                token_path=str(token_path),
            )
            manager.sync_state_from_file(conn=conn)
        if not manager.tokens_exist():
            raise ConfigError(
                f"OAuth bootstrap completed but no token was written to {token_path}"
            )
        client = _build_managed_market_client(api_key, app_secret, manager)

    return client


def main():
    """CLI entry point"""
    authenticate_market_data()
    return 0


if __name__ == "__main__":
    sys.exit(main())
