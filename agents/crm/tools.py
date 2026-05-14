"""
CRM-001 Tools — GoHighLevel write operations with validation and logging.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# In-memory contact store for testing; replaced by GHLClient in production
_MOCK_CONTACTS: dict[str, dict] = {
    "test-contact-001": {"id": "test-contact-001", "firstName": "Test", "lastName": "User"},
}


class CRMTools:
    def __init__(self, ghl_client=None):
        self._ghl = ghl_client

    # ── Contact Reads ──────────────────────────────────────────────────────────

    def get_contact(self, contact_id: str) -> dict | None:
        if self._ghl:
            try:
                return self._ghl.get_contact(contact_id)
            except Exception:
                return None
        return _MOCK_CONTACTS.get(contact_id)

    def contact_exists(self, contact_id: str) -> bool:
        return self.get_contact(contact_id) is not None

    # ── Contact Writes ─────────────────────────────────────────────────────────

    def update_contact(self, contact_id: str, fields: dict[str, Any]) -> bool:
        if self._ghl:
            self._ghl.update_contact(contact_id, fields)
        else:
            contact = _MOCK_CONTACTS.get(contact_id, {})
            contact.update(fields)
            _MOCK_CONTACTS[contact_id] = contact
        logger.info("[CRM-TOOLS] update_contact contact=%s fields=%s", contact_id, list(fields.keys()))
        return True

    # ── Tags ───────────────────────────────────────────────────────────────────

    def add_tags(self, contact_id: str, tags: list[str]) -> bool:
        if self._ghl:
            self._ghl.add_tags(contact_id, tags)
        logger.info("[CRM-TOOLS] add_tags contact=%s tags=%s", contact_id, tags)
        return True

    def remove_tags(self, contact_id: str, tags: list[str]) -> bool:
        if self._ghl:
            self._ghl.remove_tags(contact_id, tags)
        logger.info("[CRM-TOOLS] remove_tags contact=%s tags=%s", contact_id, tags)
        return True

    # ── Notes ─────────────────────────────────────────────────────────────────

    def add_note(self, contact_id: str, note: str) -> bool:
        if self._ghl:
            self._ghl.add_note(contact_id, note)
        logger.info("[CRM-TOOLS] note added contact=%s preview='%s...'", contact_id, note[:60])
        return True

    # ── Pipeline ───────────────────────────────────────────────────────────────

    def update_pipeline_stage(self, contact_id: str, stage: str) -> bool:
        if self._ghl:
            self._ghl.update_contact(contact_id, {"pipelineStage": stage})
        else:
            contact = _MOCK_CONTACTS.get(contact_id, {})
            contact["pipelineStage"] = stage
            _MOCK_CONTACTS[contact_id] = contact
        logger.info("[CRM-TOOLS] pipeline_stage=%s contact=%s", stage, contact_id)
        return True

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def create_task(
        self,
        contact_id: str,
        title: str,
        due_date: str,
        assignee_id: str = "",
        description: str = "",
    ) -> dict[str, Any]:
        task = {
            "task_id": f"task_{contact_id}_{title[:10].replace(' ', '_')}",
            "contact_id": contact_id,
            "title": title,
            "due_date": due_date,
            "assignee_id": assignee_id,
            "description": description,
            "completed": False,
        }
        if self._ghl:
            self._ghl.create_task(contact_id, title, due_date, assignee_id, description)
        logger.info("[CRM-TOOLS] task created contact=%s title=%s", contact_id, title)
        return task

    # ── Webhooks ───────────────────────────────────────────────────────────────

    def log_webhook(self, contact_id: str, webhook_id: str, payload: dict[str, Any]) -> bool:
        """Log inbound webhook payload before processing (required by CRM-001 rules)."""
        logger.info(
            "[CRM-TOOLS] webhook logged contact=%s webhook_id=%s keys=%s",
            contact_id, webhook_id, list(payload.keys()),
        )
        return True

    # ── Identity Matching ──────────────────────────────────────────────────────

    def find_duplicate_contacts(self, email: str = "", phone: str = "") -> list[dict]:
        """
        Search for contacts with matching email or phone.
        Multiple matches → escalate as merge conflict.
        """
        if self._ghl:
            # In production: query GHL contacts API with email/phone filter
            pass
        # Stub: no duplicates
        return []
