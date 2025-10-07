<div align="center">
  
# 🚀 RelayCache

<p align="center">
  <em>⚡ Universal caching library for Python with sync/async support, tagging, singleflight pattern and distributed locks</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/relaycache/">
    <img src="https://img.shields.io/pypi/v/relaycache.svg" alt="PyPI version">
  </a>
  <a href="https://pypi.org/project/relaycache/">
    <img src="https://img.shields.io/pypi/pyversions/relaycache.svg" alt="Python versions">
  </a>
  <a href="https://github.com/AIMERPRO/relaycache">
    <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License">
  </a>
  <a href="https://github.com/AIMERPRO/relaycache">
    <img src="https://img.shields.io/github/stars/AIMERPRO/relaycache?style=social" alt="GitHub stars">
  </a>
</p>

<p align="center">
  <a href="#features">✨ Features</a> •
  <a href="#installation">📦 Installation</a> •
  <a href="#quick-start">🚀 Quick Start</a> •
  <a href="#documentation">📖 Docs</a> •
  <a href="#examples">💡 Examples</a>
</p>

</div>

---

## ✨ Features

- 🔄 **Universal API**: Works with both sync and async code
- 🗄️ **Multiple backends**: In-memory, Redis, async Redis
- 🏷️ **Cache tagging**: Group and invalidate related cache entries
- ⚡ **Singleflight**: Prevent thundering herd with automatic deduplication
- 🔒 **Distributed locks**: Cross-process coordination via Redis
- ⏰ **TTL support**: Automatic expiration of cache entries
- 🎯 **Type hints**: Full typing support

## Installation

```bash
pip install relaycache
```

For development:
```bash
pip install relaycache[dev]
```

## Quick Start

### Basic Usage

```python
from custom_cache import cache, InMemoryCache

# Use with default in-memory backend
@cache(ttl=300)  # Cache for 5 minutes
def expensive_function(x, y):
    # Some expensive computation
    return x * y + 42

result = expensive_function(10, 20)  # Computed
result = expensive_function(10, 20)  # From cache
```

### Redis Backend

```python
import redis
from custom_cache import cache, RedisCache

# Setup Redis backend
redis_client = redis.Redis(host='localhost', port=6379, db=0)
redis_backend = RedisCache(redis_client, default_ttl=3600)

@cache(ttl=1800, backend=redis_backend, tags=["users"])
def get_user_profile(user_id):
    # Fetch from database
    return {"id": user_id, "name": "John", "email": "john@example.com"}

# Usage
profile = get_user_profile(123)
```

### Async Support

```python
import asyncio
from redis.asyncio import Redis
from custom_cache import cache, AioredisCache

# Setup async Redis backend
async def main():
    redis_client = Redis(host='localhost', port=6379, db=0)
    async_backend = AioredisCache(redis_client, default_ttl=3600)

    @cache(ttl=1800, backend=async_backend, tags=["posts"])
    async def get_post(post_id):
        # Async database call
        await asyncio.sleep(0.1)
        return {"id": post_id, "title": "Sample Post"}

    post = await get_post(456)  # Computed
    post = await get_post(456)  # From cache

asyncio.run(main())
```

## Advanced Features

### Cache Tagging and Invalidation

```python
from custom_cache import cache, invalidate

@cache(ttl=3600, tags=lambda user_id: [f"user:{user_id}", "users"])
def get_user_data(user_id):
    return fetch_user_from_db(user_id)

# Invalidate specific user
invalidate(tags=[f"user:{user_id}"])

# Invalidate all users  
invalidate(tags=["users"])
```

### Distributed Singleflight

Prevent multiple processes from computing the same value simultaneously:

```python
@cache(
    ttl=1800, 
    backend=redis_backend,
    distributed_singleflight=True,  # Enable distributed coordination
    dist_lock_ttl=5.0,             # Lock TTL in seconds
    dist_lock_timeout=2.0          # Lock acquisition timeout
)
def expensive_computation(key):
    # Only one process will execute this at a time per key
    time.sleep(10)  # Simulate expensive work
    return f"result_for_{key}"
```

### Custom Key Building

```python
from custom_cache import cache, KeyBuilder

# Custom key builder
kb = KeyBuilder(prefix="myapp", namespace="v1")

@cache(ttl=3600, key_builder=kb)
def my_function(arg1, arg2):
    return arg1 + arg2

# Or custom key function
@cache(ttl=3600, key=lambda x, y: f"sum:{x}:{y}")
def sum_function(x, y):
    return x + y
```

### Manual Cache Management

```python
from custom_cache import InMemoryCache

cache_backend = InMemoryCache(default_ttl=3600)

# Manual operations
cache_backend.set("key1", "value1", ttl=1800, tags=["group1"])
hit, value = cache_backend.get("key1")

if hit:
    print(f"Found: {value}")

# Delete specific key
cache_backend.delete("key1")

# Clear all cache
cache_backend.clear()

# Invalidate by tags
cache_backend.invalidate_tags(["group1"])
```

## Backends

### InMemoryCache (Sync/Async)

Fast in-process cache with thread safety:

```python
from custom_cache import InMemoryCache

backend = InMemoryCache(default_ttl=3600)

# Features:
# - Thread-safe operations
# - Automatic TTL expiration
# - Tag support
# - Memory efficient
```

### RedisCache (Sync)

Redis-based cache for distributed applications:

```python
import redis
from custom_cache import RedisCache

redis_client = redis.Redis(host='localhost', port=6379, db=0)
backend = RedisCache(
    redis_client,
    default_ttl=3600,
    value_prefix="myapp:",
    meta_prefix="myapp:meta"
)

# Features:
# - Distributed caching
# - Persistent storage
# - Tag-based invalidation
# - Distributed locks
```

### AioredisCache (Async)

Async Redis cache for high-performance async applications:

```python
from redis.asyncio import Redis
from custom_cache import AioredisCache

redis_client = Redis(host='localhost', port=6379, db=0)
backend = AioredisCache(
    redis_client,
    default_ttl=3600,
    value_prefix="myapp:",
    meta_prefix="myapp:meta"
)

# Features:
# - Non-blocking operations
# - High concurrency
# - Async/await support
# - All Redis features
```

## Error Handling

```python
from custom_cache import cache
from redis.exceptions import RedisError

@cache(ttl=1800, backend=redis_backend)
def robust_function(x):
    # Cache failures won't break your app
    return expensive_computation(x)

try:
    result = robust_function(42)
except RedisError:
    # Redis is down, function still works
    result = expensive_computation(42)
```

## Django Integration

```python
# settings.py
import redis
from custom_cache import RedisCache

REDIS_CLIENT = redis.Redis(host='localhost', port=6379, db=0)
CACHE_BACKEND = RedisCache(REDIS_CLIENT, default_ttl=3600)

# views.py
from django.conf import settings
from custom_cache import cache

@cache(backend=settings.CACHE_BACKEND, ttl=1800, tags=["articles"])
def get_article_list():
    return list(Article.objects.all().values())

# Invalidate on model changes
from django.db.models.signals import post_save
from custom_cache.utils import invalidate

@receiver(post_save, sender=Article)
def invalidate_articles(sender, **kwargs):
    invalidate(tags=["articles"], backend=settings.CACHE_BACKEND)
```

## Performance Tips

1. **Choose the right backend**: InMemory for single-process, Redis for distributed
2. **Use appropriate TTL**: Balance between freshness and performance
3. **Tag strategically**: Group related data for efficient invalidation
4. **Enable singleflight**: For expensive computations with high concurrency
5. **Monitor cache hit rates**: Use backend statistics methods

## API Reference

### @cache decorator

```python
@cache(
    ttl: float,                                    # Cache TTL in seconds
    key: Optional[Callable] = None,                # Custom key function
    namespace: Optional[str] = None,               # Key namespace
    backend: Optional[Backend] = None,             # Cache backend
    key_builder: Optional[KeyBuilder] = None,      # Custom key builder
    tags: Optional[Union[List, Callable]] = None,  # Cache tags
    distributed_singleflight: bool = False,       # Enable distributed locks
    dist_lock_ttl: float = 5.0,                   # Lock TTL
    dist_lock_timeout: float = 2.0                # Lock timeout
)
```

### Backend Methods

All backends implement:
- `get(key) -> (hit: bool, value: Any)`
- `set(key, value, ttl, *, tags=None)`
- `delete(key)`
- `clear()`
- `invalidate_tags(tags)`

Async backends also provide:
- `aget(key)`, `aset(...)`, `adelete(key)`, `aclear()`, `ainvalidate_tags(...)`

## Requirements

- Python 3.8+
- redis-py 4.0+

## License

MIT License. See LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Run the test suite: `pytest`
5. Submit a pull request

## Changelog

### 0.1.1
- Added `default_ttl` parameter to `AioredisCache` for API consistency
- All backends now have unified constructor interface
- Added `__setitem__` method to `AioredisCache` for `cache[key] = value` syntax

### 0.1.0
- Initial release
- Sync/async cache support
- Redis and in-memory backends
- Cache tagging
- Singleflight pattern
- Distributed locks
