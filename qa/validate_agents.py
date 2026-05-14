"""
Agent QA Validation Script
Source: healthcare_staffing_ai_agent_build_kit.xlsx — QA Scripts sheet
Validates all 6 agent definitions against required fields, guardrails, fusion weights, and prompt rules.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANIFESTS_DIR = ROOT / "manifests"
AGENTS_DIR = ROOT / "agents"
PROMPTS_DIR = ROOT / "prompts"
FUSION_DIR = ROOT / "fusion"

AGENT_IDS = ["ORCH-001", "REC-001", "CRED-001", "COMP-001", "SALES-001", "CRM-001"]

REQUIRED_FIELDS = [
    "id", "name", "industry", "status", "primary_role", "domain",
    "kb_scope", "tools", "human_review", "guardrails",
]


def load_agent(agent_id: str) -> dict:
    manifest = json.loads((MANIFESTS_DIR / f"{agent_id}.json").read_text())
    persona = json.loads((AGENTS_DIR / agent_id / "persona.json").read_text())
    prompt = (PROMPTS_DIR / f"{agent_id}.txt").read_text()
    fusion = json.loads((FUSION_DIR / f"{agent_id}.json").read_text())
    return {
        "agent_id": agent_id,
        "manifest": manifest,
        "persona": persona,
        "prompt": prompt,
        "fusion": fusion,
        "temperature": persona["model_settings"]["temperature"],
    }


def validate_agent(agent: dict) -> list[dict]:
    results = []
    manifest = agent["manifest"]
    persona = agent["persona"]
    prompt = agent["prompt"]
    fusion = agent["fusion"]

    # Required manifest fields
    for field in REQUIRED_FIELDS:
        results.append({
            "test": field,
            "passed": field in manifest and manifest[field] not in [None, "", []],
            "description": "Required manifest field present",
        })

    # Temperature: precision mode must be 0.00–0.10
    results.append({
        "test": "temperature_range",
        "passed": 0 <= agent["temperature"] <= 0.1,
        "description": "Precision mode temperature must be 0.00–0.10",
    })

    # Human escalation language in prompt
    prompt_lower = prompt.lower()
    results.append({
        "test": "human_escalation_in_prompt",
        "passed": any(x in prompt_lower for x in ["human", "escalate", "escalation", "approval"]),
        "description": "Prompt must contain escalation or human approval language",
    })

    # Regulated decision guardrails in manifest
    guardrails = manifest.get("guardrails", [])
    results.append({
        "test": "regulated_decision_guardrail",
        "passed": any(
            "No final credential approval" in g or "No legal/clinical advice" in g
            for g in guardrails
        ),
        "description": "Manifest must include regulated healthcare decision guardrails",
    })

    # HIPAA PHI guardrail
    results.append({
        "test": "hipaa_phi_guardrail",
        "passed": any("PHI" in g or "HIPAA" in g for g in guardrails),
        "description": "Manifest must include PHI/HIPAA guardrail",
    })

    # Fusion scoring weights sum to 1.0
    weights = fusion["scoring_bias"]
    weight_sum = sum(weights.values())
    results.append({
        "test": "fusion_weights_sum",
        "passed": abs(weight_sum - 1.0) < 1e-9,
        "description": f"Fusion scoring weights must sum to 1.0 (got {weight_sum})",
    })

    # Knowledge base scope explicitly defined (>= 20 chars)
    results.append({
        "test": "kb_scope_defined",
        "passed": len(manifest.get("kb_scope", "")) >= 20,
        "description": "Knowledge base scope must be explicitly defined",
    })

    # Persona fields present
    for pf in ["persona_name", "tone", "audience", "voice_signature", "reasoning_style"]:
        results.append({
            "test": f"persona_{pf}",
            "passed": pf in persona and bool(persona[pf]),
            "description": f"Persona field '{pf}' must be present",
        })

    return results


def run_qa() -> bool:
    all_passed = True
    print(f"\n{'='*60}")
    print("  Healthcare Staffing AI OS — Agent QA Validation")
    print(f"{'='*60}\n")

    for agent_id in AGENT_IDS:
        try:
            agent = load_agent(agent_id)
        except Exception as e:
            print(f"[FAIL] {agent_id}: Could not load agent — {e}")
            all_passed = False
            continue

        results = validate_agent(agent)
        failures = [r for r in results if not r["passed"]]

        status = "PASS" if not failures else "FAIL"
        symbol = "✓" if not failures else "✗"
        print(f"  {symbol} {agent_id} ({agent['manifest'].get('name', '')}) — {status}")

        for r in failures:
            print(f"      [FAIL] {r['test']}: {r['description']}")
            all_passed = False

    print(f"\n{'='*60}")
    print(f"  Result: {'ALL PASS' if all_passed else 'FAILURES DETECTED'}")
    print(f"{'='*60}\n")
    return all_passed


if __name__ == "__main__":
    passed = run_qa()
    sys.exit(0 if passed else 1)
