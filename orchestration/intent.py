"""
Intent classification for Healthcare Staffing AI OS.
Extracted from router.py as a standalone module for testability and extensibility.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Phrases that always escalate to HUMAN before any other routing
HUMAN_ESCALATION_PATTERNS: list[str] = [
    "legal advice", "clinical judgment", "contract amendment",
    "malpractice history", "compliance exception", "litigation",
    "phi breach", "credential approval", "final approval",
    "license revocation", "sanction", "oig exclusion",
]

# Ordered intent-keyword map — first match wins
KEYWORD_INTENT_RULES: list[tuple[list[str], str]] = [
    # Expiry/compliance checked before license to avoid "license" stealing expiry events
    (["expire", "expiring", "expiration", "compliance alert", "at risk"], "compliance_alert"),
    (["apply", "interested in", "looking for a job", "resume", "availability", "open to work"], "candidate_message"),
    (["upload", "document", "credential", "license", "checklist", "missing doc"], "document_request"),
    (["staffing need", "fill a position", "open role", "hire", "we need", "staff our"], "client_inquiry"),
    (["book", "schedule", "appointment", "calendar", "reschedule"], "book_recruiter_appointment"),
    (["tag", "pipeline", "stage", "crm", "update contact", "webhook"], "crm_update"),
]


def classify(payload: dict[str, Any]) -> tuple[str, float]:
    """
    Classify the intent of a payload.

    Returns:
        (intent_str, confidence) where confidence is 0.0–1.0.
        confidence = 1.0 for explicit event_type, 0.9 for escalation pattern,
        0.8 for keyword match, 0.5 for fallback.
    """
    # Explicit event_type — highest confidence
    if event_type := payload.get("event_type"):
        return event_type, 1.0

    message = (payload.get("message") or "").lower()

    # HUMAN escalation patterns — checked before keyword routing
    for pattern in HUMAN_ESCALATION_PATTERNS:
        if pattern in message:
            logger.info("[INTENT] Escalation pattern matched: '%s'", pattern)
            return "compliance_exception", 0.9

    # Keyword rules — ordered, first match wins
    for keywords, intent in KEYWORD_INTENT_RULES:
        if any(kw in message for kw in keywords):
            logger.debug("[INTENT] Keyword match: intent=%s", intent)
            return intent, 0.8

    return "crm_update", 0.5  # Fallback


def is_high_confidence(confidence: float, threshold: float = 0.75) -> bool:
    return confidence >= threshold
