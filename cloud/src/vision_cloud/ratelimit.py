"""Token-bucket rate limits (per device for ingest, per account for sign-in).

Redis-backed when `VISION_REDIS_URL` is set, so every API worker shares one bucket; otherwise an
in-process limiter (development and tests).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Decision:
    allowed: bool
    retry_after_s: float = 0.0


class RateLimiter(Protocol):
    def hit(self, key: str, rate_per_min: float, burst: int, cost: float = 1.0) -> Decision: ...


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, rate_per_min: float, burst: int, cost: float = 1.0) -> Decision:
        rate = rate_per_min / 60.0
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(burst), now))
            tokens = min(float(burst), tokens + (now - last) * rate)
            if tokens >= cost:
                self._buckets[key] = (tokens - cost, now)
                return Decision(True)
            self._buckets[key] = (tokens, now)
            return Decision(False, retry_after_s=(cost - tokens) / rate)


_LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1]) or burst
local ts = tonumber(state[2]) or now
tokens = math.min(burst, tokens + (now - ts) * rate)
local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(burst / rate) + 60)
return {allowed, tostring(tokens)}
"""


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        import redis

        self._redis: Any = redis.Redis.from_url(url)
        self._script = self._redis.register_script(_LUA)

    def hit(self, key: str, rate_per_min: float, burst: int, cost: float = 1.0) -> Decision:
        rate = rate_per_min / 60.0
        allowed, tokens = self._script(
            keys=[f"ratelimit:{key}"], args=[rate, burst, cost, time.time()]
        )
        if int(allowed):
            return Decision(True)
        return Decision(False, retry_after_s=(cost - float(tokens)) / rate)


def make_limiter(redis_url: str | None) -> RateLimiter:
    return RedisRateLimiter(redis_url) if redis_url else MemoryRateLimiter()
