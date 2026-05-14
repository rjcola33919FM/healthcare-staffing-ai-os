"""
Memory Summarizer — generates rolling conversation summaries via Claude.
Falls back to extractive (last-N) summary when no LLM client is available.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import MemoryTurn

logger = logging.getLogger(__name__)

_SUMMARIZE_SYSTEM = (
    "You are a memory compression assistant for a healthcare staffing AI system. "
    "Summarize the conversation below into 2–4 concise sentences that preserve: "
    "(1) what the candidate/client asked, "
    "(2) what was resolved or remains open, "
    "(3) any critical status flags. "
    "Do NOT include PHI, diagnoses, clinical details, or personal health information. "
    "Be factual and brief."
)

_SUMMARIZE_PROMPT_TEMPLATE = """\
Prior summary (if any):
{prior_summary}

New conversation turns:
{turns_text}

Produce an updated summary (2–4 sentences, no PHI):"""


class MemorySummarizer:
    """
    Wraps an Anthropic client to produce rolling summaries.
    Degrades gracefully to extractive (first+last) if client is unavailable.
    """

    def __init__(self, anthropic_client=None):
        self._client = anthropic_client

    def summarize(
        self,
        prior_summary: str,
        turns: list["MemoryTurn"],
        agent_id: str,
    ) -> str:
        if not turns:
            return prior_summary

        turns_text = self._format_turns(turns)

        if self._client:
            return self._llm_summarize(prior_summary, turns_text, agent_id)

        # Extractive fallback: keep prior summary + first + last turn
        return self._extractive_summarize(prior_summary, turns)

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    def _llm_summarize(self, prior_summary: str, turns_text: str, agent_id: str) -> str:
        prompt = _SUMMARIZE_PROMPT_TEMPLATE.format(
            prior_summary=prior_summary or "(none)",
            turns_text=turns_text,
        )
        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=256,
                temperature=0.1,
                system=_SUMMARIZE_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = response.content[0].text.strip()
            logger.debug("[MEM] LLM summary generated agent=%s chars=%d", agent_id, len(summary))
            return summary
        except Exception as exc:
            logger.warning("[MEM] LLM summarize failed — using extractive: %s", exc)
            return self._extractive_summarize(prior_summary, [])

    # ------------------------------------------------------------------
    # Extractive fallback
    # ------------------------------------------------------------------

    def _extractive_summarize(self, prior: str, turns: "list[MemoryTurn]") -> str:
        parts = []
        if prior:
            parts.append(prior)
        if turns:
            first, last = turns[0], turns[-1]
            parts.append(f"[{first.role.capitalize()}]: {first.content[:120]}")
            if len(turns) > 1:
                parts.append(f"[{last.role.capitalize()}]: {last.content[:120]}")
        return " | ".join(parts) if parts else ""

    @staticmethod
    def _format_turns(turns: "list[MemoryTurn]") -> str:
        lines = []
        for t in turns:
            label = "Candidate/Client" if t.role == "user" else "Agent"
            lines.append(f"{label}: {t.content}")
        return "\n".join(lines)
