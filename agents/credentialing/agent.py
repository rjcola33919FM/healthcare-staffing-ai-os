"""
CRED-001 — Medical Credentialing Agent
Full implementation: document collection, checklist classification, deadline reminders,
secure upload management, and escalation to human credentialing specialist.

RULES (non-negotiable):
- Never approve or deny credentials — classify and route only
- All document receipt events logged with timestamp
- Reminders at 30, 14, 7 days before expiration
- PHI in documents never stored in CRM notes — reference IDs only
- Any authenticity concern triggers immediate escalation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal

import anthropic

from config.hipaa import (
    MANDATORY_CREDENTIAL_CATEGORIES,
    PHI_RESTRICTED_FIELDS,
    REMINDER_SCHEDULE_DAYS,
)
from core.constants import AgentID, ComplianceTag, CredentialCategory
from core.exceptions import EscalationRequired
from schemas.credential import CredentialChecklist, CredentialDocument
from .tools import CredentialingTools
from .workflows import CredentialingWorkflow

logger = logging.getLogger(__name__)

ESCALATION_TRIGGERS = [
    "approve", "deny", "reject credential", "revoke", "invalid license",
    "expired license", "fraud", "falsif", "authentic", "tamper",
    "privileging", "interpret", "sufficient",
]


@dataclass
class DocumentClassification:
    document_id: str
    contact_id: str
    filename: str
    detected_category: str
    confidence: float  # 0.0–1.0
    requires_human_review: bool
    notes: str = ""


class CredentialingAgent:
    """
    CRED-001 — Medical Credentialing Agent.

    Responsibilities:
    - Request missing documents via SMS/email
    - Classify received documents into checklist categories
    - Track checklist completion per candidate
    - Schedule and send expiration reminders (30/14/7 days)
    - Generate secure upload links
    - Escalate approval decisions, authenticity concerns, and privileging to human
    """

    AGENT_ID = AgentID.CREDENTIALING

    ESCALATION_TRIGGERS = ESCALATION_TRIGGERS

    # Confidence threshold below which classification escalates for human review
    CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.75

    def __init__(self, client: anthropic.Anthropic, tools: CredentialingTools | None = None):
        self.client = client
        self.tools = tools or CredentialingTools()
        self.workflow = CredentialingWorkflow(self.tools)

    # ── Main Entry Points ──────────────────────────────────────────────────────

    def handle_document_received(
        self,
        contact_id: str,
        document_id: str,
        filename: str,
        file_content_hint: str = "",
    ) -> dict[str, Any]:
        """
        Process an inbound document upload.
        1. Log receipt with timestamp
        2. Classify into checklist category
        3. Update checklist status
        4. Check if checklist is now complete
        5. Return action dict
        """
        # Log receipt immediately — HIPAA audit requirement
        self.tools.log_document_receipt(contact_id, document_id, filename)

        # Classify document
        classification = self._classify_document(document_id, filename, file_content_hint)

        if classification.requires_human_review:
            return self._escalate(
                contact_id,
                f"Document {document_id} ({filename}) requires human review: "
                f"confidence={classification.confidence:.2f}, notes={classification.notes}",
            )

        # Update checklist
        self.tools.update_checklist_item(
            contact_id=contact_id,
            document_id=document_id,
            category=classification.detected_category,
            status="received",
            filename=filename,
        )

        # Check checklist completion
        checklist = self.tools.get_checklist(contact_id)
        return self.workflow.post_document_receipt(contact_id, document_id, classification, checklist)

    def handle_missing_document_request(
        self,
        contact_id: str,
        category: str,
        phone: str = "",
        email: str = "",
    ) -> dict[str, Any]:
        """
        Request a missing document from the candidate.
        Generates upload link and sends SMS/email.
        """
        upload_link = self.tools.generate_upload_link(contact_id, category)
        return self.workflow.request_document(
            contact_id=contact_id,
            category=category,
            upload_link=upload_link,
            phone=phone,
            email=email,
        )

    def handle_expiration_check(self, contact_id: str) -> list[dict[str, Any]]:
        """
        Check all credentialed documents for upcoming expirations.
        Sends reminders per REMINDER_SCHEDULE_DAYS = [30, 14, 7].
        Returns list of reminder actions taken.
        """
        expiring = self.tools.get_expiring_documents(contact_id, REMINDER_SCHEDULE_DAYS)
        actions = []
        for doc in expiring:
            action = self.workflow.send_expiration_reminder(contact_id, doc)
            actions.append(action)
        return actions

    def handle_checklist_status_request(self, contact_id: str) -> dict[str, Any]:
        """Return current checklist completion status."""
        checklist = self.tools.get_checklist(contact_id)
        missing = self._get_missing_categories(checklist)
        return {
            "action": "reply",
            "agent_id": self.AGENT_ID,
            "content": self._format_checklist_status(checklist, missing),
            "crm_updates": {
                "note": f"[CRED-001] Checklist status requested. Completion: {checklist.completion_pct}%.",
            },
            "checklist_pct": checklist.completion_pct,
            "missing_categories": missing,
        }

    # ── Document Classification ────────────────────────────────────────────────

    def _classify_document(
        self,
        document_id: str,
        filename: str,
        content_hint: str = "",
    ) -> DocumentClassification:
        """
        Use Claude to classify a document into a CredentialCategory.
        Falls back to filename heuristics if LLM unavailable.
        """
        category, confidence = self._classify_by_filename(filename)

        if confidence < self.CLASSIFICATION_CONFIDENCE_THRESHOLD and content_hint:
            category, confidence = self._classify_by_llm(filename, content_hint)

        requires_review = (
            confidence < self.CLASSIFICATION_CONFIDENCE_THRESHOLD
            or self._has_authenticity_concern(filename, content_hint)
        )

        return DocumentClassification(
            document_id=document_id,
            contact_id="",
            filename=filename,
            detected_category=category,
            confidence=confidence,
            requires_human_review=requires_review,
            notes="Low confidence — human review required." if requires_review else "",
        )

    def _classify_by_filename(self, filename: str) -> tuple[str, float]:
        """Heuristic classification from filename keywords."""
        lower = filename.lower()
        rules = [
            (["license", "lic_", "rn_", "md_", "do_", "np_", "dea", "npi"], CredentialCategory.LICENSURE, 0.85),
            (["passport", "driver", "id_", "ssn", "identity"], CredentialCategory.IDENTITY, 0.85),
            (["diploma", "degree", "transcript", "residency", "fellowship", "training"], CredentialCategory.EDUCATION_TRAINING, 0.80),
            (["malpractice", "insurance", "claims", "mal_"], CredentialCategory.MALPRACTICE, 0.85),
            (["tb", "mmr", "flu", "vacc", "immuniz", "hep", "titers", "health"], CredentialCategory.HEALTH_IMMUNIZATIONS, 0.80),
            (["background", "drug", "screen", "criminal", "bci"], CredentialCategory.BACKGROUND_DRUG, 0.85),
            (["employment", "reference", "work_hist", "verification"], CredentialCategory.WORK_HISTORY, 0.80),
        ]
        for keywords, category, confidence in rules:
            if any(kw in lower for kw in keywords):
                return category, confidence
        return CredentialCategory.IDENTITY, 0.40  # Unknown — low confidence

    def _classify_by_llm(self, filename: str, content_hint: str) -> tuple[str, float]:
        """Ask Claude to classify based on document content hint."""
        categories = [c.value for c in CredentialCategory]
        prompt = (
            f"Classify this healthcare credentialing document into exactly one of these categories: {categories}\n"
            f"Filename: {filename}\n"
            f"Content hint: {content_hint[:200]}\n"
            f"Return only the category name, nothing else."
        )
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=32,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip().lower()
            if raw in categories:
                return raw, 0.88
        except Exception as e:
            logger.warning("[CRED-001] LLM classification failed: %s", e)
        return CredentialCategory.IDENTITY, 0.40

    def _has_authenticity_concern(self, filename: str, content_hint: str) -> bool:
        """Flag documents that show signs of alteration or inauthenticity."""
        concern_keywords = [
            "altered", "modified", "photoshop", "edited", "scan error",
            "unreadable", "blurry", "corrupt", "expired",
        ]
        text = (filename + " " + content_hint).lower()
        return any(kw in text for kw in concern_keywords)

    def _get_missing_categories(self, checklist: CredentialChecklist) -> list[str]:
        missing = []
        for cat in CredentialCategory:
            items = getattr(checklist, cat.value, [])
            if not items or all(d.status in ("missing", "pending") for d in items):
                missing.append(cat.value)
        return missing

    def _format_checklist_status(
        self, checklist: CredentialChecklist, missing: list[str]
    ) -> str:
        lines = [f"Credentialing checklist: {checklist.completion_pct}% complete."]
        if missing:
            lines.append(f"Still needed: {', '.join(missing)}.")
        else:
            lines.append("All categories received. Pending specialist review.")
        return " ".join(lines)

    def _requires_escalation(self, text: str) -> str | None:
        lower = text.lower()
        for trigger in self.ESCALATION_TRIGGERS:
            if trigger in lower:
                return trigger
        return None

    def _escalate(self, contact_id: str, reason: str) -> dict[str, Any]:
        logger.warning("[CRED-001] Escalating contact=%s reason=%s", contact_id, reason)
        self.tools.add_crm_note(
            contact_id,
            f"[CRED-001] Escalated to credentialing specialist. Reason: {reason}",
        )
        self.tools.add_crm_tags(contact_id, [ComplianceTag.HUMAN_ESCALATION_REQUIRED])
        return {
            "action": "escalate",
            "agent_id": self.AGENT_ID,
            "content": "This credentialing item requires review by a specialist.",
            "escalation_reason": reason,
            "crm_updates": {
                "tags_add": [ComplianceTag.HUMAN_ESCALATION_REQUIRED],
                "note": f"[CRED-001] Escalated. Reason: {reason}",
            },
        }
