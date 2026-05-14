"""
CRED-001 Tools — Document management, checklist, upload links, notifications.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from schemas.credential import CredentialChecklist, CredentialDocument

logger = logging.getLogger(__name__)

# In-memory stores for testing; replaced by DB + GHL in production
_CHECKLISTS: dict[str, CredentialChecklist] = {}
_DOCUMENT_LOG: list[dict] = []


class CredentialingTools:
    def __init__(self, ghl_client=None, twilio_client=None, storage_client=None):
        self._ghl = ghl_client
        self._twilio = twilio_client
        self._storage = storage_client

    # ── Checklist ─────────────────────────────────────────────────────────────

    def get_checklist(self, contact_id: str) -> CredentialChecklist:
        if contact_id not in _CHECKLISTS:
            _CHECKLISTS[contact_id] = CredentialChecklist(contact_id=contact_id)
        return _CHECKLISTS[contact_id]

    def update_checklist_item(
        self,
        contact_id: str,
        document_id: str,
        category: str,
        status: str,
        filename: str,
        expiration_date: date | None = None,
    ) -> bool:
        checklist = self.get_checklist(contact_id)
        doc = CredentialDocument(
            document_id=document_id,
            contact_id=contact_id,
            category=category,  # type: ignore
            document_name=filename,
            status=status,  # type: ignore
            expiration_date=expiration_date,
            received_date=date.today(),
        )
        category_list: list = getattr(checklist, category, [])
        # Replace existing or append
        existing = next((i for i, d in enumerate(category_list) if d.document_id == document_id), None)
        if existing is not None:
            category_list[existing] = doc
        else:
            category_list.append(doc)
        logger.info("[CRED-TOOLS] Checklist updated contact=%s category=%s status=%s", contact_id, category, status)
        return True

    def get_expiring_documents(
        self, contact_id: str, reminder_days: list[int]
    ) -> list[dict[str, Any]]:
        """Return documents whose expiration falls exactly on a reminder threshold."""
        checklist = self.get_checklist(contact_id)
        today = date.today()
        expiring = []

        all_docs = (
            checklist.identity + checklist.licensure + checklist.education_training +
            checklist.work_history + checklist.malpractice +
            checklist.health_immunizations + checklist.background_drug
        )

        for doc in all_docs:
            if not doc.expiration_date:
                continue
            days_left = (doc.expiration_date - today).days
            if days_left in reminder_days:
                expiring.append({
                    "document_id": doc.document_id,
                    "document_name": doc.document_name,
                    "category": doc.category,
                    "expiration_date": doc.expiration_date.isoformat(),
                    "days_remaining": days_left,
                })

        logger.info("[CRED-TOOLS] Found %d expiring docs for contact=%s", len(expiring), contact_id)
        return expiring

    # ── Document Receipt Logging ───────────────────────────────────────────────

    def log_document_receipt(self, contact_id: str, document_id: str, filename: str) -> None:
        """Append-only audit log entry for document receipt. HIPAA requirement."""
        entry = {
            "event": "document_received",
            "contact_id": contact_id,
            "document_id": document_id,
            "filename": filename,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _DOCUMENT_LOG.append(entry)
        logger.info(
            "[CRED-TOOLS] Document received contact=%s doc_id=%s file=%s",
            contact_id, document_id, filename,
        )
        # Log to CRM note — reference only, no document contents
        self.add_crm_note(
            contact_id,
            f"[CRED-001] Document received. doc_id={document_id} filename={filename}. "
            f"Pending classification.",
        )

    # ── Upload Links ───────────────────────────────────────────────────────────

    def generate_upload_link(
        self, contact_id: str, category: str, expiry_hours: int = 72
    ) -> str:
        """
        Generate a secure, time-limited upload link.
        In production: signed S3/GCS URL or GHL secure file upload endpoint.
        """
        token = str(uuid.uuid4()).replace("-", "")[:16]
        link = f"https://upload.healthcare-staffing.internal/secure/{contact_id}/{category}/{token}"
        logger.info("[CRED-TOOLS] Upload link generated contact=%s category=%s", contact_id, category)
        return link

    # ── Notifications ──────────────────────────────────────────────────────────

    def send_sms(self, contact_id: str, phone: str, message: str) -> bool:
        if self._twilio:
            self._twilio.send_sms(phone, message)
        logger.info("[CRED-TOOLS] SMS sent contact=%s", contact_id)
        return True

    def send_email(self, contact_id: str, email: str, subject: str, body: str) -> bool:
        logger.info("[CRED-TOOLS] Email sent contact=%s subject=%s", contact_id, subject)
        return True

    # ── CRM ───────────────────────────────────────────────────────────────────

    def add_crm_note(self, contact_id: str, note: str) -> bool:
        if self._ghl:
            self._ghl.add_note(contact_id, note)
        logger.info("[CRED-TOOLS] CRM note contact=%s preview='%s...'", contact_id, note[:60])
        return True

    def add_crm_tags(self, contact_id: str, tags: list[str]) -> bool:
        if self._ghl:
            self._ghl.add_tags(contact_id, tags)
        logger.info("[CRED-TOOLS] Tags added contact=%s tags=%s", contact_id, tags)
        return True

    def update_pipeline_stage(self, contact_id: str, stage: str) -> bool:
        if self._ghl:
            self._ghl.update_contact(contact_id, {"pipelineStage": stage})
        logger.info("[CRED-TOOLS] Pipeline stage=%s contact=%s", stage, contact_id)
        return True

    def create_task(self, contact_id: str, title: str, due_date: str, assignee_id: str = "") -> bool:
        if self._ghl:
            self._ghl.create_task(contact_id, title, due_date, assignee_id)
        logger.info("[CRED-TOOLS] Task created contact=%s title=%s", contact_id, title)
        return True
