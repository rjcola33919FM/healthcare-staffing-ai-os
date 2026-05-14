"""
RAG Pipeline — end-to-end retrieval-augmented generation for agent calls.
Loads KB → retrieves context → augments prompt → returns ready-to-use payload.
"""

from __future__ import annotations

import logging
from typing import Any

from kb.loader import KBLoader
from kb.indexer import KBIndexer
from .retriever import Retriever, RetrievalResult
from .augmentor import ContextAugmentor

logger = logging.getLogger(__name__)


class RAGPipeline:
    """
    Full RAG pipeline for Healthcare Staffing AI OS.

    Usage:
        pipeline = RAGPipeline()
        pipeline.build_index()   # once at startup
        payload = pipeline.prepare(
            agent_id="REC-001",
            query="how long does credentialing take?",
            base_system_prompt=prompt_text,
            crm_context={"pipeline_stage": "intake_complete"},
        )
        # payload["system"] is the augmented prompt ready for Claude
    """

    def __init__(self, anthropic_client=None, use_pinecone: bool = False):
        self.loader    = KBLoader()
        self.indexer   = KBIndexer(anthropic_client, use_pinecone=use_pinecone)
        self.retriever = Retriever(self.indexer)
        self.augmentor = ContextAugmentor()
        self._index_built = False

    def build_index(self, agent_id: str | None = None) -> int:
        """
        Load and index KB documents.
        Call once at startup or when KB content changes.
        Returns total chunks indexed.
        """
        if agent_id:
            chunks = self.loader.load_for_agent(agent_id)
        else:
            chunks = self.loader.load_all()

        count = self.indexer.upsert_chunks(chunks)
        self._index_built = True
        logger.info("[RAG] Index built: %d chunks", count)
        return count

    def prepare(
        self,
        agent_id: str,
        query: str,
        base_system_prompt: str,
        crm_context: dict[str, Any] | None = None,
        memory_context: str | None = None,
        top_k: int = 4,
    ) -> dict[str, Any]:
        """
        Run the full RAG pipeline for a single agent call.

        Returns a dict with:
          - system: augmented system prompt (ready for Claude)
          - citations: list of KB source references used
          - kb_entries_used: int
          - kb_truncated: bool
        """
        if not self._index_built:
            self.build_index(agent_id)

        retrieval = self.retriever.retrieve(query, agent_id, top_k=top_k)

        payload = self.augmentor.build_rag_payload(
            base_system_prompt=base_system_prompt,
            retrieval=retrieval,
            crm_context=crm_context,
            memory_context=memory_context,
        )

        logger.info(
            "[RAG] Pipeline complete agent=%s query='%s...' entries=%d",
            agent_id, query[:40], payload["kb_entries_used"],
        )
        return payload

    def retrieve_only(self, agent_id: str, query: str, top_k: int = 5) -> RetrievalResult:
        """Retrieve without augmentation — useful for debugging or scoring."""
        if not self._index_built:
            self.build_index(agent_id)
        return self.retriever.retrieve(query, agent_id, top_k=top_k)
