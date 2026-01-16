"""
Interactive authentication CLI for Schwab API

Usage:
    schwab-auth     Start OAuth2 authentication flow
"""

import sys

from .auth import TokenManager, authenticate_interactive


def main() -> None:
    """Main entry point for interactive authentication"""
    print("\n" + "=" * 60)
    print("SCHWAB AUTHENTICATION")
    print("=" * 60)

    try:
        # Check existing token
        manager = TokenManager()
        info = manager.get_token_info()

        if info.get("valid"):
            print("Existing valid token found.")
            response = input("Re-authenticate anyway? [y/N]: ").strip().lower()
            if response != "y":
                print("Authentication cancelled.")
                return

        # Start interactive auth
        print("\nStarting OAuth2 flow...")
        print("A browser window will open for login.")
        print()

        client = authenticate_interactive()

        if client:
            print("\nAuthentication successful!")
            print("Token saved. You can now use the CLI commands.")
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
