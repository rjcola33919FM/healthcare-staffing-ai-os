"""
In-process event bus for Healthcare Staffing AI OS.
Handlers are registered per event_type and executed synchronously or queued to Redis.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable, Awaitable

from events.models import Event

logger = logging.getLogger(__name__)

HandlerFn = Callable[[Event], Awaitable[None]]

_bus_instance: "EventBus | None" = None


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[HandlerFn]] = defaultdict(list)
        self._wildcard: list[HandlerFn] = []

    def subscribe(self, event_type: str, handler: HandlerFn) -> None:
        """Subscribe a handler to a specific event type."""
        self._handlers[event_type].append(handler)
        logger.debug("[BUS] Handler registered for event_type=%s", event_type)

    def subscribe_all(self, handler: HandlerFn) -> None:
        """Subscribe a handler to every event (wildcard)."""
        self._wildcard.append(handler)

    async def publish(self, event: Event) -> None:
        """
        Publish an event synchronously to all registered handlers.
        All events are also passed to wildcard subscribers (e.g., audit logger).
        """
        logger.info(
            "[BUS] publish event_type=%s agent=%s contact=%s",
            event.event_type, event.agent_id, event.contact_id,
        )

        handlers = self._handlers.get(event.event_type, []) + self._wildcard
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    "[BUS] Handler error for event_type=%s: %s",
                    event.event_type, e,
                )

    def clear(self) -> None:
        self._handlers.clear()
        self._wildcard.clear()


def get_bus() -> EventBus:
    global _bus_instance
    if _bus_instance is None:
        _bus_instance = EventBus()
    return _bus_instance
