"""
Event models for Healthcare Staffing AI OS.
All events flowing through the system are typed here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Event(BaseModel):
    event_id: str = Field(default_factory=_uuid)
    event_type: str
    agent_id: str
    contact_id: str
    conversation_id: str
    channel: str = "webhook"
    timestamp: datetime = Field(default_factory=_now)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EscalationEvent(Event):
    event_type: str = "human_escalation"
    escalation_reason: str
    source_agent_id: str
    crm_updates: dict[str, Any] = Field(default_factory=dict)


class CRMEvent(Event):
    event_type: str = "crm_sync"
    operation: str  # note | tag_add | tag_remove | stage_change | task_create | field_update
    fields: dict[str, Any] = Field(default_factory=dict)
    tags_add: list[str] = Field(default_factory=list)
    tags_remove: list[str] = Field(default_factory=list)
    note: str | None = None


class ComplianceAlertEvent(Event):
    event_type: str = "compliance_alert"
    alert_level: str  # red | yellow | blue
    credential_type: str
    expiration_date: str | None = None
    days_remaining: int | None = None
    mandatory: bool = False


class DocumentEvent(Event):
    event_type: str = "document_received"
    document_id: str
    credential_category: str
    filename: str
    upload_url: str | None = None


class AgentResponseEvent(Event):
    """Emitted after every agent run for audit trail and downstream processing."""
    action: str  # reply | escalate | crm_update | route | noop
    response_content: str
    escalation_reason: str | None = None
    next_agent: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
