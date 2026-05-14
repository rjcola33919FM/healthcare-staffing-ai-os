"""
Memory data models — conversation turns, contact memory, agent memory snapshots.
All models are PHI-safe: no clinical data, diagnosis, or treatment information stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MemoryTurn:
    """A single conversation turn (message + response pair)."""
    role: str          # "user" | "assistant"
    content: str
    timestamp: str     # ISO-8601 UTC
    agent_id: str
    token_estimate: int = 0

    @classmethod
    def user(cls, content: str, agent_id: str) -> "MemoryTurn":
        return cls(
            role="user",
            content=content,
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent_id=agent_id,
            token_estimate=max(1, len(content) // 4),
        )

    @classmethod
    def assistant(cls, content: str, agent_id: str) -> "MemoryTurn":
        return cls(
            role="assistant",
            content=content,
            timestamp=datetime.now(timezone.utc).isoformat(),
            agent_id=agent_id,
            token_estimate=max(1, len(content) // 4),
        )


@dataclass
class ContactMemory:
    """
    Persistent, contact-scoped memory across sessions.
    Tracks pipeline state, open items, and agent interaction history.
    No PHI stored — document IDs and status labels only.
    """
    contact_id: str
    agent_id: str
    pipeline_stage: str = ""
    open_credential_categories: list[str] = field(default_factory=list)
    last_interaction_ts: str = ""
    interaction_count: int = 0
    tags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # non-PHI summaries only
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_note(self, note: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.notes.append(f"[{ts}] {note}")
        self.last_interaction_ts = ts
        self.interaction_count += 1

    def to_summary(self) -> str:
        """One-paragraph prose summary safe for injection into system prompts."""
        parts = [f"Contact {self.contact_id} (stage: {self.pipeline_stage or 'unknown'})."]
        if self.open_credential_categories:
            parts.append(f"Outstanding credentials: {', '.join(self.open_credential_categories)}.")
        if self.tags:
            parts.append(f"CRM tags: {', '.join(self.tags)}.")
        if self.notes:
            recent = self.notes[-3:]           # last 3 notes only
            parts.append("Recent notes: " + " | ".join(recent))
        parts.append(f"Total interactions: {self.interaction_count}.")
        return " ".join(parts)


@dataclass
class AgentMemorySnapshot:
    """
    Short-term working memory for a single agent session.
    Lives in Redis with TTL; reconstructed from PostgreSQL on cache miss.
    """
    session_id: str
    contact_id: str
    agent_id: str
    turns: list[MemoryTurn] = field(default_factory=list)
    summary: str = ""              # LLM-generated rolling summary
    summary_turn_index: int = 0    # last turn index included in summary
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def total_tokens(self) -> int:
        return sum(t.token_estimate for t in self.turns)

    @property
    def unsummarized_turns(self) -> list[MemoryTurn]:
        return self.turns[self.summary_turn_index:]

    def append(self, turn: MemoryTurn) -> None:
        self.turns.append(turn)

    def to_context_string(self, max_turns: int = 10) -> str:
        """
        Format recent turns as a compact dialogue block for prompt injection.
        Always uses the rolling summary + up to max_turns recent turns.
        """
        lines = []
        if self.summary:
            lines.append(f"[Prior context summary]\n{self.summary}\n")

        recent = self.unsummarized_turns[-max_turns:]
        for turn in recent:
            prefix = "Candidate" if turn.role == "user" else "Agent"
            lines.append(f"{prefix}: {turn.content}")

        return "\n".join(lines)
