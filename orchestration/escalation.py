"""
Escalation management for Healthcare Staffing AI OS.
Centralizes escalation logic, human queue routing, and CRM tagging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.constants import AgentID, ComplianceTag, EscalationReason

logger = logging.getLogger(__name__)


@dataclass
class EscalationTicket:
    ticket_id: str
    contact_id: str
    conversation_id: str
    source_agent: str
    reason: str
    severity: str  # critical | high | normal
    payload_summary: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False
    resolved_by: str = ""


# Severity by escalation reason keyword
SEVERITY_MAP: dict[str, str] = {
    "phi":            "critical",
    "breach":         "critical",
    "sanction":       "critical",
    "exclusion":      "critical",
    "adverse":        "critical",
    "mandatory":      "high",
    "credential":     "high",
    "approval":       "high",
    "contract":       "high",
    "compensation":   "high",
    "rejection":      "high",
    "merge conflict": "high",
    "delete":         "high",
}


def _compute_severity(reason: str) -> str:
    lower = reason.lower()
    for keyword, severity in SEVERITY_MAP.items():
        if keyword in lower:
            return severity
    return "normal"


class EscalationManager:
    """
    Manages escalation tickets, CRM tagging, and human queue routing.
    All escalation paths across all agents converge here.
    """

    def __init__(self, ghl_client=None, notification_client=None):
        self._ghl = ghl_client
        self._notify = notification_client
        self._tickets: dict[str, EscalationTicket] = {}

    def create_ticket(
        self,
        contact_id: str,
        conversation_id: str,
        source_agent: str,
        reason: str,
        payload_summary: str = "",
    ) -> EscalationTicket:
        import uuid
        ticket_id = f"ESC-{str(uuid.uuid4())[:8].upper()}"
        severity = _compute_severity(reason)

        ticket = EscalationTicket(
            ticket_id=ticket_id,
            contact_id=contact_id,
            conversation_id=conversation_id,
            source_agent=source_agent,
            reason=reason,
            severity=severity,
            payload_summary=payload_summary,
        )
        self._tickets[ticket_id] = ticket

        logger.warning(
            "[ESCALATION] ticket=%s severity=%s agent=%s contact=%s reason=%s",
            ticket_id, severity, source_agent, contact_id, reason,
        )

        self._apply_crm_escalation(contact_id, ticket)
        self._notify_human_queue(ticket)
        return ticket

    def resolve_ticket(self, ticket_id: str, resolved_by: str) -> bool:
        ticket = self._tickets.get(ticket_id)
        if not ticket:
            return False
        ticket.resolved = True
        ticket.resolved_by = resolved_by
        logger.info("[ESCALATION] Resolved ticket=%s by=%s", ticket_id, resolved_by)
        return True

    def get_open_tickets(self) -> list[EscalationTicket]:
        return [t for t in self._tickets.values() if not t.resolved]

    def build_escalation_response(
        self,
        contact_id: str,
        conversation_id: str,
        source_agent: str,
        reason: str,
    ) -> dict[str, Any]:
        """
        Standard escalation response dict consumed by the dispatcher and API layer.
        Creates ticket + returns response payload in one call.
        """
        ticket = self.create_ticket(
            contact_id=contact_id,
            conversation_id=conversation_id,
            source_agent=source_agent,
            reason=reason,
        )
        return {
            "action": "escalate",
            "agent_id": source_agent,
            "content": "This request has been escalated to a specialist.",
            "escalation_reason": reason,
            "ticket_id": ticket.ticket_id,
            "severity": ticket.severity,
            "crm_updates": {
                "tags_add": [ComplianceTag.HUMAN_ESCALATION_REQUIRED],
                "note": (
                    f"[{source_agent}] Escalated. "
                    f"Ticket: {ticket.ticket_id}. "
                    f"Severity: {ticket.severity}. "
                    f"Reason: {reason}"
                ),
            },
        }

    def _apply_crm_escalation(self, contact_id: str, ticket: EscalationTicket) -> None:
        if self._ghl:
            try:
                self._ghl.add_tags(contact_id, [ComplianceTag.HUMAN_ESCALATION_REQUIRED])
                self._ghl.add_note(
                    contact_id,
                    f"[ESCALATION] ticket={ticket.ticket_id} severity={ticket.severity} "
                    f"source={ticket.source_agent} reason={ticket.reason}",
                )
            except Exception as e:
                logger.error("[ESCALATION] CRM write failed: %s", e)

    def _notify_human_queue(self, ticket: EscalationTicket) -> None:
        """
        Notify human queue (Slack webhook, email, GHL internal notification).
        In production: POST to Slack/email/GHL notification endpoint.
        """
        if self._notify:
            try:
                self._notify.send(
                    subject=f"[{ticket.severity.upper()}] Escalation {ticket.ticket_id}",
                    body=f"Contact: {ticket.contact_id}\nReason: {ticket.reason}\nAgent: {ticket.source_agent}",
                )
            except Exception as e:
                logger.error("[ESCALATION] Notification failed: %s", e)
        else:
            logger.info(
                "[ESCALATION] Human queue notified (stub). ticket=%s severity=%s",
                ticket.ticket_id, ticket.severity,
            )
