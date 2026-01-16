"""Custom error types for portfolio tooling."""


class PortfolioError(Exception):
    """Base error for portfolio tooling."""


class ConfigError(PortfolioError):
    """Configuration or environment error."""


class AuthError(PortfolioError):
    """Authentication error."""


class ApiError(PortfolioError):
    """Upstream API error."""
