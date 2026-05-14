"""
Sales Qualification Workflow
Orchestrates the lead lifecycle: inbound → qualified → proposal → closed.

BANT gating: budget + authority + need + timeline.
No pricing, contract terms, or MSP/RPO commitments without human escalation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from core.constants import PipelineStage, ComplianceTag
from schemas.lead import LeadQualification, SalesOpportunity

logger = logging.getLogger(__name__)

BANT_QUESTIONS = {
    "budget_confirmed":    "Has the client confirmed they have budget allocated for staffing?",
    "authority_confirmed": "Are we speaking with the decision-maker for staffing contracts?",
    "need_confirmed":      "Have specific roles, specialties, and volume been identified?",
    "timeline_confirmed":  "Has a target start date or urgency level been established?",
}

ESCALATION_TOPICS = [
    "price", "rate", "bill rate", "pay rate", "margin", "msp", "rpo",
    "contract term", "sla", "guarantee", "exclusive", "amendment",
]


@dataclass
class QualificationCheckResult:
    qualified: bool
    score: int          # 0–4 BANT score
    tier: str           # hot | warm | cold | unqualified
    missing_bant: list[str] = field(default_factory=list)
    escalation_required: bool = False
    escalation_reason: str = ""


class SalesQualificationWorkflow:
    """
    Full sales lead qualification pipeline.
    Coordinates SALES-001, SCHED-001, and CRM-001.
    """

    def __init__(self, crm_tools=None, sched_tools=None):
        self._crm = crm_tools
        self._sched = sched_tools

    def qualify_lead(self, lead: LeadQualification, message: str = "") -> QualificationCheckResult:
        """
        Evaluate BANT score and determine qualification tier.
        Check message for escalation topics.
        """
        missing = [k for k, v in {
            "budget_confirmed": lead.budget_confirmed,
            "authority_confirmed": lead.authority_confirmed,
            "need_confirmed": lead.need_confirmed,
            "timeline_confirmed": lead.timeline_confirmed,
        }.items() if not v]

        escalation_required = any(t in message.lower() for t in ESCALATION_TOPICS)
        escalation_reason = ""
        if escalation_required:
            matched = [t for t in ESCALATION_TOPICS if t in message.lower()]
            escalation_reason = f"Message contains escalation topic(s): {matched}"

        return QualificationCheckResult(
            qualified=lead.bant_score >= 2,
            score=lead.bant_score,
            tier=lead.qualification_score,
            missing_bant=missing,
            escalation_required=escalation_required,
            escalation_reason=escalation_reason,
        )

    def next_bant_question(self, lead: LeadQualification) -> str | None:
        """Return the next unanswered BANT question, or None if all answered."""
        for field_name, question in BANT_QUESTIONS.items():
            if not getattr(lead, field_name, False):
                return question
        return None

    def advance_to_qualified(
        self, contact_id: str, lead: LeadQualification
    ) -> dict[str, Any]:
        """Move opportunity to qualified stage after BANT score >= 2."""
        tag = f"qualification_{lead.qualification_score}"
        if self._crm:
            self._crm.update_pipeline_stage(contact_id, PipelineStage.QUALIFIED)
            self._crm.add_tags(contact_id, [PipelineStage.QUALIFIED, tag])
            self._crm.add_note(
                contact_id,
                f"[SALES-001] Lead qualified. BANT score: {lead.bant_score}/4. "
                f"Tier: {lead.qualification_score}. "
                f"Specialties: {lead.specialties_needed}. "
                f"Volume: {lead.positions_count}.",
            )

        logger.info(
            "[SALES-WF] Lead qualified contact=%s bant=%d tier=%s",
            contact_id, lead.bant_score, lead.qualification_score,
        )

        return {
            "action": "crm_update",
            "contact_id": contact_id,
            "qualification_score": lead.qualification_score,
            "bant_score": lead.bant_score,
            "crm_updates": {
                "tags_add": [PipelineStage.QUALIFIED, tag],
                "note": f"[SALES-001] Qualified. BANT: {lead.bant_score}/4. Tier: {lead.qualification_score}.",
            },
        }

    def book_discovery_call(
        self,
        contact_id: str,
        phone: str = "",
        email: str = "",
        preferred_dates: list[str] | None = None,
    ) -> dict[str, Any]:
        """Route to SCHED-001 to book a sales discovery call."""
        if self._sched:
            from agents.scheduling.agent import AppointmentRequest
            request = AppointmentRequest(
                contact_id=contact_id,
                appointment_type="sales_discovery",
                requested_by_agent="SALES-001",
                preferred_dates=preferred_dates or [],
                phone=phone,
                email=email,
            )
            return self._sched.book(request)

        logger.info("[SALES-WF] Discovery call booking queued contact=%s", contact_id)
        return {
            "action": "crm_update",
            "contact_id": contact_id,
            "appointment_type": "sales_discovery",
            "crm_updates": {
                "tags_add": ["appointment_requested"],
                "note": "[SALES-001] Discovery call requested. SCHED-001 to confirm slot.",
            },
        }

    def disqualify(
        self, contact_id: str, reason: str
    ) -> dict[str, Any]:
        """
        Disqualify a lead. Tags record and logs reason.
        NEVER deletes the contact — archive only.
        """
        if self._crm:
            self._crm.update_pipeline_stage(contact_id, PipelineStage.DISQUALIFIED)
            self._crm.add_tags(contact_id, [PipelineStage.DISQUALIFIED])
            self._crm.add_note(
                contact_id,
                f"[SALES-001] Lead disqualified. Reason: {reason}. Record preserved.",
            )

        logger.info("[SALES-WF] Lead disqualified contact=%s reason=%s", contact_id, reason)

        return {
            "action": "crm_update",
            "contact_id": contact_id,
            "crm_updates": {
                "tags_add": [PipelineStage.DISQUALIFIED],
                "note": f"[SALES-001] Disqualified: {reason}.",
            },
        }

    def schedule_discovery_call(
        self,
        contact_id: str,
        lead_data: dict,
    ) -> dict:
        """
        BANT-qualified lead → schedule a discovery call.
        Called by WorkflowExecutor on lead.qualified event.
        """
        from datetime import date, timedelta
        if self._crm:
            due_date = (date.today() + timedelta(days=2)).isoformat()
            self._crm.add_tags(contact_id, ["discovery_call_scheduled"])
            self._crm.create_task(
                contact_id=contact_id,
                title="SALES: Schedule discovery call — BANT qualified lead",
                due_date=due_date,
            )
            self._crm.add_note(
                contact_id,
                "[SALES-001] Lead BANT-qualified. Discovery call task created.",
            )

        logger.info("[SALES-WF] Discovery call scheduled contact=%s", contact_id)

        return {
            "contact_id": contact_id,
            "crm_updates": {
                "tags_add": ["discovery_call_scheduled"],
                "note": "[SALES-001] Discovery call task created.",
            },
        }
