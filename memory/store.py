"""
Memory Store — Redis-backed persistence with in-memory fallback.
Stores AgentMemorySnapshot (session) and ContactMemory (cross-session).
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from .models import AgentMemorySnapshot, ContactMemory, MemoryTurn

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 3600        # 1 hour — matches orchestration/state.py
CONTACT_MEMORY_TTL_SECONDS = 604800  # 7 days

# Redis key namespaces
_SESSION_KEY = "mem:session:{session_id}"
_CONTACT_KEY = "mem:contact:{contact_id}:{agent_id}"


class MemoryStore:
    """
    Dual-layer memory store: Redis (primary) + dict (fallback/test).

    Usage:
        store = MemoryStore()              # auto-detects Redis
        store = MemoryStore(redis_client)  # explicit client
    """

    def __init__(self, redis_client=None):
        self._redis = redis_client or self._try_connect_redis()
        self._memory: dict[str, Any] = {}   # in-memory fallback

    # ------------------------------------------------------------------
    # Session memory (AgentMemorySnapshot)
    # ------------------------------------------------------------------

    def load_snapshot(self, session_id: str) -> AgentMemorySnapshot | None:
        key = _SESSION_KEY.format(session_id=session_id)
        raw = self._get(key)
        if raw is None:
            return None
        try:
            return self._deserialize_snapshot(raw)
        except Exception as exc:
            logger.warning("[MEM] Snapshot deserialize failed key=%s: %s", key, exc)
            return None

    def save_snapshot(self, snapshot: AgentMemorySnapshot) -> None:
        key = _SESSION_KEY.format(session_id=snapshot.session_id)
        self._set(key, self._serialize_snapshot(snapshot), ttl=SESSION_TTL_SECONDS)

    def delete_snapshot(self, session_id: str) -> None:
        key = _SESSION_KEY.format(session_id=session_id)
        self._delete(key)

    # ------------------------------------------------------------------
    # Contact memory (ContactMemory — cross-session, longer TTL)
    # ------------------------------------------------------------------

    def load_contact_memory(self, contact_id: str, agent_id: str) -> ContactMemory | None:
        key = _CONTACT_KEY.format(contact_id=contact_id, agent_id=agent_id)
        raw = self._get(key)
        if raw is None:
            return None
        try:
            return self._deserialize_contact(raw)
        except Exception as exc:
            logger.warning("[MEM] Contact memory deserialize failed key=%s: %s", key, exc)
            return None

    def save_contact_memory(self, memory: ContactMemory) -> None:
        key = _CONTACT_KEY.format(contact_id=memory.contact_id, agent_id=memory.agent_id)
        self._set(key, self._serialize_contact(memory), ttl=CONTACT_MEMORY_TTL_SECONDS)

    def get_or_create_contact_memory(
        self, contact_id: str, agent_id: str
    ) -> ContactMemory:
        mem = self.load_contact_memory(contact_id, agent_id)
        if mem is None:
            mem = ContactMemory(contact_id=contact_id, agent_id=agent_id)
        return mem

    # ------------------------------------------------------------------
    # Internal: Redis / fallback
    # ------------------------------------------------------------------

    def _get(self, key: str) -> bytes | None:
        if self._redis:
            try:
                return self._redis.get(key)
            except Exception as exc:
                logger.warning("[MEM] Redis GET failed key=%s — falling back: %s", key, exc)
        return self._memory.get(key)

    def _set(self, key: str, value: bytes, ttl: int) -> None:
        if self._redis:
            try:
                self._redis.setex(key, ttl, value)
                return
            except Exception as exc:
                logger.warning("[MEM] Redis SET failed key=%s — falling back: %s", key, exc)
        self._memory[key] = value

    def _delete(self, key: str) -> None:
        if self._redis:
            try:
                self._redis.delete(key)
            except Exception as exc:
                logger.warning("[MEM] Redis DEL failed key=%s: %s", key, exc)
        self._memory.pop(key, None)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _serialize_snapshot(self, snapshot: AgentMemorySnapshot) -> bytes:
        data = {
            "session_id": snapshot.session_id,
            "contact_id": snapshot.contact_id,
            "agent_id": snapshot.agent_id,
            "turns": [asdict(t) for t in snapshot.turns],
            "summary": snapshot.summary,
            "summary_turn_index": snapshot.summary_turn_index,
            "created_at": snapshot.created_at,
        }
        return json.dumps(data).encode()

    def _deserialize_snapshot(self, raw: bytes) -> AgentMemorySnapshot:
        data = json.loads(raw)
        turns = [MemoryTurn(**t) for t in data.get("turns", [])]
        return AgentMemorySnapshot(
            session_id=data["session_id"],
            contact_id=data["contact_id"],
            agent_id=data["agent_id"],
            turns=turns,
            summary=data.get("summary", ""),
            summary_turn_index=data.get("summary_turn_index", 0),
            created_at=data.get("created_at", ""),
        )

    def _serialize_contact(self, memory: ContactMemory) -> bytes:
        return json.dumps(asdict(memory)).encode()

    def _deserialize_contact(self, raw: bytes) -> ContactMemory:
        data = json.loads(raw)
        return ContactMemory(**data)

    # ------------------------------------------------------------------
    # Redis connection helper
    # ------------------------------------------------------------------

    @staticmethod
    def _try_connect_redis():
        try:
            import redis as _redis
            import os
            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            client = _redis.from_url(url, socket_connect_timeout=2)
            client.ping()
            logger.info("[MEM] Redis connected: %s", url)
            return client
        except Exception as exc:
            logger.info("[MEM] Redis unavailable — using in-memory store: %s", exc)
            return None
