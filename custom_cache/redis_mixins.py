from __future__ import annotations

import hashlib
import pickle
from typing import Any, Iterable, Optional, Set, Union, Tuple

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError


class RedisTagMixin:
    """
    Common logic for working with tags in Redis (sync/async).
    Provides helper methods for building keys and TTL.
    """

    def __init__(
        self,
        *,
        value_prefix: str = "rc:",
        meta_prefix: str = "rcmeta",
        pickle_protocol: int = pickle.HIGHEST_PROTOCOL,
    ) -> None:
        self.value_prefix = value_prefix.rstrip(":") + ":"
        self.meta_prefix = meta_prefix.rstrip(":")
        self.pickle_protocol = pickle_protocol

    def _ktags_key(self, value_key: str) -> str:
        """Key for storing tags of a specific cache key."""
        h = hashlib.sha1(value_key.encode("utf-8")).hexdigest()
        return f"{self.meta_prefix}:kt:{h}"

    def _tagset_key(self, tag: str) -> str:
        """Key for storing set of keys with a specific tag."""
        return f"{self.meta_prefix}:tag:{tag}"

    def _calculate_ttl(self, ttl: float) -> tuple[Optional[int], Optional[int]]:
        """Calculate ex/px parameters for Redis SET command."""
        if ttl >= 1:
            return int(round(ttl)), None
        else:
            return None, int(round(ttl * 1000))

    def _serialize_value(self, value: Any) -> bytes:
        """Serialize value for Redis storage."""
        return pickle.dumps(value, protocol=self.pickle_protocol)

    def _deserialize_value(self, blob: bytes) -> Any:
        """Deserialize value from Redis."""
        return pickle.loads(blob)

    def _decode_redis_strings(self, items: Set[bytes]) -> Set[str]:
        """Decode strings from Redis (bytes -> str)."""
        return {b.decode("utf-8") for b in items} if items else set()

    def _validate_ttl(self, ttl: float) -> None:
        """Validate TTL parameter."""
        if ttl is None or ttl <= 0:
            raise ValueError("ttl must be a positive number (seconds)")

    def _prepare_set_operation(
        self,
        key: str,
        value: Any,
        ttl: float,
        tags: Optional[Iterable[str]],
    ) -> Tuple[bytes, Optional[int], Optional[int], str]:
        """Prepare data for SET operation."""
        self._validate_ttl(ttl)

        blob = self._serialize_value(value)
        ex, px = self._calculate_ttl(ttl)
        kt_key = self._ktags_key(key)

        return blob, ex, px, kt_key

    def _prepare_pipeline_for_set(
        self,
        pipeline,
        key: str,
        blob: bytes,
        ex: Optional[int],
        px: Optional[int],
        kt_key: str,
        tags: Optional[Iterable[str]]
    ):
        """Prepare pipeline for SET operation with reading old tags."""
        pipeline.set(name=key, value=blob, ex=ex, px=px)
        if tags is not None:
            pipeline.smembers(kt_key)

    def _extract_old_tags_from_pipeline_result(
        self,
        pipeline_result: list,
        has_tags: bool
    ) -> set[str]:
        """Extract old tags from pipeline result."""
        old_tags = set()
        if has_tags and len(pipeline_result) >= 2 and isinstance(pipeline_result[1], set):
            old_tags = self._decode_redis_strings(pipeline_result[1])
        return old_tags

    def _prepare_add_tags_pipeline(
        self,
        pipeline,
        key: str,
        kt_key: str,
        tags: set[str],
        ex: Optional[int],
        px: Optional[int]
    ):
        """Prepare pipeline for adding tags."""
        for tag in tags:
            pipeline.sadd(self._tagset_key(tag), key)

        pipeline.sadd(kt_key, *list(tags))

        # Set TTL for tags key
        if ex is not None:
            pipeline.expire(kt_key, ex)
        elif px is not None:
            pipeline.pexpire(kt_key, px)

    def _prepare_remove_tags_pipeline_first_pass(
        self,
        pipeline,
        key: str,
        tags_to_remove: set[str]
    ):
        """First pass of tag removal - remove key from tagsets and count sizes."""
        for tag in tags_to_remove:
            tagset_key = self._tagset_key(tag)
            pipeline.srem(tagset_key, key)
            pipeline.scard(tagset_key)

    def _prepare_remove_tags_pipeline_second_pass(
        self,
        pipeline,
        tags_to_remove: set[str],
        results: list,
        kt_key: str
    ):
        """Second pass of tag removal - remove empty tagsets."""
        for i, tag in enumerate(tags_to_remove):
            scard_idx = i * 2 + 1  # scard results come after srem
            if scard_idx < len(results) and results[scard_idx] == 0:
                pipeline.delete(self._tagset_key(tag))

        if tags_to_remove:
            pipeline.delete(kt_key)

    def _calculate_tags_diff(self, old_tags: set[str], new_tags: Iterable[str]) -> tuple[set[str], set[str]]:
        """Calculate difference between old and new tags."""
        new_tags_set = set(new_tags)
        tags_to_remove = old_tags - new_tags_set
        tags_to_add = new_tags_set - old_tags
        return tags_to_remove, tags_to_add


class RedisPatternMixin:
    """
    Common logic for working with Redis key patterns.
    """

    def _get_value_pattern(self) -> str:
        """Pattern for finding all value keys."""
        return f"{self.value_prefix}*"

    def _get_meta_pattern(self) -> str:
        """Pattern for finding all meta keys."""
        return f"{self.meta_prefix}:*"


class RedisLockMixin:
    """
    Common logic for building lock keys.
    """

    def _lock_key(self, cache_key: str) -> str:
        """Key for distributed lock."""
        h = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()
        return f"{self.meta_prefix}:lock:{h}"
