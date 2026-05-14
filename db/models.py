"""
SQLAlchemy ORM models — PostgreSQL-backed persistence for:
  - Audit log entries (append-only, 7-year retention)
  - Contact memory (cross-session, agent-scoped)
  - Agent sessions (TTL-managed)
  - Credential records (per candidate, per category)
  - Escalation tickets

All tables use UUIDs as primary keys.
Soft deletes are NOT used — records are immutable (HIPAA requirement).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index, Integer,
    String, Text, JSON, ForeignKey, Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ── Audit Log ──────────────────────────────────────────────────────────────────

class AuditEntry(Base):
    """
    Append-only audit log. Never updated or deleted.
    Maps to the same events written by audit_log/audit.py (dual-write: disk + DB).
    """
    __tablename__ = "audit_entries"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    timestamp     = Column(DateTime(timezone=True), default=_now, nullable=False, index=True)
    event         = Column(String(64), nullable=False, index=True)
    agent_id      = Column(String(32), nullable=False, index=True)
    contact_id    = Column(String(128), nullable=False, index=True)
    session_id    = Column(String(128), nullable=True)
    action        = Column(String(128), nullable=True)
    detail        = Column(Text, nullable=True)
    severity      = Column(String(32), nullable=True)          # escalation severity
    phi_pattern   = Column(String(128), nullable=True)         # PHI event only
    action_taken  = Column(String(64), nullable=True)          # PHI event only
    metadata_json = Column(JSON, nullable=True)
    log_version   = Column(String(8), nullable=False, default="1.0")

    __table_args__ = (
        Index("ix_audit_ts_agent", "timestamp", "agent_id"),
        Index("ix_audit_contact_event", "contact_id", "event"),
    )


# ── Contact Memory ─────────────────────────────────────────────────────────────

class ContactMemoryRecord(Base):
    """
    Durable contact-level memory (cross-session).
    One row per (contact_id, agent_id). Upserted on every interaction.
    """
    __tablename__ = "contact_memory"

    id                          = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    contact_id                  = Column(String(128), nullable=False, index=True)
    agent_id                    = Column(String(32),  nullable=False, index=True)
    pipeline_stage              = Column(String(64),  nullable=True)
    open_credential_categories  = Column(JSON, nullable=True)   # list[str]
    tags                        = Column(JSON, nullable=True)    # list[str]
    notes                       = Column(JSON, nullable=True)    # list[str]
    interaction_count           = Column(Integer, default=0)
    last_interaction_ts         = Column(DateTime(timezone=True), nullable=True)
    metadata_json               = Column(JSON, nullable=True)
    created_at                  = Column(DateTime(timezone=True), default=_now)
    updated_at                  = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_contact_memory_uq", "contact_id", "agent_id", unique=True),
    )


# ── Agent Sessions ─────────────────────────────────────────────────────────────

class AgentSession(Base):
    """
    Short-term session store (TTL 1 hour).
    Conversation turns stored as JSON array.
    Redis is primary; this is the durable fallback.
    """
    __tablename__ = "agent_sessions"

    session_id    = Column(String(128), primary_key=True)
    contact_id    = Column(String(128), nullable=False, index=True)
    agent_id      = Column(String(32),  nullable=False, index=True)
    turns_json    = Column(JSON, nullable=True)       # list of MemoryTurn dicts
    summary       = Column(Text, nullable=True)
    summary_turn_index = Column(Integer, default=0)
    created_at    = Column(DateTime(timezone=True), default=_now)
    updated_at    = Column(DateTime(timezone=True), default=_now, onupdate=_now)
    expires_at    = Column(DateTime(timezone=True), nullable=True, index=True)


# ── Credential Records ─────────────────────────────────────────────────────────

class CredentialRecord(Base):
    """
    One row per document submitted by a candidate.
    Status: pending → received → verified | rejected | expired
    """
    __tablename__ = "credential_records"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    contact_id    = Column(String(128), nullable=False, index=True)
    category      = Column(String(64),  nullable=False, index=True)
    document_id   = Column(String(128), nullable=True)
    filename      = Column(String(256), nullable=True)
    status        = Column(String(32),  nullable=False, default="pending", index=True)
    expiry_date   = Column(DateTime(timezone=True), nullable=True, index=True)
    verified_by   = Column(String(128), nullable=True)   # human reviewer ID
    notes         = Column(Text, nullable=True)
    created_at    = Column(DateTime(timezone=True), default=_now)
    updated_at    = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_cred_contact_category", "contact_id", "category"),
        Index("ix_cred_expiry", "expiry_date", "status"),
    )


# ── Escalation Tickets ─────────────────────────────────────────────────────────

class EscalationTicket(Base):
    """
    Human escalation queue. Created by agents; resolved by humans.
    Status: open → assigned → resolved | closed
    """
    __tablename__ = "escalation_tickets"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    contact_id    = Column(String(128), nullable=False, index=True)
    agent_id      = Column(String(32),  nullable=False)
    session_id    = Column(String(128), nullable=True)
    reason        = Column(String(128), nullable=False)
    severity      = Column(String(32),  nullable=False, default="normal", index=True)
    detail        = Column(Text, nullable=True)
    status        = Column(String(32),  nullable=False, default="open", index=True)
    assigned_to   = Column(String(128), nullable=True)
    resolved_at   = Column(DateTime(timezone=True), nullable=True)
    resolution    = Column(Text, nullable=True)
    created_at    = Column(DateTime(timezone=True), default=_now, index=True)
    updated_at    = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_escalation_status_severity", "status", "severity"),
    )
