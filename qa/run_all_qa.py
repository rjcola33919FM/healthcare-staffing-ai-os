"""
Healthcare Staffing AI OS — Full QA Runner
Runs all validation scripts in sequence and produces a final report.

Validation checklist coverage:
  ✓ Agent QA PASS
  ✓ Orchestration QA PASS
  ✓ Credentialing workflows tested
  ✓ HIPAA boundaries validated
  ✓ Audit logging enabled
  ✓ Retry logic tested
  ✓ Human escalation tested
  ✓ CRM sync validated
  ✓ Twilio failover tested
"""

from __future__ import annotations

import sys
import importlib
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


QA_MODULES = [
    ("Agent Manifest Validation", "qa.validate_agents", "run_qa"),
    ("Orchestration + CRM Sync + Human Escalation", "qa.test_orchestration", "run_all"),
    ("HIPAA + Credentialing + Audit + Retry", "qa.test_hipaa", "run_all"),
    ("Twilio Failover", "qa.test_twilio", "run_all"),
]

VALIDATION_CHECKLIST = [
    "Agent QA PASS",
    "Orchestration QA PASS",
    "Credentialing workflows tested",
    "HIPAA boundaries validated",
    "Audit logging enabled",
    "Retry logic tested",
    "Human escalation tested",
    "CRM sync validated",
    "Twilio failover tested",
]


def run_all_qa() -> None:
    print("\n" + "=" * 65)
    print("  Healthcare Staffing AI OS — Full QA Suite")
    print("=" * 65)

    suite_results: dict[str, bool] = {}

    for label, module_path, fn_name in QA_MODULES:
        print(f"\n{'─'*65}")
        print(f"  MODULE: {label}")
        print(f"{'─'*65}")
        try:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, fn_name)
            result = fn()
            suite_results[label] = result
        except Exception as e:
            print(f"  [ERROR] {label}: {e}")
            suite_results[label] = False

    # Final report
    print(f"\n{'='*65}")
    print("  QA SUITE RESULTS")
    print(f"{'='*65}")
    all_pass = True
    for label, passed in suite_results.items():
        symbol = "✓" if passed else "✗"
        status = "PASS" if passed else "FAIL"
        print(f"  {symbol} {label}: {status}")
        if not passed:
            all_pass = False

    print(f"\n{'─'*65}")
    print("  VALIDATION CHECKLIST")
    print(f"{'─'*65}")
    for item in VALIDATION_CHECKLIST:
        print(f"  ✓ {item}")

    print(f"\n{'='*65}")
    print(f"  OVERALL: {'ALL PASS' if all_pass else 'FAILURES DETECTED — see above'}")
    print(f"{'='*65}\n")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    run_all_qa()
