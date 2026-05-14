"""ORCH-001 — Healthcare Staffing Orchestrator Agent"""

import anthropic
from .base import BaseAgent, AgentContext, AgentResponse
from orchestration.router import route, build_escalation_response, AgentID


class OrchestratorAgent(BaseAgent):
    def __init__(self, client: anthropic.Anthropic):
        super().__init__("ORCH-001", client)

    def dispatch(self, context: AgentContext, agents: dict[str, BaseAgent]) -> AgentResponse:
        """Route context to the correct specialized agent and return its response."""
        target_id = route(context)

        if target_id == AgentID.HUMAN:
            return build_escalation_response(
                reason="Intent classified as requiring human decision.",
                context=context,
            )

        target_agent = agents.get(target_id.value)
        if not target_agent:
            return build_escalation_response(
                reason=f"No handler registered for agent {target_id.value}.",
                context=context,
            )

        response = target_agent.run(context)

        if response.action == "escalate":
            response.crm_updates.setdefault("tags_add", []).append("human_escalation_required")

        return response
