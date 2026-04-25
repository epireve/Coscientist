"""v0.13 — retry-with-backoff wrapper for flaky calls.

For MCP timeouts, publisher 429s, and similar transient failures.
Pure Python, no external deps. Used by skills that need it; not
a global wrapper around every call.

Usage:
    from lib.retry import retry_with_backoff
    result = retry_with_backoff(
        lambda: some_flaky_fn(args),
        max_attempts=4,
        base_delay=2.0,
    )

For an async-friendly version, swap time.sleep with asyncio.sleep.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


# Default retryable exceptions: subprocess/timeout/IO. Caller can override.
DEFAULT_RETRYABLE = (TimeoutError, ConnectionError, OSError)


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_attempts: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    jitter: float = 0.1,
    retryable: tuple[type[BaseException], ...] = DEFAULT_RETRYABLE,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Call `fn()` up to `max_attempts` times with exponential backoff.

    Backoff schedule: base_delay * 2^attempt + jitter*random.
    Jitter is uniform in [0, base_delay*jitter] each retry.

    Raises the original exception after the last attempt fails.
    """
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except retryable as exc:
            last_exc = exc
            if attempt >= max_attempts - 1:
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay += random.uniform(0, base_delay * jitter)
            if on_retry:
                on_retry(attempt + 1, exc, delay)
            else:
                logger.debug(
                    "retry attempt %d/%d after %s: sleeping %.2fs",
                    attempt + 1, max_attempts, type(exc).__name__, delay,
                )
            time.sleep(delay)
    # Re-raise the most recent exception
    assert last_exc is not None
    raise last_exc


async def aretry_with_backoff(
    fn,
    *,
    max_attempts: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    jitter: float = 0.1,
    retryable: tuple[type[BaseException], ...] = DEFAULT_RETRYABLE,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
):
    """Async variant of retry_with_backoff.

    `fn` is an async callable. Uses asyncio.sleep so the event loop isn't
    blocked during backoff.
    """
    import asyncio
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except retryable as exc:
            last_exc = exc
            if attempt >= max_attempts - 1:
                break
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay += random.uniform(0, base_delay * jitter)
            if on_retry:
                on_retry(attempt + 1, exc, delay)
            else:
                logger.debug(
                    "async retry attempt %d/%d after %s: sleeping %.2fs",
                    attempt + 1, max_attempts, type(exc).__name__, delay,
                )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
