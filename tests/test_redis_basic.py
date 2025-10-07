import pytest
from custom_cache import cache
from custom_cache import invalidate


@pytest.mark.integration
def test_redis_basic(redis_cache):
    calls = {"n": 0}

    @cache(ttl=1.0, backend=redis_cache, tags=lambda uid: [f"user:{uid}"])
    def load_user(uid: int):
        calls["n"] += 1
        return {"id": uid}

    assert load_user(42) == {"id": 42}
    assert load_user(42) == {"id": 42}
    assert calls["n"] == 1

    # invalidate другой тег — no-op
    invalidate(tags=["user:43"], backend=redis_cache)
    assert load_user(42) == {"id": 42}
    assert calls["n"] == 1

    # invalidate нужный тег — сброс
    invalidate(tags=["user:42"], backend=redis_cache)
    assert load_user(42) == {"id": 42}
    assert calls["n"] == 2


@pytest.mark.integration
def test_redis_mapping_and_contains(redis_cache):
    redis_cache["k"] = {"v": 1}  # default_ttl используется
    assert "k" in redis_cache
    assert redis_cache["k"] == {"v": 1}
