"""
CRM-001 Workflows — Multi-step CRM state transitions.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from core.constants import PipelineStage, ComplianceTag

if TYPE_CHECKING:
    from .agent import CRMOperation, CRMOperationResult
    from .tools import CRMTools

logger = logging.getLogger(__name__)


class CRMWorkflow:
    def __init__(self, tools: "CRMTools"):
        self.tools = tools

    def process_webhook(self, op: "CRMOperation") -> "CRMOperationResult":
        """
        Process a GHL inbound webhook:
        1. Log raw payload
        2. Identify event type
        3. Apply CRM updates
        4. Return result
        """
        from .agent import CRMOperationResult

        payload = op.payload
        webhook_id = payload.get("webhook_id", "unknown")
        event_type = payload.get("event_type", "unknown")

        self.tools.log_webhook(op.contact_id, webhook_id, payload)

        # Map event_type to CRM action
        if event_type == "form_submitted":
            fields = payload.get("form_fields", {})
            if fields:
                self.tools.update_contact(op.contact_id, fields)
                self.tools.add_note(
                    op.contact_id,
                    f"[CRM-001] Form submission received. webhook_id={webhook_id}. Fields: {list(fields.keys())}.",
                )

        elif event_type == "appointment_booked":
            self.tools.add_tags(op.contact_id, ["appointment_booked"])
            self.tools.add_note(
                op.contact_id,
                f"[CRM-001] Appointment booking webhook received. webhook_id={webhook_id}.",
            )

        elif event_type == "document_uploaded":
            self.tools.add_tags(op.contact_id, ["document_received"])
            self.tools.update_pipeline_stage(op.contact_id, PipelineStage.CREDENTIALING)
            self.tools.add_note(
                op.contact_id,
                f"[CRM-001] Document upload webhook received. webhook_id={webhook_id}.",
            )

        logger.info("[CRM-WORKFLOW] Webhook processed webhook_id=%s event=%s", webhook_id, event_type)

        return CRMOperationResult(
            success=True,
            operation="webhook_sync",
            contact_id=op.contact_id,
            crm_response={"webhook_id": webhook_id, "event_type": event_type},
            note_logged=True,
        )

    def promote_stage(
        self,
        contact_id: str,
        from_stage: str,
        to_stage: str,
        reason: str,
        source_agent: str,
    ) -> dict[str, Any]:
        """
        Move a contact's pipeline stage with full audit trail.
        """
        self.tools.update_pipeline_stage(contact_id, to_stage)
        self.tools.add_tags(contact_id, [to_stage])
        self.tools.remove_tags(contact_id, [from_stage])
        self.tools.add_note(
            contact_id,
            f"[{source_agent}] Stage moved: {from_stage} → {to_stage}. Reason: {reason}.",
        )
        logger.info(
            "[CRM-WORKFLOW] Stage promoted contact=%s %s→%s",
            contact_id, from_stage, to_stage,
        )
        return {
            "action": "crm_update",
            "agent_id": "CRM-001",
            "contact_id": contact_id,
            "from_stage": from_stage,
            "to_stage": to_stage,
        }

    def flag_identity_conflict(self, contact_id: str, duplicate_ids: list[str]) -> dict[str, Any]:
        """
        Flag a merge conflict for human resolution.
        Applies human_escalation_required tag and logs the conflict.
        """
        self.tools.add_tags(contact_id, [ComplianceTag.HUMAN_ESCALATION_REQUIRED])
        self.tools.add_note(
            contact_id,
            f"[CRM-001] Identity conflict detected. Possible duplicates: {duplicate_ids}. "
            f"Human review required.",
        )
        logger.warning(
            "[CRM-WORKFLOW] Identity conflict contact=%s duplicates=%s",
            contact_id, duplicate_ids,
        )
        return {
            "action": "escalate",
            "agent_id": "CRM-001",
            "contact_id": contact_id,
            "escalation_reason": f"Identity conflict with contacts: {duplicate_ids}",
        }
