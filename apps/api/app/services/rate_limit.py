"""Per-user, per-action rate limiter using a fixed-window counter.

Lightweight in-memory implementation suitable for ≤10 concurrent users on a
single worker process. For multi-worker, swap the backend to Redis INCR + EXPIRE
without changing the call-site.

Usage:
    from .rate_limit import enforce, RateLimitExceeded
    enforce(user_id="...", action="brief", limit=20, window_seconds=86400)
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from ..logging_setup import get_logger

log = get_logger("rate_limit")


class RateLimitExceeded(Exception):
    """Raised when a user has exceeded the budget for a given action."""

    def __init__(self, action: str, limit: int, retry_after_seconds: int):
        self.action = action
        self.limit = limit
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"rate limit exceeded for {action}: {limit} per window. "
            f"Retry in {retry_after_seconds}s."
        )


@dataclass
class _Bucket:
    window_start: float
    count: int


_BUCKETS: dict[tuple[str, str], _Bucket] = {}


def enforce(*, user_id: str, action: str, limit: int, window_seconds: int) -> None:
    """Increment the counter for (user, action). Raise if over the budget.

    `user_id` of the literal string ``"anon"`` shares one bucket across all
    unauthenticated callers — a deliberate footgun-prevention against demo-mode
    abuse.
    """
    if limit <= 0:
        return
    key = (user_id, action)
    now = time.time()
    bucket = _BUCKETS.get(key)
    if bucket is None or now - bucket.window_start >= window_seconds:
        _BUCKETS[key] = _Bucket(window_start=now, count=1)
        return
    bucket.count += 1
    if bucket.count > limit:
        retry_after = max(1, int(window_seconds - (now - bucket.window_start)))
        log.warning(
            "rate_limit.exceeded",
            user_id=user_id, action=action,
            count=bucket.count, limit=limit,
        )
        raise RateLimitExceeded(action=action, limit=limit, retry_after_seconds=retry_after)


def reset(user_id: str, action: str) -> None:
    """Clear the bucket for tests + admin endpoints."""
    _BUCKETS.pop((user_id, action), None)
