import asyncio
import pytest
import hashlib
from redis.asyncio import Redis
from custom_cache import AioredisCache, cache, AsyncRedisKeyLock, KeyBuilder


@pytest.mark.asyncio
async def test_distributed_singleflight_with_async_lock():
    r = Redis(host="localhost", port=6379, db=13, decode_responses=False)
    try:
        await r.ping()
    except Exception:
        pytest.skip("redis not available")

    backend = AioredisCache(r, value_prefix="rc:test:", meta_prefix="rcmeta:test")
    await backend.aclear()

    calls = {"n": 0}

    @cache(ttl=1.0, backend=backend, distributed_singleflight=True, dist_lock_ttl=1.0, dist_lock_timeout=0.5)
    async def heavy(x: int):
        calls["n"] += 1
        await asyncio.sleep(0.2)
        return x * 2

    kb = KeyBuilder()
    key = kb.build(heavy, (10,), {}, None)

    lock_key = f"{backend.meta_prefix}:lock:__test__"
    # используем тот же формат, что и в декораторе (с sha1), но для простоты в тесте жёстко:
    # лучше повторить логику: из decorators._hash_short(key)
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    lock_key = f"{backend.meta_prefix}:lock:{h}"

    arlock = AsyncRedisKeyLock(r, lock_key, ttl_ms=1500, timeout_sec=0.05)
    assert await arlock.acquire()  # держим лок

    # Запускаем два конкурентных запроса: один будет ждать чужой лок и не посчитает второй раз
    t1 = asyncio.create_task(heavy(10))
    await asyncio.sleep(0.05)  # дать heavy зайти и упереться в распределённый лок
    # отпускаем лок — теперь heavy должен продолжить
    await arlock.release()
    t2 = asyncio.create_task(heavy(10))

    res = await asyncio.gather(t1, t2)
    assert res == [20, 20]
    assert calls["n"] == 1

    await backend.aclear()
    await r.aclose()