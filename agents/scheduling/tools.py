"""
SCHED-001 Tools — Calendar and notification operations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Assignee pools by appointment type — in production, populated from GHL/HR system
ASSIGNEE_POOLS: dict[str, list[str]] = {
    "recruiter_intro":       ["recruiter_01", "recruiter_02", "recruiter_03"],
    "recruiter_followup":    ["recruiter_01", "recruiter_02"],
    "sales_discovery":       ["sales_01", "sales_02"],
    "credentialing_review":  ["credentialing_01"],
    "compliance_review":     ["compliance_01"],
}


class SchedulingTools:
    """
    Wraps GoHighLevel calendar API and notification dispatch.
    In production, inject GHLClient and TwilioClient.
    """

    def __init__(self, ghl_client=None, twilio_client=None):
        self._ghl = ghl_client
        self._twilio = twilio_client
        # In-memory store for testing; replaced by GHL in production
        self._appointments: dict[str, dict] = {}

    # ── Slot Discovery ─────────────────────────────────────────────────────────

    def get_available_slots(
        self,
        appointment_type: str,
        preferred_dates: list[str] | None = None,
        days_ahead: int = 7,
    ) -> list[dict[str, Any]]:
        """
        Return available calendar slots for the given appointment type.
        In production: queries GHL calendar API filtered by assignee pool.
        """
        assignees = ASSIGNEE_POOLS.get(appointment_type, [])
        now = datetime.now(timezone.utc)
        slots = []
        for i, assignee in enumerate(assignees[:2]):  # stub: 2 slots per assignee
            for offset_days in [1, 2]:
                slot_dt = now + timedelta(days=offset_days, hours=9 + i * 4)
                slots.append({
                    "slot_id": f"slot_{appointment_type}_{assignee}_{offset_days}",
                    "datetime": slot_dt.isoformat(),
                    "assignee_id": assignee,
                    "appointment_type": appointment_type,
                    "duration_minutes": 30,
                })
        logger.info("[SCHED-TOOLS] Found %d slots for type=%s", len(slots), appointment_type)
        return slots

    # ── Booking ────────────────────────────────────────────────────────────────

    def create_appointment(
        self,
        contact_id: str,
        slot: dict[str, Any],
        appointment_type: str,
        notes: str = "",
    ) -> dict[str, Any]:
        appt = {
            "appointment_id": f"appt_{slot['slot_id']}",
            "contact_id": contact_id,
            "slot_id": slot["slot_id"],
            "datetime": slot["datetime"],
            "assignee_id": slot.get("assignee_id", ""),
            "appointment_type": appointment_type,
            "status": "booked",
            "notes": notes,
            "reminder_sent": False,
        }
        self._appointments[appt["appointment_id"]] = appt
        if self._ghl:
            # In production: call GHL calendar booking endpoint
            pass
        logger.info(
            "[SCHED-TOOLS] Appointment created id=%s contact=%s type=%s dt=%s",
            appt["appointment_id"], contact_id, appointment_type, slot["datetime"],
        )
        return appt

    def cancel_appointment(self, appointment_id: str) -> bool:
        appt = self._appointments.get(appointment_id)
        if appt:
            appt["status"] = "cancelled"
            logger.info("[SCHED-TOOLS] Appointment cancelled id=%s", appointment_id)
            return True
        return False

    def mark_no_show(self, appointment_id: str) -> bool:
        appt = self._appointments.get(appointment_id)
        if appt:
            appt["status"] = "no_show"
            logger.info("[SCHED-TOOLS] No-show marked id=%s", appointment_id)
            return True
        return False

    def get_appointments_needing_reminder(self, within_hours: int = 25) -> list[dict]:
        """Return booked appointments whose datetime is within `within_hours` that haven't been reminded."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=within_hours)
        due = []
        for appt in self._appointments.values():
            if appt["status"] != "booked" or appt.get("reminder_sent"):
                continue
            appt_dt = datetime.fromisoformat(appt["datetime"])
            if now < appt_dt <= cutoff:
                due.append(appt)
        return due

    # ── Notifications ──────────────────────────────────────────────────────────

    def send_sms_reminder(self, contact_id: str, phone: str, appointment: dict) -> bool:
        msg = (
            f"Reminder: You have an appointment on {appointment['datetime'][:10]} "
            f"at {appointment['datetime'][11:16]} UTC. Reply CANCEL to cancel. "
            f"— Healthcare Staffing"
        )
        if self._twilio:
            self._twilio.send_sms(phone, msg)
        logger.info("[SCHED-TOOLS] SMS reminder sent contact=%s", contact_id)
        appointment["reminder_sent"] = True
        return True

    def send_email_confirmation(self, contact_id: str, email: str, appointment: dict) -> bool:
        logger.info("[SCHED-TOOLS] Email confirmation sent contact=%s email=%s", contact_id, email)
        return True

    # ── CRM ───────────────────────────────────────────────────────────────────

    def add_crm_note(self, contact_id: str, note: str) -> bool:
        if self._ghl:
            self._ghl.add_note(contact_id, note)
        logger.info("[SCHED-TOOLS] CRM note added contact=%s", contact_id)
        return True

    def add_crm_tags(self, contact_id: str, tags: list[str]) -> bool:
        if self._ghl:
            self._ghl.add_tags(contact_id, tags)
        logger.info("[SCHED-TOOLS] Tags added contact=%s tags=%s", contact_id, tags)
        return True
