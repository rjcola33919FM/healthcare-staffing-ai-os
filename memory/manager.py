"""
Memory Manager — high-level interface for agent memory operations.
Handles read, write, summarize, and TTL-aware eviction.
"""

from __future__ import annotations

import logging
from typing import Any

from .models import AgentMemorySnapshot, ContactMemory, MemoryTurn
from .store import MemoryStore
from .summarizer import MemorySummarizer

logger = logging.getLogger(__name__)

# Trigger rolling summary when unsummarized turns exceed this count
SUMMARIZE_THRESHOLD = 12
# Max tokens allowed in raw turn history before forcing summarization
MAX_RAW_TOKEN_BUDGET = 2000


class MemoryManager:
    """
    Unified interface for agent memory.

    Responsibilities:
    - Load/save session snapshots (short-term, TTL 1hr)
    - Load/save contact memory (cross-session, TTL 7 days)
    - Trigger rolling summarization when buffer is large
    - Provide context strings safe for prompt injection

    Usage:
        mgr = MemoryManager()
        mgr.record_turn(session_id, contact_id, agent_id, role="user", content="...")
        context_str = mgr.get_context(session_id, contact_id, agent_id)
    """

    def __init__(self, store: MemoryStore | None = None, anthropic_client=None):
        self.store = store or MemoryStore()
        self.summarizer = MemorySummarizer(anthropic_client)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_turn(
        self,
        session_id: str,
        contact_id: str,
        agent_id: str,
        role: str,
        content: str,
    ) -> None:
        """Append a conversation turn and persist the snapshot."""
        snapshot = self._load_or_create(session_id, contact_id, agent_id)

        if role == "user":
            turn = MemoryTurn.user(content, agent_id)
        else:
            turn = MemoryTurn.assistant(content, agent_id)

        snapshot.append(turn)

        # Trigger summarization if buffer is large
        if (
            len(snapshot.unsummarized_turns) >= SUMMARIZE_THRESHOLD
            or snapshot.total_tokens > MAX_RAW_TOKEN_BUDGET
        ):
            self._summarize(snapshot)

        self.store.save_snapshot(snapshot)

        # Update contact memory interaction count
        contact_mem = self.store.get_or_create_contact_memory(contact_id, agent_id)
        contact_mem.interaction_count += 1
        self.store.save_contact_memory(contact_mem)

    def get_context(
        self,
        session_id: str,
        contact_id: str,
        agent_id: str,
        max_turns: int = 10,
    ) -> str:
        """
        Return a formatted context string ready for prompt injection.
        Combines rolling summary + recent turns + contact-level memory.
        """
        snapshot = self.store.load_snapshot(session_id)
        contact_mem = self.store.load_contact_memory(contact_id, agent_id)

        parts = []

        if contact_mem:
            contact_summary = contact_mem.to_summary()
            if contact_summary:
                parts.append(f"[Contact History]\n{contact_summary}")

        if snapshot:
            conv_context = snapshot.to_context_string(max_turns=max_turns)
            if conv_context:
                parts.append(f"[Conversation]\n{conv_context}")

        return "\n\n".join(parts)

    def update_contact_memory(
        self,
        contact_id: str,
        agent_id: str,
        *,
        pipeline_stage: str | None = None,
        open_credentials: list[str] | None = None,
        tags: list[str] | None = None,
        note: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ContactMemory:
        """Patch contact-level memory fields and persist."""
        mem = self.store.get_or_create_contact_memory(contact_id, agent_id)

        if pipeline_stage is not None:
            mem.pipeline_stage = pipeline_stage
        if open_credentials is not None:
            mem.open_credential_categories = open_credentials
        if tags is not None:
            mem.tags = list(set(mem.tags) | set(tags))
        if note:
            mem.add_note(note)
        if metadata:
            mem.metadata.update(metadata)

        self.store.save_contact_memory(mem)
        return mem

    def get_contact_memory(self, contact_id: str, agent_id: str) -> ContactMemory | None:
        return self.store.load_contact_memory(contact_id, agent_id)

    def get_snapshot(self, session_id: str) -> AgentMemorySnapshot | None:
        return self.store.load_snapshot(session_id)

    def clear_session(self, session_id: str) -> None:
        """Remove session snapshot (e.g., after conversation ends)."""
        self.store.delete_snapshot(session_id)
        logger.info("[MEM] Session cleared: %s", session_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_or_create(
        self, session_id: str, contact_id: str, agent_id: str
    ) -> AgentMemorySnapshot:
        snapshot = self.store.load_snapshot(session_id)
        if snapshot is None:
            snapshot = AgentMemorySnapshot(
                session_id=session_id,
                contact_id=contact_id,
                agent_id=agent_id,
            )
        return snapshot

    def _summarize(self, snapshot: AgentMemorySnapshot) -> None:
        """Generate a rolling summary of unsummarized turns and compress them."""
        turns_to_summarize = snapshot.unsummarized_turns
        if not turns_to_summarize:
            return

        new_summary = self.summarizer.summarize(
            prior_summary=snapshot.summary,
            turns=turns_to_summarize,
            agent_id=snapshot.agent_id,
        )

        snapshot.summary = new_summary
        snapshot.summary_turn_index = len(snapshot.turns)
        logger.debug(
            "[MEM] Summarized %d turns for session=%s",
            len(turns_to_summarize), snapshot.session_id,
        )
