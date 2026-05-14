"""
Workflow Executor — routes GHL stage-change webhooks to the correct workflow.
Single entry point: WorkflowExecutor.run(event) called from the GHL webhook handler.

Supported trigger events:
  - contact.stage_changed     → pipeline stage automation
  - contact.tag_added         → tag-driven workflow side effects
  - document.uploaded         → credential classification + checklist update
  - compliance.expiry_check   → scheduled expiry scan (called by cron endpoint)
  - lead.qualified            → BANT-complete handoff to sales
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .candidate_intake import CandidateIntakeWorkflow
from .credentialing import CredentialingPipelineWorkflow
from .compliance_monitoring import ComplianceMonitoringWorkflow
from .sales_qualification import SalesQualificationWorkflow
from core.constants import PipelineStage, ComplianceTag
from audit_log import get_audit_logger

logger = logging.getLogger(__name__)
_audit = get_audit_logger()


@dataclass
class WorkflowEvent:
    """Normalised internal event consumed by the executor."""
    event_type: str
    contact_id: str
    agent_id: str = "ORCH-001"
    session_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class WorkflowResult:
    success: bool
    event_type: str
    contact_id: str
    actions_taken: list[str] = field(default_factory=list)
    crm_updates: dict[str, Any] = field(default_factory=dict)
    escalation: dict[str, Any] | None = None
    error: str = ""


class WorkflowExecutor:
    """
    Central dispatcher for all workflow automation.

    Wires together the four workflow classes with real CRM/tool adapters
    at construction time, then routes each WorkflowEvent to the correct handler.

    Usage:
        executor = WorkflowExecutor(crm_tools=ghl_client)
        result = executor.run(WorkflowEvent(
            event_type="contact.stage_changed",
            contact_id="c-123",
            data={"from_stage": "new_lead", "candidate_data": {...}},
        ))
    """

    def __init__(
        self,
        crm_tools=None,
        cred_tools=None,
        comp_tools=None,
        rec_tools=None,
    ):
        self.intake     = CandidateIntakeWorkflow(crm_tools=crm_tools, rec_tools=rec_tools)
        self.credential = CredentialingPipelineWorkflow(cred_tools=cred_tools, comp_tools=comp_tools, crm_tools=crm_tools)
        self.compliance = ComplianceMonitoringWorkflow(comp_tools=comp_tools, crm_tools=crm_tools)
        self.sales      = SalesQualificationWorkflow(crm_tools=crm_tools)

        # Routing table: event_type → handler method
        self._handlers = {
            "contact.stage_changed":   self._handle_stage_changed,
            "contact.tag_added":       self._handle_tag_added,
            "document.uploaded":       self._handle_document_uploaded,
            "compliance.expiry_check": self._handle_expiry_check,
            "lead.qualified":          self._handle_lead_qualified,
        }

    def run(self, event: WorkflowEvent) -> WorkflowResult:
        handler = self._handlers.get(event.event_type)
        if not handler:
            logger.warning("[WF] Unknown event_type=%s contact=%s", event.event_type, event.contact_id)
            return WorkflowResult(
                success=False,
                event_type=event.event_type,
                contact_id=event.contact_id,
                error=f"No handler for event_type '{event.event_type}'",
            )

        try:
            result = handler(event)
            _audit.log_agent_action(
                agent_id=event.agent_id,
                contact_id=event.contact_id,
                action=f"workflow:{event.event_type}",
                detail=f"actions={result.actions_taken}",
                session_id=event.session_id,
            )
            return result
        except Exception as exc:
            logger.error("[WF] Handler error event=%s contact=%s: %s", event.event_type, event.contact_id, exc)
            _audit.log_agent_action(
                agent_id=event.agent_id,
                contact_id=event.contact_id,
                action=f"workflow_error:{event.event_type}",
                detail=str(exc),
            )
            return WorkflowResult(
                success=False,
                event_type=event.event_type,
                contact_id=event.contact_id,
                error=str(exc),
            )

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _handle_stage_changed(self, event: WorkflowEvent) -> WorkflowResult:
        """
        A GHL pipeline stage change fires here.
        Routes to the appropriate workflow step.
        """
        from_stage = event.data.get("from_stage", "")
        candidate_data = event.data.get("candidate_data", {})
        actions = []
        crm_updates = {}
        escalation = None

        # new_lead → intake_in_progress: fire first message sequence
        if from_stage == PipelineStage.NEW_LEAD:
            result = self.intake.advance_stage(
                event.contact_id, PipelineStage.NEW_LEAD, candidate_data
            )
            actions.append(f"stage_advanced:{PipelineStage.NEW_LEAD}→{result.get('to_stage','?')}")
            crm_updates = result.get("crm_updates", {})

        # intake_complete → credentialing: full handoff + doc requests
        elif from_stage == PipelineStage.INTAKE_COMPLETE:
            result = self.intake.trigger_credentialing_handoff(event.contact_id, candidate_data)
            actions.append("credentialing_handoff_triggered")
            actions.extend(f"doc_request:{r['category']}" for r in result.get("credentialing_requests", []))
            crm_updates = result.get("crm_updates", {})

        # credentialing: check if complete → route to specialist
        elif from_stage == PipelineStage.CREDENTIALING:
            status = self.credential.get_status(event.contact_id)
            if status.ready_for_review:
                result = self.credential.route_to_specialist(event.contact_id)
                actions.append("routed_to_specialist")
                crm_updates = result.get("crm_updates", {})
                escalation = {"reason": "credential_approval", "severity": "high"}
            else:
                missing = status.categories_missing
                actions.append(f"credentialing_incomplete:missing={missing}")

        logger.info("[WF] stage_changed contact=%s from=%s actions=%s", event.contact_id, from_stage, actions)

        return WorkflowResult(
            success=True,
            event_type=event.event_type,
            contact_id=event.contact_id,
            actions_taken=actions,
            crm_updates=crm_updates,
            escalation=escalation,
        )

    def _handle_tag_added(self, event: WorkflowEvent) -> WorkflowResult:
        """
        Tag addition side effects:
          human_escalation_required → create escalation ticket
          at_risk / non_compliant   → trigger compliance workflow
        """
        tag = event.data.get("tag", "")
        actions = []

        if tag == ComplianceTag.HUMAN_ESCALATION_REQUIRED:
            actions.append("escalation_ticket_queued")

        elif tag in (ComplianceTag.AT_RISK, ComplianceTag.NON_COMPLIANT):
            alert_result = self.compliance.generate_alert(
                contact_id=event.contact_id,
                alert_type=tag,
                detail=event.data.get("detail", ""),
            )
            actions.append(f"compliance_alert:{alert_result.get('alert_level','?')}")

        return WorkflowResult(
            success=True,
            event_type=event.event_type,
            contact_id=event.contact_id,
            actions_taken=actions,
        )

    def _handle_document_uploaded(self, event: WorkflowEvent) -> WorkflowResult:
        """
        A credential document was uploaded.
        CRED-001 classifies, updates checklist, checks if credentialing is complete.
        """
        filename     = event.data.get("filename", "")
        document_id  = event.data.get("document_id", "")
        actions      = [f"document_received:{filename}"]
        crm_updates  = {}
        escalation   = None

        # Check if credentialing is now complete
        status = self.credential.get_status(event.contact_id)
        if status.ready_for_review:
            result = self.credential.route_to_specialist(event.contact_id)
            actions.append("credentialing_complete_routed_to_specialist")
            crm_updates = result.get("crm_updates", {})
            escalation = {"reason": "credential_approval", "severity": "high"}

        return WorkflowResult(
            success=True,
            event_type=event.event_type,
            contact_id=event.contact_id,
            actions_taken=actions,
            crm_updates=crm_updates,
            escalation=escalation,
        )

    def _handle_expiry_check(self, event: WorkflowEvent) -> WorkflowResult:
        """
        Scheduled expiry scan — called by the /internal/expiry-check cron endpoint.
        Runs reminders for the contact specified in event.data, or system-wide.
        """
        phone  = event.data.get("phone", "")
        email  = event.data.get("email", "")
        results = self.credential.run_expiry_reminders(event.contact_id, phone, email)

        actions = [f"reminder_sent:{r.get('category','?')}" for r in results]

        if not actions:
            actions = ["no_expiring_documents"]

        return WorkflowResult(
            success=True,
            event_type=event.event_type,
            contact_id=event.contact_id,
            actions_taken=actions,
        )

    def _handle_lead_qualified(self, event: WorkflowEvent) -> WorkflowResult:
        """BANT complete — hand off to SALES-001 appointment booking."""
        result = self.sales.schedule_discovery_call(
            contact_id=event.contact_id,
            lead_data=event.data.get("lead_data", {}),
        )
        return WorkflowResult(
            success=True,
            event_type=event.event_type,
            contact_id=event.contact_id,
            actions_taken=["sales_discovery_call_scheduled"],
            crm_updates=result.get("crm_updates", {}),
        )
