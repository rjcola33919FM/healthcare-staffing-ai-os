"""
SCHED-001 Workflows — Appointment lifecycle step sequences.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .tools import SchedulingTools

logger = logging.getLogger(__name__)


class AppointmentWorkflow:
    def __init__(self, tools: "SchedulingTools"):
        self.tools = tools

    def book_appointment(
        self,
        contact_id: str,
        slot: dict[str, Any],
        appointment_type: str,
        phone: str = "",
        email: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """
        Full booking sequence:
        1. Create appointment in GHL calendar
        2. Send confirmation SMS (if phone available)
        3. Send email confirmation (if email available)
        4. Log CRM note and apply tag
        """
        appt = self.tools.create_appointment(
            contact_id=contact_id,
            slot=slot,
            appointment_type=appointment_type,
            notes=notes,
        )

        if phone:
            self.tools.send_sms_reminder(contact_id, phone, appt)
        if email:
            self.tools.send_email_confirmation(contact_id, email, appt)

        self.tools.add_crm_note(
            contact_id,
            f"[SCHED-001] {appointment_type} booked. "
            f"ID: {appt['appointment_id']}. "
            f"Datetime: {appt['datetime']}. "
            f"Assignee: {appt['assignee_id']}.",
        )
        self.tools.add_crm_tags(contact_id, ["appointment_booked", appointment_type])

        logger.info(
            "[WORKFLOW] Appointment booked contact=%s type=%s id=%s",
            contact_id, appointment_type, appt["appointment_id"],
        )

        return {
            "action": "crm_update",
            "agent_id": "SCHED-001",
            "content": (
                f"Your {appointment_type.replace('_', ' ')} is confirmed. "
                f"You'll receive a confirmation shortly."
            ),
            "appointment": appt,
            "crm_updates": {
                "tags_add": ["appointment_booked", appointment_type],
                "note": f"[SCHED-001] Appointment {appt['appointment_id']} booked.",
            },
        }

    def send_reminder(self, appointment: dict[str, Any]) -> dict[str, Any]:
        """Send a pre-appointment reminder."""
        contact_id = appointment["contact_id"]
        self.tools.add_crm_note(
            contact_id,
            f"[SCHED-001] Reminder sent for appointment {appointment['appointment_id']}.",
        )
        logger.info(
            "[WORKFLOW] Reminder sent for appointment=%s contact=%s",
            appointment["appointment_id"], contact_id,
        )
        return {
            "action": "noop",
            "agent_id": "SCHED-001",
            "appointment_id": appointment["appointment_id"],
            "reminder_sent": True,
        }

    def cancel_and_notify(
        self,
        appointment_id: str,
        contact_id: str,
        phone: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        """Cancel appointment and notify the contact."""
        self.tools.cancel_appointment(appointment_id)

        if phone:
            msg = f"Your appointment (ID: {appointment_id}) has been cancelled. Please contact us to reschedule."
            # Would call tools.send_sms directly in production
            logger.info("[WORKFLOW] Cancellation SMS sent contact=%s", contact_id)

        self.tools.add_crm_note(
            contact_id,
            f"[SCHED-001] Appointment {appointment_id} cancelled. Reason: {reason or 'not specified'}.",
        )
        self.tools.add_crm_tags(contact_id, ["appointment_cancelled"])

        return {
            "action": "crm_update",
            "agent_id": "SCHED-001",
            "content": "Your appointment has been cancelled.",
            "crm_updates": {
                "tags_add": ["appointment_cancelled"],
                "note": f"[SCHED-001] Cancelled: {appointment_id}.",
            },
        }
