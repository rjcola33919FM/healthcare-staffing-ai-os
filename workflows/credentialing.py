"""
Credentialing Pipeline Workflow
Orchestrates the full credentialing lifecycle: document collection →
classification → specialist review → approval (human-only).

Stage: credentialing → credentialing_complete
Human gate: final approval always routes to specialist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from core.constants import ComplianceTag, CredentialCategory, PipelineStage
from config.hipaa import MANDATORY_CREDENTIAL_CATEGORIES, REMINDER_SCHEDULE_DAYS

logger = logging.getLogger(__name__)

ALL_CREDENTIAL_CATEGORIES = [c.value for c in CredentialCategory]


@dataclass
class CredentialingStatus:
    contact_id: str
    categories_received: list[str] = field(default_factory=list)
    categories_verified: list[str] = field(default_factory=list)
    categories_missing: list[str] = field(default_factory=list)
    categories_expiring: list[str] = field(default_factory=list)
    completion_pct: float = 0.0
    mandatory_complete: bool = False
    ready_for_review: bool = False


class CredentialingPipelineWorkflow:
    """
    Full credentialing pipeline for a candidate.
    Coordinates CRED-001 document requests, compliance expiry checks,
    and specialist handoff.
    """

    def __init__(self, cred_tools=None, comp_tools=None, crm_tools=None):
        self._cred = cred_tools
        self._comp = comp_tools
        self._crm = crm_tools

    def initialize_credentialing(
        self, contact_id: str, phone: str = "", email: str = ""
    ) -> dict[str, Any]:
        """
        Kick off credentialing for a candidate:
        1. Set pipeline stage → credentialing
        2. Request all mandatory document categories
        3. Create credentialing timeline task
        """
        if self._crm:
            self._crm.update_pipeline_stage(contact_id, PipelineStage.CREDENTIALING)
            self._crm.add_tags(contact_id, [PipelineStage.CREDENTIALING])
            self._crm.add_note(contact_id, "[CRED-001] Credentialing process initiated.")

        requests = []
        for category in MANDATORY_CREDENTIAL_CATEGORIES:
            upload_url = self._get_upload_url(contact_id, category)
            requests.append({
                "category": category,
                "upload_url": upload_url,
                "phone": phone,
                "email": email,
            })

        if self._crm:
            due_date = (date.today() + timedelta(days=14)).isoformat()
            self._crm.create_task(
                contact_id=contact_id,
                title="Collect all mandatory credentialing documents",
                due_date=due_date,
            )

        logger.info("[CRED-WF] Credentialing initialized contact=%s", contact_id)

        return {
            "action": "crm_update",
            "contact_id": contact_id,
            "stage": PipelineStage.CREDENTIALING,
            "document_requests": requests,
            "crm_updates": {
                "tags_add": [PipelineStage.CREDENTIALING],
                "note": "[ORCH-001] Credentialing pipeline initiated.",
            },
        }

    def get_status(self, contact_id: str) -> CredentialingStatus:
        """Build a credentialing status snapshot for a candidate."""
        status = CredentialingStatus(contact_id=contact_id)

        if self._cred:
            checklist = self._cred.get_checklist(contact_id)
            for cat in ALL_CREDENTIAL_CATEGORIES:
                docs = getattr(checklist, cat, [])
                if any(d.status == "verified" for d in docs):
                    status.categories_verified.append(cat)
                elif any(d.status == "received" for d in docs):
                    status.categories_received.append(cat)
                else:
                    status.categories_missing.append(cat)

            status.completion_pct = checklist.completion_pct
            status.mandatory_complete = not checklist.has_missing_mandatory

        status.ready_for_review = (
            status.mandatory_complete and
            status.completion_pct >= 100.0
        )

        return status

    def run_expiry_reminders(self, contact_id: str, phone: str = "", email: str = "") -> list[dict]:
        """Check all documents for expiry and send reminders per REMINDER_SCHEDULE_DAYS."""
        if not self._cred:
            return []
        expiring = self._cred.get_expiring_documents(contact_id, REMINDER_SCHEDULE_DAYS)
        results = []
        for doc in expiring:
            result = self._cred.send_expiration_reminder(contact_id, doc, phone, email)
            results.append(result)
        return results

    def route_to_specialist(self, contact_id: str) -> dict[str, Any]:
        """
        Route complete credentialing file to human specialist.
        NEVER approve — route only.
        """
        if self._crm:
            self._crm.add_tags(contact_id, [
                PipelineStage.CREDENTIALING_COMPLETE,
                ComplianceTag.HUMAN_ESCALATION_REQUIRED,
            ])
            self._crm.create_task(
                contact_id=contact_id,
                title="SPECIALIST REVIEW: Complete credentialing file ready for approval",
                due_date=(date.today() + timedelta(days=2)).isoformat(),
            )
            self._crm.add_note(
                contact_id,
                "[CRED-001] All documents received. File routed to specialist for final review. "
                "Approval decision requires human credentialing specialist.",
            )

        logger.info("[CRED-WF] File routed to specialist contact=%s", contact_id)

        return {
            "action": "escalate",
            "contact_id": contact_id,
            "escalation_reason": "Credentialing file complete — specialist approval required.",
            "crm_updates": {
                "tags_add": [PipelineStage.CREDENTIALING_COMPLETE, ComplianceTag.HUMAN_ESCALATION_REQUIRED],
                "note": "[CRED-001] File routed to specialist.",
            },
        }

    def _get_upload_url(self, contact_id: str, category: str) -> str:
        import uuid
        token = str(uuid.uuid4()).replace("-", "")[:12]
        return f"https://upload.healthcare-staffing.internal/secure/{contact_id}/{category}/{token}"
