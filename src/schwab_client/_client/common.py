"""Shared client constants and decorators."""

from __future__ import annotations

import logging
import time
from functools import wraps

import httpx

logger = logging.getLogger(__name__)

# Money market fund symbols treated as cash equivalents
MONEY_MARKET_SYMBOLS = frozenset({"SWGXX", "SWVXX", "SNOXX", "SNSXX", "SNVXX"})


def _retry_on_transient_error(max_retries: int = 2, backoff_base: float = 1.0):
    """Retry on transient HTTP errors with exponential backoff."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status in (429, 500, 502, 503, 504) and attempt < max_retries:
                        wait = backoff_base * (2**attempt)
                        logger.warning(
                            "Transient error %s, retrying in %.1fs (attempt %s/%s)",
                            status,
                            wait,
                            attempt + 1,
                            max_retries,
                        )
                        time.sleep(wait)
                        last_exc = exc
                    else:
                        raise
            raise last_exc

        return wrapper

    return decorator
