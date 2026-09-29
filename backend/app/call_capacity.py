"""Limit total tutor pipelines across practice and study in one API process."""

import asyncio


class CallCapacity:
    def __init__(self, limit: int = 2):
        self.limit = limit
        self._used = 0
        self._lock = asyncio.Lock()

    async def available(self) -> bool:
        async with self._lock:
            return self._used < self.limit

    async def acquire(self) -> bool:
        async with self._lock:
            if self._used >= self.limit:
                return False
            self._used += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self._used -= 1
