"""
SCHED-001 — Scheduling Agent
Owns all calendar operations: recruiter appointments, sales discovery calls,
credentialing deadlines, and compliance review windows.
Decoupled from REC-001 and SALES-001 so scheduling logic is a single concern.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import anthropic

from core.constants import AgentID
from core.exceptions import EscalationRequired
from .tools import SchedulingTools
from .workflows import AppointmentWorkflow

logger = logging.getLogger(__name__)

AppointmentType = Literal[
    "recruiter_intro",
    "recruiter_followup",
    "sales_discovery",
    "credentialing_review",
    "compliance_review",
]


@dataclass
class AppointmentRequest:
    contact_id: str
    appointment_type: AppointmentType
    requested_by_agent: str
    preferred_dates: list[str] = field(default_factory=list)
    phone: str = ""
    email: str = ""
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ScheduledAppointment:
    appointment_id: str
    contact_id: str
    appointment_type: AppointmentType
    slot_id: str
    datetime_iso: str
    assignee_id: str
    status: Literal["booked", "confirmed", "cancelled", "rescheduled", "no_show"] = "booked"
    reminder_sent: bool = False


class SchedulingAgent:
    """
    SCHED-001 — Scheduling Agent.

    Central calendar coordination agent. All appointment booking from any
    upstream agent (REC-001, SALES-001, CRED-001) routes through here.

    Responsibilities:
    - Find available slots for recruiters, sales reps, credentialing specialists
    - Book, confirm, reschedule, and cancel appointments
    - Send reminders (SMS/email) at configured intervals
    - Log all scheduling events to CRM
    - Escalate conflicts, double-bookings, and no-shows to human
    """

    AGENT_ID = "SCHED-001"
    REMINDER_INTERVALS_HOURS = [24, 1]  # 24h and 1h before

    def __init__(self, client: anthropic.Anthropic, tools: SchedulingTools | None = None):
        self.client = client
        self.tools = tools or SchedulingTools()
        self.workflow = AppointmentWorkflow(self.tools)

    def book(self, request: AppointmentRequest) -> dict[str, Any]:
        """
        Book an appointment for a contact.
        Returns the scheduled appointment dict or an escalation.
        """
        logger.info(
            "[SCHED-001] book request contact=%s type=%s requested_by=%s",
            request.contact_id, request.appointment_type, request.requested_by_agent,
        )

        # Find available slots
        slots = self.tools.get_available_slots(
            appointment_type=request.appointment_type,
            preferred_dates=request.preferred_dates,
        )

        if not slots:
            return self._escalate(
                request.contact_id,
                f"No available slots for appointment_type={request.appointment_type}.",
            )

        # Pick best slot (first available; in production: match preference)
        selected = slots[0]

        return self.workflow.book_appointment(
            contact_id=request.contact_id,
            slot=selected,
            appointment_type=request.appointment_type,
            phone=request.phone,
            email=request.email,
            notes=request.notes,
        )

    def reschedule(self, appointment_id: str, contact_id: str, reason: str = "") -> dict[str, Any]:
        """Cancel existing appointment and book the next available slot."""
        logger.info("[SCHED-001] reschedule appointment=%s contact=%s", appointment_id, contact_id)

        cancelled = self.tools.cancel_appointment(appointment_id)
        if not cancelled:
            return self._escalate(contact_id, f"Could not cancel appointment {appointment_id}.")

        slots = self.tools.get_available_slots("recruiter_intro")
        if not slots:
            return self._escalate(contact_id, "No slots available for rescheduling.")

        return self.workflow.book_appointment(
            contact_id=contact_id,
            slot=slots[0],
            appointment_type="recruiter_intro",
            notes=f"Rescheduled. Original reason: {reason}",
        )

    def send_reminders(self, upcoming_window_hours: int = 25) -> list[dict[str, Any]]:
        """
        Find appointments within the reminder window and send reminders.
        Called by a scheduled job (cron / Redis worker).
        """
        due = self.tools.get_appointments_needing_reminder(upcoming_window_hours)
        results = []
        for appt in due:
            result = self.workflow.send_reminder(appt)
            results.append(result)
        logger.info("[SCHED-001] Sent %d reminders.", len(results))
        return results

    def handle_no_show(self, appointment_id: str, contact_id: str) -> dict[str, Any]:
        """Mark no-show and escalate to human for follow-up decision."""
        self.tools.mark_no_show(appointment_id)
        return self._escalate(
            contact_id,
            f"No-show on appointment {appointment_id}. Human decision required on next steps.",
        )

    def _escalate(self, contact_id: str, reason: str) -> dict[str, Any]:
        logger.warning("[SCHED-001] Escalating contact=%s reason=%s", contact_id, reason)
        return {
            "action": "escalate",
            "agent_id": self.AGENT_ID,
            "content": "This scheduling request needs human assistance.",
            "escalation_reason": reason,
            "crm_updates": {
                "tags_add": ["human_escalation_required"],
                "note": f"[SCHED-001] Escalated. Reason: {reason}",
            },
        }
