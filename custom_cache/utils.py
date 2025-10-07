from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from contextlib import contextmanager
from typing import Dict, Optional, Iterable, Any, Union
from uuid import uuid4

from redis import Redis, RedisError

from . import AsyncRedisKeyLock
from .async_custom_cache import AsyncCustomCache, AioredisCache
from .custom_cache import CustomCache, default_backend, RedisCache


class Singleflight:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: Dict[str, threading.Lock] = {}

    def get_lock(self, key: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    @contextmanager
    def for_key(self, key: str):
        lock = self.get_lock(key)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def reset(self) -> None:
        with self._guard:
            self._locks.clear()


class AsyncSingleflight:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks_by_loop: Dict[int, Dict[str, asyncio.Lock]] = {}

    def _per_loop(self) -> Dict[str, asyncio.Lock]:
        loop = asyncio.get_running_loop()
        lid = id(loop)
        with self._guard:
            d = self._locks_by_loop.get(lid)
            if d is None:
                d = {}
                self._locks_by_loop[lid] = d
            return d

    def get_lock(self, key: str) -> asyncio.Lock:
        d = self._per_loop()
        lock = d.get(key)
        if lock is None:
            lock = asyncio.Lock()
            d[key] = lock
        return lock

    async def for_key(self, key: str):
        lock = self.get_lock(key)
        return _AsyncLockCtx(lock)

    def reset(self) -> None:
        with self._guard:
            self._locks_by_loop.clear()


class _AsyncLockCtx:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock

    async def __aenter__(self):
        await self._lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._lock.release()


def resolve_tags(tags, args, kwargs) -> Optional[Any]:
    if tags is None:
        return None
    if callable(tags):
        try:
            return tags(*args, **kwargs)
        except TypeError:
            return tags(*args, **kwargs)
    return tags


def invalidate(*, tags: Iterable[str], backend: Optional[CustomCache] = None) -> None:
    """
    Synchronous tag-based invalidation (OR semantics).
    For async backends use `ainvalidate(...)`.
    """
    store = backend or default_backend
    if isinstance(store, AsyncCustomCache):
        raise TypeError("Async backend detected. Use `await ainvalidate(tags=..., backend=...)`.")
    store.invalidate_tags(tags)  # type: ignore[union-attr]


async def ainvalidate(*, tags: Iterable[str], backend: Optional[AsyncCustomCache] = None) -> None:
    """
    Asynchronous tag-based invalidation for async backends.
    """
    if backend is None:
        raise ValueError("Async invalidation requires explicit async backend.")
    if not isinstance(backend, AsyncCustomCache):
        raise TypeError("Backend is not async. Use `invalidate(...)` instead.")
    await backend.ainvalidate_tags(tags)


def hash_short(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


RELEASE_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
else
  return 0
end
"""


class RedisKeyLock:
    """
    Simple distributed lock by key:
    - acquire(): SET lock_key token NX PX ttl_ms with retries until timeout_sec
    - release(): Lua script deletes lock only if token matches
    """

    def __init__(self, r: Redis, lock_key: str, ttl_ms: int, timeout_sec: float) -> None:
        self.r = r
        self.lock_key = lock_key
        self.ttl_ms = int(max(1, ttl_ms))
        self.timeout_sec = float(max(0.001, timeout_sec))
        self.token: Optional[str] = None

    def acquire(self) -> bool:
        token = uuid4().hex
        deadline = time.monotonic() + self.timeout_sec
        while True:
            try:
                ok = self.r.set(self.lock_key, token, nx=True, px=self.ttl_ms)
            except RedisError:
                return False
            if ok:
                self.token = token
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def release(self) -> None:
        if not self.token:
            return
        try:
            self.r.eval(RELEASE_LUA, 1, self.lock_key, self.token)
        except RedisError:
            pass
        finally:
            self.token = None


BackendT = Union[CustomCache, AsyncCustomCache]


def make_sync_redis_lock(store: BackendT, cache_key: str, dist_lock_ttl: float, dist_lock_timeout: float):
    if RedisCache is None or RedisKeyLock is None:
        return None
    if not isinstance(store, RedisCache):
        return None
    lock_key = f"{store.meta_prefix}:lock:{hash_short(cache_key)}"
    return RedisKeyLock(store.r, lock_key, ttl_ms=int(dist_lock_ttl * 1000), timeout_sec=dist_lock_timeout)


def make_async_redis_lock(store: BackendT, cache_key: str, dist_lock_ttl: float, dist_lock_timeout: float):
    if AioredisCache is None or AsyncRedisKeyLock is None:
        return None
    if not isinstance(store, AioredisCache):
        return None
    lock_key = f"{store.meta_prefix}:lock:{hash_short(cache_key)}"
    return AsyncRedisKeyLock(store.r, lock_key, ttl_ms=int(dist_lock_ttl * 1000), timeout_sec=dist_lock_timeout)
