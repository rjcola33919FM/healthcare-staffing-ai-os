"""
KB Indexer — embeds chunks and stores them in Pinecone (or in-memory for dev).
Supports upsert, similarity search, and agent-scoped retrieval.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Any

from .loader import KBChunk

logger = logging.getLogger(__name__)

PINECONE_API_KEY    = os.environ.get("PINECONE_API_KEY", "")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "healthcare-staffing-kb")
EMBED_MODEL         = "text-embedding-3-small"   # OpenAI / Anthropic compatible
EMBED_DIMENSIONS    = 1536


@dataclass
class KBEntry:
    chunk_id: str
    source_file: str
    heading: str
    content: str
    agent_scope: list[str]
    score: float = 0.0

    @property
    def char_count(self) -> int:
        return len(self.content)


class KBIndexer:
    """
    Manages embedding and vector storage for KB chunks.

    In production: uses Pinecone.
    In development / tests: uses in-memory dot-product search on raw text hashes.
    """

    def __init__(self, anthropic_client=None, use_pinecone: bool = False):
        self._client = anthropic_client
        self._use_pinecone = use_pinecone and bool(PINECONE_API_KEY)
        self._index = self._init_pinecone() if self._use_pinecone else None
        self._memory_store: list[dict[str, Any]] = []  # dev fallback

    def _init_pinecone(self):
        try:
            import pinecone
            pinecone.init(api_key=PINECONE_API_KEY)
            return pinecone.Index(PINECONE_INDEX_NAME)
        except ImportError:
            logger.warning("[KB] pinecone-client not installed, using in-memory store.")
            return None

    def upsert_chunks(self, chunks: list[KBChunk]) -> int:
        """Embed and store chunks. Returns count upserted."""
        if self._use_pinecone and self._index:
            return self._upsert_pinecone(chunks)
        return self._upsert_memory(chunks)

    def search(
        self,
        query: str,
        agent_id: str,
        top_k: int = 5,
    ) -> list[KBEntry]:
        """Retrieve top-k relevant KB chunks for a query, scoped to an agent."""
        if self._use_pinecone and self._index:
            return self._search_pinecone(query, agent_id, top_k)
        return self._search_memory(query, agent_id, top_k)

    # ── Pinecone path ──────────────────────────────────────────────────────────

    def _upsert_pinecone(self, chunks: list[KBChunk]) -> int:
        vectors = []
        for chunk in chunks:
            embedding = self._embed(chunk.content)
            vectors.append({
                "id": chunk.chunk_id,
                "values": embedding,
                "metadata": {
                    "source_file": chunk.source_file,
                    "heading": chunk.heading,
                    "content": chunk.content[:1000],
                    "agent_scope": ",".join(chunk.agent_scope),
                },
            })
        if vectors:
            self._index.upsert(vectors=vectors)
        logger.info("[KB] Upserted %d vectors to Pinecone.", len(vectors))
        return len(vectors)

    def _search_pinecone(self, query: str, agent_id: str, top_k: int) -> list[KBEntry]:
        embedding = self._embed(query)
        results = self._index.query(
            vector=embedding,
            top_k=top_k,
            filter={"agent_scope": {"$contains": agent_id}},
            include_metadata=True,
        )
        entries = []
        for match in results.get("matches", []):
            meta = match["metadata"]
            entries.append(KBEntry(
                chunk_id=match["id"],
                source_file=meta["source_file"],
                heading=meta["heading"],
                content=meta["content"],
                agent_scope=meta.get("agent_scope", "").split(","),
                score=match["score"],
            ))
        return entries

    def _embed(self, text: str) -> list[float]:
        """Embed text. Uses Claude/OpenAI API in production."""
        if self._client:
            # In production: call embedding API
            pass
        # Stub: deterministic pseudo-embedding from hash (for dev/test only)
        h = int(hashlib.sha256(text.encode()).hexdigest(), 16)
        import random
        rng = random.Random(h)
        return [rng.gauss(0, 1) for _ in range(EMBED_DIMENSIONS)]

    # ── In-memory fallback ─────────────────────────────────────────────────────

    def _upsert_memory(self, chunks: list[KBChunk]) -> int:
        ids = {e["chunk_id"] for e in self._memory_store}
        added = 0
        for chunk in chunks:
            if chunk.chunk_id not in ids:
                self._memory_store.append({
                    "chunk_id": chunk.chunk_id,
                    "source_file": chunk.source_file,
                    "heading": chunk.heading,
                    "content": chunk.content,
                    "agent_scope": chunk.agent_scope,
                })
                added += 1
        logger.info("[KB] In-memory store: %d chunks added, %d total.", added, len(self._memory_store))
        return added

    def _search_memory(self, query: str, agent_id: str, top_k: int) -> list[KBEntry]:
        """Keyword overlap search for dev/test (no embeddings required)."""
        query_words = set(query.lower().split())
        scored: list[tuple[float, dict]] = []

        for entry in self._memory_store:
            if agent_id not in entry["agent_scope"] and agent_id != "ORCH-001":
                continue
            content_words = set(entry["content"].lower().split())
            heading_words = set(entry["heading"].lower().split())
            overlap = len(query_words & (content_words | heading_words))
            if overlap > 0:
                score = overlap / max(len(query_words), 1)
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            KBEntry(
                chunk_id=e["chunk_id"],
                source_file=e["source_file"],
                heading=e["heading"],
                content=e["content"],
                agent_scope=e["agent_scope"],
                score=round(s, 4),
            )
            for s, e in scored[:top_k]
        ]
