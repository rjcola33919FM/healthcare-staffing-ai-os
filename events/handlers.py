"""
Event handlers for Healthcare Staffing AI OS.
Each handler is registered to a specific event type on the EventBus.
"""

from __future__ import annotations

import logging

from events.bus import EventBus
from events.models import (
    Event,
    EscalationEvent,
    CRMEvent,
    ComplianceAlertEvent,
    AgentResponseEvent,
)

logger = logging.getLogger(__name__)


# ── Audit Handler (wildcard — runs on every event) ─────────────────────────────

async def audit_log_handler(event: Event) -> None:
    """Append-only audit log for every event. HIPAA compliance requirement."""
    logger.info(
        "[AUDIT] event_id=%s type=%s agent=%s contact=%s channel=%s ts=%s",
        event.event_id,
        event.event_type,
        event.agent_id,
        event.contact_id,
        event.channel,
        event.timestamp.isoformat(),
    )


# ── Escalation Handler ─────────────────────────────────────────────────────────

async def escalation_handler(event: Event) -> None:
    if not isinstance(event, EscalationEvent):
        return
    logger.warning(
        "[ESCALATION] contact=%s reason=%s source_agent=%s",
        event.contact_id,
        event.escalation_reason,
        event.source_agent_id,
    )
    # In production: create GHL task, notify human queue via Slack/email webhook


# ── CRM Sync Handler ───────────────────────────────────────────────────────────

async def crm_sync_handler(event: Event) -> None:
    if not isinstance(event, CRMEvent):
        return
    logger.info(
        "[CRM_SYNC] op=%s contact=%s tags_add=%s note=%s",
        event.operation,
        event.contact_id,
        event.tags_add,
        event.note[:80] if event.note else None,
    )
    # In production: call GHLClient.apply_crm_updates()


# ── Compliance Alert Handler ───────────────────────────────────────────────────

async def compliance_alert_handler(event: Event) -> None:
    if not isinstance(event, ComplianceAlertEvent):
        return
    logger.warning(
        "[COMPLIANCE] level=%s credential=%s contact=%s days_remaining=%s mandatory=%s",
        event.alert_level,
        event.credential_type,
        event.contact_id,
        event.days_remaining,
        event.mandatory,
    )
    # In production: create GHL task, apply compliance tag, notify COMP-001


# ── Agent Response Handler ─────────────────────────────────────────────────────

async def agent_response_handler(event: Event) -> None:
    if not isinstance(event, AgentResponseEvent):
        return
    logger.info(
        "[AGENT_RESPONSE] agent=%s contact=%s action=%s tokens=%d/%d",
        event.agent_id,
        event.contact_id,
        event.action,
        event.input_tokens,
        event.output_tokens,
    )


# ── Registration ───────────────────────────────────────────────────────────────

def register_all_handlers(bus: EventBus) -> None:
    """Register all event handlers on the bus. Called at app startup."""
    bus.subscribe_all(audit_log_handler)
    bus.subscribe("human_escalation", escalation_handler)
    bus.subscribe("crm_sync", crm_sync_handler)
    bus.subscribe("compliance_alert", compliance_alert_handler)
    bus.subscribe("agent_response", agent_response_handler)
    logger.info("[BUS] All handlers registered.")
