"""
Admin commands: auth, doctor, accounts.
"""

import os

from config.secure_account_config import ACCOUNTS_FILE, secure_config

from ...auth import TokenManager, resolve_data_dir, resolve_token_path
from ...market_auth import resolve_market_token_path
from ..output import format_header, handle_cli_error, print_json_response


def cmd_auth(*, output_mode: str = "text") -> None:
    """Check authentication status."""
    command = "auth"
    try:
        manager = TokenManager()
        info = manager.get_token_info()

        if output_mode == "json":
            print_json_response(command, data={"token": info})
            return

        print(format_header("AUTHENTICATION STATUS"))
        print(f"  Token exists: {info.get('exists', False)}")
        print(f"  Token valid:  {info.get('valid', False)}")

        expires_at = info.get("expires") or info.get("expires_at")
        if expires_at:
            print(f"  Expires at:   {expires_at}")

        if info.get("warning"):
            print(f"  Warning:      {info['warning']}")

        if not info.get("valid", False):
            print("\n  Run 'schwab-auth' to authenticate.")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_doctor(*, output_mode: str = "text") -> None:
    """Run diagnostics for configuration and auth."""
    command = "doctor"
    try:
        data_dir = resolve_data_dir()
        portfolio_token_path = resolve_token_path()
        market_token_path = resolve_market_token_path()

        portfolio_creds = {
            "app_key": bool(os.getenv("SCHWAB_INTEL_APP_KEY")),
            "app_secret": bool(os.getenv("SCHWAB_INTEL_CLIENT_SECRET")),
            "callback_url": os.getenv("SCHWAB_INTEL_CALLBACK_URL", "https://127.0.0.1:8001"),
        }
        market_creds = {
            "app_key": bool(os.getenv("SCHWAB_MARKET_APP_KEY")),
            "app_secret": bool(os.getenv("SCHWAB_MARKET_CLIENT_SECRET")),
            "callback_url": os.getenv("SCHWAB_MARKET_CALLBACK_URL", "https://127.0.0.1:8002"),
        }

        portfolio_token = TokenManager(token_path=portfolio_token_path).get_token_info()
        market_token = TokenManager(token_path=market_token_path).get_token_info()

        accounts = secure_config.get_all_accounts()
        accounts_configured = bool(accounts)

        warnings: list[str] = []

        # Portfolio warnings
        if not (portfolio_creds["app_key"] and portfolio_creds["app_secret"]):
            warnings.append("portfolio_credentials_missing")
        if not portfolio_token.get("exists", False):
            warnings.append("portfolio_token_missing")
        if portfolio_token.get("exists") and not portfolio_token.get("valid", False):
            warnings.append("portfolio_token_expired")
        if portfolio_token.get("warning_level") == "critical":
            warnings.append("portfolio_token_expiring_critical")
        elif portfolio_token.get("warning_level") == "warning":
            warnings.append("portfolio_token_expiring_soon")

        # Market warnings
        if not (market_creds["app_key"] and market_creds["app_secret"]):
            warnings.append("market_credentials_missing")
        if not market_token.get("exists", False):
            warnings.append("market_token_missing")
        if market_token.get("exists") and not market_token.get("valid", False):
            warnings.append("market_token_expired")
        if market_token.get("warning_level") == "critical":
            warnings.append("market_token_expiring_critical")
        elif market_token.get("warning_level") == "warning":
            warnings.append("market_token_expiring_soon")

        # Account warnings
        if not accounts_configured:
            warnings.append("accounts_config_missing")

        data = {
            "data_dir": str(data_dir),
            "portfolio": {
                "credentials_present": portfolio_creds["app_key"] and portfolio_creds["app_secret"],
                "token_path": str(portfolio_token_path),
                "token": portfolio_token,
            },
            "market": {
                "credentials_present": market_creds["app_key"] and market_creds["app_secret"],
                "token_path": str(market_token_path),
                "token": market_token,
            },
            "accounts": {
                "configured": accounts_configured,
                "count": len(accounts),
                "path": str(ACCOUNTS_FILE),
            },
            "warnings": warnings,
        }

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        # Text output
        print(format_header("SCHWAB CLI DOCTOR"))
        print(f"  Data directory: {data_dir}")

        print("\n  Portfolio API:")
        print(
            f"    Credentials: {'OK' if data['portfolio']['credentials_present'] else 'MISSING'}"
        )
        print(
            f"    Token: {'present' if portfolio_token.get('exists') else 'missing'}"
            f" ({'valid' if portfolio_token.get('valid') else 'EXPIRED'})"
        )
        if portfolio_token.get("expires_in_hours") is not None:
            hours = portfolio_token["expires_in_hours"]
            days = portfolio_token.get("expires_in_days", 0)
            if hours <= 0:
                print("    Expires: EXPIRED")
            elif hours < 24:
                print(f"    Expires: {hours:.1f} hours remaining")
            else:
                print(f"    Expires: {days} days ({hours:.0f} hours)")
        if portfolio_token.get("warning"):
            print(f"    WARNING: {portfolio_token['warning']}")
        print(f"    Token path: {portfolio_token_path}")

        print("\n  Market API:")
        print(
            f"    Credentials: {'OK' if data['market']['credentials_present'] else 'MISSING'}"
        )
        print(
            f"    Token: {'present' if market_token.get('exists') else 'missing'}"
            f" ({'valid' if market_token.get('valid') else 'EXPIRED'})"
        )
        if market_token.get("expires_in_hours") is not None:
            hours = market_token["expires_in_hours"]
            days = market_token.get("expires_in_days", 0)
            if hours <= 0:
                print("    Expires: EXPIRED")
            elif hours < 24:
                print(f"    Expires: {hours:.1f} hours remaining")
            else:
                print(f"    Expires: {days} days ({hours:.0f} hours)")
        if market_token.get("warning"):
            print(f"    WARNING: {market_token['warning']}")
        print(f"    Token path: {market_token_path}")

        print("\n  Accounts:")
        print(
            f"    Configured: {'yes' if accounts_configured else 'no'}"
            f" ({len(accounts)} accounts)"
        )
        print(f"    Config path: {ACCOUNTS_FILE}")

        if warnings:
            print("\n  Warnings:")
            for warning in warnings:
                print(f"    - {warning}")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)


def cmd_accounts(*, output_mode: str = "text") -> None:
    """List available account aliases."""
    command = "accounts"
    try:
        accounts = secure_config.get_all_accounts()

        data = {
            "accounts": [
                {
                    "alias": alias,
                    "label": info.label,
                    "description": info.description,
                    "account_number_last4": info.account_number[-4:] if info.account_number else None,
                }
                for alias, info in accounts.items()
            ]
        }

        if output_mode == "json":
            print_json_response(command, data=data)
            return

        print(format_header("CONFIGURED ACCOUNTS"))
        if not accounts:
            print("  No accounts configured.")
            print(f"  Create {ACCOUNTS_FILE} from accounts.template.json")
        else:
            for alias, info in accounts.items():
                last4 = info.account_number[-4:] if info.account_number else "????"
                print(f"  {alias:20s} (...{last4})  {info.description or ''}")

        print()

    except Exception as exc:
        handle_cli_error(exc, output_mode=output_mode, command=command)
