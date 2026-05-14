"""
CRED-001 Workflows — Credentialing lifecycle step sequences.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, TYPE_CHECKING

from core.constants import PipelineStage, ComplianceTag
from schemas.credential import CredentialChecklist

if TYPE_CHECKING:
    from .agent import DocumentClassification
    from .tools import CredentialingTools

logger = logging.getLogger(__name__)

DOCUMENT_REQUEST_TEMPLATES: dict[str, str] = {
    "identity":             "a government-issued photo ID (passport or driver's license)",
    "licensure":            "your current state medical license and DEA certificate (if applicable)",
    "education_training":   "your diploma and residency/fellowship completion certificates",
    "work_history":         "employment verification letters from your last 5 years",
    "malpractice":          "your current malpractice insurance certificate and claims history",
    "health_immunizations": "proof of immunizations (TB, MMR, flu, Hep B, and titers)",
    "background_drug":      "consent for background check and drug screening",
}


class CredentialingWorkflow:
    def __init__(self, tools: "CredentialingTools"):
        self.tools = tools

    def request_document(
        self,
        contact_id: str,
        category: str,
        upload_link: str,
        phone: str = "",
        email: str = "",
    ) -> dict[str, Any]:
        """
        Request a missing document:
        1. Generate human-readable request message
        2. Send via SMS and/or email
        3. Log CRM note
        4. Create follow-up task
        """
        doc_description = DOCUMENT_REQUEST_TEMPLATES.get(
            category, f"required {category.replace('_', ' ')} documentation"
        )
        message = (
            f"To complete your credentialing file, we need {doc_description}. "
            f"Please upload securely here: {upload_link} "
            f"(link expires in 72 hours). Reply with any questions."
        )

        if phone:
            self.tools.send_sms(contact_id, phone, message)
        if email:
            self.tools.send_email(
                contact_id, email,
                subject=f"Action Required: Upload {category.replace('_', ' ').title()}",
                body=message,
            )

        due = (date.today() + timedelta(days=5)).isoformat()
        self.tools.create_task(
            contact_id=contact_id,
            title=f"Follow up: {category} document not received",
            due_date=due,
        )
        self.tools.add_crm_note(
            contact_id,
            f"[CRED-001] Document request sent. Category: {category}. "
            f"Upload link issued. Due: {due}.",
        )

        logger.info("[CRED-WF] Document requested contact=%s category=%s", contact_id, category)

        return {
            "action": "reply",
            "agent_id": "CRED-001",
            "content": message,
            "crm_updates": {
                "note": f"[CRED-001] Document request sent for category={category}.",
                "task": {"title": f"Follow up: {category} not received", "due_date": due},
            },
        }

    def post_document_receipt(
        self,
        contact_id: str,
        document_id: str,
        classification: "DocumentClassification",
        checklist: CredentialChecklist,
    ) -> dict[str, Any]:
        """
        Actions after a document is successfully classified:
        - Update CRM note
        - Check if checklist now complete
        - If complete → move pipeline to credentialing_complete + notify specialist
        """
        self.tools.add_crm_note(
            contact_id,
            f"[CRED-001] Document classified. doc_id={document_id} "
            f"category={classification.detected_category} "
            f"confidence={classification.confidence:.2f}. "
            f"Checklist now {checklist.completion_pct}% complete.",
        )

        if checklist.completion_pct == 100.0 and not checklist.has_missing_mandatory:
            return self._checklist_complete(contact_id, checklist)

        return {
            "action": "crm_update",
            "agent_id": "CRED-001",
            "content": (
                f"Document received and classified as {classification.detected_category}. "
                f"Checklist is {checklist.completion_pct}% complete."
            ),
            "crm_updates": {
                "note": f"[CRED-001] Document {document_id} classified → {classification.detected_category}.",
            },
            "checklist_pct": checklist.completion_pct,
        }

    def _checklist_complete(self, contact_id: str, checklist: CredentialChecklist) -> dict[str, Any]:
        """All documents received — move to credentialing_complete, notify specialist."""
        self.tools.update_pipeline_stage(contact_id, PipelineStage.CREDENTIALING_COMPLETE)
        self.tools.add_crm_tags(contact_id, [PipelineStage.CREDENTIALING_COMPLETE])
        self.tools.add_crm_tags(contact_id, [ComplianceTag.HUMAN_ESCALATION_REQUIRED])
        self.tools.create_task(
            contact_id=contact_id,
            title="Review complete credentialing file — specialist approval required",
            due_date=(date.today() + timedelta(days=2)).isoformat(),
        )
        self.tools.add_crm_note(
            contact_id,
            f"[CRED-001] All credentialing documents received. "
            f"File routed to specialist for final review and approval.",
        )

        logger.info("[CRED-WF] Checklist complete — routed to specialist. contact=%s", contact_id)

        return {
            "action": "escalate",
            "agent_id": "CRED-001",
            "content": (
                "All credentialing documents have been received. "
                "Your file has been routed to a credentialing specialist for final review."
            ),
            "escalation_reason": "Checklist 100% complete — final approval required by specialist.",
            "crm_updates": {
                "tags_add": [PipelineStage.CREDENTIALING_COMPLETE, ComplianceTag.HUMAN_ESCALATION_REQUIRED],
                "note": "[CRED-001] Complete file routed to specialist.",
            },
        }

    def send_expiration_reminder(
        self,
        contact_id: str,
        doc: dict[str, Any],
        phone: str = "",
        email: str = "",
    ) -> dict[str, Any]:
        """Send a credential expiration reminder for a single document."""
        days = doc["days_remaining"]
        category = doc.get("category", "credential")
        name = doc.get("document_name", category)
        exp_date = doc.get("expiration_date", "")

        message = (
            f"Important: Your {name} expires in {days} day{'s' if days != 1 else ''} "
            f"({exp_date}). Please renew and upload your updated document to maintain "
            f"your active placement status."
        )
        upload_link = self.tools.generate_upload_link(contact_id, category)
        full_message = f"{message} Upload here: {upload_link}"

        if phone:
            self.tools.send_sms(contact_id, phone, full_message)
        if email:
            self.tools.send_email(
                contact_id, email,
                subject=f"Action Required: {name} Expiring in {days} Days",
                body=full_message,
            )

        self.tools.add_crm_note(
            contact_id,
            f"[CRED-001] Expiration reminder sent. doc_id={doc['document_id']} "
            f"days_remaining={days} exp_date={exp_date}.",
        )
        self.tools.add_crm_tags(contact_id, [ComplianceTag.AT_RISK])

        return {
            "action": "crm_update",
            "agent_id": "CRED-001",
            "document_id": doc["document_id"],
            "days_remaining": days,
            "reminder_sent": True,
            "crm_updates": {
                "tags_add": [ComplianceTag.AT_RISK],
                "note": f"[CRED-001] Reminder sent: {name} expires in {days} days.",
            },
        }
