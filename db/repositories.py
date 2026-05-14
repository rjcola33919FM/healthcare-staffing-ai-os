"""
Repository layer — typed async CRUD operations for each DB model.
Agents and services import these; they never touch SQLAlchemy directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select, update, and_, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AuditEntry, ContactMemoryRecord, AgentSession,
    CredentialRecord, EscalationTicket,
)

logger = logging.getLogger(__name__)


# ── Audit Repository ───────────────────────────────────────────────────────────

class AuditRepository:
    """Append-only. insert() is the only write operation."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert(self, **kwargs) -> AuditEntry:
        entry = AuditEntry(**kwargs)
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def query(
        self,
        agent_id: str | None = None,
        contact_id: str | None = None,
        event: str | None = None,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[AuditEntry]:
        stmt = select(AuditEntry)
        if agent_id:
            stmt = stmt.where(AuditEntry.agent_id == agent_id)
        if contact_id:
            stmt = stmt.where(AuditEntry.contact_id == contact_id)
        if event:
            stmt = stmt.where(AuditEntry.event == event)
        if since:
            stmt = stmt.where(AuditEntry.timestamp >= since)
        stmt = stmt.order_by(AuditEntry.timestamp.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_event(
        self, since: datetime, agent_id: str | None = None
    ) -> dict[str, int]:
        stmt = (
            select(AuditEntry.event, func.count().label("n"))
            .where(AuditEntry.timestamp >= since)
            .group_by(AuditEntry.event)
        )
        if agent_id:
            stmt = stmt.where(AuditEntry.agent_id == agent_id)
        result = await self.session.execute(stmt)
        return {row.event: row.n for row in result}


# ── Contact Memory Repository ──────────────────────────────────────────────────

class ContactMemoryRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, contact_id: str, agent_id: str) -> ContactMemoryRecord | None:
        stmt = select(ContactMemoryRecord).where(
            ContactMemoryRecord.contact_id == contact_id,
            ContactMemoryRecord.agent_id  == agent_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        contact_id: str,
        agent_id: str,
        **fields,
    ) -> ContactMemoryRecord:
        """
        Insert or update contact memory.
        Uses PostgreSQL ON CONFLICT DO UPDATE for atomicity.
        """
        now = datetime.now(timezone.utc)
        fields["updated_at"] = now

        stmt = (
            pg_insert(ContactMemoryRecord)
            .values(contact_id=contact_id, agent_id=agent_id, created_at=now, **fields)
            .on_conflict_do_update(
                index_elements=["contact_id", "agent_id"],
                set_={k: v for k, v in fields.items()},
            )
            .returning(ContactMemoryRecord)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def increment_interaction(
        self, contact_id: str, agent_id: str
    ) -> None:
        stmt = (
            update(ContactMemoryRecord)
            .where(
                ContactMemoryRecord.contact_id == contact_id,
                ContactMemoryRecord.agent_id   == agent_id,
            )
            .values(
                interaction_count=ContactMemoryRecord.interaction_count + 1,
                last_interaction_ts=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)


# ── Session Repository ─────────────────────────────────────────────────────────

class SessionRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, session_id: str) -> AgentSession | None:
        result = await self.session.execute(
            select(AgentSession).where(AgentSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def save(
        self,
        session_id: str,
        contact_id: str,
        agent_id: str,
        turns_json: list,
        summary: str = "",
        summary_turn_index: int = 0,
        ttl_seconds: int = 3600,
    ) -> AgentSession:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        stmt = (
            pg_insert(AgentSession)
            .values(
                session_id=session_id,
                contact_id=contact_id,
                agent_id=agent_id,
                turns_json=turns_json,
                summary=summary,
                summary_turn_index=summary_turn_index,
                expires_at=expires_at,
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                index_elements=["session_id"],
                set_={
                    "turns_json": turns_json,
                    "summary": summary,
                    "summary_turn_index": summary_turn_index,
                    "expires_at": expires_at,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            .returning(AgentSession)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def delete(self, session_id: str) -> None:
        result = await self.session.execute(
            select(AgentSession).where(AgentSession.session_id == session_id)
        )
        row = result.scalar_one_or_none()
        if row:
            await self.session.delete(row)

    async def purge_expired(self) -> int:
        """Delete expired sessions. Call from a scheduled task."""
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(AgentSession).where(AgentSession.expires_at < now)
        )
        rows = result.scalars().all()
        for row in rows:
            await self.session.delete(row)
        return len(rows)


# ── Credential Repository ──────────────────────────────────────────────────────

class CredentialRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_contact(
        self, contact_id: str, category: str | None = None
    ) -> list[CredentialRecord]:
        stmt = select(CredentialRecord).where(CredentialRecord.contact_id == contact_id)
        if category:
            stmt = stmt.where(CredentialRecord.category == category)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(self, contact_id: str, category: str, **fields) -> CredentialRecord:
        now = datetime.now(timezone.utc)
        fields["updated_at"] = now
        stmt = (
            pg_insert(CredentialRecord)
            .values(contact_id=contact_id, category=category, created_at=now, **fields)
            .on_conflict_do_update(
                index_elements=["contact_id", "category"],
                set_={k: v for k, v in fields.items()},
            )
            .returning(CredentialRecord)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def get_expiring(
        self, days_ahead: int = 30, status: str = "verified"
    ) -> list[CredentialRecord]:
        """Return credentials expiring within the next N days."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days_ahead)
        stmt = (
            select(CredentialRecord)
            .where(
                CredentialRecord.expiry_date.between(now, cutoff),
                CredentialRecord.status == status,
            )
            .order_by(CredentialRecord.expiry_date)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ── Escalation Repository ──────────────────────────────────────────────────────

class EscalationRepository:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **kwargs) -> EscalationTicket:
        ticket = EscalationTicket(**kwargs)
        self.session.add(ticket)
        await self.session.flush()
        await self.session.refresh(ticket)
        logger.info(
            "[DB] Escalation ticket created id=%s contact=%s severity=%s",
            ticket.id, ticket.contact_id, ticket.severity,
        )
        return ticket

    async def get(self, ticket_id: str) -> EscalationTicket | None:
        result = await self.session.execute(
            select(EscalationTicket).where(EscalationTicket.id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def list_open(
        self, severity: str | None = None, limit: int = 100
    ) -> list[EscalationTicket]:
        stmt = (
            select(EscalationTicket)
            .where(EscalationTicket.status == "open")
            .order_by(EscalationTicket.created_at.desc())
            .limit(limit)
        )
        if severity:
            stmt = stmt.where(EscalationTicket.severity == severity)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def resolve(
        self, ticket_id: str, resolution: str, resolved_by: str = ""
    ) -> EscalationTicket | None:
        ticket = await self.get(ticket_id)
        if not ticket:
            return None
        ticket.status = "resolved"
        ticket.resolution = resolution
        ticket.resolved_at = datetime.now(timezone.utc)
        ticket.assigned_to = resolved_by
        await self.session.flush()
        return ticket
