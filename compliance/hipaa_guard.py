"""
HIPAA Guard — runtime enforcement layer.
Called before any data leaves an agent (CRM writes, SMS sends, notes).
Blocks PHI, enforces required escalation tags, validates audit trail completeness.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from config.hipaa import PHI_RESTRICTED_FIELDS, GUARDRAIL_KEYWORDS
from core.exceptions import HIPAAGuardrailError, PHIExposureError

logger = logging.getLogger(__name__)

# Compiled PHI pattern — matches field names as whole words, case-insensitive
_PHI_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(f) for f in PHI_RESTRICTED_FIELDS) + r")\b",
    re.IGNORECASE,
)

# Compiled guardrail pattern
_GUARDRAIL_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in GUARDRAIL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


class HIPAAGuard:
    """
    Stateless enforcement utilities. All methods are class-level so they
    can be called without instantiation for lightweight inline checks.

    Usage:
        HIPAAGuard.check_text(response_text, agent_id="REC-001", contact_id="c-123")
        HIPAAGuard.check_crm_payload(payload, agent_id="CRM-001")
        HIPAAGuard.assert_escalation_tag(crm_updates, agent_id="COMP-001")
    """

    # ------------------------------------------------------------------
    # Text scanning
    # ------------------------------------------------------------------

    @classmethod
    def check_text(
        cls,
        text: str,
        agent_id: str = "",
        contact_id: str = "",
        source: str = "agent_response",
    ) -> list[str]:
        """
        Scan text for PHI patterns.
        Returns list of matched PHI field names (empty = clean).
        Does NOT raise — callers decide whether to block or redact.
        """
        matches = _PHI_PATTERN.findall(text)
        if matches:
            unique = list(dict.fromkeys(m.lower() for m in matches))
            logger.warning(
                "[HIPAA] PHI detected agent=%s contact=%s source=%s patterns=%s",
                agent_id, contact_id, source, unique,
            )
        return list(dict.fromkeys(m.lower() for m in matches))

    @classmethod
    def assert_no_phi(
        cls,
        text: str,
        agent_id: str = "",
        contact_id: str = "",
        source: str = "agent_response",
    ) -> None:
        """Raise PHIExposureError if PHI is detected."""
        hits = cls.check_text(text, agent_id, contact_id, source)
        if hits:
            raise PHIExposureError(
                context=f"PHI detected in {source} for agent {agent_id}: {hits}"
            )

    @classmethod
    def redact_phi(cls, text: str) -> str:
        """Replace PHI field mentions with [REDACTED] inline."""
        return _PHI_PATTERN.sub("[REDACTED]", text)

    # ------------------------------------------------------------------
    # Guardrail keyword check (triggers human escalation)
    # ------------------------------------------------------------------

    @classmethod
    def check_guardrails(cls, text: str) -> list[str]:
        """
        Scan for keywords that require human escalation.
        Returns matched keyword list (empty = safe to proceed autonomously).
        """
        return list(dict.fromkeys(m.lower() for m in _GUARDRAIL_PATTERN.findall(text)))

    @classmethod
    def assert_no_guardrail_violation(cls, text: str, agent_id: str = "") -> None:
        """Raise HIPAAGuardrailError if any escalation keyword is found."""
        hits = cls.check_guardrails(text)
        if hits:
            raise HIPAAGuardrailError(
                agent_id=agent_id,
                trigger=f"Guardrail keyword(s) detected: {hits}",
            )

    # ------------------------------------------------------------------
    # CRM payload validation
    # ------------------------------------------------------------------

    @classmethod
    def check_crm_payload(
        cls,
        payload: dict[str, Any],
        agent_id: str = "",
    ) -> list[str]:
        """
        Scan CRM payload keys and string values for PHI.
        Returns list of offending field names.
        """
        violations: list[str] = []
        for key, value in payload.items():
            if _PHI_PATTERN.search(key):
                violations.append(f"key:{key}")
            if isinstance(value, str) and _PHI_PATTERN.search(value):
                violations.append(f"value:{key}")
        if violations:
            logger.warning(
                "[HIPAA] CRM payload PHI violations agent=%s fields=%s",
                agent_id, violations,
            )
        return violations

    @classmethod
    def sanitize_crm_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of the payload with PHI field values redacted."""
        clean: dict[str, Any] = {}
        for key, value in payload.items():
            if _PHI_PATTERN.search(key):
                clean[key] = "[REDACTED]"
            elif isinstance(value, str):
                clean[key] = cls.redact_phi(value)
            else:
                clean[key] = value
        return clean

    # ------------------------------------------------------------------
    # Escalation tag enforcement
    # ------------------------------------------------------------------

    @classmethod
    def assert_escalation_tag(
        cls,
        crm_updates: dict[str, Any],
        agent_id: str = "",
    ) -> None:
        """
        Verify that 'human_escalation_required' tag is present in crm_updates
        before routing to the human queue. Raises HIPAAGuardrailError if missing.
        """
        tags = crm_updates.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        if "human_escalation_required" not in tags:
            raise HIPAAGuardrailError(
                agent_id=agent_id,
                trigger="human escalation routed without 'human_escalation_required' CRM tag",
            )
