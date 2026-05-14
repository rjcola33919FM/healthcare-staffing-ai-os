"""
Integration: Workflow End-to-End
Tests complete candidate lifecycle: new_lead → intake → credentialing → specialist routing.
Uses FakeCRMTools — no live GHL calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from qa.integration.helpers import (
    assert_all, FakeCRMTools, CANDIDATE_DATA, CONTACT_ID,
)
from workflows import WorkflowExecutor, WorkflowEvent
from core.constants import PipelineStage, ComplianceTag


def _executor(crm: FakeCRMTools) -> WorkflowExecutor:
    return WorkflowExecutor(crm_tools=crm)


def test_new_lead_to_intake():
    print("\n[INT] Workflow: new_lead → intake_in_progress")
    crm = FakeCRMTools()
    crm.contacts[CONTACT_ID] = {"pipeline_stage": PipelineStage.NEW_LEAD}
    executor = _executor(crm)

    result = executor.run(WorkflowEvent(
        event_type="contact.stage_changed",
        contact_id=CONTACT_ID,
        data={"from_stage": PipelineStage.NEW_LEAD, "candidate_data": {}},
    ))

    return assert_all([
        ("Workflow succeeded",             result.success),
        ("Stage advanced action fired",    any("stage_advanced" in a for a in result.actions_taken)),
        ("CRM stage updated",              crm.contacts.get(CONTACT_ID, {}).get("pipeline_stage") == PipelineStage.INTAKE_IN_PROGRESS),
        ("CRM tag added",                  PipelineStage.INTAKE_IN_PROGRESS in crm.get_tags(CONTACT_ID)),
        ("CRM note written",               len(crm.get_notes(CONTACT_ID)) > 0),
    ])


def test_intake_complete_to_credentialing():
    print("\n[INT] Workflow: intake_complete → credentialing handoff")
    crm = FakeCRMTools()
    crm.contacts[CONTACT_ID] = {"pipeline_stage": PipelineStage.INTAKE_COMPLETE}
    executor = _executor(crm)

    result = executor.run(WorkflowEvent(
        event_type="contact.stage_changed",
        contact_id=CONTACT_ID,
        data={
            "from_stage": PipelineStage.INTAKE_COMPLETE,
            "candidate_data": CANDIDATE_DATA,
        },
    ))

    return assert_all([
        ("Workflow succeeded",                   result.success),
        ("Handoff action fired",                 "credentialing_handoff_triggered" in result.actions_taken),
        ("Identity doc request queued",          "doc_request:identity" in result.actions_taken),
        ("Licensure doc request queued",         "doc_request:licensure" in result.actions_taken),
        ("Background/drug doc request queued",   "doc_request:background_drug" in result.actions_taken),
        ("CRM stage updated to credentialing",   crm.contacts.get(CONTACT_ID, {}).get("pipeline_stage") == PipelineStage.CREDENTIALING),
        ("Note written for credentialing",       len(crm.get_notes(CONTACT_ID)) > 0),
    ])


def test_tag_added_compliance_alert():
    print("\n[INT] Workflow: tag_added → compliance alert (non_compliant)")
    crm = FakeCRMTools()
    crm.contacts[CONTACT_ID] = {"pipeline_stage": PipelineStage.CREDENTIALING}
    executor = _executor(crm)

    result = executor.run(WorkflowEvent(
        event_type="contact.tag_added",
        contact_id=CONTACT_ID,
        data={"tag": ComplianceTag.NON_COMPLIANT, "detail": "License expired 3 days ago"},
    ))

    return assert_all([
        ("Workflow succeeded",       result.success),
        ("Alert action fired",       any("compliance_alert" in a for a in result.actions_taken)),
        ("CRM note written",         len(crm.get_notes(CONTACT_ID)) > 0),
    ])


def test_document_uploaded_incomplete():
    print("\n[INT] Workflow: document.uploaded → credentialing incomplete (no cred tools)")
    crm = FakeCRMTools()
    executor = _executor(crm)   # no cred_tools → status.ready_for_review = False

    result = executor.run(WorkflowEvent(
        event_type="document.uploaded",
        contact_id=CONTACT_ID,
        data={"filename": "rn_license_tx.pdf", "document_id": "doc-001"},
    ))

    return assert_all([
        ("Workflow succeeded",       result.success),
        ("Document received action", any("document_received" in a for a in result.actions_taken)),
        ("No escalation yet",        result.escalation is None),
    ])


def test_lead_qualified_discovery_call():
    print("\n[INT] Workflow: lead.qualified → discovery call scheduled")
    crm = FakeCRMTools()
    crm.contacts[CONTACT_ID] = {"pipeline_stage": "proposal"}
    executor = _executor(crm)

    result = executor.run(WorkflowEvent(
        event_type="lead.qualified",
        contact_id=CONTACT_ID,
        data={"lead_data": {"company": "HCA Healthcare", "specialty": "ICU RN", "volume": 10}},
    ))

    return assert_all([
        ("Workflow succeeded",                result.success),
        ("Discovery call action fired",       "sales_discovery_call_scheduled" in result.actions_taken),
        ("CRM tag added",                     "discovery_call_scheduled" in crm.get_tags(CONTACT_ID)),
        ("Task created",                      len(crm.get_tasks(CONTACT_ID)) > 0),
    ])


def test_full_candidate_lifecycle():
    print("\n[INT] Workflow: FULL LIFECYCLE new_lead → intake → credentialing → specialist")
    crm = FakeCRMTools()
    crm.contacts[CONTACT_ID] = {"pipeline_stage": PipelineStage.NEW_LEAD}
    executor = _executor(crm)

    # Step 1: new_lead → intake_in_progress
    r1 = executor.run(WorkflowEvent(
        event_type="contact.stage_changed", contact_id=CONTACT_ID,
        data={"from_stage": PipelineStage.NEW_LEAD, "candidate_data": {}},
    ))

    # Step 2: intake_complete → credentialing
    r2 = executor.run(WorkflowEvent(
        event_type="contact.stage_changed", contact_id=CONTACT_ID,
        data={"from_stage": PipelineStage.INTAKE_COMPLETE, "candidate_data": CANDIDATE_DATA},
    ))

    # Step 3: compliance tag added
    r3 = executor.run(WorkflowEvent(
        event_type="contact.tag_added", contact_id=CONTACT_ID,
        data={"tag": ComplianceTag.AT_RISK, "detail": "Expiring in 14 days"},
    ))

    notes = crm.get_notes(CONTACT_ID)
    tasks = crm.get_tasks(CONTACT_ID)

    return assert_all([
        ("Step 1 succeeded",             r1.success),
        ("Step 2 succeeded",             r2.success),
        ("Step 3 succeeded",             r3.success),
        ("Multiple CRM notes written",   len(notes) >= 2),
        ("No crashes in full lifecycle", True),
        ("Credentialing tag present",    PipelineStage.CREDENTIALING in crm.get_tags(CONTACT_ID)),
    ])


def run_all() -> bool:
    results = [
        test_new_lead_to_intake(),
        test_intake_complete_to_credentialing(),
        test_tag_added_compliance_alert(),
        test_document_uploaded_incomplete(),
        test_lead_qualified_discovery_call(),
        test_full_candidate_lifecycle(),
    ]
    return all(results)


if __name__ == "__main__":
    passed = run_all()
    print(f"\nWorkflow E2E Integration: {'PASS' if passed else 'FAIL'}")
    sys.exit(0 if passed else 1)
