"""
Compliance Monitoring Workflow
Scheduled and event-driven compliance checks across all active candidates.

Runs:
  - Daily expiry scan (cron)
  - Missing mandatory check (on pipeline stage change)
  - PHI exposure scan (on every CRM note write)
  - Adverse flag check (on document receipt / external data ingestion)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.constants import AlertLevel, ComplianceTag

logger = logging.getLogger(__name__)


@dataclass
class ComplianceScanResult:
    scan_id: str
    scanned_contacts: int = 0
    alerts_generated: int = 0
    escalations_triggered: int = 0
    red_alerts: int = 0
    yellow_alerts: int = 0
    phi_exposures: int = 0
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ComplianceMonitoringWorkflow:
    """
    Orchestrates compliance monitoring runs across the candidate population.
    Coordinates COMP-001 and CRM-001 for bulk and per-contact scans.
    """

    def __init__(self, comp_tools=None, crm_tools=None, cred_tools=None):
        self._comp = comp_tools
        self._crm = crm_tools
        self._cred = cred_tools

    def run_daily_scan(self, contact_ids: list[str]) -> ComplianceScanResult:
        """
        Daily cron job: scan all active candidates for expiring credentials.
        Called by the Redis worker or AWS scheduled Lambda.
        """
        import uuid, time
        scan_id = f"SCAN-{str(uuid.uuid4())[:8].upper()}"
        start = time.monotonic()
        result = ComplianceScanResult(scan_id=scan_id, scanned_contacts=len(contact_ids))

        for contact_id in contact_ids:
            if not self._comp:
                continue
            scan = self._comp.run_expiry_scan(contact_id)
            alerts = scan.get("alerts", [])
            result.alerts_generated += len(alerts)
            for alert in alerts:
                level = alert.get("alert_level")
                if level == AlertLevel.RED:
                    result.red_alerts += 1
                    result.escalations_triggered += 1
                elif level == AlertLevel.YELLOW:
                    result.yellow_alerts += 1

        result.duration_ms = (time.monotonic() - start) * 1000

        logger.info(
            "[COMP-WF] Daily scan complete scan_id=%s contacts=%d alerts=%d red=%d yellow=%d",
            scan_id, result.scanned_contacts, result.alerts_generated,
            result.red_alerts, result.yellow_alerts,
        )
        return result

    def check_on_stage_change(
        self, contact_id: str, new_stage: str
    ) -> dict[str, Any]:
        """
        Triggered when a candidate's pipeline stage changes.
        Runs missing mandatory check for placement-blocking stages.
        """
        placement_critical_stages = {"credentialing", "credentialing_complete", "placed"}
        if new_stage not in placement_critical_stages or not self._comp:
            return {"action": "noop", "contact_id": contact_id}

        result = self._comp.run_missing_mandatory_check(contact_id)
        logger.info(
            "[COMP-WF] Stage-change compliance check contact=%s stage=%s action=%s",
            contact_id, new_stage, result.get("action"),
        )
        return result

    def scan_content_for_phi(
        self, contact_id: str, content: str, context: str
    ) -> dict[str, Any]:
        """
        Scan any content being written to CRM for PHI outside HIPAA context.
        Called before every CRM note write by CRM-001.
        """
        if not self._comp:
            return {"action": "noop", "phi_detected": False}
        return self._comp.detect_phi_exposure(contact_id, content, context)

    def check_adverse_flags(self, contact_id: str, content: str) -> dict[str, Any]:
        """Run adverse flag scan on inbound document or data content."""
        if not self._comp:
            return {"action": "noop", "adverse_flags": []}
        return self._comp.check_adverse_flags(contact_id, content)

    def generate_population_report(self, contact_ids: list[str]) -> dict[str, Any]:
        """
        Generate a compliance summary across a population of contacts.
        Used for dashboard and reporting.
        """
        total = len(contact_ids)
        statuses: dict[str, int] = {
            ComplianceTag.COMPLIANT: 0,
            ComplianceTag.AT_RISK: 0,
            ComplianceTag.NON_COMPLIANT: 0,
            ComplianceTag.ESCALATED: 0,
        }

        if self._comp:
            for contact_id in contact_ids:
                record = self._comp.tools.get_compliance_record(contact_id) if hasattr(self._comp, "tools") else None
                if record:
                    statuses[record.overall_status] = statuses.get(record.overall_status, 0) + 1

        return {
            "total_candidates": total,
            "compliant": statuses[ComplianceTag.COMPLIANT],
            "at_risk": statuses[ComplianceTag.AT_RISK],
            "non_compliant": statuses[ComplianceTag.NON_COMPLIANT],
            "escalated": statuses[ComplianceTag.ESCALATED],
            "compliance_rate_pct": round(
                statuses[ComplianceTag.COMPLIANT] / total * 100, 1
            ) if total else 0.0,
        }

    def generate_alert(
        self,
        contact_id: str,
        alert_type: str,
        detail: str = "",
    ) -> dict:
        """
        Generate a compliance alert for a specific contact.
        Called by the WorkflowExecutor when a compliance tag is added.
        """
        from core.constants import AlertLevel
        alert_level = (
            AlertLevel.RED if alert_type == "non_compliant"
            else AlertLevel.YELLOW
        )

        if self._crm:
            self._crm.add_note(
                contact_id,
                f"[COMP-001] Compliance alert level={alert_level}. "
                f"type={alert_type}. {detail}",
            )

        logger.info(
            "[COMP-WF] Alert generated contact=%s type=%s level=%s",
            contact_id, alert_type, alert_level,
        )

        return {
            "contact_id": contact_id,
            "alert_type": alert_type,
            "alert_level": alert_level,
            "detail": detail,
        }
