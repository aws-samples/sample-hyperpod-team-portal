"""极简 in-process async TTL cache (替代 Redis + cachetools, 4 行胜千言).

只覆盖我们 DDB 化场景的实际需求:
    - 单值缓存 (cluster_describe), 不是 LRU
    - key 是字符串, value 是 dict
    - TTL 秒级
    - 进程级单实例; 多副本不需共享 (每实例命中 ≥95% 即可)

并发安全: 用 asyncio.Lock 围绕 fetch_cb, 避免雪崩.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")


class TtlCache(Generic[T]):
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, T]] = {}
        self._lock = asyncio.Lock()

    async def get_or_load(self, key: str, loader: Callable[[], Awaitable[T]]) -> T:
        now = time.monotonic()
        cached = self._store.get(key)
        if cached and (now - cached[0] < self._ttl):
            return cached[1]
        async with self._lock:
            cached = self._store.get(key)
            if cached and (time.monotonic() - cached[0] < self._ttl):
                return cached[1]
            value = await loader()
            self._store[key] = (time.monotonic(), value)
            return value

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)
