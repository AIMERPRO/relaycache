"""
RelayCache Examples
==================

This file contains practical examples of how to use RelayCache in various scenarios.
"""

import asyncio

import redis
from redis.asyncio import Redis as AsyncRedis

from custom_cache import cache, InMemoryCache, RedisCache, AioredisCache
from custom_cache import invalidate

# ==============================================================================
# Example 1: Basic In-Memory Caching
# ==============================================================================

print("=== Example 1: Basic In-Memory Caching ===")


@cache(ttl=5)  # Cache for 5 seconds
def fibonacci(n):
    """Compute fibonacci number with caching."""
    print(f"Computing fibonacci({n})")
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


# First call - will compute
result1 = fibonacci(10)
print(f"First call: {result1}")

# Second call - from cache
result2 = fibonacci(10)
print(f"Second call: {result2}")

# ==============================================================================
# Example 2: Redis Backend with Tags
# ==============================================================================

print("\n=== Example 2: Redis Backend with Tags ===")

# Setup Redis backend
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=15, decode_responses=False)
    redis_client.ping()
    redis_backend = RedisCache(
        redis_client,
        default_ttl=3600,
        value_prefix="example:",
        meta_prefix="example:meta"
    )


    @cache(ttl=300, backend=redis_backend, tags=lambda user_id: [f"user:{user_id}", "users"])
    def get_user_profile(user_id):
        """Simulate fetching user profile from database."""
        print(f"Fetching user profile for user {user_id}")
        return {
            "id": user_id,
            "name": f"User {user_id}",
            "email": f"user{user_id}@example.com",
            "created_at": "2025-01-01"
        }


    # Get user profiles
    profile1 = get_user_profile(123)
    profile2 = get_user_profile(456)
    print(f"User 123: {profile1}")
    print(f"User 456: {profile2}")

    # Get from cache
    profile1_cached = get_user_profile(123)
    print(f"User 123 (cached): {profile1_cached}")

    # Invalidate specific user
    invalidate(tags=[f"user:123"], backend=redis_backend)
    print("Invalidated user 123")

    # This will fetch from database again
    profile1_fresh = get_user_profile(123)
    print(f"User 123 (fresh): {profile1_fresh}")

    # Clean up
    redis_backend.clear()

except Exception as e:
    print(f"Redis not available: {e}")

# ==============================================================================
# Example 3: Async Redis with Distributed Singleflight
# ==============================================================================

print("\n=== Example 3: Async Redis with Distributed Singleflight ===")


async def async_example():
    try:
        # Setup async Redis
        async_redis = AsyncRedis(host='localhost', port=6379, db=15)
        await async_redis.ping()

        async_backend = AioredisCache(
            async_redis,
            default_ttl=3600,
            value_prefix="async_example:",
            meta_prefix="async_example:meta"
        )

        @cache(
            ttl=300,
            backend=async_backend,
            tags=["expensive_computation"],
            distributed_singleflight=True,  # Prevent multiple processes from computing same value
            dist_lock_ttl=10.0,
            dist_lock_timeout=5.0
        )
        async def expensive_async_computation(x):
            """Simulate expensive async computation."""
            print(f"Computing expensive operation for {x}")
            await asyncio.sleep(2)  # Simulate work
            return x ** 2 + 42

        # Multiple concurrent calls - only one will compute
        tasks = [expensive_async_computation(100) for _ in range(5)]
        results = await asyncio.gather(*tasks)
        print(f"Results: {results}")

        # Clean up
        await async_backend.aclear()
        await async_redis.aclose()

    except Exception as e:
        print(f"Async Redis not available: {e}")


# Run async example
asyncio.run(async_example())

# ==============================================================================
# Example 4: Custom Key Building
# ==============================================================================

print("\n=== Example 4: Custom Key Building ===")

from custom_cache import KeyBuilder

# Custom key builder with namespace
kb = KeyBuilder(prefix="myapp", namespace="v1")


@cache(ttl=60, key_builder=kb, tags=["calculations"])
def calculate_area(length, width, unit="m"):
    """Calculate area with custom key building."""
    print(f"Calculating area: {length} x {width} {unit}")
    return length * width


# Custom key function
@cache(ttl=60, key=lambda name, age: f"person:{name}:{age}")
def create_person(name, age):
    """Create person with custom key."""
    print(f"Creating person: {name}, {age}")
    return {"name": name, "age": age, "id": hash(f"{name}{age}")}


area1 = calculate_area(10, 20)
area2 = calculate_area(10, 20)  # From cache
print(f"Area: {area1}")

person1 = create_person("Alice", 30)
person2 = create_person("Alice", 30)  # From cache
print(f"Person: {person1}")

# ==============================================================================
# Example 5: Manual Cache Management
# ==============================================================================

print("\n=== Example 5: Manual Cache Management ===")

# Create cache backend
manual_cache = InMemoryCache(default_ttl=300)

# Manual operations
manual_cache.set("product:123", {"name": "Laptop", "price": 999}, ttl=60, tags=["products", "electronics"])
manual_cache.set("product:456", {"name": "Mouse", "price": 25}, ttl=60, tags=["products", "electronics"])
manual_cache.set("user:789", {"name": "John"}, ttl=60, tags=["users"])

# Get values
hit, laptop = manual_cache.get("product:123")
if hit:
    print(f"Found laptop: {laptop}")

# Check if key exists
if "product:456" in manual_cache:
    print("Mouse is in cache")

# Get cache statistics
stats = manual_cache.stats()
print(f"Cache stats: {stats}")

# Invalidate by tags
manual_cache.invalidate_tags(["electronics"])
print("Invalidated electronics")

# Check what's left
hit, laptop_after = manual_cache.get("product:123")
hit, user_after = manual_cache.get("user:789")
print(f"Laptop after invalidation: {hit}")
print(f"User after invalidation: {hit}")

# ==============================================================================
# Example 6: Error Handling and Fallbacks
# ==============================================================================

print("\n=== Example 6: Error Handling and Fallbacks ===")


def unreliable_cache_backend():
    """Simulate unreliable cache backend."""
    # This would normally be your Redis instance
    return InMemoryCache(default_ttl=60)


@cache(ttl=300, backend=unreliable_cache_backend())
def robust_function(x):
    """Function that works even if cache fails."""
    print(f"Computing robust function for {x}")
    return x * 2 + 1


try:
    result1 = robust_function(42)
    result2 = robust_function(42)  # From cache
    print(f"Robust function results: {result1}, {result2}")
except Exception as e:
    print(f"Cache error (but function still works): {e}")
    # Function would still execute without cache

print("\n=== All examples completed! ===")
