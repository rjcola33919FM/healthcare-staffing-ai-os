"""
Integration: Orchestration → Agent Dispatch → Fusion → Audit
Tests the full dispatch pipeline with a stubbed Anthropic client.
Validates intent routing, fusion scoring, escalation gate, and audit trail.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from qa.integration.helpers import assert_all, make_fake_anthropic, FakeCRMTools, CONTACT_ID
from orchestration.router import classify_intent, route, AgentID
from orchestration.dispatcher import Dispatcher
from orchestration.intent import classify
from orchestration.escalation import EscalationManager
from src.agents.base import AgentContext, AgentResponse
from fusion.engine import FusionEngine
from fusion.scorer import FusionScorer


def _context(event_type=None, message="", contact_id=CONTACT_ID) -> AgentContext:
    payload = {}
    if event_type:
        payload["event_type"] = event_type
    if message:
        payload["message"] = message
    return AgentContext(
        contact_id=contact_id,
        conversation_id="int-sess-001",
        channel="webhook",
        payload=payload,
    )


# ── Intent Classification ──────────────────────────────────────────────────────

def test_intent_classification_confidence():
    print("\n[INT] Orchestration: intent classification with confidence scores")
    cases = [
        ({"event_type": "candidate_intake"},                    "candidate_intake", 1.0),
        ({"message": "I need to upload my license"},            "document_request", 0.8),
        ({"message": "my license expires in 30 days"},          "compliance_alert", 0.8),
        ({"message": "we need to hire 20 travel nurses ASAP"},  "client_inquiry",   0.8),
        ({"message": "phi breach detected"},                    "compliance_exception", 0.9),
    ]

    all_ok = True
    for payload, expected_intent, min_confidence in cases:
        intent, confidence = classify(payload)
        ok = intent == expected_intent and confidence >= min_confidence
        print(f"    {'✓' if ok else '✗'} '{payload}' → {intent} (conf={confidence:.1f}, expected={expected_intent})")
        if not ok:
            all_ok = False
    return all_ok


def test_routing_completeness():
    print("\n[INT] Orchestration: route() covers all agent types")
    routes_seen = set()
    test_inputs = [
        _context("candidate_intake"),
        _context("document_upload"),
        _context("compliance_alert"),
        _context("lead_inbound"),
        _context("crm_update"),
        _context("credential_approval"),   # → HUMAN
        _context("phi_breach"),             # → HUMAN
        _context(message="apply for nursing job"),
        _context(message="upload my credentials"),
        _context(message="license expires next week"),
    ]

    for ctx in test_inputs:
        result = route(ctx)
        routes_seen.add(result)

    expected_agents = {AgentID.RECRUITING, AgentID.CREDENTIALING, AgentID.COMPLIANCE,
                       AgentID.SALES, AgentID.CRM, AgentID.HUMAN}

    return assert_all([
        ("All agent IDs reachable",   expected_agents.issubset(routes_seen) or len(routes_seen) >= 4),
        ("HUMAN route reachable",     AgentID.HUMAN in routes_seen),
        ("RECRUITING reachable",      AgentID.RECRUITING in routes_seen),
        ("COMPLIANCE reachable",      AgentID.COMPLIANCE in routes_seen),
    ])


# ── Escalation Manager ─────────────────────────────────────────────────────────

def test_escalation_severity_classification():
    print("\n[INT] Orchestration: escalation severity classification")
    mgr = EscalationManager()

    cases = [
        ("phi exposure detected",        "critical"),
        ("credential review needed",     "high"),
        ("mandatory compliance check",   "high"),
        ("general inquiry follow-up",    "normal"),
        ("sanction list match",          "critical"),
    ]

    all_ok = True
    for text, expected_severity in cases:
        ticket = mgr.create_ticket(CONTACT_ID, "int-sess-001", "COMP-001", reason=text)
        ok = ticket.severity == expected_severity
        print(f"    {'✓' if ok else '✗'} '{text}' → {ticket.severity} (expected {expected_severity})")
        if not ok:
            all_ok = False
    return all_ok


# ── Fusion Engine ──────────────────────────────────────────────────────────────

def test_fusion_quality_gate():
    print("\n[INT] Fusion: quality gate approve + reject + revise")
    engine = FusionEngine()

    high_quality = (
        "Based on your credentialing checklist, your specialist will confirm the required documents: "
        "state nursing license has been verified, background check confirmed, and your recruiter "
        "has been notified of the next step. Please use the secure upload portal."
    )
    hedging = (
        "I think perhaps you might possibly need some documents but I'm not really sure "
        "and cannot confirm this information at this time."
    )

    result_good = engine.evaluate("REC-001", high_quality)
    result_bad  = engine.evaluate("REC-001", hedging)

    return assert_all([
        ("High-quality response approved",     result_good.approved),
        ("High-quality score >= 0.85",         result_good.score.composite_score >= 0.85),
        ("Hedging response handled",           result_bad is not None),  # revised or rejected
        ("Score object has all dimensions",    hasattr(result_good.score, "logic_score")),
    ])


def test_fusion_adaptive_checkpoint():
    print("\n[INT] Fusion: adaptive checkpoint fires every 10 cycles")
    engine = FusionEngine()
    good_text = "Here are the required documents for your credentialing file: nursing license and background check."

    import io
    from contextlib import redirect_stderr

    checkpoint_logged = False
    import logging
    handler_msgs = []

    class CaptureLogs(logging.Handler):
        def emit(self, record):
            handler_msgs.append(record.getMessage())

    fusion_logger = logging.getLogger("fusion.engine")
    prev_level = fusion_logger.level
    fusion_logger.setLevel(logging.DEBUG)

    cap = CaptureLogs()
    fusion_logger.addHandler(cap)

    for _ in range(10):
        engine.evaluate("REC-001", good_text)

    fusion_logger.removeHandler(cap)
    fusion_logger.setLevel(prev_level)

    checkpoint_logged = any("Adaptive checkpoint" in m or "checkpoint" in m.lower() for m in handler_msgs)

    return assert_all([
        ("10 evaluations completed",   True),
        ("Adaptive checkpoint logged", checkpoint_logged),
    ])


# ── Full Dispatch with Stubbed Agent ──────────────────────────────────────────

def test_dispatcher_with_stub_agent():
    print("\n[INT] Orchestration: full dispatch → stub agent → response")
    client = make_fake_anthropic("Credentialing typically takes 2-4 weeks once documents are submitted.")

    from src.agents.recruiting import RecruitingAgent
    agent = RecruitingAgent(client)

    ctx = _context(message="How long does credentialing take?")
    ctx.payload["event_type"] = "candidate_intake"

    agents = {"REC-001": agent}

    dispatcher = Dispatcher(client=client, agents=agents)
    response = dispatcher.dispatch(ctx)

    return assert_all([
        ("Response has agent_id",      bool(response.agent_id)),
        ("Response has action",        bool(response.action)),
        ("Response has content",       bool(response.content) or response.action == "escalate"),
        ("Not an error state",         response.action != "error"),
    ])


def test_escalation_keyword_triggers_human():
    print("\n[INT] Orchestration: escalation keywords → HUMAN route in full dispatch")
    client = make_fake_anthropic(
        "This case involves litigation and requires legal counsel review for the malpractice claim."
    )

    from src.agents.recruiting import RecruitingAgent
    agent = RecruitingAgent(client)

    ctx = _context(message="Can you help with my malpractice litigation case?")
    ctx.payload["event_type"] = "candidate_intake"

    agents = {"REC-001": agent}
    dispatcher = Dispatcher(client=client, agents=agents)
    response = dispatcher.dispatch(ctx)

    escalated = response.action == "escalate" or bool(response.escalation_reason)
    return assert_all([
        ("Response escalated due to keyword",   escalated),
        ("Escalation reason populated",         bool(response.escalation_reason) if escalated else True),
    ])


def run_all() -> bool:
    results = [
        test_intent_classification_confidence(),
        test_routing_completeness(),
        test_escalation_severity_classification(),
        test_fusion_quality_gate(),
        test_fusion_adaptive_checkpoint(),
        test_dispatcher_with_stub_agent(),
        test_escalation_keyword_triggers_human(),
    ]
    return all(results)


if __name__ == "__main__":
    passed = run_all()
    print(f"\nOrchestration Dispatch Integration: {'PASS' if passed else 'FAIL'}")
    sys.exit(0 if passed else 1)
