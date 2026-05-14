# Credentialing Requirements by Role
# Source of truth for CRED-001 document classification and request logic.

## Universal Requirements (All Roles)

| Category | Documents Required |
|---|---|
| Identity | Government-issued photo ID (passport or driver's license) + SSN verification |
| Licensure | Current state medical license (active, unencumbered) |
| Background | Criminal background check consent + drug screening consent |
| Health | TB test (within 1 year), flu vaccination (current season), COVID-19 status |

## Role-Specific Requirements

### Registered Nurse (RN) / Licensed Practical Nurse (LPN)
- State RN/LPN license (primary state + compact states if applicable)
- BLS certification (current)
- ACLS certification (ICU, ED, OR, Telemetry roles)
- PALS certification (Pediatric, NICU roles)
- 1–2 years recent clinical experience verification

### Advanced Practice (NP, CRNA, PA)
- State APRN/PA license
- DEA registration (if prescribing)
- NPI number
- Board certification certificate
- Malpractice insurance (minimum $1M/$3M)
- Work history: 5 years + references from supervising physicians

### Physician (MD, DO)
- State medical license (all states of practice)
- DEA registration
- NPI number
- Board certification
- Medical school diploma + residency/fellowship certificates
- Malpractice insurance (minimum $1M/$3M)
- NPDB self-query (within 30 days)
- Full work history: 10 years

### Allied Health (PT, OT, RT, Rad Tech, etc.)
- State professional license
- National certification (NBRC, ARRT, NBCOT, etc.)
- BLS certification
- 1–2 years recent experience verification

## Document Expiration Windows

| Document | Expiration Alert (Yellow) | Blocked (Red) |
|---|---|---|
| State License | 30 days before expiry | Day of expiry |
| DEA Registration | 30 days before expiry | Day of expiry |
| BLS/ACLS/PALS | 30 days before expiry | Day of expiry |
| Malpractice Insurance | 30 days before expiry | Day of expiry |
| TB Test | 30 days before 1-year mark | After 1 year |
| Flu Vaccination | Season end (April 30) | After season |

## Escalation Rules for CRED-001
- NEVER approve or deny credentials
- NEVER interpret license status, scope of practice, or privileging
- NEVER make authenticity determinations on documents
- Route ALL of the above to human credentialing specialist immediately
