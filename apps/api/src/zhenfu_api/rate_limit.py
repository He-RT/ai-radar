from __future__ import annotations

import hmac
import math
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from threading import BoundedSemaphore, RLock
from typing import Protocol, cast

from redis import Redis
from redis.exceptions import RedisError


class RateLimiterUnavailable(RuntimeError):
    """The shared rate-limit backend could not make a safe decision."""


class ConcurrencyLimitExceeded(RuntimeError):
    """This process has no free high-cost execution slots."""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int


class RateLimiter(Protocol):
    """Injectable boundary for one fixed-window rate-limit counter."""

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult: ...

    def is_ready(self) -> bool: ...


def private_rate_limit_key(secret: str, scope: str, dimension: str, identity: str) -> str:
    """Build a non-reversible key; raw IPs, emails, tokens, and questions never leave the API."""
    message = f"{scope}\0{dimension}\0{identity}".encode()
    digest = hmac.new(secret.encode(), message, sha256).hexdigest()
    return f"radar:rl:{scope}:{dimension}:{digest}"


@dataclass
class _MemoryWindow:
    count: int
    expires_at: float


@dataclass
class InMemoryRateLimiter:
    """Thread-safe deterministic limiter for development and tests."""

    clock: Callable[[], float] = time.monotonic
    _windows: dict[str, _MemoryWindow] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = self.clock()
        with self._lock:
            window = self._windows.get(key)
            if window is None or now >= window.expires_at:
                window = _MemoryWindow(count=0, expires_at=now + window_seconds)
                self._windows[key] = window
            window.count += 1
            retry_after = max(1, math.ceil(window.expires_at - now))
            return RateLimitResult(allowed=window.count <= limit, retry_after=retry_after)

    def is_ready(self) -> bool:
        return True


_FIXED_WINDOW_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
if ttl < 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
  ttl = tonumber(ARGV[1])
end
return {current, ttl}
"""


@dataclass
class RedisRateLimiter:
    """Redis-backed fixed windows; Lua keeps increment and initial expiry atomic."""

    client: Redis

    @classmethod
    def from_url(cls, url: str) -> RedisRateLimiter:
        return cls(
            Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
        )

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        try:
            raw = self.client.eval(_FIXED_WINDOW_LUA, 1, key, str(window_seconds))
            values = cast(list[object], raw)
            current = int(cast(int | str | bytes, values[0]))
            retry_after = max(1, int(cast(int | str | bytes, values[1])))
        except Exception as exc:
            # A backend failure must never turn into an unlimited expensive endpoint.
            raise RateLimiterUnavailable("shared rate limiter unavailable") from exc
        return RateLimitResult(allowed=current <= limit, retry_after=retry_after)

    def is_ready(self) -> bool:
        try:
            return bool(self.client.ping())
        except (OSError, RedisError):
            return False


@dataclass
class HighCostGate:
    """Non-blocking, process-local concurrency insurance for CPU/LLM-heavy work."""

    limit: int
    retry_after: int = 1
    _semaphore: BoundedSemaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._semaphore = BoundedSemaphore(self.limit)

    @contextmanager
    def slot(self) -> Iterator[None]:
        if not self._semaphore.acquire(blocking=False):
            raise ConcurrencyLimitExceeded
        try:
            yield
        finally:
            self._semaphore.release()
