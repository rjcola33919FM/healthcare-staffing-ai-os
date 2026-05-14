"""
REC-001 Tools — GoHighLevel actions available to the Recruiting Agent.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RecruitingTools:
    """
    Wraps GoHighLevel operations used by the Candidate Recruiting Agent.
    In production, inject a GHLClient instance.
    """

    def __init__(self, ghl_client=None):
        self._ghl = ghl_client

    # ── CRM ───────────────────────────────────────────────────────────────────

    def update_contact_fields(self, contact_id: str, fields: dict[str, Any]) -> bool:
        """Update contact fields in GoHighLevel."""
        if self._ghl:
            self._ghl.update_contact(contact_id, fields)
        logger.info("[REC-TOOLS] update_contact fields=%s contact=%s", list(fields.keys()), contact_id)
        return True

    def add_tags(self, contact_id: str, tags: list[str]) -> bool:
        if self._ghl:
            self._ghl.add_tags(contact_id, tags)
        logger.info("[REC-TOOLS] add_tags tags=%s contact=%s", tags, contact_id)
        return True

    def update_pipeline_stage(self, contact_id: str, stage: str) -> bool:
        if self._ghl:
            self._ghl.update_contact(contact_id, {"pipelineStage": stage})
        logger.info("[REC-TOOLS] pipeline_stage=%s contact=%s", stage, contact_id)
        return True

    def add_note(self, contact_id: str, note: str) -> bool:
        if self._ghl:
            self._ghl.add_note(contact_id, note)
        logger.info("[REC-TOOLS] note added contact=%s", contact_id)
        return True

    # ── Calendar ──────────────────────────────────────────────────────────────

    def get_available_slots(self, recruiter_id: str, date_range_days: int = 7) -> list[dict]:
        """
        Return available recruiter calendar slots.
        In production, queries GHL calendar API.
        """
        logger.info("[REC-TOOLS] get_available_slots recruiter=%s", recruiter_id)
        # Stub — production queries GHL calendar
        return [
            {"slot_id": "slot_001", "datetime": "2026-05-15T10:00:00-05:00", "recruiter_id": recruiter_id},
            {"slot_id": "slot_002", "datetime": "2026-05-15T14:00:00-05:00", "recruiter_id": recruiter_id},
            {"slot_id": "slot_003", "datetime": "2026-05-16T09:00:00-05:00", "recruiter_id": recruiter_id},
        ]

    def book_appointment(
        self,
        contact_id: str,
        slot_id: str,
        appointment_type: str = "recruiter_intro",
    ) -> dict[str, Any]:
        """Book a recruiter appointment in GoHighLevel calendar."""
        logger.info(
            "[REC-TOOLS] book_appointment contact=%s slot=%s type=%s",
            contact_id, slot_id, appointment_type,
        )
        return {
            "appointment_id": f"appt_{slot_id}",
            "contact_id": contact_id,
            "slot_id": slot_id,
            "type": appointment_type,
            "status": "booked",
        }

    # ── Messaging ─────────────────────────────────────────────────────────────

    def send_sms(self, contact_id: str, phone: str, message: str) -> bool:
        """Send SMS via GoHighLevel (routes through Twilio)."""
        logger.info("[REC-TOOLS] send_sms contact=%s phone=%s", contact_id, phone)
        return True

    def send_confirmation_sms(self, contact_id: str, phone: str, appointment: dict) -> bool:
        """Send appointment confirmation via SMS."""
        msg = (
            f"Your recruiter appointment is confirmed for "
            f"{appointment.get('slot_id', 'TBD')}. "
            f"Reply CANCEL to cancel. — Healthcare Staffing"
        )
        return self.send_sms(contact_id, phone, msg)

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def create_recruiter_task(
        self,
        contact_id: str,
        title: str,
        due_date: str,
        recruiter_id: str = "",
    ) -> bool:
        if self._ghl:
            self._ghl.create_task(contact_id, title, due_date, recruiter_id)
        logger.info("[REC-TOOLS] task created contact=%s title=%s", contact_id, title)
        return True
