"""
COMP-001 Workflows — Alert creation, compliance state transitions, reporting.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, TYPE_CHECKING

from core.constants import AlertLevel, ComplianceTag
from schemas.compliance import ComplianceAlert

if TYPE_CHECKING:
    from .agent import AlertSpec
    from .tools import ComplianceTools

logger = logging.getLogger(__name__)

# GHL task titles per alert level
ALERT_TASK_TITLES: dict[str, str] = {
    AlertLevel.RED:    "URGENT: Expired/missing credential — placement blocked",
    AlertLevel.YELLOW: "Action required: Credential expiring within 30 days",
    AlertLevel.BLUE:   "Document received — classification pending",
}

ALERT_TAGS: dict[str, str] = {
    AlertLevel.RED:    ComplianceTag.NON_COMPLIANT,
    AlertLevel.YELLOW: ComplianceTag.AT_RISK,
    AlertLevel.BLUE:   ComplianceTag.PENDING_REVIEW,
}


class ComplianceWorkflow:
    def __init__(self, tools: "ComplianceTools"):
        self.tools = tools

    def create_alert(self, spec: "AlertSpec") -> dict[str, Any]:
        """
        Full alert creation sequence:
        1. Write ComplianceAlert to record
        2. Apply compliance tag in CRM
        3. Create GHL task for human review (red/yellow)
        4. Log audit entry
        5. Return alert dict with required fields
        """
        alert = self.tools.create_alert(
            contact_id=spec.contact_id,
            alert_level=spec.alert_level,
            credential_type=spec.credential_type,
            description=spec.description,
            expiration_date=spec.expiration_date,
            days_remaining=spec.days_remaining,
            mandatory=spec.mandatory,
        )

        # Apply tag
        tag = ALERT_TAGS.get(spec.alert_level, ComplianceTag.AT_RISK)
        self.tools.add_crm_tags(spec.contact_id, [tag])

        # CRM note — required fields per spec
        note = (
            f"[COMP-001] {spec.alert_level.upper()} ALERT — "
            f"candidate_id={spec.contact_id} "
            f"credential_type={spec.credential_type} "
            f"expiration_date={spec.expiration_date or 'N/A'} "
            f"days_remaining={spec.days_remaining if spec.days_remaining is not None else 'N/A'} "
            f"mandatory={spec.mandatory}. "
            f"{spec.description}"
        )
        self.tools.add_crm_note(spec.contact_id, note)

        # Create task for actionable alerts
        if spec.alert_level in (AlertLevel.RED, AlertLevel.YELLOW):
            due_days = 1 if spec.alert_level == AlertLevel.RED else 7
            due_date = (date.today() + timedelta(days=due_days)).isoformat()
            self.tools.create_task(
                contact_id=spec.contact_id,
                title=ALERT_TASK_TITLES[spec.alert_level],
                due_date=due_date,
            )

        logger.info(
            "[COMP-WF] Alert created contact=%s level=%s type=%s",
            spec.contact_id, spec.alert_level, spec.credential_type,
        )

        return {
            "alert_id": alert.alert_id,
            "alert_level": spec.alert_level,
            "credential_type": spec.credential_type,
            "expiration_date": spec.expiration_date,
            "days_remaining": spec.days_remaining,
            "mandatory": spec.mandatory,
            "description": spec.description,
        }

    def resolve_alert_workflow(
        self,
        contact_id: str,
        alert_id: str,
        resolved_by: str,
    ) -> dict[str, Any]:
        """
        Mark an alert as resolved and log the resolution.
        Recompute overall compliance status after resolution.
        """
        resolved = self.tools.resolve_alert(contact_id, alert_id)
        if not resolved:
            return {"success": False, "alert_id": alert_id}

        self.tools.add_crm_note(
            contact_id,
            f"[COMP-001] Alert {alert_id} resolved by {resolved_by}.",
        )

        # Recompute overall status
        record = self.tools.get_compliance_record(contact_id)
        if not record.red_alerts:
            new_status = ComplianceTag.AT_RISK if record.active_alerts else ComplianceTag.COMPLIANT
            self.tools.set_compliance_tag(contact_id, new_status)

        logger.info("[COMP-WF] Alert resolved contact=%s alert_id=%s", contact_id, alert_id)

        return {"success": True, "alert_id": alert_id, "resolved_by": resolved_by}

    def generate_compliance_report(self, contact_id: str) -> dict[str, Any]:
        """
        Build a structured compliance report for dashboard or human review.
        """
        record = self.tools.get_compliance_record(contact_id)
        return {
            "contact_id": contact_id,
            "overall_status": record.overall_status,
            "total_alerts": len(record.alerts),
            "active_alerts": len(record.active_alerts),
            "red_alerts": [
                {
                    "alert_id": a.alert_id,
                    "credential_type": a.credential_type,
                    "expiration_date": a.expiration_date,
                    "days_remaining": a.days_remaining,
                    "mandatory": a.mandatory,
                }
                for a in record.red_alerts
            ],
            "phi_exposure_detected": record.phi_exposure_detected,
            "audit_entries": len(record.audit_log),
            "last_reviewed": record.last_reviewed.isoformat() if record.last_reviewed else None,
        }
