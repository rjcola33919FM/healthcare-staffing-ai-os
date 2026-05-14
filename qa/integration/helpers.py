"""
Integration test helpers — shared fixtures, fake data, and assertion utilities.
No live external services: Anthropic, GHL, Twilio, Pinecone are all stubbed.
PostgreSQL uses SQLite in-memory. Redis uses the in-memory fallback.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


# ── Fake Anthropic client ──────────────────────────────────────────────────────

def make_fake_anthropic(response_text: str = "Test response from agent."):
    """Returns a mock Anthropic client whose messages.create() returns a fixed response."""
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=response_text)]
    msg.usage = MagicMock(input_tokens=100, output_tokens=50)
    client.messages.create.return_value = msg
    return client


# ── Fake CRM tools ─────────────────────────────────────────────────────────────

class FakeCRMTools:
    """In-memory CRM store for integration tests."""

    def __init__(self):
        self.contacts: dict[str, dict] = {}
        self.notes: dict[str, list] = {}
        self.tags: dict[str, set] = {}
        self.tasks: dict[str, list] = {}

    def get_contact(self, contact_id: str) -> dict | None:
        return self.contacts.get(contact_id)

    def update_pipeline_stage(self, contact_id: str, stage: str) -> None:
        self.contacts.setdefault(contact_id, {})["pipeline_stage"] = stage

    def add_tags(self, contact_id: str, tags: list[str]) -> None:
        self.tags.setdefault(contact_id, set()).update(tags)

    def remove_tags(self, contact_id: str, tags: list[str]) -> None:
        self.tags.setdefault(contact_id, set()).difference_update(tags)

    def add_note(self, contact_id: str, note: str) -> None:
        self.notes.setdefault(contact_id, []).append(note)

    def create_task(self, contact_id: str, title: str, due_date: str = "") -> None:
        self.tasks.setdefault(contact_id, []).append({"title": title, "due_date": due_date})

    def get_tags(self, contact_id: str) -> set:
        return self.tags.get(contact_id, set())

    def get_notes(self, contact_id: str) -> list:
        return self.notes.get(contact_id, [])

    def get_tasks(self, contact_id: str) -> list:
        return self.tasks.get(contact_id, [])


# ── SQLite async session factory ───────────────────────────────────────────────

async def make_test_db():
    """Create an in-memory SQLite DB with the full schema. Returns (engine, session_factory)."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, factory


# ── Assertion helpers ──────────────────────────────────────────────────────────

def assert_all(checks: list[tuple[str, bool]]) -> bool:
    all_ok = True
    for label, ok in checks:
        print(f"    {'✓' if ok else '✗'} {label}")
        if not ok:
            all_ok = False
    return all_ok


# ── Contact fixture ────────────────────────────────────────────────────────────

CANDIDATE_DATA = {
    "first_name": "Jane",
    "last_name":  "Smith",
    "specialty":  "RN",
    "license_state": "TX",
    "phone":      "+15551234567",
    "email":      "jane.smith@example.com",
}

CONTACT_ID   = "int-test-c-001"
SESSION_ID   = "int-test-sess-001"
