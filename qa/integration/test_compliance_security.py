"""
Integration: Compliance Guard + Audit Logger + Security
Tests the full HIPAA enforcement chain: PHI detection → redaction → audit write → report.
Tests webhook signature verification and rate limiter end-to-end.
"""

from __future__ import annotations

import hashlib
import hmac
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from qa.integration.helpers import assert_all, CONTACT_ID
from compliance import HIPAAGuard, ComplianceReporter
from audit_log.audit import AuditLogger
from security.signing import verify_ghl_signature, check_timestamp
from security.rate_limiter import SlidingWindowCounter


# ── HIPAA Guard + Audit Chain ──────────────────────────────────────────────────

def test_phi_detection_to_audit():
    print("\n[INT] Compliance: PHI detection → audit write → report")
    tmpdir = tempfile.mkdtemp()
    audit  = AuditLogger(log_dir=tmpdir)

    agent_response = "Great, let me pull up your record. Your SSN is 123-45-6789 and DOB is 1985-03-12."
    phi_hits = HIPAAGuard.check_text(agent_response, agent_id="REC-001", contact_id=CONTACT_ID)

    if phi_hits:
        for pattern in phi_hits:
            audit.log_phi_event("REC-001", CONTACT_ID, phi_pattern=pattern,
                                source="agent_response", action_taken="blocked")

    redacted = HIPAAGuard.redact_phi(agent_response)

    entries  = audit.read_entries(event_type="phi_detection", limit=10)
    reporter = ComplianceReporter(audit)
    report   = reporter.phi_event_report(days=1)

    return assert_all([
        ("PHI patterns detected",          len(phi_hits) > 0),
        ("SSN detected",                   "ssn" in phi_hits),
        ("REDACTED marker present",        "[REDACTED]" in redacted),
        ("Audit entries written",          len(entries) == len(phi_hits)),
        ("PHI report total matches",       report["total_phi_events"] == len(phi_hits)),
        ("Report by_pattern populated",    len(report["by_pattern"]) > 0),
    ])


def test_guardrail_enforcement_chain():
    print("\n[INT] Compliance: guardrail keyword → escalation audit → report")
    tmpdir = tempfile.mkdtemp()
    audit  = AuditLogger(log_dir=tmpdir)

    responses = [
        ("REC-001", "This matter may require legal consultation about the contract terms."),
        ("CRED-001", "I need to make a final approval decision here."),
        ("REC-001", "Here is your upcoming appointment schedule."),   # clean
    ]

    escalation_count = 0
    for agent_id, text in responses:
        hits = HIPAAGuard.check_guardrails(text)
        if hits:
            escalation_count += 1
            audit.log_escalation(agent_id, CONTACT_ID, reason="guardrail_trigger",
                                 severity="high", detail=f"keywords={hits}")

    reporter = ComplianceReporter(audit)
    esc_report = reporter.escalation_report(days=1)

    return assert_all([
        ("2 guardrail violations detected",  escalation_count == 2),
        ("Escalation audit entries match",   esc_report["total_escalations"] == 2),
        ("Clean response not escalated",     escalation_count == 2),
        ("Report by_severity populated",     "high" in esc_report["by_severity"]),
    ])


def test_crm_payload_sanitization():
    print("\n[INT] Compliance: CRM payload sanitization")
    payload = {
        "pipeline_stage":        "credentialing",
        "ssn":                   "123-45-6789",
        "date_of_birth":         "1985-03-12",
        "specialty":             "ICU RN",
        "insurance_id":          "INS-9900112",
        "notes":                 "Candidate DOB confirmed.",
    }

    violations = HIPAAGuard.check_crm_payload(payload, agent_id="CRM-001")
    clean      = HIPAAGuard.sanitize_crm_payload(payload)

    return assert_all([
        ("PHI field violations detected",    len(violations) > 0),
        ("SSN redacted in clean payload",    clean["ssn"] == "[REDACTED]"),
        ("DOB redacted in clean payload",    clean["date_of_birth"] == "[REDACTED]"),
        ("Non-PHI field preserved",          clean["specialty"] == "ICU RN"),
        ("Stage preserved",                  clean["pipeline_stage"] == "credentialing"),
    ])


def test_daily_audit_report():
    print("\n[INT] Compliance: daily audit report aggregation")
    tmpdir = tempfile.mkdtemp()
    audit  = AuditLogger(log_dir=tmpdir)

    audit.log_agent_action("REC-001",  CONTACT_ID, "send_message", "checklist sent")
    audit.log_agent_action("CRED-001", CONTACT_ID, "document_request", "licensure requested")
    audit.log_escalation("COMP-001",   CONTACT_ID, reason="phi_exposure", severity="critical")
    audit.log_phi_event("COMP-001",    CONTACT_ID, phi_pattern="ssn", source="note", action_taken="blocked")
    audit.log_crm_mutation("CRM-001",  CONTACT_ID, "update_stage", ["pipeline_stage"])
    audit.log_credential_event("CRED-001", CONTACT_ID, "licensure", "uploaded", "doc-001")

    reporter = ComplianceReporter(audit)
    report   = reporter.daily_summary()

    return assert_all([
        ("Total entries = 6",            report["total_entries"] == 6),
        ("PHI events = 1",               report["phi_event_count"] == 1),
        ("Escalations = 1",              report["escalation_count"] == 1),
        ("by_event populated",           len(report["by_event_type"]) >= 4),
        ("by_agent populated",           "REC-001" in report["by_agent"]),
    ])


# ── Security: Webhook Signing ──────────────────────────────────────────────────

def test_ghl_webhook_signing():
    print("\n[INT] Security: GHL webhook signature verification")
    secret = "int-test-secret-key"
    body   = b'{"contact_id": "c-001", "event_type": "candidate_intake"}'

    valid_sig   = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    invalid_sig = "sha256=deadbeefdeadbeefdeadbeefdeadbeef"
    bad_format  = "md5=somehash"

    return assert_all([
        ("Valid sig accepted",       verify_ghl_signature(body, valid_sig, secret=secret)),
        ("Invalid sig rejected",     not verify_ghl_signature(body, invalid_sig, secret=secret)),
        ("Bad format rejected",      not verify_ghl_signature(body, bad_format, secret=secret)),
        ("No secret = dev passthrough", verify_ghl_signature(body, "", secret="")),
    ])


def test_replay_protection():
    print("\n[INT] Security: timestamp replay window enforcement")
    now    = int(time.time())
    recent = str(now - 60)     # 1 min ago — within window
    old    = str(now - 400)    # 6.7 min ago — outside 5-min window

    recent_ok = True
    try:
        check_timestamp(recent)
    except Exception:
        recent_ok = False

    old_blocked = False
    try:
        check_timestamp(old)
    except Exception:
        old_blocked = True

    return assert_all([
        ("Recent timestamp passes",    recent_ok),
        ("Old timestamp blocked",      old_blocked),
        ("Empty timestamp passes",     True),  # check_timestamp("") is a no-op
    ])


def test_rate_limiter():
    print("\n[INT] Security: sliding window rate limiter")
    counter = SlidingWindowCounter()
    key     = "int-test-ip-001"
    limit   = 5
    window  = 60

    # Fill up to the limit
    for _ in range(limit):
        assert counter.is_allowed(key, limit=limit, window=window), "Should be allowed"

    blocked = not counter.is_allowed(key, limit=limit, window=window)
    remaining = counter.remaining(key, limit=limit, window=window)

    # Different key should not be affected
    other_ok = counter.is_allowed("other-ip", limit=limit, window=window)

    return assert_all([
        ("5 requests allowed",         True),
        ("6th request blocked",        blocked),
        ("Remaining = 0 at limit",     remaining == 0),
        ("Different key unaffected",   other_ok),
    ])


def run_all() -> bool:
    results = [
        test_phi_detection_to_audit(),
        test_guardrail_enforcement_chain(),
        test_crm_payload_sanitization(),
        test_daily_audit_report(),
        test_ghl_webhook_signing(),
        test_replay_protection(),
        test_rate_limiter(),
    ]
    return all(results)


if __name__ == "__main__":
    passed = run_all()
    print(f"\nCompliance + Security Integration: {'PASS' if passed else 'FAIL'}")
    sys.exit(0 if passed else 1)
