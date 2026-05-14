"""
Integration: Memory + Database Persistence
Tests conversation memory round-trips and DB repository operations
using an in-memory SQLite database.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from qa.integration.helpers import assert_all, make_test_db, CONTACT_ID, SESSION_ID
from memory import MemoryManager, MemoryStore, AgentMemorySnapshot, ContactMemory, MemoryTurn


# ── Memory Manager ─────────────────────────────────────────────────────────────

def test_memory_record_and_retrieve():
    print("\n[INT] Memory: record turns + retrieve context")
    mgr = MemoryManager()

    mgr.record_turn(SESSION_ID, CONTACT_ID, "REC-001", role="user",    content="When will I be placed?")
    mgr.record_turn(SESSION_ID, CONTACT_ID, "REC-001", role="assistant", content="Typically 2-4 weeks after credentialing is complete.")
    mgr.record_turn(SESSION_ID, CONTACT_ID, "REC-001", role="user",    content="What documents do I still need?")

    snap    = mgr.get_snapshot(SESSION_ID)
    context = mgr.get_context(SESSION_ID, CONTACT_ID, "REC-001")

    return assert_all([
        ("Snapshot has 3 turns",        snap is not None and len(snap.turns) == 3),
        ("Token estimate > 0",          snap.total_tokens > 0),
        ("Context string non-empty",    len(context) > 10),
        ("Conversation block present",  "[Conversation]" in context),
    ])


def test_memory_contact_update():
    print("\n[INT] Memory: contact memory update + summary")
    mgr = MemoryManager()

    mgr.update_contact_memory(
        CONTACT_ID, "CRED-001",
        pipeline_stage="credentialing",
        open_credentials=["licensure", "background_drug"],
        tags=["credentialing"],
        note="Documents requested via SMS",
    )
    mem = mgr.get_contact_memory(CONTACT_ID, "CRED-001")
    summary = mem.to_summary()

    return assert_all([
        ("Contact memory created",               mem is not None),
        ("Pipeline stage stored",                mem.pipeline_stage == "credentialing"),
        ("Open credentials stored",              "licensure" in mem.open_credential_categories),
        ("Note stored",                          len(mem.notes) == 1),
        ("Interaction count incremented",        mem.interaction_count >= 1),
        ("Summary contains stage",               "credentialing" in summary),
        ("Summary contains credentials",         "licensure" in summary),
    ])


def test_memory_rolling_summarization():
    print("\n[INT] Memory: rolling summarization trigger at 12 turns")
    from memory.manager import SUMMARIZE_THRESHOLD
    mgr = MemoryManager()  # no LLM client → extractive fallback

    for i in range(SUMMARIZE_THRESHOLD + 2):
        role = "user" if i % 2 == 0 else "assistant"
        mgr.record_turn(SESSION_ID + "-sum", CONTACT_ID, "REC-001",
                        role=role, content=f"Message {i}: testing summarization trigger.")

    snap = mgr.get_snapshot(SESSION_ID + "-sum")

    return assert_all([
        ("Summary generated",            bool(snap.summary)),
        ("summary_turn_index advanced",  snap.summary_turn_index > 0),
        ("Unsummarized turns < threshold", len(snap.unsummarized_turns) < SUMMARIZE_THRESHOLD),
    ])


def test_memory_session_clear():
    print("\n[INT] Memory: session clear")
    mgr = MemoryManager()
    sid = SESSION_ID + "-clear"

    mgr.record_turn(sid, CONTACT_ID, "REC-001", role="user", content="hello")
    assert mgr.get_snapshot(sid) is not None

    mgr.clear_session(sid)

    return assert_all([
        ("Snapshot removed after clear", mgr.get_snapshot(sid) is None),
    ])


# ── DB Repositories ─────────────────────────────────────────────────────────────

async def _test_db_repositories():
    engine, factory = await make_test_db()

    async with factory() as session:
        from db.repositories import (
            AuditRepository, ContactMemoryRepository,
            SessionRepository, EscalationRepository, CredentialRepository,
        )
        from db.models import ContactMemoryRecord, AgentSession, CredentialRecord, EscalationTicket

        # ── Audit ──────────────────────────────────────────────────────────────
        audit = AuditRepository(session)
        await audit.insert(event="agent_action", agent_id="REC-001",
                           contact_id=CONTACT_ID, action="send_message", detail="Test")
        await audit.insert(event="phi_detection", agent_id="COMP-001",
                           contact_id=CONTACT_ID, phi_pattern="ssn", action_taken="blocked")
        await audit.insert(event="escalation",   agent_id="COMP-001",
                           contact_id=CONTACT_ID, detail="phi_exposure", severity="critical")

        entries = await audit.query(contact_id=CONTACT_ID)
        phi_entries = await audit.query(event="phi_detection")
        counts = await audit.count_by_event(since=datetime.now(timezone.utc) - timedelta(hours=1))

        print("\n[INT] DB AuditRepository:")
        audit_ok = assert_all([
            ("3 entries inserted",          len(entries) == 3),
            ("PHI filter works",            len(phi_entries) == 1),
            ("count_by_event works",        "phi_detection" in counts),
        ])

        # ── ContactMemory ──────────────────────────────────────────────────────
        mem_repo = ContactMemoryRepository(session)
        rec = ContactMemoryRecord(
            contact_id=CONTACT_ID, agent_id="REC-001",
            pipeline_stage="intake_complete", interaction_count=3,
            tags=["intake_complete"], notes=["[ts] First note"],
        )
        session.add(rec)
        await session.flush()
        fetched = await mem_repo.get(CONTACT_ID, "REC-001")

        # increment_interaction uses UPDATE — works on SQLite
        await mem_repo.increment_interaction(CONTACT_ID, "REC-001")
        await session.flush()
        updated = await mem_repo.get(CONTACT_ID, "REC-001")

        print("\n[INT] DB ContactMemoryRepository:")
        mem_ok = assert_all([
            ("Record persisted",              fetched is not None),
            ("Pipeline stage correct",        fetched.pipeline_stage == "intake_complete"),
            ("Interaction count incremented", updated.interaction_count == 4),
        ])

        # ── Sessions ───────────────────────────────────────────────────────────
        s = AgentSession(
            session_id=SESSION_ID, contact_id=CONTACT_ID, agent_id="REC-001",
            turns_json=[{"role": "user", "content": "hello"}],
            summary="Prior summary", summary_turn_index=1,
        )
        session.add(s)
        await session.flush()

        sess_repo = SessionRepository(session)
        loaded = await sess_repo.get(SESSION_ID)
        expired_count = await sess_repo.purge_expired()

        print("\n[INT] DB SessionRepository:")
        sess_ok = assert_all([
            ("Session persisted",           loaded is not None),
            ("Turns stored as JSON",        len(loaded.turns_json) == 1),
            ("Summary stored",              loaded.summary == "Prior summary"),
            ("Purge expired returns int",   isinstance(expired_count, int)),
        ])

        # ── Credentials ────────────────────────────────────────────────────────
        past_expiry = datetime.now(timezone.utc) + timedelta(days=10)
        cr = CredentialRecord(
            contact_id=CONTACT_ID, category="licensure",
            status="verified", document_id="doc-001",
            expiry_date=past_expiry,
        )
        session.add(cr)
        await session.flush()

        cred_repo = CredentialRepository(session)
        creds = await cred_repo.get_by_contact(CONTACT_ID)
        expiring = await cred_repo.get_expiring(days_ahead=30)

        print("\n[INT] DB CredentialRepository:")
        cred_ok = assert_all([
            ("Credential persisted",        len(creds) == 1),
            ("Category correct",            creds[0].category == "licensure"),
            ("Expiring within 30 days",     len(expiring) >= 1),
        ])

    # ── Escalations (fresh session, avoids any pg_insert state from prior session) ──
    async with factory() as esc_session:
        esc_repo = EscalationRepository(esc_session)
        ticket = await esc_repo.create(
            contact_id=CONTACT_ID, agent_id="COMP-001",
            reason="phi_exposure", severity="critical",
            detail="SSN pattern in CRM note",
        )
        await esc_session.flush()
        ticket_status_on_create = ticket.status   # capture before resolve mutates same object
        open_list = await esc_repo.list_open(severity="critical")
        resolved  = await esc_repo.resolve(ticket.id, "PHI removed", "human-01")
        await esc_session.flush()
        after_resolve = await esc_repo.list_open(severity="critical")

        print("\n[INT] DB EscalationRepository:")
        esc_ok = assert_all([
            ("Ticket created open",          ticket_status_on_create == "open"),
            ("Listed as open/critical",      len(open_list) >= 1),
            ("Resolved correctly",           resolved.status == "resolved"),
            ("No longer in open list",       len(after_resolve) == 0),
        ])

    await engine.dispose()
    return all([audit_ok, mem_ok, sess_ok, cred_ok, esc_ok])


def test_db_repositories():
    # Run in a fresh isolated event loop to avoid state from prior async tests
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, _test_db_repositories())
        return future.result()


def run_all() -> bool:
    results = [
        test_memory_record_and_retrieve(),
        test_memory_contact_update(),
        test_memory_rolling_summarization(),
        test_memory_session_clear(),
        test_db_repositories(),
    ]
    return all(results)


if __name__ == "__main__":
    passed = run_all()
    print(f"\nMemory + DB Integration: {'PASS' if passed else 'FAIL'}")
    sys.exit(0 if passed else 1)
