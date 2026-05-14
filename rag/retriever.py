"""
RAG Retriever — queries the KB index and returns ranked, de-duplicated results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from kb.indexer import KBEntry, KBIndexer

logger = logging.getLogger(__name__)

# Minimum similarity score to include a result
SCORE_THRESHOLD = 0.15
# Maximum tokens to return from retrieval (approx 4 chars per token)
MAX_RETRIEVAL_CHARS = 3000


@dataclass
class RetrievalResult:
    query: str
    agent_id: str
    entries: list[KBEntry] = field(default_factory=list)
    total_chars: int = 0
    truncated: bool = False

    @property
    def context_text(self) -> str:
        """Format retrieved entries as a context block for prompt injection."""
        if not self.entries:
            return ""
        sections = []
        for entry in self.entries:
            sections.append(f"[{entry.source_file} — {entry.heading}]\n{entry.content}")
        return "\n\n---\n\n".join(sections)

    @property
    def source_citations(self) -> list[str]:
        return list({f"{e.source_file}#{e.heading}" for e in self.entries})


class Retriever:
    """
    Retrieves relevant KB context for a query, scoped to an agent.
    Applies score threshold, de-duplication, and char-budget truncation.
    """

    def __init__(self, indexer: KBIndexer):
        self.indexer = indexer

    def retrieve(
        self,
        query: str,
        agent_id: str,
        top_k: int = 5,
        score_threshold: float = SCORE_THRESHOLD,
    ) -> RetrievalResult:
        raw = self.indexer.search(query, agent_id, top_k=top_k * 2)  # over-fetch then filter

        # Filter by score
        filtered = [e for e in raw if e.score >= score_threshold]

        # De-duplicate by chunk_id
        seen, unique = set(), []
        for entry in filtered:
            if entry.chunk_id not in seen:
                seen.add(entry.chunk_id)
                unique.append(entry)

        # Enforce char budget
        kept, total_chars, truncated = [], 0, False
        for entry in unique[:top_k]:
            if total_chars + entry.char_count > MAX_RETRIEVAL_CHARS:
                truncated = True
                break
            kept.append(entry)
            total_chars += entry.char_count

        logger.debug(
            "[RAG] Retrieved %d/%d entries query='%s...' agent=%s truncated=%s",
            len(kept), len(raw), query[:40], agent_id, truncated,
        )

        return RetrievalResult(
            query=query,
            agent_id=agent_id,
            entries=kept,
            total_chars=total_chars,
            truncated=truncated,
        )
