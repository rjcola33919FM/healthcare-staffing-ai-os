"""
HIPAA compliance configuration.
Defines guardrail keywords, PHI field restrictions, and audit requirements.
"""

from __future__ import annotations

# Keywords that trigger immediate human escalation when found in agent responses
GUARDRAIL_KEYWORDS: list[str] = [
    "legal",
    "clinical judgment",
    "diagnosis",
    "treatment",
    "privileging",
    "final approval",
    "contract terms",
    "litigation",
    "malpractice",
    "contract amendment",
    "employment eligibility",
    "license revocation",
    "sanctions",
    "exclusion list",
]

# CRM fields that must never be stored in plain-text notes
PHI_RESTRICTED_FIELDS: list[str] = [
    "ssn",
    "social_security_number",
    "date_of_birth",
    "dob",
    "medical_record_number",
    "health_history",
    "insurance_id",
    "diagnosis_code",
    "icd_code",
]

# Credential reminder schedule (days before expiration)
REMINDER_SCHEDULE_DAYS: list[int] = [30, 14, 7]

# Mandatory credential categories that must be present before placement
MANDATORY_CREDENTIAL_CATEGORIES: list[str] = [
    "identity",
    "licensure",
    "background_drug",
]

# Compliance tag hierarchy
COMPLIANCE_TAG_HIERARCHY: dict[str, int] = {
    "compliant": 0,
    "at_risk": 1,
    "non_compliant": 2,
    "escalated": 3,
    "human_escalation_required": 4,
}

# Audit log is append-only — no deletion or modification allowed
AUDIT_LOG_IMMUTABLE: bool = True

# Maximum retention period for audit logs (days)
AUDIT_LOG_RETENTION_DAYS: int = 2555  # 7 years (HIPAA requirement)
