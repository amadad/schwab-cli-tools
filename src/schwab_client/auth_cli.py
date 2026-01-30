"""
Interactive authentication CLI for Schwab API

Usage:
    schwab-auth     Start OAuth2 authentication flow
"""

import argparse
import sys

from .auth import TokenManager, authenticate_interactive, authenticate_manual


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Schwab OAuth authentication")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-authenticate even if a valid token exists.",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Use manual flow for headless/remote environments. "
        "Prints URL to open on any browser, then prompts for callback URL.",
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


def main() -> None:
    """Main entry point for interactive authentication"""
    print("\n" + "=" * 60)
    print("SCHWAB AUTHENTICATION")
    print("=" * 60)

    args = parse_args()

    try:
        manager = TokenManager()
        info = manager.get_token_info()

        if info.get("exists"):
            if not info.get("valid", True):
                print("Existing token expired or invalid. Removing it...")
                manager.delete_tokens()
            elif not args.force:
                print("Existing valid token found.")
                print("Use --force to re-authenticate.")
                return
            else:
                print("Re-authenticating (forced).")

        if args.manual:
            print("\nStarting manual OAuth2 flow (for headless/remote)...\n")
            client = authenticate_manual()
        else:
            print("\nStarting OAuth2 flow...")
            print("A browser window will open for login.\n")
            client = authenticate_interactive(
                interactive=args.interactive,
                requested_browser=args.browser,
                callback_timeout=args.timeout,
            )

        if client:
            print("\nAuthentication successful!")
            print(f"Token saved to {manager.token_path}")
            token_info = manager.get_token_info()
            if token_info.get("expires"):
                print(
                    "Token expires: "
                    f"{token_info['expires']} "
                    f"({token_info.get('expires_in_days', 0)} days)"
                )
            print("You can now use the CLI commands.")
        else:
            print("\nAuthentication failed.", file=sys.stderr)
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\nAuthentication cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError during authentication: {e}", file=sys.stderr)
        sys.exit(1)

    print()


if __name__ == "__main__":
    main()
