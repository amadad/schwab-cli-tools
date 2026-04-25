"""Portfolio OAuth flows for ``schwab-py``.

Token path resolution, locking, metadata, and atomic writes live in
``auth_tokens.py`` and are re-exported here for compatibility.
"""

from __future__ import annotations

import logging
import os
from functools import cache
from pathlib import Path

from dotenv import load_dotenv

from src.core.errors import ConfigError
from src.schwab_client.auth_tokens import (
    AUTH_PROBE_ERRORS,
    AUTH_RECOVERY_ERRORS,
    DEFAULT_TOKEN_PATH,
    TOKEN_MAX_AGE_SECONDS,
    TokenManager,
    get_token_manager,
    oauth_error_type,
    resolve_data_dir,
    resolve_token_db_path,
    resolve_token_path,
    suppress_authlib_jose_warning,
)
from src.schwab_client.secure_files import ensure_sensitive_dir

load_dotenv()
logger = logging.getLogger(__name__)

__all__ = [
    "AUTH_PROBE_ERRORS",
    "AUTH_RECOVERY_ERRORS",
    "DEFAULT_TOKEN_PATH",
    "TOKEN_MAX_AGE_SECONDS",
    "TokenManager",
    "authenticate_interactive",
    "authenticate_manual",
    "get_authenticated_client",
    "get_token_manager",
    "oauth_error_type",
    "resolve_data_dir",
    "resolve_token_db_path",
    "resolve_token_path",
    "verify_portfolio_token_live",
]


@cache
def _schwab_auth_module():
    with suppress_authlib_jose_warning():
        from schwab import auth as schwab_auth
    return schwab_auth


class _SchwabAuthProxy:
    def __getattr__(self, name: str):
        return getattr(_schwab_auth_module(), name)


auth = _SchwabAuthProxy()


def verify_portfolio_token_live() -> tuple[bool, str | None]:
    """Probe the Schwab API with the current portfolio token.

    Returns (success, error_message).  A successful probe means the refresh
    token is still accepted server-side.
    """
    api_key = os.getenv("SCHWAB_INTEL_APP_KEY")
    app_secret = os.getenv("SCHWAB_INTEL_CLIENT_SECRET")
    if not api_key or not app_secret:
        return False, "credentials_missing"

    manager = get_token_manager()
    if not manager.tokens_exist():
        return False, "token_file_missing"

    try:
        client = _build_locked_client(
            api_key=api_key, app_secret=app_secret, manager=manager
        )
        resp = client.get_account_numbers()
        resp.raise_for_status()
        return True, None
    except (*AUTH_PROBE_ERRORS, oauth_error_type()) as exc:
        return False, str(exc)


def _build_locked_client(
    *,
    api_key: str,
    app_secret: str,
    manager: TokenManager,
    asyncio: bool = False,
):
    return auth.client_from_access_functions(
        api_key=api_key,
        app_secret=app_secret,
        token_read_func=manager.read_token_object,
        token_write_func=manager.write_token_object,
        asyncio=asyncio,
    )


def _get_or_create_locked_client(
    *,
    api_key: str,
    app_secret: str,
    callback_url: str,
    token_path: Path,
    asyncio: bool = False,
):
    manager = get_token_manager(token_path=token_path)
    client = None

    if manager.tokens_exist():
        try:
            client = _build_locked_client(
                api_key=api_key,
                app_secret=app_secret,
                manager=manager,
                asyncio=asyncio,
            )
            if client.token_age() >= TOKEN_MAX_AGE_SECONDS:
                logger.info("Token too old, proactively re-authenticating")
                manager.delete_tokens()
                client = None
        except AUTH_RECOVERY_ERRORS as exc:
            logger.warning("Failed to load managed token state, re-authenticating: %s", exc)
            manager.delete_tokens()
            client = None

    if client is None:
        with manager.auth_lock() as conn:
            bootstrap_client = auth.easy_client(
                api_key=api_key,
                app_secret=app_secret,
                callback_url=callback_url,
                token_path=str(token_path),
                asyncio=asyncio,
            )
            manager.sync_state_from_file(conn=conn)

        if not manager.tokens_exist():
            return bootstrap_client

        client = _build_locked_client(
            api_key=api_key,
            app_secret=app_secret,
            manager=manager,
            asyncio=asyncio,
        )

    return client


def get_authenticated_client(
    api_key: str | None = None,
    app_secret: str | None = None,
    callback_url: str = "https://127.0.0.1:8001",
    token_path: Path | None = None,
    asyncio: bool = False,
):
    """Get an authenticated Schwab client backed by managed token storage."""
    api_key = api_key or os.getenv("SCHWAB_INTEL_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_INTEL_CLIENT_SECRET")
    token_path = token_path or DEFAULT_TOKEN_PATH

    if not api_key or not app_secret:
        raise ConfigError(
            "Missing Schwab credentials. Set SCHWAB_INTEL_APP_KEY and "
            "SCHWAB_INTEL_CLIENT_SECRET environment variables."
        )

    ensure_sensitive_dir(Path(token_path).parent)

    client = _get_or_create_locked_client(
        api_key=api_key,
        app_secret=app_secret,
        callback_url=callback_url,
        token_path=Path(token_path),
        asyncio=asyncio,
    )
    logger.info("Schwab client authenticated successfully")
    return client


def authenticate_interactive(
    api_key: str | None = None,
    app_secret: str | None = None,
    callback_url: str = "https://127.0.0.1:8001",
    token_path: Path | None = None,
    interactive: bool = False,
    requested_browser: str | None = None,
    callback_timeout: float | None = 300.0,
):
    """Run the browser-based authentication flow and return a managed client."""
    api_key = api_key or os.getenv("SCHWAB_INTEL_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_INTEL_CLIENT_SECRET")
    token_path = token_path or DEFAULT_TOKEN_PATH

    if not api_key or not app_secret:
        raise ConfigError(
            "Missing Schwab credentials. Set SCHWAB_INTEL_APP_KEY and "
            "SCHWAB_INTEL_CLIENT_SECRET environment variables."
        )

    manager = get_token_manager(token_path=token_path)
    ensure_sensitive_dir(Path(token_path).parent)

    print("Opening browser for Schwab authentication...")
    print("Complete the login and authorize the application.")
    print(f"Callback URL: {callback_url}")
    print()

    with manager.auth_lock() as conn:
        auth.client_from_login_flow(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=callback_url,
            token_path=str(token_path),
            callback_timeout=callback_timeout,
            interactive=interactive,
            requested_browser=requested_browser,
        )
        manager.sync_state_from_file(conn=conn)

    print()
    print(f"Authentication successful! Tokens saved to {token_path}")
    print("Tokens are valid for 7 days before re-authentication is required.")
    return _build_locked_client(
        api_key=api_key,
        app_secret=app_secret,
        manager=manager,
    )


def authenticate_manual(
    api_key: str | None = None,
    app_secret: str | None = None,
    callback_url: str = "https://127.0.0.1:8001",
    token_path: Path | None = None,
):
    """Run the manual authentication flow and return a managed client."""
    api_key = api_key or os.getenv("SCHWAB_INTEL_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_INTEL_CLIENT_SECRET")
    token_path = token_path or DEFAULT_TOKEN_PATH

    if not api_key or not app_secret:
        raise ConfigError(
            "Missing Schwab credentials. Set SCHWAB_INTEL_APP_KEY and "
            "SCHWAB_INTEL_CLIENT_SECRET environment variables."
        )

    manager = get_token_manager(token_path=token_path)
    ensure_sensitive_dir(Path(token_path).parent)

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
    print("     (starts with https://127.0.0.1:8001/?code=...)")
    print("  6. Paste it back here")
    print()

    with manager.auth_lock() as conn:
        auth.client_from_manual_flow(
            api_key=api_key,
            app_secret=app_secret,
            callback_url=callback_url,
            token_path=str(token_path),
        )
        manager.sync_state_from_file(conn=conn)

    print()
    print(f"Authentication successful! Tokens saved to {token_path}")
    print("Tokens are valid for 7 days before re-authentication is required.")
    return _build_locked_client(
        api_key=api_key,
        app_secret=app_secret,
        manager=manager,
    )


def main():
    """CLI entry point for authentication."""
    try:
        client = authenticate_interactive()

        response = client.get_account_numbers()
        if response.status_code == 200:
            accounts = response.json()
            print(f"Found {len(accounts)} accounts")
            print("Authentication complete!")
        else:
            print(f"Warning: API test returned {response.status_code}")

    except AUTH_RECOVERY_ERRORS as exc:
        print(f"Authentication failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
