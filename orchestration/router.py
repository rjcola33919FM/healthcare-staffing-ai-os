"""
Healthcare Staffing AI OS — Orchestration Router
ORCH-001: Routes inbound events to the correct specialized agent.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from src.agents.base import AgentContext, AgentResponse

logger = logging.getLogger(__name__)


class AgentID(str, Enum):
    ORCHESTRATOR = "ORCH-001"
    RECRUITING = "REC-001"
    CREDENTIALING = "CRED-001"
    COMPLIANCE = "COMP-001"
    SALES = "SALES-001"
    CRM = "CRM-001"
    HUMAN = "HUMAN"


# Intent-to-agent routing table
INTENT_ROUTING: dict[str, AgentID] = {
    # Recruiting signals
    "candidate_intake": AgentID.RECRUITING,
    "candidate_faq": AgentID.RECRUITING,
    "book_recruiter_appointment": AgentID.RECRUITING,
    "candidate_message": AgentID.RECRUITING,

    # Credentialing signals
    "document_upload": AgentID.CREDENTIALING,
    "document_request": AgentID.CREDENTIALING,
    "checklist_status": AgentID.CREDENTIALING,
    "credential_reminder": AgentID.CREDENTIALING,
    "license_expiry": AgentID.CREDENTIALING,

    # Compliance signals
    "compliance_alert": AgentID.COMPLIANCE,
    "audit_event": AgentID.COMPLIANCE,
    "credential_expiry": AgentID.COMPLIANCE,
    "phi_exposure": AgentID.COMPLIANCE,
    "sanctions_check": AgentID.COMPLIANCE,

    # Sales signals
    "lead_inbound": AgentID.SALES,
    "client_inquiry": AgentID.SALES,
    "book_sales_appointment": AgentID.SALES,
    "lead_qualification": AgentID.SALES,

    # CRM signals
    "crm_update": AgentID.CRM,
    "tag_apply": AgentID.CRM,
    "pipeline_stage_change": AgentID.CRM,
    "webhook_sync": AgentID.CRM,
    "note_create": AgentID.CRM,

    # Always-human signals
    "credential_approval": AgentID.HUMAN,
    "contract_terms": AgentID.HUMAN,
    "candidate_rejection": AgentID.HUMAN,
    "compliance_exception": AgentID.HUMAN,
    "pricing_exception": AgentID.HUMAN,
    "phi_breach": AgentID.HUMAN,
}

# Escalation patterns — any of these in the payload trigger human routing
ESCALATION_PATTERNS = [
    "legal advice",
    "clinical judgment",
    "final approval",
    "malpractice",
    "contract amendment",
    "termination",
    "phi",
    "hipaa breach",
    "sanction",
    "exclusion",
]


def classify_intent(payload: dict[str, Any]) -> str:
    """
    Classify the intent of an inbound event.
    Priority: explicit event_type field > keyword matching on message.
    """
    if "event_type" in payload:
        return payload["event_type"]

    message = payload.get("message", "").lower()

    if any(p in message for p in ESCALATION_PATTERNS):
        return "compliance_exception"

    # Keyword-based fallback classification — order matters: more specific before general
    if any(kw in message for kw in ["apply", "interested in a position", "resume", "availability"]):
        return "candidate_message"
    if any(kw in message for kw in ["expire", "expiring", "expiration", "compliance", "alert"]):
        return "compliance_alert"
    if any(kw in message for kw in ["license", "credential", "document", "upload", "checklist"]):
        return "document_request"
    if any(kw in message for kw in ["staffing need", "fill a position", "open role", "hire"]):
        return "client_inquiry"

    return "crm_update"


def route(context: AgentContext) -> AgentID:
    """
    Route an inbound context to the appropriate agent.
    Returns AgentID for the handler.
    """
    intent = classify_intent(context.payload)
    target = INTENT_ROUTING.get(intent, AgentID.ORCHESTRATOR)

    logger.info(
        "[ROUTER] contact=%s intent=%s -> agent=%s",
        context.contact_id, intent, target,
    )
    return target


def build_escalation_response(reason: str, context: AgentContext) -> AgentResponse:
    """Create a standardized human escalation response."""
    return AgentResponse(
        agent_id=AgentID.ORCHESTRATOR,
        action="escalate",
        content="This request has been flagged for human review.",
        crm_updates={
            "tags_add": ["human_escalation_required"],
            "note": f"[ORCH-001] Escalated to human. Reason: {reason}",
        },
        escalation_reason=reason,
    )
