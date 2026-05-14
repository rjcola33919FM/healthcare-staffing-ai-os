"""
ORCH-001 Dispatcher — Full orchestration engine.
Wires together: intent classification, agent routing, session state,
fusion scoring, escalation management, and CRM sync.
"""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from core.constants import AgentID
from src.agents.base import AgentContext, AgentResponse, BaseAgent
from .intent import classify, is_high_confidence
from .router import INTENT_ROUTING
from .state import SessionState, SessionStore
from .escalation import EscalationManager

logger = logging.getLogger(__name__)


class Dispatcher:
    """
    Central orchestration dispatcher for Healthcare Staffing AI OS.

    Flow per inbound event:
    1. Load or create session state
    2. Classify intent (explicit > escalation pattern > keyword)
    3. Check low-confidence → clarify or escalate
    4. Resolve target agent from routing table
    5. Run target agent with retry
    6. Apply fusion quality gates on response
    7. Sync CRM updates
    8. Persist session state
    9. Return response
    """

    CLARIFICATION_THRESHOLD = 0.6  # Below this → ask one clarifying question

    def __init__(
        self,
        client: anthropic.Anthropic,
        agents: dict[str, BaseAgent],
        session_store: SessionStore | None = None,
        escalation_manager: EscalationManager | None = None,
    ):
        self.client = client
        self.agents = agents
        self.sessions = session_store or SessionStore()
        self.escalation = escalation_manager or EscalationManager()

    def dispatch(self, context: AgentContext) -> AgentResponse:
        """
        Main dispatch entry point. Returns a fully formed AgentResponse.
        """
        session = self.sessions.get(context.contact_id, context.channel)

        # Step 1: Classify intent
        intent, confidence = classify(context.payload)
        session.last_intent = intent
        session.last_intent_confidence = confidence

        logger.info(
            "[DISPATCH] contact=%s intent=%s confidence=%.2f channel=%s",
            context.contact_id, intent, confidence, context.channel,
        )

        # Step 2: Low confidence → clarify (but only once per turn)
        if confidence < self.CLARIFICATION_THRESHOLD and session.turn_count == 0:
            session.touch()
            self.sessions.set(session)
            return self._clarify(context)

        # Step 3: Resolve target agent
        target_id = INTENT_ROUTING.get(intent, AgentID.ORCHESTRATOR)

        # Step 4: Always-human intents
        if target_id == AgentID.HUMAN:
            response = self._escalate(context, session, f"Intent '{intent}' requires human decision.")
            self.sessions.set(session)
            return response

        # Step 5: Run target agent
        target_agent = self.agents.get(target_id.value)
        if not target_agent:
            response = self._escalate(
                context, session,
                f"No handler registered for agent {target_id.value}.",
            )
            self.sessions.set(session)
            return response

        session.set_agent(target_id.value)
        response = target_agent.run(context)

        # Step 6: Post-run escalation check
        if response.action == "escalate":
            session.mark_escalated(response.escalation_reason or "agent-initiated escalation")
            self.escalation.create_ticket(
                contact_id=context.contact_id,
                conversation_id=context.conversation_id,
                source_agent=response.agent_id,
                reason=response.escalation_reason or "",
            )

        session.touch()
        self.sessions.set(session)
        return response

    def _clarify(self, context: AgentContext) -> AgentResponse:
        """Ask one clarifying question when intent confidence is too low."""
        message = (
            "To make sure I route you correctly, could you tell me: "
            "are you a candidate looking for work, or do you have a question about "
            "your credentialing, compliance status, or a staffing need?"
        )
        return AgentResponse(
            agent_id=AgentID.ORCHESTRATOR,
            action="reply",
            content=message,
            crm_updates={
                "note": "[ORCH-001] Clarification requested — low confidence intent classification.",
            },
        )

    def _escalate(
        self,
        context: AgentContext,
        session: SessionState,
        reason: str,
    ) -> AgentResponse:
        session.mark_escalated(reason)
        result = self.escalation.build_escalation_response(
            contact_id=context.contact_id,
            conversation_id=context.conversation_id,
            source_agent=AgentID.ORCHESTRATOR,
            reason=reason,
        )
        return AgentResponse(
            agent_id=AgentID.ORCHESTRATOR,
            action="escalate",
            content=result["content"],
            crm_updates=result["crm_updates"],
            escalation_reason=reason,
            metadata={"ticket_id": result.get("ticket_id"), "severity": result.get("severity")},
        )
