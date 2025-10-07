from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, Optional, Iterable

from .async_custom_cache import AsyncCustomCache
from .custom_cache import default_backend
from .key_builder import KeyBuilder
from .utils import Singleflight, AsyncSingleflight, resolve_tags, BackendT, \
    make_async_redis_lock, make_sync_redis_lock

singleflight = Singleflight()
async_singleflight = AsyncSingleflight()


def cache(
        ttl: Optional[float] = None,
        *,
        key: Optional[Callable[..., str]] = None,
        namespace: Optional[str] = None,
        backend: Optional[BackendT] = None,
        key_builder: Optional[KeyBuilder] = None,
        tags: Optional[Iterable[str] | Callable[..., Iterable[str]]] = None,
        distributed_singleflight: bool = False,
        dist_lock_ttl: float = 5.0,
        dist_lock_timeout: float = 2.0,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Cache decorator with support for sync/async functions and backends.

    Args:
        ttl: Required, > 0 (seconds)
        key: Custom key building function (otherwise KeyBuilder)
        namespace: Prefix for KeyBuilder
        backend: CustomCache (sync) or AsyncCustomCache (async)
        tags: Iterable or callable(*args, **kwargs) -> iterable
        distributed_singleflight: Cross-process coordination (Redis lock)
        dist_lock_ttl: Distributed lock TTL in seconds
        dist_lock_timeout: Distributed lock timeout in seconds
    """
    if ttl is None or ttl <= 0:
        raise ValueError("ttl must be a positive number (seconds)")

    store: BackendT = backend or default_backend
    kb = key_builder or KeyBuilder()

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        # -------------------- ASYNC FUNCTION --------------------
        if inspect.iscoroutinefunction(func):
            is_async_backend = isinstance(store, AsyncCustomCache)

            @functools.wraps(func)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                k = key(*args, **kwargs) if key else kb.build(func, args, kwargs, namespace)

                async def _lookup():
                    if is_async_backend:
                        return await store.aget(k)
                    else:
                        return store.get(k)

                async def _compute_and_set():
                    result = await func(*args, **kwargs)
                    t = resolve_tags(tags, args, kwargs)
                    if is_async_backend:
                        await store.aset(k, result, ttl=ttl, tags=t)
                    else:
                        store.set(k, result, ttl=ttl, tags=t)
                    return result

                hit, value = await _lookup()
                if hit:
                    return value

                async with (await async_singleflight.for_key(k)):
                    hit, value = await _lookup()
                    if hit:
                        return value

                    if distributed_singleflight:
                        arlock = make_async_redis_lock(store, k, dist_lock_ttl, dist_lock_timeout)
                        if arlock:
                            if not await arlock.acquire():
                                hit, value = await _lookup()
                                return value if hit else await _compute_and_set()
                            try:
                                hit, value = await _lookup()
                                return value if hit else await _compute_and_set()
                            finally:
                                await arlock.release()

                    return await _compute_and_set()

            return awrapper

        # -------------------- SYNC FUNCTION --------------------
        else:
            if isinstance(store, AsyncCustomCache):
                raise TypeError(
                    "Async cache backend cannot be used with a sync function. "
                    "Use an async function or provide a sync backend."
                )

            @functools.wraps(func)
            def swrapper(*args: Any, **kwargs: Any) -> Any:
                k = key(*args, **kwargs) if key else kb.build(func, args, kwargs, namespace)

                def _lookup():
                    return store.get(k)

                def _compute_and_set():
                    result = func(*args, **kwargs)
                    t = resolve_tags(tags, args, kwargs)
                    store.set(k, result, ttl=ttl, tags=t)
                    return result

                hit, value = _lookup()
                if hit:
                    return value

                with singleflight.for_key(k):
                    hit, value = _lookup()
                    if hit:
                        return value

                    if distributed_singleflight:
                        rlock = make_sync_redis_lock(store, k, dist_lock_ttl, dist_lock_timeout)
                        if rlock:
                            if not rlock.acquire():
                                hit, value = _lookup()
                                return value if hit else _compute_and_set()
                            try:
                                hit, value = _lookup()
                                return value if hit else _compute_and_set()
                            finally:
                                rlock.release()

                    return _compute_and_set()

            return swrapper

    return decorator
