import time
from asyncio import Lock
from typing import Any, Awaitable, Callable


class TTLCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, Lock] = {}

    async def get_or_set(
        self,
        key: str,
        ttl: int,
        loader: Callable[[], Awaitable[Any]],
    ) -> Any:
        hit = self._store.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]

        lock = self._locks.setdefault(key, Lock())
        async with lock:
            hit = self._store.get(key)
            if hit and hit[0] > time.monotonic():
                return hit[1]
            value = await loader()
            self._store[key] = (time.monotonic() + ttl, value)
            return value

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
        self._locks.clear()


cache = TTLCache()
