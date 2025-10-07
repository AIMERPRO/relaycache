import os
import pytest
import threading
from redis import Redis
from custom_cache import InMemoryCache
from custom_cache import RedisCache


@pytest.fixture
def mem_cache():
    return InMemoryCache(default_ttl=1.5)


@pytest.fixture(scope="session")
def redis_client():
    host = os.getenv("TEST_REDIS_HOST", "localhost")
    port = int(os.getenv("TEST_REDIS_PORT", "6379"))
    try:
        r = Redis(host=host, port=port, db=15, decode_responses=False, socket_connect_timeout=0.2)
        r.ping()
        return r
    except Exception:
        pytest.skip("Redis is not available on test host", allow_module_level=True)


@pytest.fixture
def redis_cache(redis_client):
    cache = RedisCache(redis_client, default_ttl=2.0, value_prefix="rc:test:", meta_prefix="rcmeta:test")
    cache.clear()
    yield cache
    cache.clear()