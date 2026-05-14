"""
Session state management for multi-turn agent conversations.
Tracks per-contact conversation context across channels.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 3600  # 1 hour


@dataclass
class SessionState:
    contact_id: str
    channel: str
    current_agent: str = "ORCH-001"
    last_intent: str = ""
    last_intent_confidence: float = 0.0
    turn_count: int = 0
    context: dict[str, Any] = field(default_factory=dict)
    crm_snapshot: dict[str, Any] = field(default_factory=dict)
    escalated: bool = False
    escalation_reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
        self.turn_count += 1

    def set_agent(self, agent_id: str) -> None:
        logger.debug(
            "[STATE] Agent transition contact=%s %s → %s",
            self.contact_id, self.current_agent, agent_id,
        )
        self.current_agent = agent_id
        self.touch()

    def mark_escalated(self, reason: str) -> None:
        self.escalated = True
        self.escalation_reason = reason
        self.touch()

    def update_context(self, key: str, value: Any) -> None:
        self.context[key] = value
        self.touch()

    @property
    def is_expired(self) -> bool:
        elapsed = (datetime.now(timezone.utc) - self.updated_at).total_seconds()
        return elapsed > SESSION_TTL_SECONDS


class SessionStore:
    """
    In-process session store.
    In production: backed by Redis with TTL.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def get(self, contact_id: str, channel: str = "webhook") -> SessionState:
        session = self._sessions.get(contact_id)
        if session is None or session.is_expired:
            session = SessionState(contact_id=contact_id, channel=channel)
            self._sessions[contact_id] = session
            logger.debug("[SESSION] New session contact=%s channel=%s", contact_id, channel)
        return session

    def set(self, session: SessionState) -> None:
        self._sessions[session.contact_id] = session

    def clear(self, contact_id: str) -> None:
        self._sessions.pop(contact_id, None)

    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if not s.is_expired)
