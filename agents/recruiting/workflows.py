"""
REC-001 Workflows — Step-by-step candidate lifecycle workflows.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from core.constants import PipelineStage, ComplianceTag

if TYPE_CHECKING:
    from .agent import IntakeState
    from .tools import RecruitingTools

logger = logging.getLogger(__name__)


class CandidateWorkflow:
    """
    Orchestrates multi-step candidate workflows.
    Triggered by the RecruitingAgent at key lifecycle transitions.
    """

    def __init__(self, tools: "RecruitingTools"):
        self.tools = tools

    def complete_intake(self, contact_id: str, state: "IntakeState") -> dict[str, Any]:
        """
        Execute intake completion workflow:
        1. Update all collected fields in CRM
        2. Move pipeline to intake_complete
        3. Apply intake_complete tag
        4. Create recruiter follow-up task
        5. Send confirmation SMS
        """
        collected = state.collected

        self.tools.update_contact_fields(contact_id, collected)
        self.tools.update_pipeline_stage(contact_id, PipelineStage.INTAKE_COMPLETE)
        self.tools.add_tags(contact_id, [PipelineStage.INTAKE_COMPLETE])
        self.tools.create_recruiter_task(
            contact_id=contact_id,
            title=f"Review intake: {collected.get('first_name', '')} {collected.get('last_name', '')} — {collected.get('specialty', '')}",
            due_date="",
        )
        self.tools.add_note(
            contact_id,
            f"[REC-001] Intake complete. Specialty: {collected.get('specialty')}. "
            f"License state: {collected.get('license_state')}. "
            f"Availability: {collected.get('availability_date', 'not provided')}.",
        )

        if phone := collected.get("phone"):
            self.tools.send_sms(
                contact_id, phone,
                "Thanks for completing your intake! Your recruiter will be in touch shortly. — Healthcare Staffing",
            )

        logger.info("[WORKFLOW] Intake complete for contact=%s", contact_id)

        return {
            "action": "crm_update",
            "content": (
                f"Great — I have everything I need, "
                f"{collected.get('first_name', 'there')}! Your recruiter will reach out shortly "
                f"to discuss next steps."
            ),
            "crm_updates": {
                "fields": collected,
                "tags_add": [PipelineStage.INTAKE_COMPLETE],
                "tags_remove": [PipelineStage.INTAKE_IN_PROGRESS],
                "note": f"[REC-001] Intake complete. Pipeline moved to {PipelineStage.INTAKE_COMPLETE}.",
            },
        }

    def book_appointment_workflow(
        self,
        contact_id: str,
        slot_id: str,
        phone: str,
        recruiter_id: str = "",
    ) -> dict[str, Any]:
        """
        Execute appointment booking workflow:
        1. Book slot in GHL calendar
        2. Send confirmation SMS
        3. Log note and tag in CRM
        """
        appt = self.tools.book_appointment(contact_id, slot_id)
        if phone:
            self.tools.send_confirmation_sms(contact_id, phone, appt)
        self.tools.add_note(
            contact_id,
            f"[REC-001] Recruiter appointment booked. Slot: {slot_id}. "
            f"Appointment ID: {appt.get('appointment_id')}.",
        )
        self.tools.add_tags(contact_id, ["appointment_booked"])

        return {
            "action": "crm_update",
            "content": (
                f"Your appointment is confirmed! "
                f"You'll receive a confirmation SMS shortly."
            ),
            "crm_updates": {
                "tags_add": ["appointment_booked"],
                "note": f"[REC-001] Appointment booked: {appt.get('appointment_id')}.",
            },
            "appointment": appt,
        }

    def silence_followup_workflow(self, contact_id: str, attempt: int) -> dict[str, Any]:
        """Send a follow-up nudge when candidate goes silent."""
        message = (
            "Hi! Just checking in — we'd love to help you find your next opportunity. "
            "Reply anytime to continue where we left off."
        )
        self.tools.add_note(
            contact_id,
            f"[REC-001] Silence follow-up #{attempt} sent.",
        )
        return {
            "action": "reply",
            "content": message,
            "crm_updates": {
                "note": f"[REC-001] Follow-up #{attempt} sent due to candidate silence.",
            },
        }
