"""Public package exports for Schwab CLI tools."""

from __future__ import annotations

__all__ = [
    "SchwabClientWrapper",
    "TokenManager",
    "HistoryStore",
    "collect_snapshot",
    "get_authenticated_client",
    "authenticate_interactive",
    "MONEY_MARKET_SYMBOLS",
]


def __getattr__(name: str):
    if name in {"MONEY_MARKET_SYMBOLS", "SchwabClientWrapper"}:
        from .client import MONEY_MARKET_SYMBOLS, SchwabClientWrapper

        exports = {
            "MONEY_MARKET_SYMBOLS": MONEY_MARKET_SYMBOLS,
            "SchwabClientWrapper": SchwabClientWrapper,
        }
    elif name == "TokenManager":
        from .auth_tokens import TokenManager

        exports = {"TokenManager": TokenManager}
    elif name in {"authenticate_interactive", "get_authenticated_client"}:
        from .auth import authenticate_interactive, get_authenticated_client

        exports = {
            "authenticate_interactive": authenticate_interactive,
            "get_authenticated_client": get_authenticated_client,
        }
    elif name == "HistoryStore":
        from .history import HistoryStore

        exports = {"HistoryStore": HistoryStore}
    elif name == "collect_snapshot":
        from .snapshot import collect_snapshot

        exports = {"collect_snapshot": collect_snapshot}
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = exports[name]
    globals()[name] = value
    return value
