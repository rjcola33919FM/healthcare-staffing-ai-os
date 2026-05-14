"""
REC-001 — Candidate Recruiting Agent
Full implementation: intake, FAQ, appointment booking, CRM updates, escalation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic

from config.hipaa import GUARDRAIL_KEYWORDS
from core.constants import AgentID, PipelineStage, ComplianceTag
from core.exceptions import EscalationRequired
from schemas.candidate import CandidateIntake
from .tools import RecruitingTools
from .workflows import CandidateWorkflow

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = "prompts/REC-001.txt"

REQUIRED_INTAKE_FIELDS = [
    "first_name", "last_name", "specialty",
    "license_state", "phone",
]

ESCALATION_TRIGGERS = [
    "compensation", "pay rate", "salary", "negotiate",
    "disqualif", "reject", "screen out",
    "complaint", "dispute", "lawsuit",
]


@dataclass
class IntakeState:
    """Tracks multi-turn intake progress for a candidate."""
    contact_id: str
    collected: dict[str, Any] = field(default_factory=dict)
    follow_up_count: int = 0
    intake_complete: bool = False
    escalated: bool = False


class RecruitingAgent:
    """
    REC-001 — Candidate Recruiting Agent.

    Responsibilities:
    - Collect candidate intake fields one at a time
    - Answer approved FAQs
    - Book recruiter appointments via GoHighLevel calendar
    - Update CRM pipeline stages and contact fields
    - Escalate compensation, screening, and disqualification decisions to human
    """

    AGENT_ID = AgentID.RECRUITING
    MAX_FOLLOW_UPS = 2

    def __init__(self, client: anthropic.Anthropic, tools: RecruitingTools | None = None):
        self.client = client
        self.tools = tools or RecruitingTools()
        self.workflow = CandidateWorkflow(self.tools)
        self._system_prompt = self._load_prompt()
        self._intake_states: dict[str, IntakeState] = {}

    def _load_prompt(self) -> str:
        try:
            return open(SYSTEM_PROMPT_PATH).read()
        except FileNotFoundError:
            logger.warning("[REC-001] Prompt file not found, using inline fallback.")
            return (
                "You are the Candidate Recruiting Agent. Collect candidate intake information, "
                "answer approved FAQs, book recruiter appointments, update CRM fields, and escalate "
                "incomplete, sensitive, or decision-heavy issues to a human recruiter."
            )

    def _requires_escalation(self, text: str) -> str | None:
        lower = text.lower()
        for trigger in ESCALATION_TRIGGERS:
            if trigger in lower:
                return trigger
        for kw in GUARDRAIL_KEYWORDS:
            if kw in lower:
                return kw
        return None

    def _get_or_create_state(self, contact_id: str) -> IntakeState:
        if contact_id not in self._intake_states:
            self._intake_states[contact_id] = IntakeState(contact_id=contact_id)
        return self._intake_states[contact_id]

    def _next_missing_field(self, state: IntakeState) -> str | None:
        for f in REQUIRED_INTAKE_FIELDS:
            if not state.collected.get(f):
                return f
        return None

    def process(self, contact_id: str, message: str, crm_state: dict[str, Any]) -> dict[str, Any]:
        """
        Main entry point. Returns action dict with reply, crm_updates, and escalation info.
        """
        # Check for escalation triggers in inbound message
        trigger = self._requires_escalation(message)
        if trigger:
            return self._escalate(contact_id, f"Inbound message triggered escalation: '{trigger}'")

        state = self._get_or_create_state(contact_id)

        # Merge any CRM fields already on the record
        for field_name in REQUIRED_INTAKE_FIELDS:
            if crm_state.get(field_name) and not state.collected.get(field_name):
                state.collected[field_name] = crm_state[field_name]

        # Extract fields from message via LLM
        extracted = self._extract_fields(message, state)
        state.collected.update({k: v for k, v in extracted.items() if v})

        # Check silence/follow-up limit
        if not extracted and not any(state.collected.values()):
            state.follow_up_count += 1
            if state.follow_up_count >= self.MAX_FOLLOW_UPS:
                return self._escalate(contact_id, "Candidate unresponsive after max follow-ups.")

        # Check completion
        missing = self._next_missing_field(state)
        if missing:
            reply = self._ask_for_field(missing, state)
            return {
                "action": "reply",
                "content": reply,
                "crm_updates": self._build_crm_partial(state),
            }

        # Intake complete
        state.intake_complete = True
        return self.workflow.complete_intake(contact_id, state)

    def _extract_fields(self, message: str, state: IntakeState) -> dict[str, Any]:
        """Use Claude to extract intake fields from free-text message."""
        missing = [f for f in REQUIRED_INTAKE_FIELDS if not state.collected.get(f)]
        if not missing:
            return {}

        prompt = (
            f"Extract the following fields from this candidate message if present. "
            f"Return a JSON object with only the fields found.\n"
            f"Fields to extract: {missing}\n"
            f"Message: {message}\n"
            f"Return only valid JSON, no explanation."
        )
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=256,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            import json
            raw = response.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(raw)
        except Exception as e:
            logger.debug("[REC-001] Field extraction failed: %s", e)
            return {}

    def _ask_for_field(self, field_name: str, state: IntakeState) -> str:
        field_questions = {
            "first_name": "What is your first name?",
            "last_name": "What is your last name?",
            "specialty": "What is your clinical specialty? (e.g., RN, ICU, OR, ER)",
            "license_state": "Which state is your primary license in?",
            "phone": "What is the best phone number to reach you?",
            "availability_date": "When are you available to start?",
            "desired_locations": "What locations or states are you open to working in?",
        }
        base = field_questions.get(field_name, f"Could you provide your {field_name.replace('_', ' ')}?")
        if state.collected.get("first_name"):
            return f"{state.collected['first_name']}, {base[0].lower()}{base[1:]}"
        return base

    def _build_crm_partial(self, state: IntakeState) -> dict[str, Any]:
        return {
            "fields": {k: v for k, v in state.collected.items() if v},
            "tags_add": [PipelineStage.INTAKE_IN_PROGRESS],
            "note": f"[REC-001] Intake in progress. Collected fields: {list(state.collected.keys())}",
        }

    def _escalate(self, contact_id: str, reason: str) -> dict[str, Any]:
        logger.warning("[REC-001] Escalating contact=%s reason=%s", contact_id, reason)
        return {
            "action": "escalate",
            "content": "I'm connecting you with a recruiter who can assist you further.",
            "escalation_reason": reason,
            "crm_updates": {
                "tags_add": [ComplianceTag.HUMAN_ESCALATION_REQUIRED],
                "note": f"[REC-001] Escalated. Reason: {reason}",
            },
        }
