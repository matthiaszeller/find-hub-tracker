import time
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

T = TypeVar("T")

class AsyncTTLCache(Generic[T]):
    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._value: T | None = None
        self._time: float = 0.0
        self._has_value = False

    async def get_or_set(self, factory: Callable[[], Awaitable[T]]) -> T:
        now = time.monotonic()
        if self._has_value and (now - self._time) < self._ttl:
            return self._value  # type: ignore[return-value]

        value = await factory()
        self._value = value
        self._time = now
        self._has_value = True
        return value

    def invalidate(self) -> None:
        self._has_value = False
