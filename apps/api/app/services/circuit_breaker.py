"""Async circuit breaker for external HTTP calls.

CLAUDE.md §8.7 mandates rate limits + circuit breakers on every external API
call. tenacity (already used) handles retries/backoff but does not implement
the "open after N consecutive failures, cool down for D seconds" pattern. This
module fills that gap.

Usage:
    from .circuit_breaker import breaker

    @breaker("coingecko", failure_threshold=5, cool_down_seconds=60)
    async def fetch_price(...):
        ...

When the circuit is open:
    raise BreakerOpen(name="coingecko", until=ts)
Callers should let it propagate or fall back gracefully.

The breaker is process-local. For multi-worker deploys, share state via Redis
in a follow-up. For ≤10 users on one worker the in-memory version is fine.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from ..logging_setup import get_logger

log = get_logger("circuit_breaker")

T = TypeVar("T")


class BreakerOpen(RuntimeError):
    """Raised when the circuit is open. Includes the time it'll re-close."""

    def __init__(self, name: str, until: float):
        self.name = name
        self.until = until
        wait = max(0.0, until - time.time())
        super().__init__(f"circuit '{name}' is open; retry in {wait:.0f}s")


@dataclass
class _BreakerState:
    name: str
    failure_threshold: int
    cool_down_seconds: float
    half_open_after_seconds: float

    consecutive_failures: int = 0
    open_until: float = 0.0
    half_open_probe_in_flight: bool = False

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def state(self) -> str:
        now = time.time()
        if self.open_until > now:
            return "open"
        if self.consecutive_failures >= self.failure_threshold:
            return "half_open"
        return "closed"


_REGISTRY: dict[str, _BreakerState] = {}


def get_state(name: str) -> _BreakerState | None:
    return _REGISTRY.get(name)


def reset(name: str) -> None:
    """Force the breaker closed. For tests + admin endpoints."""
    if name in _REGISTRY:
        _REGISTRY[name].consecutive_failures = 0
        _REGISTRY[name].open_until = 0.0


def breaker(
    name: str,
    *,
    failure_threshold: int = 5,
    cool_down_seconds: float = 60.0,
    half_open_after_seconds: float | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Wrap an async function with circuit-breaker semantics."""
    state = _REGISTRY.setdefault(
        name,
        _BreakerState(
            name=name,
            failure_threshold=failure_threshold,
            cool_down_seconds=cool_down_seconds,
            half_open_after_seconds=half_open_after_seconds or cool_down_seconds,
        ),
    )

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            now = time.time()
            if state.open_until > now:
                raise BreakerOpen(state.name, state.open_until)
            try:
                result = await fn(*args, **kwargs)
            except Exception:
                async with state._lock:
                    state.consecutive_failures += 1
                    if state.consecutive_failures >= state.failure_threshold:
                        state.open_until = time.time() + state.cool_down_seconds
                        log.warning(
                            "breaker.open",
                            name=state.name,
                            failures=state.consecutive_failures,
                            cool_down_s=state.cool_down_seconds,
                        )
                raise
            else:
                if state.consecutive_failures > 0 or state.open_until:
                    log.info("breaker.recovered", name=state.name)
                state.consecutive_failures = 0
                state.open_until = 0.0
                return result

        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        wrapper.__name__ = getattr(fn, "__name__", "wrapped")
        return wrapper

    return decorator
