import asyncio
import logging
from typing import Any, Coroutine, TypeVar

logger = logging.getLogger(__name__)

ReturnT = TypeVar("ReturnT")


class SingleFlight:
    """
    Ensures that for a given key, only one coroutine executes at a time.

    When multiple concurrent callers request the same key, only the first
    one runs. All others wait for that result. This prevents duplicate
    upstream calls (e.g., 20 concurrent requests for the same BCCR date
    causing 20 BCCR fetches instead of 1).

    If the in-flight coroutine fails, all waiters receive the same exception.
    Cancellation of a waiter does not cancel the in-flight task, so other
    waiters still receive their result.
    """

    def __init__(self) -> None:
        self._pending_tasks: dict[str, asyncio.Task] = {}

    async def execute(self, key: str, coro: Coroutine[Any, Any, ReturnT]) -> ReturnT:
        if key in self._pending_tasks:
            logger.debug("Coalescing request for key %r — reusing in-flight result", key)
            coro.close()
            return await asyncio.shield(self._pending_tasks[key])

        pending_task: asyncio.Task[ReturnT] = asyncio.create_task(coro)
        self._pending_tasks[key] = pending_task
        try:
            return await asyncio.shield(pending_task)
        finally:
            self._pending_tasks.pop(key, None)
