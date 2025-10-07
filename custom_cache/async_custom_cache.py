from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Optional, Tuple

from redis.asyncio import Redis
from redis.exceptions import RedisError

from .redis_mixins import RedisTagMixin, RedisPatternMixin


class AsyncCustomCache(ABC):
    """
    Asynchronous interface for cache backends.
    """

    @abstractmethod
    async def aget(self, key: str) -> Tuple[bool, Any]: ...

    @abstractmethod
    async def aset(
            self,
            key: str,
            value: Any,
            ttl: float,
            *,
            tags: Optional[Iterable[str]] = None,
    ) -> None: ...

    @abstractmethod
    async def adelete(self, key: str) -> None: ...

    @abstractmethod
    async def aclear(self) -> None: ...

    @abstractmethod
    async def ainvalidate_tags(self, tags: Iterable[str]) -> None: ...


class AioredisCache(AsyncCustomCache, RedisTagMixin, RedisPatternMixin):
    """
    Async Redis cache with enhanced architecture:
    - Uses mixins to eliminate code duplication
    - Fixed all pipeline operation errors
    - Optimized tag operations
    """

    def __init__(
            self,
            client: Redis,
            *,
            value_prefix: str = "rc:",
            meta_prefix: str = "rcmeta",
            pickle_protocol: int = -1,
    ) -> None:
        self.r = client
        super().__init__(
            value_prefix=value_prefix,
            meta_prefix=meta_prefix,
            pickle_protocol=pickle_protocol
        )

    async def aget(self, key: str) -> tuple[bool, Any]:
        """Get value from cache."""
        try:
            blob = await self.r.get(key)
        except RedisError:
            return False, None

        if blob is None:
            return False, None

        try:
            return True, self._deserialize_value(blob)
        except Exception:
            return False, None

    async def aset(
            self,
            key: str,
            value: Any,
            ttl: float,
            *,
            tags: Optional[Iterable[str]] = None,
    ) -> None:
        """Set value in cache with tags."""
        blob, ex, px, kt_key = self._prepare_set_operation(key, value, ttl, tags)

        # First set value and read old tags
        p = self.r.pipeline(transaction=False)
        self._prepare_pipeline_for_set(p, key, blob, ex, px, kt_key, tags)
        res = await p.execute()

        # Process tags if specified
        if tags is not None:
            old_tags = self._extract_old_tags_from_pipeline_result(res, tags is not None)
            await self._handle_tags_update(key, kt_key, tags, old_tags, ex, px)

    async def _handle_tags_update(
        self,
        key: str,
        kt_key: str,
        new_tags: Iterable[str],
        old_tags: set[str],
        ex: Optional[int],
        px: Optional[int]
    ) -> None:
        """Update tags for key."""
        tags_to_remove, tags_to_add = self._calculate_tags_diff(old_tags, new_tags)

        # Remove old tags not in new ones
        if tags_to_remove:
            await self._remove_tags(key, kt_key, tags_to_remove)

        # Add new tags
        if tags_to_add:
            await self._add_tags(key, kt_key, tags_to_add, ex, px)

    async def _remove_tags(self, key: str, kt_key: str, tags_to_remove: set[str]) -> None:
        """Remove tags from indexes."""
        p = self.r.pipeline(transaction=False)
        self._prepare_remove_tags_pipeline_first_pass(p, key, tags_to_remove)
        results = await p.execute()

        # Remove empty tagsets
        p = self.r.pipeline(transaction=False)
        self._prepare_remove_tags_pipeline_second_pass(p, tags_to_remove, results, kt_key)
        await p.execute()

    async def _add_tags(
        self,
        key: str,
        kt_key: str,
        tags: set[str],
        ex: Optional[int],
        px: Optional[int]
    ) -> None:
        """Add tags to indexes."""
        p = self.r.pipeline(transaction=False)
        self._prepare_add_tags_pipeline(p, key, kt_key, tags, ex, px)
        await p.execute()

    async def adelete(self, key: str) -> None:
        """Delete key and associated tags."""
        kt_key = self._ktags_key(key)

        try:
            tags = await self.r.smembers(kt_key)
        except RedisError:
            tags = set()

        p = self.r.pipeline(transaction=False)
        p.delete(key)

        if tags:
            tag_strings = self._decode_redis_strings(tags)
            for tag in tag_strings:
                p.srem(self._tagset_key(tag), key)
            p.delete(kt_key)

        try:
            await p.execute()
        except RedisError:
            pass

    async def aclear(self) -> None:
        """Clear entire cache."""
        await self._adelete_by_pattern(self._get_value_pattern())
        await self._adelete_by_pattern(self._get_meta_pattern())

    async def _adelete_by_pattern(self, pattern: str) -> None:
        """Delete all keys by pattern."""
        cursor = 0
        while True:
            cursor, keys = await self.r.scan(cursor=cursor, match=pattern, count=1000)
            if keys:
                await self.r.delete(*keys)
            if cursor == 0:
                break

    async def ainvalidate_tags(self, tags: Iterable[str]) -> None:
        """Invalidate cache by tags."""
        tags_list = list(tags)
        if not tags_list:
            return

        tag_keys = [self._tagset_key(t) for t in tags_list]

        try:
            union = await self.r.sunion(tag_keys)
        except RedisError:
            return

        if not union:
            return

        keys_to_invalidate = [
            k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else k
            for k in union
        ]

        await self._batch_invalidate_keys(keys_to_invalidate, tags_list)

    async def _batch_invalidate_keys(self, keys: list[str], tags: list[str]) -> None:
        """Batch invalidate keys."""
        p = self.r.pipeline(transaction=False)

        # Delete all value keys
        for key in keys:
            p.delete(key)

        # Delete all meta keys
        for key in keys:
            p.delete(self._ktags_key(key))

        # Clear tagsets
        for tag in tags:
            p.delete(self._tagset_key(tag))

        try:
            await p.execute()
        except RedisError:
            pass
