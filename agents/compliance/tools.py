"""
COMP-001 Tools — Compliance monitoring, alert storage, audit log, CRM tags.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from schemas.compliance import AuditLogEntry, ComplianceAlert, ComplianceRecord

logger = logging.getLogger(__name__)

# In-memory stores — replaced by PostgreSQL in production
_COMPLIANCE_RECORDS: dict[str, ComplianceRecord] = {}
_AUDIT_LOG: list[AuditLogEntry] = []  # Global append-only log


class ComplianceTools:
    def __init__(self, ghl_client=None, db_session=None):
        self._ghl = ghl_client
        self._db = db_session

    # ── Compliance Record ──────────────────────────────────────────────────────

    def get_compliance_record(self, contact_id: str) -> ComplianceRecord:
        if contact_id not in _COMPLIANCE_RECORDS:
            _COMPLIANCE_RECORDS[contact_id] = ComplianceRecord(contact_id=contact_id)
        return _COMPLIANCE_RECORDS[contact_id]

    def set_compliance_tag(self, contact_id: str, status: str) -> None:
        record = self.get_compliance_record(contact_id)
        record.overall_status = status  # type: ignore
        record.last_reviewed = datetime.now(timezone.utc)

        # Remove existing compliance status tags, apply new one
        old_tags = ["compliant", "at_risk", "non_compliant", "escalated"]
        self.remove_crm_tags(contact_id, old_tags)
        self.add_crm_tags(contact_id, [status])
        logger.info("[COMP-TOOLS] Compliance status set contact=%s status=%s", contact_id, status)

    # ── Alerts ─────────────────────────────────────────────────────────────────

    def create_alert(
        self,
        contact_id: str,
        alert_level: str,
        credential_type: str,
        description: str,
        expiration_date: str | None = None,
        days_remaining: int | None = None,
        mandatory: bool = False,
    ) -> ComplianceAlert:
        alert = ComplianceAlert(
            alert_id=str(uuid.uuid4()),
            contact_id=contact_id,
            alert_level=alert_level,  # type: ignore
            credential_type=credential_type,
            expiration_date=expiration_date,
            days_remaining=days_remaining,
            mandatory=mandatory,
            description=description,
        )
        record = self.get_compliance_record(contact_id)
        record.alerts.append(alert)
        logger.info(
            "[COMP-TOOLS] Alert created contact=%s level=%s type=%s days=%s",
            contact_id, alert_level, credential_type, days_remaining,
        )
        return alert

    def resolve_alert(self, contact_id: str, alert_id: str) -> bool:
        record = self.get_compliance_record(contact_id)
        for alert in record.alerts:
            if alert.alert_id == alert_id:
                alert.resolved = True
                logger.info("[COMP-TOOLS] Alert resolved contact=%s alert_id=%s", contact_id, alert_id)
                return True
        return False

    # ── Audit Log ──────────────────────────────────────────────────────────────

    def append_audit_log(self, entry: AuditLogEntry) -> None:
        """Append-only. Never modify or delete existing entries."""
        _AUDIT_LOG.append(entry)

        # Also persist to compliance record for contact-scoped queries
        record = self.get_compliance_record(entry.contact_id)
        record.audit_log.append(entry)

        logger.info(
            "[COMP-TOOLS] Audit entry contact=%s action=%s escalated=%s",
            entry.contact_id, entry.action, entry.escalated,
        )

    def get_audit_log(self, contact_id: str) -> list[AuditLogEntry]:
        record = self.get_compliance_record(contact_id)
        return record.audit_log

    def get_global_audit_log(self) -> list[AuditLogEntry]:
        return list(_AUDIT_LOG)  # Copy — do not expose mutable reference

    # ── Credential Lookups ─────────────────────────────────────────────────────

    def get_all_credential_docs(self, contact_id: str) -> list[dict[str, Any]]:
        """
        Return all credentialed documents for a contact.
        In production: queries PostgreSQL credential table joined to contact.
        """
        # Stub — production queries DB
        return []

    def get_missing_mandatory_categories(
        self, contact_id: str, mandatory_categories: list[str]
    ) -> list[str]:
        """
        Return mandatory categories with no verified document on file.
        In production: queries credential checklist table.
        """
        # Stub — production queries DB
        return []

    # ── PHI Flag ──────────────────────────────────────────────────────────────

    def flag_phi_exposure(self, contact_id: str) -> None:
        record = self.get_compliance_record(contact_id)
        record.phi_exposure_detected = True
        logger.warning("[COMP-TOOLS] PHI exposure flagged contact=%s", contact_id)

    # ── CRM ───────────────────────────────────────────────────────────────────

    def add_crm_note(self, contact_id: str, note: str) -> bool:
        if self._ghl:
            self._ghl.add_note(contact_id, note)
        logger.info("[COMP-TOOLS] CRM note contact=%s preview='%s...'", contact_id, note[:60])
        return True

    def add_crm_tags(self, contact_id: str, tags: list[str]) -> bool:
        if self._ghl:
            self._ghl.add_tags(contact_id, tags)
        logger.info("[COMP-TOOLS] Tags added contact=%s tags=%s", contact_id, tags)
        return True

    def remove_crm_tags(self, contact_id: str, tags: list[str]) -> bool:
        if self._ghl:
            self._ghl.remove_tags(contact_id, tags)
        return True

    def create_task(self, contact_id: str, title: str, due_date: str, assignee_id: str = "") -> bool:
        if self._ghl:
            self._ghl.create_task(contact_id, title, due_date, assignee_id)
        logger.info("[COMP-TOOLS] Task created contact=%s title=%s", contact_id, title)
        return True
