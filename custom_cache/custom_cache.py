from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from redis import Redis
from redis.exceptions import RedisError

from .redis_mixins import RedisTagMixin, RedisPatternMixin


class CustomCache(ABC):
    """
    Base interface for cache backends.
    """

    @abstractmethod
    def get(self, key: str) -> Tuple[bool, Any]: ...

    @abstractmethod
    def set(
            self,
            key: str,
            value: Any,
            ttl: float,
            *,
            tags: Optional[Iterable[str]] = None,
    ) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    def invalidate_tags(self, tags: Iterable[str]) -> None: ...


class InMemoryCache(CustomCache):
    """
    Enhanced in-memory cache with thread safety.
    """

    def __init__(self, *, default_ttl: float) -> None:
        if default_ttl <= 0:
            raise ValueError("default_ttl must be > 0 seconds")

        self.default_ttl = float(default_ttl)
        self._data: Dict[str, Tuple[Optional[float], bytes]] = {}
        self._lock = threading.RLock()  # Use RLock for recursive calls
        self._tag_index: Dict[str, Set[str]] = {}
        self._key_tags: Dict[str, Set[str]] = {}

    @contextmanager
    def _locked(self):
        """Context manager for locking."""
        with self._lock:
            yield

    @staticmethod
    def _now() -> float:
        """Current time for TTL checks."""
        return time.monotonic()

    def _serialize_value(self, value: Any) -> bytes:
        """Serialize value for storage."""
        import pickle
        return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)

    def _deserialize_value(self, blob: bytes) -> Any:
        """Deserialize value from storage."""
        import pickle
        return pickle.loads(blob)

    def _unlink_key_unlocked(self, key: str) -> None:
        """Remove key's tag associations (without locking)."""
        tags = self._key_tags.pop(key, None)
        if not tags:
            return

        for tag in tags:
            tag_keys = self._tag_index.get(tag)
            if tag_keys is None:
                continue
            tag_keys.discard(key)
            if not tag_keys:
                self._tag_index.pop(tag, None)

    def _is_expired_unlocked(self, key: str) -> bool:
        """Check if key's TTL has expired (without locking)."""
        item = self._data.get(key)
        if item is None:
            return True
        expires_at, _ = item
        return expires_at is not None and expires_at <= self._now()

    def _cleanup_expired_unlocked(self, key: str) -> bool:
        """Remove expired key and return True if it was deleted."""
        if self._is_expired_unlocked(key):
            self._data.pop(key, None)
            self._unlink_key_unlocked(key)
            return True
        return False

    def get(self, key: str) -> tuple[bool, Any]:
        """Get value from cache."""
        with self._locked():
            if self._cleanup_expired_unlocked(key):
                return False, None

            item = self._data.get(key)
            if item is None:
                return False, None

            _, blob = item

        try:
            return True, self._deserialize_value(blob)
        except Exception:
            with self._locked():
                self._data.pop(key, None)
                self._unlink_key_unlocked(key)
            return False, None

    def set(
        self,
        key: str,
        value: Any,
        ttl: float,
        *,
        tags: Optional[Iterable[str]] = None
    ) -> None:
        """Set value in cache."""
        if ttl is None or ttl <= 0:
            raise ValueError("ttl must be a positive number (seconds)")

        expires_at = self._now() + float(ttl)

        try:
            blob = self._serialize_value(value)
        except Exception as e:
            raise ValueError(f"Cannot serialize value: {e}")

        with self._locked():
            if key in self._data:
                self._unlink_key_unlocked(key)

            self._data[key] = (expires_at, blob)

            if tags:
                tag_set = set(tags)
                self._key_tags[key] = tag_set
                for tag in tag_set:
                    if tag not in self._tag_index:
                        self._tag_index[tag] = set()
                    self._tag_index[tag].add(key)

    def delete(self, key: str) -> None:
        """Delete key from cache."""
        with self._locked():
            self._data.pop(key, None)
            self._unlink_key_unlocked(key)

    def clear(self) -> None:
        """Clear entire cache."""
        with self._locked():
            self._data.clear()
            self._tag_index.clear()
            self._key_tags.clear()

    def invalidate_tags(self, tags: Iterable[str]) -> None:
        """Invalidate cache by tags."""
        with self._locked():
            keys_to_drop: Set[str] = set()

            for tag in tags:
                tag_keys = self._tag_index.get(tag)
                if tag_keys:
                    keys_to_drop.update(tag_keys)

            for key in keys_to_drop:
                self._data.pop(key, None)
                self._unlink_key_unlocked(key)

    def __contains__(self, key: str) -> bool:
        """Check if key exists in cache."""
        with self._locked():
            return not self._cleanup_expired_unlocked(key) and key in self._data

    def __getitem__(self, key: str) -> Any:
        """Get value as dict[key]."""
        hit, value = self.get(key)
        if not hit:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        """Set value as dict[key] = value."""
        self.set(key, value, ttl=self.default_ttl)

    def stats(self) -> dict:
        """Get cache statistics."""
        with self._locked():
            total_keys = len(self._data)
            expired_keys = sum(1 for k in self._data if self._is_expired_unlocked(k))
            return {
                "total_keys": total_keys,
                "active_keys": total_keys - expired_keys,
                "expired_keys": expired_keys,
                "total_tags": len(self._tag_index)
            }


class RedisCache(CustomCache, RedisTagMixin, RedisPatternMixin):
    """
    Enhanced Redis cache using mixins.
    """

    def __init__(
            self,
            client: Redis,
            *,
            default_ttl: float,
            value_prefix: str = "rc:",
            meta_prefix: str = "rcmeta",
            pickle_protocol: int = -1,
    ) -> None:
        if default_ttl <= 0:
            raise ValueError("default_ttl must be > 0 seconds")

        self.default_ttl = float(default_ttl)
        self.r = client
        super().__init__(
            value_prefix=value_prefix,
            meta_prefix=meta_prefix,
            pickle_protocol=pickle_protocol
        )

    def get(self, key: str) -> tuple[bool, Any]:
        """Get value from Redis."""
        try:
            blob = self.r.get(key)
        except RedisError:
            return False, None

        if blob is None:
            return False, None

        try:
            return True, self._deserialize_value(blob)
        except Exception:
            return False, None

    def set(
        self,
        key: str,
        value: Any,
        ttl: float,
        *,
        tags: Optional[Iterable[str]] = None
    ) -> None:
        """Set value in Redis with tags."""
        blob, ex, px, kt_key = self._prepare_set_operation(key, value, ttl, tags)

        p = self.r.pipeline(transaction=False)
        self._prepare_pipeline_for_set(p, key, blob, ex, px, kt_key, tags)
        res = p.execute()

        if tags is not None:
            old_tags = self._extract_old_tags_from_pipeline_result(res, tags is not None)
            self._handle_tags_update(key, kt_key, tags, old_tags, ex, px)

    def _handle_tags_update(
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

        if tags_to_remove:
            self._remove_tags(key, kt_key, tags_to_remove)

        if tags_to_add:
            self._add_tags(key, kt_key, tags_to_add, ex, px)

    def _remove_tags(self, key: str, kt_key: str, tags_to_remove: set[str]) -> None:
        """Remove tags from indexes."""
        try:
            p = self.r.pipeline(transaction=False)
            self._prepare_remove_tags_pipeline_first_pass(p, key, tags_to_remove)
            results = p.execute()

            # Remove empty tagsets
            p = self.r.pipeline(transaction=False)
            self._prepare_remove_tags_pipeline_second_pass(p, tags_to_remove, results, kt_key)
            p.execute()
        except RedisError:
            pass

    def _add_tags(
        self,
        key: str,
        kt_key: str,
        tags: set[str],
        ex: Optional[int],
        px: Optional[int]
    ) -> None:
        """Add tags to indexes."""
        try:
            p = self.r.pipeline(transaction=False)
            self._prepare_add_tags_pipeline(p, key, kt_key, tags, ex, px)
            p.execute()
        except RedisError:
            pass

    def delete(self, key: str) -> None:
        """Delete key and associated tags."""
        try:
            kt_key = self._ktags_key(key)
            tags = self.r.smembers(kt_key)

            p = self.r.pipeline(transaction=False)
            p.delete(key)

            if tags:
                tag_strings = self._decode_redis_strings(tags)
                for tag in tag_strings:
                    p.srem(self._tagset_key(tag), key)
                p.delete(kt_key)

            p.execute()
        except RedisError:
            pass

    def clear(self) -> None:
        """Clear entire cache."""
        try:
            self._delete_by_pattern(self._get_value_pattern())
            self._delete_by_pattern(self._get_meta_pattern())
        except RedisError:
            pass

    def _delete_by_pattern(self, pattern: str) -> None:
        """Delete all keys by pattern."""
        cursor = 0
        while True:
            cursor, keys = self.r.scan(cursor=cursor, match=pattern, count=1000)
            if keys:
                self.r.delete(*keys)
            if cursor == 0:
                break

    def invalidate_tags(self, tags: Iterable[str]) -> None:
        """Invalidate cache by tags."""
        tags_list = list(tags)
        if not tags_list:
            return

        try:
            tag_keys = [self._tagset_key(t) for t in tags_list]
            union = self.r.sunion(tag_keys)

            if not union:
                return

            keys_to_invalidate = [
                k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else k
                for k in union
            ]

            self._batch_invalidate_keys(keys_to_invalidate, tags_list)

        except RedisError:
            pass

    def _batch_invalidate_keys(self, keys: list[str], tags: list[str]) -> None:
        """Batch invalidate keys."""
        p = self.r.pipeline(transaction=False)

        for key in keys:
            p.delete(key)
            p.delete(self._ktags_key(key))

        # Delete tagsets
        for tag in tags:
            p.delete(self._tagset_key(tag))

        p.execute()

    def __contains__(self, key: str) -> bool:
        """Check if key exists."""
        try:
            return bool(self.r.exists(key))
        except RedisError:
            return False

    def __getitem__(self, key: str) -> Any:
        """Get value as dict[key]."""
        hit, value = self.get(key)
        if not hit:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        """Set value as dict[key] = value."""
        self.set(key, value, ttl=self.default_ttl)


# Global default instance
default_backend = InMemoryCache(default_ttl=300)
