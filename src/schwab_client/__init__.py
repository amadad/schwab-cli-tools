"""
Schwab Client Wrapper

Wraps official schwab-py with project-specific features:
- Account label mapping
- Money market fund detection
- Structured error handling
- CLI for portfolio management
"""

from .auth import TokenManager, authenticate_interactive, get_authenticated_client
from .client import MONEY_MARKET_SYMBOLS, SchwabClientWrapper

__all__ = [
    "SchwabClientWrapper",
    "TokenManager",
    "get_authenticated_client",
    "authenticate_interactive",
    "MONEY_MARKET_SYMBOLS",
]
