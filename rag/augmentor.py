"""
Context Augmentor — injects retrieved KB context into agent system prompts.
Maintains HIPAA boundaries: no PHI in injected context.
"""

from __future__ import annotations

import logging
from typing import Any

from config.hipaa import PHI_RESTRICTED_FIELDS
from .retriever import RetrievalResult

logger = logging.getLogger(__name__)

KB_CONTEXT_HEADER = "## Relevant Knowledge Base Context\n\nUse the following approved reference material to inform your response. Do not fabricate information outside this context.\n\n"
KB_CONTEXT_FOOTER = "\n\n---\nEnd of knowledge base context. Respond based on the above and your operating rules only."


class ContextAugmentor:
    """
    Augments agent system prompts with retrieved KB context.
    Strips any PHI-sensitive content before injection.
    """

    PHI_PATTERNS = PHI_RESTRICTED_FIELDS

    def augment_system_prompt(
        self,
        base_prompt: str,
        retrieval: RetrievalResult,
    ) -> str:
        """Append KB context block to the base system prompt."""
        if not retrieval.entries:
            return base_prompt

        context_text = self._sanitize(retrieval.context_text)
        if not context_text.strip():
            return base_prompt

        kb_block = KB_CONTEXT_HEADER + context_text + KB_CONTEXT_FOOTER
        augmented = f"{base_prompt.rstrip()}\n\n{kb_block}"

        logger.debug(
            "[RAG] Augmented prompt agent=%s entries=%d chars=%d truncated=%s",
            retrieval.agent_id,
            len(retrieval.entries),
            retrieval.total_chars,
            retrieval.truncated,
        )
        return augmented

    def augment_message(
        self,
        user_message: str,
        retrieval: RetrievalResult,
        position: str = "prefix",
    ) -> str:
        """
        Inject KB context into a user message turn.
        position='prefix'  → context before message
        position='suffix'  → context after message
        """
        if not retrieval.entries:
            return user_message

        context_block = (
            f"[KB Context]\n{self._sanitize(retrieval.context_text)}\n[/KB Context]\n\n"
        )
        if position == "prefix":
            return context_block + user_message
        return user_message + "\n\n" + context_block

    def build_rag_payload(
        self,
        base_system_prompt: str,
        retrieval: RetrievalResult,
        crm_context: dict[str, Any] | None = None,
        memory_context: str | None = None,
    ) -> dict[str, Any]:
        """
        Build a complete augmented payload for an agent call.
        Combines: base prompt + KB context + CRM snapshot + memory summary.
        """
        system = base_system_prompt

        # 1. KB context
        if retrieval.entries:
            system = self.augment_system_prompt(system, retrieval)

        # 2. CRM context (contact state snapshot)
        if crm_context:
            crm_block = self._format_crm_context(crm_context)
            system = f"{system}\n\n## Current CRM State\n{crm_block}"

        # 3. Memory summary
        if memory_context:
            system = f"{system}\n\n## Conversation Memory\n{memory_context}"

        return {
            "system": system,
            "citations": retrieval.source_citations,
            "kb_entries_used": len(retrieval.entries),
            "kb_truncated": retrieval.truncated,
        }

    def _sanitize(self, text: str) -> str:
        """Strip any PHI patterns that should never appear in injected context."""
        lower = text.lower()
        for phi_field in self.PHI_PATTERNS:
            if phi_field in lower:
                logger.warning("[RAG] PHI pattern '%s' detected in KB content — stripping.", phi_field)
                import re
                text = re.sub(
                    rf"(?i)\b{re.escape(phi_field)}\b[^\n]*",
                    "[REDACTED]",
                    text,
                )
        return text

    def _format_crm_context(self, crm_context: dict[str, Any]) -> str:
        safe_fields = {
            k: v for k, v in crm_context.items()
            if k.lower() not in self.PHI_PATTERNS
        }
        lines = [f"- {k}: {v}" for k, v in safe_fields.items() if v]
        return "\n".join(lines) if lines else "(no CRM context available)"
