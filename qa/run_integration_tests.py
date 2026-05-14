"""
Healthcare Staffing AI OS — Integration Test Runner

Runs all four integration suites in sequence.
No live external services required:
  - Anthropic API   → stubbed (MagicMock)
  - GHL / Twilio    → FakeCRMTools / in-memory
  - PostgreSQL      → SQLite in-memory (aiosqlite)
  - Redis           → in-memory MemoryStore fallback
  - Pinecone        → in-memory KB indexer

Usage:
    python qa/run_integration_tests.py
    python qa/run_integration_tests.py --suite rag
    python qa/run_integration_tests.py --suite workflow
    python qa/run_integration_tests.py --suite memory
    python qa/run_integration_tests.py --suite compliance
    python qa/run_integration_tests.py --suite orchestration
"""

from __future__ import annotations

import sys
import importlib
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

SUITES = [
    ("RAG Pipeline",                 "qa.integration.test_rag_pipeline",           "run_all"),
    ("Workflow E2E",                 "qa.integration.test_workflow_e2e",            "run_all"),
    ("Memory + DB Persistence",      "qa.integration.test_memory_db",               "run_all"),
    ("Compliance + Security",        "qa.integration.test_compliance_security",     "run_all"),
    ("Orchestration Dispatch",       "qa.integration.test_orchestration_dispatch",  "run_all"),
]

SUITE_ALIASES = {
    "rag":           "qa.integration.test_rag_pipeline",
    "workflow":      "qa.integration.test_workflow_e2e",
    "memory":        "qa.integration.test_memory_db",
    "compliance":    "qa.integration.test_compliance_security",
    "orchestration": "qa.integration.test_orchestration_dispatch",
}


def run(suites_to_run=None):
    target = suites_to_run or SUITES

    print("\n" + "=" * 65)
    print("  Healthcare Staffing AI OS — Integration Test Suite")
    print("=" * 65)

    results: dict[str, bool] = {}

    for label, module_path, fn_name in target:
        print(f"\n{'─'*65}")
        print(f"  SUITE: {label}")
        print(f"{'─'*65}")
        try:
            mod = importlib.import_module(module_path)
            fn  = getattr(mod, fn_name)
            ok  = fn()
            results[label] = ok
        except Exception as exc:
            import traceback
            print(f"\n  [ERROR] {label} raised an exception:")
            traceback.print_exc()
            results[label] = False

    # Summary
    print(f"\n{'='*65}")
    print("  INTEGRATION TEST RESULTS")
    print(f"{'='*65}")
    all_pass = True
    for label, ok in results.items():
        symbol = "✓" if ok else "✗"
        status = "PASS" if ok else "FAIL"
        print(f"  {symbol} {label}: {status}")
        if not ok:
            all_pass = False

    total  = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n  {passed}/{total} suites passed")
    print(f"{'='*65}")
    print(f"  OVERALL: {'ALL PASS' if all_pass else 'FAILURES DETECTED — see above'}")
    print(f"{'='*65}\n")

    return all_pass


def main():
    parser = argparse.ArgumentParser(description="Run Healthcare Staffing integration tests.")
    parser.add_argument("--suite", choices=list(SUITE_ALIASES.keys()),
                        help="Run a single suite by name.")
    args = parser.parse_args()

    if args.suite:
        module_path = SUITE_ALIASES[args.suite]
        label = next(l for l, m, _ in SUITES if m == module_path)
        ok = run([(label, module_path, "run_all")])
    else:
        ok = run()

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
