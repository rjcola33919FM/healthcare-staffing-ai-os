"""
Context Injector — high-level orchestrator that wires RAGPipeline + MemoryManager
into a single call that returns a ContextPayload ready for Claude.

This is the primary entry point used by agent runners.
"""

from __future__ import annotations

import logging
from typing import Any

from .builder import ContextBuilder, ContextPayload

logger = logging.getLogger(__name__)


class ContextInjector:
    """
    Combines RAG retrieval + memory lookup + CRM state into one ContextPayload.

    Dependencies injected at construction time so each component is independently
    testable and swappable (no hard imports of RAGPipeline or MemoryManager here).

    Usage:
        injector = ContextInjector(
            rag_pipeline=rag,
            memory_manager=memory,
        )
        payload = injector.prepare(
            agent_id="REC-001",
            session_id="sess-abc",
            contact_id="contact-123",
            query="How long does credentialing take?",
            base_system_prompt=prompt_text,
            crm_context={"pipeline_stage": "intake_complete"},
        )
        # use payload.system + payload.messages with anthropic client
    """

    def __init__(
        self,
        rag_pipeline=None,
        memory_manager=None,
        builder: ContextBuilder | None = None,
    ):
        self.rag = rag_pipeline
        self.memory = memory_manager
        self.builder = builder or ContextBuilder()

    def prepare(
        self,
        agent_id: str,
        session_id: str,
        contact_id: str,
        query: str,
        base_system_prompt: str,
        crm_context: dict[str, Any] | None = None,
        top_k: int = 4,
    ) -> ContextPayload:
        """
        Full pipeline:
          1. RAG retrieval → kb_context
          2. Memory lookup → memory_context
          3. Context assembly → ContextPayload
        """
        # --- RAG ---
        kb_context: dict[str, Any] | None = None
        if self.rag:
            try:
                kb_context = self.rag.prepare(
                    agent_id=agent_id,
                    query=query,
                    base_system_prompt=base_system_prompt,
                    crm_context=crm_context,
                    top_k=top_k,
                )
            except Exception as exc:
                logger.warning("[CTX] RAG prepare failed agent=%s: %s", agent_id, exc)

        # --- Memory ---
        memory_context: str | None = None
        if self.memory:
            try:
                memory_context = self.memory.get_context(
                    session_id=session_id,
                    contact_id=contact_id,
                    agent_id=agent_id,
                )
            except Exception as exc:
                logger.warning("[CTX] Memory get_context failed session=%s: %s", session_id, exc)

        return self.builder.build(
            agent_id=agent_id,
            base_system_prompt=base_system_prompt,
            user_message=query,
            kb_context=kb_context,
            crm_context=crm_context,
            memory_context=memory_context,
        )

    def record_response(
        self,
        session_id: str,
        contact_id: str,
        agent_id: str,
        user_message: str,
        agent_response: str,
    ) -> None:
        """
        After a successful agent call, persist the turn pair to memory.
        Call this after every interaction to keep memory up to date.
        """
        if not self.memory:
            return
        try:
            self.memory.record_turn(
                session_id, contact_id, agent_id, role="user", content=user_message
            )
            self.memory.record_turn(
                session_id, contact_id, agent_id, role="assistant", content=agent_response
            )
        except Exception as exc:
            logger.warning("[CTX] Memory record_turn failed session=%s: %s", session_id, exc)
