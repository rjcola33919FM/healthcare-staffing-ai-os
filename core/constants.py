"""
Core constants for Healthcare Staffing AI OS.
Single source of truth for agent IDs, event types, tags, and pipeline stages.
"""

from enum import Enum


class AgentID(str, Enum):
    ORCHESTRATOR = "ORCH-001"
    RECRUITING    = "REC-001"
    CREDENTIALING = "CRED-001"
    COMPLIANCE    = "COMP-001"
    SALES         = "SALES-001"
    CRM           = "CRM-001"
    HUMAN         = "HUMAN"


class EventType(str, Enum):
    # Recruiting
    CANDIDATE_INTAKE          = "candidate_intake"
    CANDIDATE_MESSAGE         = "candidate_message"
    CANDIDATE_FAQ             = "candidate_faq"
    BOOK_RECRUITER_APPT       = "book_recruiter_appointment"

    # Credentialing
    DOCUMENT_UPLOAD           = "document_upload"
    DOCUMENT_REQUEST          = "document_request"
    CHECKLIST_STATUS          = "checklist_status"
    CREDENTIAL_REMINDER       = "credential_reminder"
    LICENSE_EXPIRY            = "license_expiry"

    # Compliance
    COMPLIANCE_ALERT          = "compliance_alert"
    AUDIT_EVENT               = "audit_event"
    CREDENTIAL_EXPIRY         = "credential_expiry"
    PHI_EXPOSURE              = "phi_exposure"
    SANCTIONS_CHECK           = "sanctions_check"

    # Sales
    LEAD_INBOUND              = "lead_inbound"
    CLIENT_INQUIRY            = "client_inquiry"
    BOOK_SALES_APPT           = "book_sales_appointment"
    LEAD_QUALIFICATION        = "lead_qualification"

    # CRM
    CRM_UPDATE                = "crm_update"
    TAG_APPLY                 = "tag_apply"
    PIPELINE_STAGE_CHANGE     = "pipeline_stage_change"
    WEBHOOK_SYNC              = "webhook_sync"
    NOTE_CREATE               = "note_create"

    # Always-human
    CREDENTIAL_APPROVAL       = "credential_approval"
    CONTRACT_TERMS            = "contract_terms"
    CANDIDATE_REJECTION       = "candidate_rejection"
    COMPLIANCE_EXCEPTION      = "compliance_exception"
    PRICING_EXCEPTION         = "pricing_exception"
    PHI_BREACH                = "phi_breach"


class EscalationReason(str, Enum):
    HIPAA_GUARDRAIL           = "HIPAA guardrail triggered in response content"
    CREDENTIAL_APPROVAL       = "Credential approval requires human specialist"
    CONTRACT_TERMS            = "Contract terms require human sales leader"
    CANDIDATE_REJECTION       = "Candidate rejection requires human recruiter"
    COMPLIANCE_EXCEPTION      = "Adverse compliance flag requires human review"
    PRICING_EXCEPTION         = "Pricing exception requires human approval"
    PHI_EXPOSURE              = "PHI exposure event — immediate escalation required"
    CRM_MERGE_CONFLICT        = "CRM merge conflict requires human operator"
    AMBIGUOUS_INTENT          = "Intent too ambiguous to route confidently"
    AGENT_NOT_FOUND           = "No registered handler for target agent"
    API_ERROR                 = "Upstream API failure after max retries"


class ComplianceTag(str, Enum):
    COMPLIANT                 = "compliant"
    AT_RISK                   = "at_risk"
    NON_COMPLIANT             = "non_compliant"
    ESCALATED                 = "escalated"
    HUMAN_ESCALATION_REQUIRED = "human_escalation_required"
    PENDING_REVIEW            = "pending_review"
    ACTION_REQUIRED           = "action_required"


class PipelineStage(str, Enum):
    # Candidate pipeline
    NEW_LEAD                  = "new_lead"
    INTAKE_IN_PROGRESS        = "intake_in_progress"
    INTAKE_COMPLETE           = "intake_complete"
    CREDENTIALING             = "credentialing"
    CREDENTIALING_COMPLETE    = "credentialing_complete"
    PLACED                    = "placed"
    INACTIVE                  = "inactive"

    # Sales/client pipeline
    NEW_OPPORTUNITY           = "new_opportunity"
    QUALIFIED                 = "qualified"
    PROPOSAL_SENT             = "proposal_sent"
    CLOSED_WON                = "closed_won"
    CLOSED_LOST               = "closed_lost"
    DISQUALIFIED              = "disqualified"


class CredentialCategory(str, Enum):
    IDENTITY                  = "identity"
    LICENSURE                 = "licensure"
    EDUCATION_TRAINING        = "education_training"
    WORK_HISTORY              = "work_history"
    MALPRACTICE               = "malpractice"
    HEALTH_IMMUNIZATIONS      = "health_immunizations"
    BACKGROUND_DRUG           = "background_drug"


class AlertLevel(str, Enum):
    RED    = "red"    # Expired or missing mandatory item
    YELLOW = "yellow" # Expiring within 30 days
    BLUE   = "blue"   # Received, awaiting classification
