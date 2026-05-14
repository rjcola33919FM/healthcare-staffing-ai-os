"""
Rate limiter — per-contact and per-IP sliding window using Redis (or in-memory).
Protects webhook endpoints from abuse and enforces per-agent call quotas.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock
from typing import Any

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

# Default limits (requests per window)
DEFAULT_WEBHOOK_LIMIT  = 60     # per IP per minute
DEFAULT_CONTACT_LIMIT  = 30     # per contact_id per minute
DEFAULT_WINDOW_SECS    = 60


class SlidingWindowCounter:
    """
    Thread-safe in-memory sliding window rate counter.
    Each bucket key stores a list of request timestamps.
    """

    def __init__(self):
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str, limit: int, window: int) -> bool:
        now = time.time()
        cutoff = now - window
        with self._lock:
            bucket = self._buckets[key]
            # Evict expired entries
            self._buckets[key] = [t for t in bucket if t > cutoff]
            if len(self._buckets[key]) >= limit:
                return False
            self._buckets[key].append(now)
            return True

    def remaining(self, key: str, limit: int, window: int) -> int:
        now = time.time()
        cutoff = now - window
        with self._lock:
            active = [t for t in self._buckets.get(key, []) if t > cutoff]
            return max(0, limit - len(active))


class RedisRateLimiter:
    """
    Redis-backed sliding window rate limiter using sorted sets.
    Falls back to SlidingWindowCounter if Redis is unavailable.
    """

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._fallback = SlidingWindowCounter()

    def is_allowed(
        self, key: str, limit: int = DEFAULT_WEBHOOK_LIMIT, window: int = DEFAULT_WINDOW_SECS
    ) -> bool:
        if self._redis:
            return self._redis_check(key, limit, window)
        return self._fallback.is_allowed(key, limit, window)

    def _redis_check(self, key: str, limit: int, window: int) -> bool:
        now = time.time()
        cutoff = now - window
        pipe_key = f"rate:{key}"
        try:
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(pipe_key, "-inf", cutoff)
            pipe.zcard(pipe_key)
            pipe.zadd(pipe_key, {str(now): now})
            pipe.expire(pipe_key, window * 2)
            _, count, *_ = pipe.execute()
            return count < limit
        except Exception as exc:
            logger.warning("[RATE] Redis check failed — using fallback: %s", exc)
            return self._fallback.is_allowed(key, limit, window)


# Module-level singleton
_limiter: RedisRateLimiter | None = None


def get_rate_limiter(redis_client=None) -> RedisRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RedisRateLimiter(redis_client)
    return _limiter


# ── FastAPI dependencies ───────────────────────────────────────────────────────

def ip_rate_limit(
    limit: int = DEFAULT_WEBHOOK_LIMIT,
    window: int = DEFAULT_WINDOW_SECS,
):
    """Factory for per-IP rate limit dependencies."""
    def _check(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        limiter = get_rate_limiter()
        if not limiter.is_allowed(f"ip:{ip}", limit=limit, window=window):
            logger.warning("[RATE] IP rate limit exceeded: %s", ip)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please slow down.",
                headers={"Retry-After": str(window)},
            )
    return _check


def contact_rate_limit(
    limit: int = DEFAULT_CONTACT_LIMIT,
    window: int = DEFAULT_WINDOW_SECS,
):
    """Factory for per-contact_id rate limit dependencies."""
    def _check(contact_id: str) -> None:
        limiter = get_rate_limiter()
        if not limiter.is_allowed(f"contact:{contact_id}", limit=limit, window=window):
            logger.warning("[RATE] Contact rate limit exceeded: %s", contact_id)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests for this contact.",
                headers={"Retry-After": str(window)},
            )
    return _check
