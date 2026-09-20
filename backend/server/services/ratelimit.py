"""Small fixed-window rate limiter (Redis, with in-process fallback).

Phase 1 protection against accidental rapid duplicate requests, not a
distributed abuse-prevention system.
"""

from __future__ import annotations

import time
from collections import defaultdict
from functools import lru_cache

import structlog

from server.core.config import get_settings
from server.core.errors import AppError, ErrorCode

log = structlog.get_logger(__name__)


class RateLimiter:
    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._local: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))

    def hit(self, bucket: str, subject: str, limit: int, window_seconds: int = 60) -> None:
        window = int(time.time() // window_seconds)
        key = f"rl:{bucket}:{subject}:{window}"
        count = self._incr(key, window, window_seconds)
        if count > limit:
            retry = window_seconds - int(time.time() % window_seconds)
            raise AppError(
                ErrorCode.RATE_LIMITED,
                "Too many requests. Please slow down.",
                429,
                headers={"Retry-After": str(retry)},
            )

    def _incr(self, key: str, window: int, ttl: int) -> int:
        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.incr(key)
                pipe.expire(key, ttl * 2)
                return int(pipe.execute()[0])
            except Exception:
                log.warning("rate_limit_redis_unavailable_falling_back")
        w, c = self._local[key]
        c = c + 1 if w == window else 1
        self._local[key] = (window, c)
        return c


@lru_cache
def get_redis():
    import redis

    return redis.Redis.from_url(
        get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True
    )


@lru_cache
def get_rate_limiter() -> RateLimiter:
    try:
        return RateLimiter(get_redis())
    except Exception:
        return RateLimiter(None)
