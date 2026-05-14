"""
COMP-001 — Compliance Monitoring Agent
Full implementation: expiry monitoring, alert generation, audit trail,
PHI exposure detection, and adverse flag escalation.

RULES (non-negotiable):
- Never make legal or clinical judgments — flag and escalate only
- Every alert includes: candidate_id, credential_type, expiration_date, days_remaining
- Audit log is append-only — never delete entries
- PHI encountered outside HIPAA-compliant config triggers immediate escalation
- Compliance tags: compliant | at_risk | non_compliant | escalated
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal

import anthropic

from config.hipaa import (
    GUARDRAIL_KEYWORDS,
    MANDATORY_CREDENTIAL_CATEGORIES,
    PHI_RESTRICTED_FIELDS,
    AUDIT_LOG_IMMUTABLE,
    AUDIT_LOG_RETENTION_DAYS,
)
from core.constants import AgentID, AlertLevel, ComplianceTag, CredentialCategory
from core.exceptions import EscalationRequired
from schemas.compliance import AuditLogEntry, ComplianceAlert, ComplianceRecord
from .tools import ComplianceTools
from .workflows import ComplianceWorkflow

logger = logging.getLogger(__name__)

ADVERSE_FLAG_TRIGGERS = [
    "sanction", "exclusion", "debarment", "license revocation",
    "license surrender", "probation", "suspension", "adverse action",
    "malpractice judgment", "criminal conviction", "oig exclusion",
    "sam exclusion", "npdb report",
]

PHI_EXPOSURE_PATTERNS = [
    "ssn", "social security", "date of birth", "dob",
    "medical record", "diagnosis", "icd-", "patient",
    "insurance id", "health plan",
]


@dataclass
class AlertSpec:
    """Specification for a compliance alert before it is written."""
    contact_id: str
    alert_level: AlertLevel
    credential_type: str
    expiration_date: str | None
    days_remaining: int | None
    mandatory: bool
    description: str


class ComplianceAgent:
    """
    COMP-001 — Compliance Monitoring Agent.

    Responsibilities:
    - Monitor credential expiration across all active candidates
    - Detect missing mandatory requirements by role and state
    - Generate tiered alerts (red/yellow/blue) with full metadata
    - Preserve immutable audit trail for every state change
    - Detect PHI outside HIPAA-compliant context
    - Escalate: adverse flags, missing mandatory credentials, PHI exposure, audit exceptions
    """

    AGENT_ID = AgentID.COMPLIANCE

    # Alert thresholds
    RED_THRESHOLD_DAYS = 0    # Expired or zero days
    YELLOW_THRESHOLD_DAYS = 30

    def __init__(self, client: anthropic.Anthropic, tools: ComplianceTools | None = None):
        self.client = client
        self.tools = tools or ComplianceTools()
        self.workflow = ComplianceWorkflow(self.tools)

    # ── Main Entry Points ──────────────────────────────────────────────────────

    def run_expiry_scan(self, contact_id: str) -> dict[str, Any]:
        """
        Full expiry scan for a candidate:
        - Check all credentialed docs for expiry
        - Generate alerts by threshold
        - Update compliance tags
        - Return scan summary
        """
        docs = self.tools.get_all_credential_docs(contact_id)
        alerts_created = []
        today = date.today()

        for doc in docs:
            if not doc.get("expiration_date"):
                continue

            exp_date = date.fromisoformat(doc["expiration_date"])
            days_remaining = (exp_date - today).days
            mandatory = doc.get("category", "") in MANDATORY_CREDENTIAL_CATEGORIES

            level = self._determine_alert_level(days_remaining)
            if level:
                spec = AlertSpec(
                    contact_id=contact_id,
                    alert_level=level,
                    credential_type=doc.get("category", "unknown"),
                    expiration_date=doc["expiration_date"],
                    days_remaining=days_remaining,
                    mandatory=mandatory,
                    description=self._build_alert_description(doc, days_remaining, level),
                )
                alert = self.workflow.create_alert(spec)
                alerts_created.append(alert)

        # Update compliance status tag
        overall_status = self._compute_overall_status(alerts_created)
        self.tools.set_compliance_tag(contact_id, overall_status)
        self._write_audit_entry(
            contact_id=contact_id,
            action="EXPIRY_SCAN",
            detail=f"Scan complete. {len(alerts_created)} alerts generated. Status: {overall_status}.",
        )

        return {
            "action": "crm_update",
            "agent_id": self.AGENT_ID,
            "contact_id": contact_id,
            "alerts_count": len(alerts_created),
            "overall_status": overall_status,
            "alerts": alerts_created,
        }

    def run_missing_mandatory_check(self, contact_id: str) -> dict[str, Any]:
        """
        Check for missing mandatory credential categories.
        Missing mandatory = RED alert + escalation.
        """
        missing = self.tools.get_missing_mandatory_categories(
            contact_id, MANDATORY_CREDENTIAL_CATEGORIES
        )

        if not missing:
            return {
                "action": "noop",
                "agent_id": self.AGENT_ID,
                "contact_id": contact_id,
                "missing_mandatory": [],
            }

        alerts = []
        for category in missing:
            spec = AlertSpec(
                contact_id=contact_id,
                alert_level=AlertLevel.RED,
                credential_type=category,
                expiration_date=None,
                days_remaining=None,
                mandatory=True,
                description=f"Mandatory credential '{category}' is missing. Placement blocked.",
            )
            alert = self.workflow.create_alert(spec)
            alerts.append(alert)

        self.tools.set_compliance_tag(contact_id, ComplianceTag.NON_COMPLIANT)
        self._write_audit_entry(
            contact_id=contact_id,
            action="MISSING_MANDATORY_CHECK",
            detail=f"Missing mandatory categories: {missing}. Status set to non_compliant.",
        )

        return self._escalate(
            contact_id=contact_id,
            reason=f"Missing mandatory credentials blocking placement: {missing}",
            alerts=alerts,
        )

    def detect_phi_exposure(self, contact_id: str, content: str, context: str = "") -> dict[str, Any]:
        """
        Scan content for PHI outside HIPAA-compliant context.
        Any detection → immediate escalation + audit entry.
        """
        detected = [p for p in PHI_EXPOSURE_PATTERNS if p in content.lower()]
        if not detected:
            return {"action": "noop", "phi_detected": False}

        reason = (
            f"PHI exposure detected in {context or 'content'}. "
            f"Patterns found: {detected}. Immediate review required."
        )
        self._write_audit_entry(
            contact_id=contact_id,
            action="PHI_EXPOSURE_DETECTED",
            detail=reason,
            escalated=True,
        )
        self.tools.set_compliance_tag(contact_id, ComplianceTag.ESCALATED)

        return self._escalate(contact_id=contact_id, reason=reason)

    def check_adverse_flags(self, contact_id: str, content: str) -> dict[str, Any]:
        """
        Scan content for adverse compliance flags (sanctions, exclusions, revocations).
        Any match → escalate immediately.
        """
        found = [t for t in ADVERSE_FLAG_TRIGGERS if t in content.lower()]
        if not found:
            return {"action": "noop", "adverse_flags": []}

        reason = f"Adverse compliance flag detected: {found}. Human review required immediately."
        self._write_audit_entry(
            contact_id=contact_id,
            action="ADVERSE_FLAG_DETECTED",
            detail=reason,
            escalated=True,
        )
        return self._escalate(contact_id=contact_id, reason=reason)

    def log_audit_event(
        self,
        contact_id: str,
        action: str,
        detail: str,
        agent_id: str = "",
        channel: str = "system",
    ) -> AuditLogEntry:
        """
        Public method for other agents to write audit entries through COMP-001.
        Enforces append-only immutability.
        """
        return self._write_audit_entry(
            contact_id=contact_id,
            action=action,
            detail=detail,
            source_agent=agent_id or self.AGENT_ID,
            channel=channel,
        )

    def get_compliance_report(self, contact_id: str) -> dict[str, Any]:
        """Return full compliance record for a candidate."""
        record = self.tools.get_compliance_record(contact_id)
        return {
            "contact_id": contact_id,
            "overall_status": record.overall_status,
            "active_alerts": len(record.active_alerts),
            "red_alerts": len(record.red_alerts),
            "phi_exposure_detected": record.phi_exposure_detected,
            "audit_entries": len(record.audit_log),
            "last_reviewed": record.last_reviewed.isoformat() if record.last_reviewed else None,
        }

    # ── Internal ───────────────────────────────────────────────────────────────

    def _determine_alert_level(self, days_remaining: int) -> AlertLevel | None:
        if days_remaining <= self.RED_THRESHOLD_DAYS:
            return AlertLevel.RED
        if days_remaining <= self.YELLOW_THRESHOLD_DAYS:
            return AlertLevel.YELLOW
        return None

    def _build_alert_description(self, doc: dict, days_remaining: int, level: AlertLevel) -> str:
        category = doc.get("category", "credential")
        exp = doc.get("expiration_date", "unknown")
        if level == AlertLevel.RED:
            return f"{category} has expired or expires today ({exp}). Placement blocked."
        return f"{category} expires in {days_remaining} days ({exp})."

    def _compute_overall_status(self, alerts: list[dict]) -> str:
        if any(a.get("alert_level") == AlertLevel.RED for a in alerts):
            return ComplianceTag.NON_COMPLIANT
        if any(a.get("alert_level") == AlertLevel.YELLOW for a in alerts):
            return ComplianceTag.AT_RISK
        return ComplianceTag.COMPLIANT

    def _write_audit_entry(
        self,
        contact_id: str,
        action: str,
        detail: str,
        source_agent: str = "",
        channel: str = "system",
        escalated: bool = False,
    ) -> AuditLogEntry:
        import uuid
        entry = AuditLogEntry(
            log_id=str(uuid.uuid4()),
            agent_id=source_agent or self.AGENT_ID,
            contact_id=contact_id,
            action=action,
            detail=detail,
            channel=channel,
            escalated=escalated,
        )
        self.tools.append_audit_log(entry)
        return entry

    def _escalate(
        self,
        contact_id: str,
        reason: str,
        alerts: list[dict] | None = None,
    ) -> dict[str, Any]:
        logger.warning("[COMP-001] Escalating contact=%s reason=%s", contact_id, reason)
        self.tools.add_crm_tags(contact_id, [ComplianceTag.HUMAN_ESCALATION_REQUIRED])
        self.tools.add_crm_note(
            contact_id,
            f"[COMP-001] Escalated to compliance officer. Reason: {reason}",
        )
        return {
            "action": "escalate",
            "agent_id": self.AGENT_ID,
            "content": "A compliance issue requires immediate human review.",
            "escalation_reason": reason,
            "alerts": alerts or [],
            "crm_updates": {
                "tags_add": [ComplianceTag.HUMAN_ESCALATION_REQUIRED],
                "note": f"[COMP-001] Escalated. Reason: {reason}",
            },
        }
