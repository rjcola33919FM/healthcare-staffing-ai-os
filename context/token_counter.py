"""
Token Counter — estimates token counts without requiring tiktoken.
Uses the 4-chars-per-token heuristic (accurate ±10% for Claude).
Provides hard limits per context zone.
"""

from __future__ import annotations

# Claude Opus / Sonnet context window
CONTEXT_WINDOW_TOKENS = 200_000

# Per-zone token budgets (total must leave headroom for response)
ZONE_BUDGETS: dict[str, int] = {
    "system_prompt":  2_000,   # base agent system prompt
    "kb_context":     1_500,   # RAG-retrieved KB chunks
    "crm_context":      500,   # CRM state snapshot
    "memory_context": 1_000,   # conversation memory + contact history
    "response_buffer": 4_000,  # reserved for model output
}

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Fast token estimate: len(text) / 4, minimum 1."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def budget_for_zone(zone: str) -> int:
    """Return token budget for the named zone, defaulting to 500."""
    return ZONE_BUDGETS.get(zone, 500)


def fits_in_budget(text: str, zone: str) -> bool:
    return estimate_tokens(text) <= budget_for_zone(zone)


def truncate_to_budget(text: str, zone: str, suffix: str = "\n...[truncated]") -> str:
    """
    Hard-truncate text to stay within the zone's token budget.
    Appends suffix so consumers know truncation occurred.
    """
    budget = budget_for_zone(zone)
    max_chars = budget * CHARS_PER_TOKEN - len(suffix)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + suffix


def total_prompt_tokens(
    system_prompt: str,
    messages: list[dict],
) -> int:
    """Estimate total tokens for a full Claude API call."""
    total = estimate_tokens(system_prompt)
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += estimate_tokens(block.get("text", ""))
    return total
