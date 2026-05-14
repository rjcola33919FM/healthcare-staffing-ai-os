"""
Base agent class for Healthcare Staffing AI OS.
All specialized agents inherit from this class.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

MANIFESTS_DIR = Path(__file__).parent.parent.parent / "manifests"
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
FUSION_DIR = Path(__file__).parent.parent.parent / "fusion"


@dataclass
class AgentContext:
    contact_id: str
    conversation_id: str
    channel: str  # sms | email | voice | webhook | chat
    payload: dict[str, Any]
    crm_state: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    agent_id: str
    action: str  # reply | escalate | crm_update | route | noop
    content: str
    crm_updates: dict[str, Any] = field(default_factory=dict)
    escalation_reason: str | None = None
    next_agent: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    """
    Base class for all Healthcare Staffing AI agents.
    Loads manifest, persona, prompt, and fusion config from disk.
    Enforces HIPAA guardrails, human escalation, and audit logging.
    """

    ESCALATION_KEYWORDS = [
        "legal", "clinical judgment", "diagnosis", "treatment",
        "privileging", "final approval", "contract terms", "litigation",
        "malpractice", "contract amendment",
    ]

    def __init__(self, agent_id: str, client: anthropic.Anthropic):
        self.agent_id = agent_id
        self.client = client
        self.manifest = self._load_json(MANIFESTS_DIR / f"{agent_id}.json")
        self.fusion = self._load_json(FUSION_DIR / f"{agent_id}.json")
        self.system_prompt = self._load_prompt()
        self.persona = self._load_json(
            Path(__file__).parent.parent.parent / "agents" / agent_id / "persona.json"
        )
        self.model_settings = self.persona["model_settings"]

    def _load_json(self, path: Path) -> dict:
        with open(path) as f:
            return json.load(f)

    def _load_prompt(self) -> str:
        prompt_path = PROMPTS_DIR / f"{self.agent_id}.txt"
        return prompt_path.read_text()

    def _check_hipaa_guardrails(self, content: str) -> bool:
        """Return True if content triggers a HIPAA/regulated decision guardrail."""
        content_lower = content.lower()
        for keyword in self.ESCALATION_KEYWORDS:
            if keyword in content_lower:
                return True
        return False

    def _build_messages(self, context: AgentContext) -> list[dict]:
        user_content = json.dumps({
            "contact_id": context.contact_id,
            "conversation_id": context.conversation_id,
            "channel": context.channel,
            "message": context.payload.get("message", ""),
            "crm_state": context.crm_state,
        }, indent=2)
        return [{"role": "user", "content": user_content}]

    def run(self, context: AgentContext, max_retries: int = 3) -> AgentResponse:
        """
        Execute agent with retry logic and audit logging.
        """
        for attempt in range(1, max_retries + 1):
            try:
                response = self._call_model(context)
                self._audit_log(context, response)
                return response
            except anthropic.RateLimitError:
                if attempt == max_retries:
                    raise
                wait = 2 ** attempt
                logger.warning(f"[{self.agent_id}] Rate limit hit, retry {attempt}/{max_retries} in {wait}s")
                time.sleep(wait)
            except anthropic.APIError as e:
                logger.error(f"[{self.agent_id}] API error on attempt {attempt}: {e}")
                if attempt == max_retries:
                    raise

    def _call_model(self, context: AgentContext) -> AgentResponse:
        messages = self._build_messages(context)

        response = self.client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=self.system_prompt,
            messages=messages,
            temperature=self.model_settings["temperature"],
        )

        raw_text = response.content[0].text

        if self._check_hipaa_guardrails(raw_text):
            return AgentResponse(
                agent_id=self.agent_id,
                action="escalate",
                content="This request requires human review.",
                escalation_reason="HIPAA guardrail triggered in response content.",
            )

        return AgentResponse(
            agent_id=self.agent_id,
            action="reply",
            content=raw_text,
            metadata={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        )

    def _audit_log(self, context: AgentContext, response: AgentResponse) -> None:
        logger.info(
            "[AUDIT] agent=%s contact=%s conversation=%s action=%s escalation_reason=%s",
            self.agent_id,
            context.contact_id,
            context.conversation_id,
            response.action,
            response.escalation_reason,
        )
