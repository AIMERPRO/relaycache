import asyncio

import pytest
from redis.asyncio import Redis

from custom_cache import AioredisCache
from custom_cache import cache


@pytest.mark.asyncio
async def test_aioredis_cache_basic():
    r = Redis(host="localhost", port=6379, db=14, decode_responses=False)
    try:
        await r.ping()
    except Exception:
        pytest.skip("redis not available")

    backend = AioredisCache(r, value_prefix="rc:test:", meta_prefix="rcmeta:test")
    await backend.aclear()

    calls = {"n": 0}

    @cache(ttl=1.0, backend=backend, tags=lambda x: [f"x:{x}"])
    async def f(x: int):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return x * 2

    res = await asyncio.gather(*[f(10) for _ in range(5)])
    assert res == [20] * 5
    assert calls["n"] == 1

    # invalidate по тегу
    await backend.ainvalidate_tags(["x:10"])
    res2 = await f(10)
    assert res2 == 20
    assert calls["n"] == 2

    await backend.aclear()
    await r.aclose()
