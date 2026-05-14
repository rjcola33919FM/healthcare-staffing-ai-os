"""
Redis event queue for async CRM sync and background processing.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
QUEUE_KEY = "healthcare_staffing:events"


class RedisQueue:
    def __init__(self, url: str = REDIS_URL):
        self._url = url
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._redis = await aioredis.from_url(self._url, decode_responses=True)
        logger.info("[REDIS] Connected to %s", self._url)

    async def enqueue(self, event_type: str, data: dict[str, Any]) -> None:
        if not self._redis:
            await self.connect()
        payload = json.dumps({"event_type": event_type, "data": data})
        await self._redis.rpush(QUEUE_KEY, payload)
        logger.debug("[REDIS] Enqueued event: %s", event_type)

    async def dequeue(self) -> dict[str, Any] | None:
        if not self._redis:
            await self.connect()
        item = await self._redis.lpop(QUEUE_KEY)
        if item:
            return json.loads(item)
        return None

    async def queue_length(self) -> int:
        if not self._redis:
            await self.connect()
        return await self._redis.llen(QUEUE_KEY)


_queue_instance: RedisQueue | None = None


async def get_queue() -> RedisQueue:
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = RedisQueue()
        await _queue_instance.connect()
    return _queue_instance


async def enqueue_event(event_type: str, data: dict[str, Any]) -> None:
    queue = await get_queue()
    await queue.enqueue(event_type, data)
