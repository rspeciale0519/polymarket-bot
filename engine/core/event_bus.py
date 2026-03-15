"""
Internal asyncio pub/sub event bus.

Modules subscribe to typed event channels rather than holding direct references.
All callbacks are async and dispatched via asyncio.create_task for non-blocking execution.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

import structlog

logger = structlog.get_logger(__name__)

Callback = Callable[[Any], Coroutine[Any, Any, None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[type, list[Callback]] = defaultdict(list)
        self._running_tasks: set[asyncio.Task[None]] = set()

    def subscribe(self, event_type: type, callback: Callback) -> None:
        self._subscribers[event_type].append(callback)
        logger.debug("event_bus.subscribe", event_type=event_type.__name__)

    def unsubscribe(self, event_type: type, callback: Callback) -> None:
        subs = self._subscribers.get(event_type, [])
        if callback in subs:
            subs.remove(callback)

    async def publish(self, event: Any) -> None:
        event_type = type(event)
        subscribers = self._subscribers.get(event_type, [])

        if not subscribers:
            return

        logger.debug(
            "event_bus.publish",
            event_type=event_type.__name__,
            subscriber_count=len(subscribers),
        )

        for callback in subscribers:
            task = asyncio.create_task(self._safe_dispatch(callback, event))
            self._running_tasks.add(task)
            task.add_done_callback(self._running_tasks.discard)

    async def _safe_dispatch(self, callback: Callback, event: Any) -> None:
        try:
            await callback(event)
        except Exception:
            logger.exception(
                "event_bus.callback_error",
                callback=callback.__qualname__,
                event_type=type(event).__name__,
            )

    async def drain(self) -> None:
        """Wait for all dispatched callbacks to complete."""
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks, return_exceptions=True)

    @property
    def subscriber_count(self) -> int:
        return sum(len(subs) for subs in self._subscribers.values())
