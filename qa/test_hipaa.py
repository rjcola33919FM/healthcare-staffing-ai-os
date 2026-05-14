"""
HIPAA Boundaries & Compliance QA
Validation checklist: HIPAA boundaries validated, Credentialing workflows tested,
Audit logging enabled, Retry logic tested.
"""

from __future__ import annotations

import sys
import time
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch, call

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.base import BaseAgent, AgentContext, AgentResponse


# ── HIPAA Guardrail Tests ──────────────────────────────────────────────────────

PHI_TRIGGER_PHRASES = [
    "legal advice",
    "clinical judgment",
    "diagnosis of the patient",
    "final approval for credentialing",
    "malpractice history",
    "contract amendment terms",
    "litigation strategy",
]

SAFE_PHRASES = [
    "Your recruiter will follow up shortly.",
    "Please upload your license document.",
    "Your appointment is confirmed for Friday.",
    "I've updated your pipeline stage.",
]


class MockBaseAgent(BaseAgent):
    """Minimal subclass to test guardrail logic without loading files."""
    def __init__(self):
        # Bypass file loading
        self.agent_id = "TEST-001"
        self.model_settings = {"temperature": 0.05}
        self.system_prompt = ""
        self.manifest = {"guardrails": ["No legal/clinical advice", "No PHI unless HIPAA-compliant"]}
        self.fusion = {}
        self.persona = {}


def test_hipaa_guardrails():
    print("\n[TEST] HIPAA Guardrail Triggers")
    agent = MockBaseAgent()
    all_ok = True

    for phrase in PHI_TRIGGER_PHRASES:
        triggered = agent._check_hipaa_guardrails(phrase)
        symbol = "✓" if triggered else "✗"
        print(f"  {symbol} Triggers on: \"{phrase[:60]}\"")
        if not triggered:
            all_ok = False

    for phrase in SAFE_PHRASES:
        triggered = agent._check_hipaa_guardrails(phrase)
        symbol = "✓" if not triggered else "✗"
        print(f"  {symbol} Safe phrase passes: \"{phrase[:60]}\"")
        if triggered:
            all_ok = False

    return all_ok


# ── Audit Logging Tests ────────────────────────────────────────────────────────

def test_audit_logging():
    print("\n[TEST] Audit Logging")
    agent = MockBaseAgent()

    ctx = AgentContext(
        contact_id="contact-audit-001",
        conversation_id="conv-audit-001",
        channel="sms",
        payload={"message": "test"},
    )
    response = AgentResponse(
        agent_id="TEST-001",
        action="escalate",
        content="Escalated.",
        escalation_reason="PHI guardrail",
    )

    with patch.object(logging.getLogger("src.agents.base"), "info") as mock_log:
        agent._audit_log(ctx, response)
        log_called = mock_log.called

    checks = [
        ("audit log called", log_called),
    ]
    all_ok = True
    for label, ok in checks:
        symbol = "✓" if ok else "✗"
        print(f"  {symbol} {label}")
        if not ok:
            all_ok = False
    return all_ok


# ── Credentialing Workflow Tests ───────────────────────────────────────────────

def test_credentialing_workflows():
    print("\n[TEST] Credentialing Workflow Boundaries")
    import json

    manifest_path = ROOT / "manifests" / "CRED-001.json"
    manifest = json.loads(manifest_path.read_text())
    prompt = (ROOT / "prompts" / "CRED-001.txt").read_text()

    checks = [
        ("final approval escalation in human_review", "final file approval" in manifest["human_review"].lower()),
        ("authenticity concern escalation", "authenticity" in manifest["human_review"].lower()),
        ("privileging escalation", "privileging" in manifest["human_review"].lower()),
        ("Never approve in prompt", "never approve" in prompt.lower()),
        ("PHI boundary in prompt", "phi" in prompt.lower()),
        ("Reminders schedule in prompt", "30" in prompt and "14" in prompt and "7" in prompt),
        ("Document categories defined in prompt", "licensure" in prompt.lower()),
    ]

    all_ok = True
    for label, ok in checks:
        symbol = "✓" if ok else "✗"
        print(f"  {symbol} {label}")
        if not ok:
            all_ok = False
    return all_ok


# ── Retry Logic Tests ──────────────────────────────────────────────────────────

def test_retry_logic():
    print("\n[TEST] Retry Logic")
    import anthropic

    agent = MockBaseAgent()
    ctx = AgentContext(
        contact_id="contact-retry-001",
        conversation_id="conv-retry-001",
        channel="webhook",
        payload={"message": "test"},
    )

    call_count = 0

    def mock_call(context):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise anthropic.RateLimitError(
                message="rate limit",
                response=MagicMock(status_code=429, headers={}),
                body={},
            )
        return AgentResponse(agent_id="TEST-001", action="reply", content="ok")

    agent._call_model = mock_call

    with patch("time.sleep"):  # Don't actually sleep in tests
        try:
            response = agent.run(ctx, max_retries=3)
            retried = call_count == 3 and response.action == "reply"
        except Exception:
            retried = False

    checks = [
        ("retried on rate limit", retried),
        ("succeeded after retries", call_count == 3),
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
        test_hipaa_guardrails(),
        test_audit_logging(),
        test_credentialing_workflows(),
        test_retry_logic(),
    ]
    return all(results)


if __name__ == "__main__":
    passed = run_all()
    print(f"\nHIPAA & Compliance QA: {'PASS' if passed else 'FAIL'}")
    sys.exit(0 if passed else 1)
