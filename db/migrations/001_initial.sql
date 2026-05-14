-- Healthcare Staffing AI OS — Initial Schema Migration
-- Run once against a fresh PostgreSQL database.
-- SQLAlchemy create_all() handles this automatically in development.
-- Use this file for production deployments via Alembic or manual apply.

-- ── Extensions ────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";   -- for future full-text search on audit

-- ── Audit Entries (append-only) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_entries (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event           VARCHAR(64)  NOT NULL,
    agent_id        VARCHAR(32)  NOT NULL,
    contact_id      VARCHAR(128) NOT NULL,
    session_id      VARCHAR(128),
    action          VARCHAR(128),
    detail          TEXT,
    severity        VARCHAR(32),
    phi_pattern     VARCHAR(128),
    action_taken    VARCHAR(64),
    metadata_json   JSONB,
    log_version     VARCHAR(8)   NOT NULL DEFAULT '1.0'
);

CREATE INDEX IF NOT EXISTS ix_audit_ts_agent       ON audit_entries (timestamp DESC, agent_id);
CREATE INDEX IF NOT EXISTS ix_audit_contact_event  ON audit_entries (contact_id, event);

-- Row-level security: append-only enforced at DB level
-- No UPDATE or DELETE grants should be issued to the application role.

-- ── Contact Memory ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS contact_memory (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    contact_id                  VARCHAR(128) NOT NULL,
    agent_id                    VARCHAR(32)  NOT NULL,
    pipeline_stage              VARCHAR(64),
    open_credential_categories  JSONB,
    tags                        JSONB,
    notes                       JSONB,
    interaction_count           INTEGER DEFAULT 0,
    last_interaction_ts         TIMESTAMPTZ,
    metadata_json               JSONB,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_contact_memory UNIQUE (contact_id, agent_id)
);

CREATE INDEX IF NOT EXISTS ix_contact_memory_contact ON contact_memory (contact_id);

-- ── Agent Sessions ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_sessions (
    session_id          VARCHAR(128) PRIMARY KEY,
    contact_id          VARCHAR(128) NOT NULL,
    agent_id            VARCHAR(32)  NOT NULL,
    turns_json          JSONB,
    summary             TEXT,
    summary_turn_index  INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_sessions_contact ON agent_sessions (contact_id);
CREATE INDEX IF NOT EXISTS ix_sessions_expires ON agent_sessions (expires_at)
    WHERE expires_at IS NOT NULL;

-- ── Credential Records ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS credential_records (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    contact_id    VARCHAR(128) NOT NULL,
    category      VARCHAR(64)  NOT NULL,
    document_id   VARCHAR(128),
    filename      VARCHAR(256),
    status        VARCHAR(32)  NOT NULL DEFAULT 'pending',
    expiry_date   TIMESTAMPTZ,
    verified_by   VARCHAR(128),
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_cred_contact_category ON credential_records (contact_id, category);
CREATE INDEX IF NOT EXISTS ix_cred_expiry           ON credential_records (expiry_date, status)
    WHERE expiry_date IS NOT NULL;

-- ── Escalation Tickets ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS escalation_tickets (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    contact_id    VARCHAR(128) NOT NULL,
    agent_id      VARCHAR(32)  NOT NULL,
    session_id    VARCHAR(128),
    reason        VARCHAR(128) NOT NULL,
    severity      VARCHAR(32)  NOT NULL DEFAULT 'normal',
    detail        TEXT,
    status        VARCHAR(32)  NOT NULL DEFAULT 'open',
    assigned_to   VARCHAR(128),
    resolved_at   TIMESTAMPTZ,
    resolution    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_escalation_status   ON escalation_tickets (status, severity);
CREATE INDEX IF NOT EXISTS ix_escalation_contact  ON escalation_tickets (contact_id);
CREATE INDEX IF NOT EXISTS ix_escalation_created  ON escalation_tickets (created_at DESC);
