# Compliance Monitoring Rules
# Source of truth for COMP-001 alert generation and escalation logic.

## Alert Level Definitions

| Level | Color | Trigger | Action |
|---|---|---|---|
| RED | 🔴 | Credential expired OR missing mandatory item | Block placement + escalate immediately |
| YELLOW | 🟡 | Credential expiring within 30 days | Alert + reminder + task creation |
| BLUE | 🔵 | Document received, awaiting classification | Notify CRED-001 for classification |

## Mandatory Credentials (Placement Blocking)

A candidate CANNOT be placed without verified:
1. Active state license (unencumbered)
2. Current background check (within 12 months)
3. Current drug screen (within 12 months)
4. Valid government-issued identity document

## Adverse Flag Definitions

These triggers require IMMEDIATE escalation to compliance officer:

| Flag | Source | Severity |
|---|---|---|
| OIG Exclusion | OIG LEIE database | CRITICAL |
| SAM Exclusion | SAM.gov | CRITICAL |
| License Revocation/Surrender | State licensing board | CRITICAL |
| License Probation/Restriction | State licensing board | HIGH |
| NPDB Adverse Report | NPDB query | HIGH |
| Malpractice Judgment | Court records / NPDB | HIGH |
| Criminal Conviction (felony) | Background check | CRITICAL |
| PHI Exposure | System detection | CRITICAL |

## HIPAA PHI Rules

PHI must NEVER appear in:
- CRM contact notes (use document_id references only)
- SMS/email messages
- Agent response content
- Audit log entries

PHI fields that trigger detection:
- SSN / Social Security Number
- Date of Birth
- Medical record numbers
- Diagnosis codes (ICD-10)
- Health plan / insurance IDs
- Patient identifiers

## Audit Log Requirements

- Every credential state change must be logged
- Log entry format: [AGENT_ID] [ISO_TIMESTAMP] [ACTION]: [DETAIL]
- Logs are append-only — no modification or deletion
- Retention: 7 years (2,555 days) — HIPAA minimum
- PHI exposure events must be logged with escalated=True

## Compliance Tag Lifecycle

```
new_lead
  → intake_in_progress (no compliance tags yet)
  → intake_complete (run missing_mandatory_check)
  → credentialing (apply at_risk until all docs verified)
  → credentialing_complete (run full compliance scan)
  → placed (compliant tag required before placement)
```
