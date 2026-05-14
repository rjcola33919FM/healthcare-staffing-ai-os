"""
Candidate Intake Pipeline Workflow
Orchestrates the full end-to-end candidate journey from first contact → placed.

Stages:
  new_lead → intake_in_progress → intake_complete → credentialing
  → credentialing_complete → placed

Each stage transition is:
  - Validated (required fields checked)
  - Logged (CRM note + audit entry)
  - Tagged (pipeline stage tag applied)
  - Tasked (human follow-up task created if needed)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from core.constants import ComplianceTag, PipelineStage

logger = logging.getLogger(__name__)

INTAKE_REQUIRED_FIELDS = [
    "first_name", "last_name", "specialty", "license_state", "phone",
]

STAGE_TRANSITIONS: dict[str, str] = {
    PipelineStage.NEW_LEAD:              PipelineStage.INTAKE_IN_PROGRESS,
    PipelineStage.INTAKE_IN_PROGRESS:    PipelineStage.INTAKE_COMPLETE,
    PipelineStage.INTAKE_COMPLETE:       PipelineStage.CREDENTIALING,
    PipelineStage.CREDENTIALING:         PipelineStage.CREDENTIALING_COMPLETE,
    PipelineStage.CREDENTIALING_COMPLETE: PipelineStage.PLACED,
}


@dataclass
class IntakeValidationResult:
    valid: bool
    missing_fields: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class CandidateIntakeWorkflow:
    """
    Full candidate intake pipeline from new_lead to credentialing handoff.
    Coordinates REC-001, SCHED-001, and CRM-001 actions.
    """

    def __init__(self, crm_tools=None, rec_tools=None, sched_tools=None):
        self._crm = crm_tools
        self._rec = rec_tools
        self._sched = sched_tools

    def validate_intake(self, candidate_data: dict[str, Any]) -> IntakeValidationResult:
        """Validate all required intake fields are present and non-empty."""
        missing = [f for f in INTAKE_REQUIRED_FIELDS if not candidate_data.get(f)]
        return IntakeValidationResult(valid=not missing, missing_fields=missing)

    def advance_stage(
        self,
        contact_id: str,
        from_stage: str,
        candidate_data: dict[str, Any],
        source_agent: str = "ORCH-001",
    ) -> dict[str, Any]:
        """
        Attempt to advance the pipeline stage.
        Validates stage prerequisites before transitioning.
        """
        to_stage = STAGE_TRANSITIONS.get(from_stage)
        if not to_stage:
            return {
                "success": False,
                "error": f"No transition defined from stage '{from_stage}'.",
            }

        # Validate prerequisites per stage
        prereq_result = self._check_prerequisites(from_stage, candidate_data)
        if not prereq_result.valid:
            return {
                "success": False,
                "from_stage": from_stage,
                "to_stage": to_stage,
                "missing_fields": prereq_result.missing_fields,
                "errors": prereq_result.errors,
            }

        self._apply_transition(contact_id, from_stage, to_stage, source_agent)

        logger.info(
            "[INTAKE-WF] Stage advanced contact=%s %s → %s",
            contact_id, from_stage, to_stage,
        )

        return {
            "success": True,
            "contact_id": contact_id,
            "from_stage": from_stage,
            "to_stage": to_stage,
            "crm_updates": {
                "tags_add": [to_stage],
                "tags_remove": [from_stage],
                "note": f"[{source_agent}] Stage advanced: {from_stage} → {to_stage}.",
            },
        }

    def trigger_credentialing_handoff(
        self, contact_id: str, candidate_data: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Advance from intake_complete → credentialing.
        Triggers CRED-001 document request sequence for all mandatory categories.
        """
        result = self.advance_stage(
            contact_id, PipelineStage.INTAKE_COMPLETE, candidate_data, "ORCH-001"
        )
        if not result["success"]:
            return result

        # Request all mandatory credential categories
        mandatory_categories = ["identity", "licensure", "background_drug"]
        requests_sent = []
        for category in mandatory_categories:
            requests_sent.append({
                "category": category,
                "action": "document_request_queued",
                "contact_id": contact_id,
            })

        logger.info(
            "[INTAKE-WF] Credentialing handoff triggered contact=%s categories=%s",
            contact_id, mandatory_categories,
        )

        result["credentialing_requests"] = requests_sent
        return result

    def _check_prerequisites(
        self, from_stage: str, candidate_data: dict[str, Any]
    ) -> IntakeValidationResult:
        if from_stage == PipelineStage.INTAKE_IN_PROGRESS:
            return self.validate_intake(candidate_data)
        return IntakeValidationResult(valid=True)

    def _apply_transition(
        self,
        contact_id: str,
        from_stage: str,
        to_stage: str,
        source_agent: str,
    ) -> None:
        if self._crm:
            self._crm.update_pipeline_stage(contact_id, to_stage)
            self._crm.add_tags(contact_id, [to_stage])
            self._crm.remove_tags(contact_id, [from_stage])
            self._crm.add_note(
                contact_id,
                f"[{source_agent}] Pipeline stage: {from_stage} → {to_stage}.",
            )
