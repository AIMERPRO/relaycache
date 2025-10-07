import time

from custom_cache import cache


def test_basic_set_get(mem_cache):
    calls = {"n": 0}

    @cache(ttl=0.5, backend=mem_cache, tags=lambda x: [f"x:{x}"])
    def f(x):
        calls["n"] += 1
        return x * 2

    assert f(3) == 6
    assert f(3) == 6
    assert calls["n"] == 1

    # mapping API с коротким TTL
    mem_cache.set("k1", "v", ttl=0.5)  # Используем явный короткий TTL
    assert "k1" in mem_cache
    assert mem_cache["k1"] == "v"

    # TTL expiry
    time.sleep(0.6)
    # после TTL промах
    hit, _ = mem_cache.get("k1")
    assert not hit
    # __getitem__ теперь должен поднять KeyError
    try:
        _ = mem_cache["k1"]
        raise AssertionError("expected KeyError")
    except KeyError:
        pass


def test_none_value_cached(mem_cache):
    calls = {"n": 0}

    @cache(ttl=0.4, backend=mem_cache)
    def maybe_none(flag: bool):
        calls["n"] += 1
        return None if flag else 1

    assert maybe_none(True) is None
    assert maybe_none(True) is None
    assert calls["n"] == 1
    time.sleep(0.45)
    assert maybe_none(True) is None
    assert calls["n"] == 2
