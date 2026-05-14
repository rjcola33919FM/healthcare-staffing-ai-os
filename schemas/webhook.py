"""Inbound webhook payload schemas — matches FastAPI request models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class GHLWebhookPayload(BaseModel):
    contact_id: str
    conversation_id: str
    channel: str = "webhook"
    event_type: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = {}


class TwilioSMSPayload(BaseModel):
    From: str
    To: str
    Body: str
    MessageSid: str


class VAPIVoicePayload(BaseModel):
    call_id: str
    contact_id: str
    transcript: str
    event_type: str = "candidate_message"
