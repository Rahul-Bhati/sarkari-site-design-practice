"""Feed cache backed by Upstash Redis, with an in-process fallback.

Redis is optional: without UPSTASH_REDIS_URL the cache degrades to a small
in-memory dict, so local dev and tests need no extra service.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import settings

log = logging.getLogger(__name__)

_redis = None
_memory: dict[str, tuple[float, str]] = {}
_MEMORY_MAX = 500


def _client():
    global _redis
    if _redis is not None or not settings.upstash_redis_url:
        return _redis
    try:
        import redis

        _redis = redis.from_url(settings.upstash_redis_url, decode_responses=True)
        _redis.ping()
        log.info("Redis cache connected")
    except Exception as exc:
        log.warning("Redis unavailable, using in-memory cache: %s", exc)
        _redis = None
    return _redis


def get(key: str) -> Any | None:
    client = _client()
    if client is not None:
        try:
            raw = client.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:
            log.warning("cache get failed: %s", exc)
            return None

    hit = _memory.get(key)
    if not hit:
        return None
    expires_at, raw = hit
    if expires_at < time.time():
        _memory.pop(key, None)
        return None
    return json.loads(raw)


def set(key: str, value: Any, ttl: int | None = None) -> None:
    ttl = ttl or settings.feed_cache_ttl_seconds
    raw = json.dumps(value, default=str)

    client = _client()
    if client is not None:
        try:
            client.setex(key, ttl, raw)
            return
        except Exception as exc:
            log.warning("cache set failed: %s", exc)
            return

    if len(_memory) >= _MEMORY_MAX:
        _memory.clear()
    _memory[key] = (time.time() + ttl, raw)


def invalidate_feed() -> None:
    """Drop every cached feed/stats response. Called when an entry is approved."""
    client = _client()
    if client is not None:
        try:
            for pattern in ("feed:*", "entry:*", "stats"):
                for key in client.scan_iter(match=pattern, count=500):
                    client.delete(key)
            return
        except Exception as exc:
            log.warning("cache invalidate failed: %s", exc)
            return

    for key in [k for k in _memory if k.startswith(("feed:", "entry:", "stats"))]:
        _memory.pop(key, None)


def feed_key(**params: Any) -> str:
    parts = [f"{k}={params[k]}" for k in sorted(params) if params[k] not in (None, "", [])]
    return "feed:" + "|".join(parts)
