"""
Context Builder — assembles the final prompt payload for a Claude API call.
Combines: base system prompt + KB context + CRM state + memory context.
Enforces per-zone token budgets and returns a fully-formed API-ready payload.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .token_counter import (
    estimate_tokens,
    truncate_to_budget,
    fits_in_budget,
    total_prompt_tokens,
    ZONE_BUDGETS,
)

logger = logging.getLogger(__name__)


@dataclass
class ContextPayload:
    """
    Ready-to-use payload for a Claude API call.

    system:         final assembled system prompt
    messages:       list of message dicts [{"role": ..., "content": ...}]
    token_estimate: rough total token count
    zones_used:     per-zone token breakdown for observability
    truncations:    list of zones where content was truncated
    """
    system: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    token_estimate: int = 0
    zones_used: dict[str, int] = field(default_factory=dict)
    truncations: list[str] = field(default_factory=list)


class ContextBuilder:
    """
    Builds the full context payload for one agent call.

    Zones injected (in order):
      1. base_system_prompt   — raw agent system prompt
      2. kb_context           — RAG-retrieved KB chunks (from RAGPipeline)
      3. crm_context          — CRM state snapshot (key/value pairs)
      4. memory_context       — conversation memory + contact history

    Each zone is independently truncated to its budget before assembly.

    Usage:
        builder = ContextBuilder()
        payload = builder.build(
            agent_id="REC-001",
            base_system_prompt=prompt_text,
            user_message="How long does credentialing take?",
            kb_context=rag_pipeline.prepare(...),
            crm_context={"pipeline_stage": "intake_complete"},
            memory_context=memory_manager.get_context(...),
        )
        # payload.system → final system prompt
        # payload.messages → [{"role": "user", "content": "..."}]
    """

    def build(
        self,
        agent_id: str,
        base_system_prompt: str,
        user_message: str,
        *,
        kb_context: dict[str, Any] | None = None,
        crm_context: dict[str, Any] | None = None,
        memory_context: str | None = None,
    ) -> ContextPayload:
        truncations: list[str] = []
        zones_used: dict[str, int] = {}

        # --- Zone 1: base system prompt ---
        system = self._apply_zone(
            base_system_prompt, "system_prompt", truncations, zones_used
        )

        # --- Zone 2: KB context ---
        if kb_context and kb_context.get("kb_entries_used", 0) > 0:
            kb_text = kb_context.get("system", "")
            # kb_context["system"] already contains the augmented prompt from RAGPipeline;
            # extract only the KB block (everything after the base prompt)
            kb_block = kb_text[len(base_system_prompt):].strip() if kb_text.startswith(base_system_prompt) else kb_text
            if kb_block:
                kb_block = self._apply_zone(kb_block, "kb_context", truncations, zones_used)
                system = f"{system.rstrip()}\n\n{kb_block}"
        else:
            zones_used["kb_context"] = 0

        # --- Zone 3: CRM context ---
        if crm_context:
            crm_block = self._format_crm(crm_context)
            crm_block = self._apply_zone(crm_block, "crm_context", truncations, zones_used)
            system = f"{system.rstrip()}\n\n## Current CRM State\n{crm_block}"
        else:
            zones_used["crm_context"] = 0

        # --- Zone 4: Memory context ---
        if memory_context and memory_context.strip():
            mem_block = self._apply_zone(
                memory_context, "memory_context", truncations, zones_used
            )
            system = f"{system.rstrip()}\n\n## Conversation Memory\n{mem_block}"
        else:
            zones_used["memory_context"] = 0

        messages = [{"role": "user", "content": user_message}]
        token_est = total_prompt_tokens(system, messages)

        payload = ContextPayload(
            system=system,
            messages=messages,
            token_estimate=token_est,
            zones_used=zones_used,
            truncations=truncations,
        )

        logger.info(
            "[CTX] Built payload agent=%s tokens≈%d zones=%s truncations=%s",
            agent_id, token_est, zones_used, truncations or "none",
        )
        return payload

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_zone(
        self,
        text: str,
        zone: str,
        truncations: list[str],
        zones_used: dict[str, int],
    ) -> str:
        if not fits_in_budget(text, zone):
            truncations.append(zone)
            text = truncate_to_budget(text, zone)
        zones_used[zone] = estimate_tokens(text)
        return text

    @staticmethod
    def _format_crm(crm_context: dict[str, Any]) -> str:
        lines = [f"- {k}: {v}" for k, v in crm_context.items() if v is not None]
        return "\n".join(lines) if lines else "(no CRM context available)"
