from __future__ import annotations

import asyncio
from typing import Optional
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError


_RELEASE_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
else
  return 0
end
"""


class AsyncRedisKeyLock:
    """
    Simple distributed async lock by key.
    - acquire(): SET lock_key token NX PX ttl_ms with retries until timeout_sec
    - release(): deletes lock only if token matches (Lua)
    - supports async with
    """

    def __init__(self, r: Redis, lock_key: str, ttl_ms: int, timeout_sec: float) -> None:
        self.r = r
        self.lock_key = lock_key
        self.ttl_ms = max(1, int(ttl_ms))
        self.timeout_sec = max(0.001, float(timeout_sec))
        self.token: Optional[str] = None

    async def acquire(self) -> bool:
        token = uuid4().hex
        deadline = asyncio.get_running_loop().time() + self.timeout_sec
        while True:
            try:
                ok = await self.r.set(self.lock_key, token, nx=True, px=self.ttl_ms)
            except RedisError:
                return False
            if ok:
                self.token = token
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.01)  # light backoff

    async def release(self) -> None:
        if not self.token:
            return
        try:
            await self.r.eval(_RELEASE_LUA, 1, self.lock_key, self.token)
        except RedisError:
            pass
        finally:
            self.token = None

    async def __aenter__(self):
        ok = await self.acquire()
        if not ok:
            raise TimeoutError("Failed to acquire distributed lock in time")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.release()
