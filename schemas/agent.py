"""Agent request/response payload schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AgentRequest(BaseModel):
    agent_id: str
    contact_id: str
    conversation_id: str
    channel: str
    event_type: str | None = None
    message: str | None = None
    crm_state: dict[str, Any] = {}


class AgentResponsePayload(BaseModel):
    agent_id: str
    action: str  # reply | escalate | crm_update | route | noop
    content: str
    crm_updates: dict[str, Any] = {}
    escalation_reason: str | None = None
    next_agent: str | None = None
    metadata: dict[str, Any] = {}
