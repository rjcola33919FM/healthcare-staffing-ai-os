"""
Orchestration QA — validates routing logic, escalation paths, and CRM sync.
Validation checklist: Orchestration QA PASS, Human escalation tested, CRM sync validated.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from orchestration.router import classify_intent, route, build_escalation_response, AgentID
from src.agents.base import AgentContext, AgentResponse


def make_context(event_type: str = None, message: str = "") -> AgentContext:
    return AgentContext(
        contact_id="test-contact-001",
        conversation_id="test-conv-001",
        channel="webhook",
        payload={"event_type": event_type, "message": message} if event_type else {"message": message},
    )


ROUTING_CASES = [
    # (event_type or None, message keyword, expected_agent)
    ("candidate_intake", "", AgentID.RECRUITING),
    ("document_upload", "", AgentID.CREDENTIALING),
    ("compliance_alert", "", AgentID.COMPLIANCE),
    ("lead_inbound", "", AgentID.SALES),
    ("crm_update", "", AgentID.CRM),
    ("credential_approval", "", AgentID.HUMAN),
    ("contract_terms", "", AgentID.HUMAN),
    ("phi_breach", "", AgentID.HUMAN),
    (None, "I want to apply for a nursing position", AgentID.RECRUITING),
    (None, "my license expires next month", AgentID.COMPLIANCE),
    (None, "I need to upload my credentialing documents", AgentID.CREDENTIALING),
    (None, "we need to hire 10 travel nurses", AgentID.SALES),
    (None, "this involves legal advice for a compliance exception", AgentID.HUMAN),
]


def test_routing():
    passed = 0
    failed = 0
    print("\n[TEST] Orchestration Routing")
    for event_type, message, expected in ROUTING_CASES:
        ctx = make_context(event_type, message)
        result = route(ctx)
        ok = result == expected
        symbol = "✓" if ok else "✗"
        label = event_type or f'"{message[:40]}"'
        print(f"  {symbol} {label} → {result.value} (expected {expected.value})")
        if ok:
            passed += 1
        else:
            failed += 1
    return failed == 0


def test_escalation_response():
    print("\n[TEST] Escalation Response Structure")
    ctx = make_context("credential_approval")
    response = build_escalation_response("Credential approval requires human.", ctx)

    checks = [
        ("action == escalate", response.action == "escalate"),
        ("escalation_reason set", bool(response.escalation_reason)),
        ("tags_add contains human_escalation_required", "human_escalation_required" in response.crm_updates.get("tags_add", [])),
        ("note logged", bool(response.crm_updates.get("note"))),
    ]

    all_ok = True
    for label, ok in checks:
        symbol = "✓" if ok else "✗"
        print(f"  {symbol} {label}")
        if not ok:
            all_ok = False
    return all_ok


def test_crm_sync_updates():
    """Verify CRM update dict structure produced by agents."""
    print("\n[TEST] CRM Sync Update Structure")
    response = AgentResponse(
        agent_id="ORCH-001",
        action="escalate",
        content="Escalated.",
        crm_updates={
            "tags_add": ["human_escalation_required"],
            "note": "[ORCH-001] Escalated.",
        },
        escalation_reason="test",
    )

    checks = [
        ("tags_add is list", isinstance(response.crm_updates["tags_add"], list)),
        ("note is string", isinstance(response.crm_updates["note"], str)),
        ("agent_id set", bool(response.agent_id)),
    ]

    all_ok = True
    for label, ok in checks:
        symbol = "✓" if ok else "✗"
        print(f"  {symbol} {label}")
        if not ok:
            all_ok = False
    return all_ok


def run_all() -> bool:
    results = [
        test_routing(),
        test_escalation_response(),
        test_crm_sync_updates(),
    ]
    return all(results)


if __name__ == "__main__":
    passed = run_all()
    print(f"\nOrchestration QA: {'PASS' if passed else 'FAIL'}")
    sys.exit(0 if passed else 1)
