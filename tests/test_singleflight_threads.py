import threading
import time

from custom_cache import cache, InMemoryCache


def test_singleflight_threads():
    backend = InMemoryCache(default_ttl=1.0)
    calls = {"n": 0}

    @cache(ttl=0.5, backend=backend)
    def slow(x):
        calls["n"] += 1
        time.sleep(0.2)
        return x * 2

    results = []

    def worker():
        results.append(slow(10))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert results == [20] * 8
    # должно посчитаться ровно один раз
    assert calls["n"] == 1
