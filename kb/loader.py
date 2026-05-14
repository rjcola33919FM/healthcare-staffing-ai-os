"""
KB Loader — reads source documents and prepares them for indexing.
Supports Markdown, plain text, and JSON. Chunks by heading or paragraph.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

KB_DIR = Path(__file__).parent / "documents"

# Agent → which KB documents are in scope
AGENT_KB_SCOPE: dict[str, list[str]] = {
    "REC-001":   ["candidate_faq.md"],
    "CRED-001":  ["credentialing_requirements.md"],
    "COMP-001":  ["compliance_rules.md"],
    "SALES-001": ["sales_playbook.md"],
    "ORCH-001":  ["candidate_faq.md", "credentialing_requirements.md",
                  "compliance_rules.md", "sales_playbook.md"],
    "CRM-001":   [],
}


@dataclass
class KBChunk:
    chunk_id: str
    source_file: str
    heading: str
    content: str
    agent_scope: list[str] = field(default_factory=list)
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.content)


class KBLoader:
    """
    Loads and chunks KB documents for indexing.
    Chunks on Markdown H2/H3 headings, with a max chunk size fallback.
    """

    MAX_CHUNK_CHARS = 1200

    def __init__(self, kb_dir: Path = KB_DIR):
        self.kb_dir = kb_dir

    def load_for_agent(self, agent_id: str) -> list[KBChunk]:
        """Load and chunk all KB documents in scope for an agent."""
        filenames = AGENT_KB_SCOPE.get(agent_id, [])
        chunks: list[KBChunk] = []
        for filename in filenames:
            path = self.kb_dir / filename
            if not path.exists():
                logger.warning("[KB] File not found: %s", path)
                continue
            chunks.extend(self._load_file(path, agent_id))
        logger.info("[KB] Loaded %d chunks for agent=%s", len(chunks), agent_id)
        return chunks

    def load_all(self) -> list[KBChunk]:
        """Load all KB documents."""
        chunks: list[KBChunk] = []
        for path in sorted(self.kb_dir.glob("*.md")):
            chunks.extend(self._load_file(path, agent_id=None))
        logger.info("[KB] Loaded %d total chunks", len(chunks))
        return chunks

    def _load_file(self, path: Path, agent_id: str | None) -> list[KBChunk]:
        text = path.read_text(encoding="utf-8")
        scope = [a for a, files in AGENT_KB_SCOPE.items() if path.name in files]

        # Split on H2/H3 headings
        sections = re.split(r"\n(?=#{2,3} )", text)
        chunks: list[KBChunk] = []

        for i, section in enumerate(sections):
            heading_match = re.match(r"#{2,3} (.+)", section)
            heading = heading_match.group(1).strip() if heading_match else path.stem
            body = section[heading_match.end():].strip() if heading_match else section.strip()

            # Skip empty sections or comment-only lines
            content_lines = [l for l in body.splitlines() if l.strip() and not l.startswith("#")]
            if not content_lines:
                continue

            content = "\n".join(content_lines)

            # Sub-chunk if too long
            for j, sub in enumerate(self._split_if_long(content)):
                chunk_id = f"{path.stem}_{i}_{j}"
                chunks.append(KBChunk(
                    chunk_id=chunk_id,
                    source_file=path.name,
                    heading=heading,
                    content=sub,
                    agent_scope=scope,
                ))

        return chunks

    def _split_if_long(self, text: str) -> list[str]:
        if len(text) <= self.MAX_CHUNK_CHARS:
            return [text]
        # Split on double newline (paragraph boundary)
        parts = re.split(r"\n\n+", text)
        chunks, current = [], ""
        for part in parts:
            if len(current) + len(part) > self.MAX_CHUNK_CHARS and current:
                chunks.append(current.strip())
                current = part
            else:
                current = f"{current}\n\n{part}" if current else part
        if current.strip():
            chunks.append(current.strip())
        return chunks or [text]
