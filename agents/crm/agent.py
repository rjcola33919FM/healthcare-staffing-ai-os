"""
CRM-001 — CRM Operations Agent
Full implementation: contact management, tags, pipeline, notes, tasks, webhook sync, escalation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import anthropic

from core.constants import AgentID, ComplianceTag, PipelineStage
from core.exceptions import CRMSyncError, EscalationRequired
from .tools import CRMTools
from .workflows import CRMWorkflow

logger = logging.getLogger(__name__)

Operation = Literal[
    "note", "tag_add", "tag_remove", "stage_change",
    "task_create", "field_update", "webhook_sync",
    "merge", "delete", "archive",
]

ESCALATION_OPERATIONS = {"merge", "delete"}


@dataclass
class CRMOperation:
    operation: Operation
    contact_id: str
    payload: dict[str, Any]
    source_agent: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CRMOperationResult:
    success: bool
    operation: Operation
    contact_id: str
    escalated: bool = False
    escalation_reason: str | None = None
    crm_response: dict[str, Any] = field(default_factory=dict)
    note_logged: bool = False


class CRMAgent:
    """
    CRM-001 — CRM Operations Agent.

    Responsibilities:
    - Validate contact_id exists before any write
    - Apply tags, update fields, move pipeline stages
    - Create tasks with assignee and due date
    - Log structured audit notes for every agent action
    - Process inbound GHL webhooks and sync state
    - Escalate: merges, deletions, integration failures, ambiguous identity matches

    Note format: [AGENT_ID] [ISO_TIMESTAMP] [OPERATION]: [DETAIL]
    """

    AGENT_ID = AgentID.CRM
    PROTECTED_STAGES = {PipelineStage.PLACED, PipelineStage.INACTIVE}
    ESCALATION_OPERATIONS = {"merge", "delete"}

    def __init__(self, client: anthropic.Anthropic, tools: CRMTools | None = None):
        self.client = client
        self.tools = tools or CRMTools()
        self.workflow = CRMWorkflow(self.tools)

    def execute(self, op: CRMOperation) -> CRMOperationResult:
        """
        Execute a CRM operation with validation, audit logging, and escalation guard.
        """
        logger.info(
            "[CRM-001] execute op=%s contact=%s source=%s",
            op.operation, op.contact_id, op.source_agent,
        )

        # Escalate destructive operations immediately
        if op.operation in self.ESCALATION_OPERATIONS:
            return self._escalate_operation(op, f"{op.operation} requires human approval.")

        # Validate contact exists
        contact = self.tools.get_contact(op.contact_id)
        if not contact:
            return self._escalate_operation(
                op, f"contact_id={op.contact_id} not found in CRM."
            )

        # Dispatch to operation handler
        handler = {
            "note":          self._handle_note,
            "tag_add":       self._handle_tag_add,
            "tag_remove":    self._handle_tag_remove,
            "stage_change":  self._handle_stage_change,
            "task_create":   self._handle_task_create,
            "field_update":  self._handle_field_update,
            "webhook_sync":  self._handle_webhook_sync,
            "archive":       self._handle_archive,
        }.get(op.operation)

        if not handler:
            return self._escalate_operation(op, f"Unknown operation: {op.operation}")

        result = handler(op)
        self._write_audit_note(op, result)
        return result

    # ── Operation Handlers ─────────────────────────────────────────────────────

    def _handle_note(self, op: CRMOperation) -> CRMOperationResult:
        note_body = op.payload.get("note", "")
        formatted = self._format_note(op.source_agent, op.operation, note_body)
        self.tools.add_note(op.contact_id, formatted)
        return CRMOperationResult(
            success=True, operation=op.operation, contact_id=op.contact_id, note_logged=True,
        )

    def _handle_tag_add(self, op: CRMOperation) -> CRMOperationResult:
        tags = op.payload.get("tags", [])
        self.tools.add_tags(op.contact_id, tags)
        return CRMOperationResult(
            success=True, operation=op.operation, contact_id=op.contact_id,
            crm_response={"tags_added": tags},
        )

    def _handle_tag_remove(self, op: CRMOperation) -> CRMOperationResult:
        tags = op.payload.get("tags", [])
        self.tools.remove_tags(op.contact_id, tags)
        return CRMOperationResult(
            success=True, operation=op.operation, contact_id=op.contact_id,
            crm_response={"tags_removed": tags},
        )

    def _handle_stage_change(self, op: CRMOperation) -> CRMOperationResult:
        new_stage = op.payload.get("stage")
        if not new_stage:
            return CRMOperationResult(
                success=False, operation=op.operation, contact_id=op.contact_id,
                escalated=True, escalation_reason="stage_change missing 'stage' field.",
            )
        self.tools.update_pipeline_stage(op.contact_id, new_stage)
        return CRMOperationResult(
            success=True, operation=op.operation, contact_id=op.contact_id,
            crm_response={"new_stage": new_stage},
        )

    def _handle_task_create(self, op: CRMOperation) -> CRMOperationResult:
        task = self.tools.create_task(
            contact_id=op.contact_id,
            title=op.payload.get("title", "Follow-up task"),
            due_date=op.payload.get("due_date", ""),
            assignee_id=op.payload.get("assignee_id", ""),
            description=op.payload.get("description", ""),
        )
        return CRMOperationResult(
            success=True, operation=op.operation, contact_id=op.contact_id,
            crm_response={"task": task},
        )

    def _handle_field_update(self, op: CRMOperation) -> CRMOperationResult:
        fields = op.payload.get("fields", {})
        if not fields:
            return CRMOperationResult(success=False, operation=op.operation, contact_id=op.contact_id)
        self.tools.update_contact(op.contact_id, fields)
        return CRMOperationResult(
            success=True, operation=op.operation, contact_id=op.contact_id,
            crm_response={"updated_fields": list(fields.keys())},
        )

    def _handle_webhook_sync(self, op: CRMOperation) -> CRMOperationResult:
        """Log webhook payload receipt before processing."""
        webhook_id = op.payload.get("webhook_id", "unknown")
        self.tools.add_note(
            op.contact_id,
            self._format_note(op.source_agent, "WEBHOOK_RECEIVED", f"webhook_id={webhook_id}"),
        )
        return self.workflow.process_webhook(op)

    def _handle_archive(self, op: CRMOperation) -> CRMOperationResult:
        """Archive contact — never delete records with placement history."""
        self.tools.add_tags(op.contact_id, [PipelineStage.INACTIVE])
        self.tools.update_pipeline_stage(op.contact_id, PipelineStage.INACTIVE)
        self.tools.add_note(
            op.contact_id,
            self._format_note(op.source_agent, "ARCHIVE", "Contact archived. Record preserved."),
        )
        return CRMOperationResult(
            success=True, operation=op.operation, contact_id=op.contact_id,
            crm_response={"archived": True},
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _format_note(self, agent_id: str, operation: str, detail: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return f"[{agent_id}] [{ts}] [{operation.upper()}]: {detail}"

    def _write_audit_note(self, op: CRMOperation, result: CRMOperationResult) -> None:
        if result.note_logged:
            return
        note = self._format_note(
            op.source_agent,
            op.operation,
            f"success={result.success} escalated={result.escalated}",
        )
        try:
            self.tools.add_note(op.contact_id, note)
        except Exception as e:
            logger.error("[CRM-001] Audit note write failed: %s", e)

    def _escalate_operation(self, op: CRMOperation, reason: str) -> CRMOperationResult:
        logger.warning("[CRM-001] Escalating op=%s contact=%s reason=%s", op.operation, op.contact_id, reason)
        try:
            self.tools.add_tags(op.contact_id, [ComplianceTag.HUMAN_ESCALATION_REQUIRED])
            self.tools.add_note(
                op.contact_id,
                self._format_note("CRM-001", "ESCALATION", reason),
            )
        except Exception:
            pass
        return CRMOperationResult(
            success=False,
            operation=op.operation,
            contact_id=op.contact_id,
            escalated=True,
            escalation_reason=reason,
        )

    def apply_agent_response_updates(
        self, contact_id: str, crm_updates: dict[str, Any], source_agent: str
    ) -> list[CRMOperationResult]:
        """
        Convenience method: apply a crm_updates dict from any AgentResponse.
        Used by the orchestrator after every agent run.
        """
        results = []

        if tags := crm_updates.get("tags_add"):
            results.append(self.execute(CRMOperation(
                operation="tag_add", contact_id=contact_id,
                payload={"tags": tags}, source_agent=source_agent,
            )))

        if tags := crm_updates.get("tags_remove"):
            results.append(self.execute(CRMOperation(
                operation="tag_remove", contact_id=contact_id,
                payload={"tags": tags}, source_agent=source_agent,
            )))

        if fields := crm_updates.get("fields"):
            results.append(self.execute(CRMOperation(
                operation="field_update", contact_id=contact_id,
                payload={"fields": fields}, source_agent=source_agent,
            )))

        if note := crm_updates.get("note"):
            results.append(self.execute(CRMOperation(
                operation="note", contact_id=contact_id,
                payload={"note": note}, source_agent=source_agent,
            )))

        if task := crm_updates.get("task"):
            results.append(self.execute(CRMOperation(
                operation="task_create", contact_id=contact_id,
                payload=task, source_agent=source_agent,
            )))

        return results
