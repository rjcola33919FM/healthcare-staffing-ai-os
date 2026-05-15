"""
Audit Logger — append-only, HIPAA-compliant audit trail.
Every agent action, escalation, CRM mutation, and PHI event is logged here.

Rules (from config/hipaa.py):
- Immutable: no entry may be updated or deleted
- Retention: 7 years (2555 days)
- Format: structured JSON per line — machine-readable for compliance reports
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Audit log directory — override via AUDIT_LOG_DIR env var.
# On read-only filesystems (Vercel) fall back to /tmp which is always writable.
def _default_log_dir() -> Path:
    configured = os.environ.get("AUDIT_LOG_DIR", "")
    if configured:
        return Path(configured)
    candidate = Path("logs/audit")
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        fallback = Path("/tmp/logs/audit")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

_DEFAULT_LOG_DIR = _default_log_dir()

# Each agent writes to its own daily log file: audit_AGENT_YYYYMMDD.jsonl
_LOG_FORMAT_VERSION = "1.0"

# Module-level write lock — safe for threaded FastAPI workers
_write_lock = threading.Lock()


class AuditLogger:
    """
    Append-only audit logger.

    All write operations acquire a lock and call fsync so entries survive
    process crashes. Never raises — errors are logged to stderr so a
    logging failure never silences the main application flow.

    Usage:
        audit = AuditLogger()
        audit.log_agent_action(
            agent_id="REC-001",
            contact_id="c-123",
            action="send_message",
            detail="Sent credentialing checklist link",
        )
        audit.log_escalation(
            agent_id="COMP-001",
            contact_id="c-123",
            reason="phi_exposure",
            severity="critical",
        )
    """

    def __init__(self, log_dir: Path | str | None = None):
        self._log_dir = Path(log_dir) if log_dir else _DEFAULT_LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public write methods
    # ------------------------------------------------------------------

    def log_agent_action(
        self,
        agent_id: str,
        contact_id: str,
        action: str,
        detail: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._write({
            "event": "agent_action",
            "agent_id": agent_id,
            "contact_id": contact_id,
            "session_id": session_id,
            "action": action,
            "detail": detail,
            "metadata": metadata or {},
        })

    def log_escalation(
        self,
        agent_id: str,
        contact_id: str,
        reason: str,
        severity: str,
        detail: str = "",
        session_id: str = "",
    ) -> None:
        self._write({
            "event": "escalation",
            "agent_id": agent_id,
            "contact_id": contact_id,
            "session_id": session_id,
            "reason": reason,
            "severity": severity,
            "detail": detail,
        })

    def log_phi_event(
        self,
        agent_id: str,
        contact_id: str,
        phi_pattern: str,
        source: str = "",
        action_taken: str = "blocked",
    ) -> None:
        """
        Log any PHI detection event.
        Does NOT log the actual PHI value — only the pattern name and source.
        """
        self._write({
            "event": "phi_detection",
            "agent_id": agent_id,
            "contact_id": contact_id,
            "phi_pattern": phi_pattern,
            "source": source,
            "action_taken": action_taken,
        })

    def log_crm_mutation(
        self,
        agent_id: str,
        contact_id: str,
        operation: str,
        fields_changed: list[str],
        session_id: str = "",
    ) -> None:
        self._write({
            "event": "crm_mutation",
            "agent_id": agent_id,
            "contact_id": contact_id,
            "session_id": session_id,
            "operation": operation,
            "fields_changed": fields_changed,
        })

    def log_auth_event(
        self,
        event_type: str,
        user_id: str = "",
        ip_address: str = "",
        success: bool = True,
        detail: str = "",
    ) -> None:
        self._write({
            "event": "auth",
            "event_type": event_type,
            "user_id": user_id,
            "ip_address": ip_address,
            "success": success,
            "detail": detail,
        })

    def log_credential_event(
        self,
        agent_id: str,
        contact_id: str,
        category: str,
        event_type: str,
        document_id: str = "",
        detail: str = "",
    ) -> None:
        self._write({
            "event": "credential_event",
            "agent_id": agent_id,
            "contact_id": contact_id,
            "category": category,
            "event_type": event_type,   # e.g. "uploaded", "expired", "reminder_sent"
            "document_id": document_id,
            "detail": detail,
        })

    # ------------------------------------------------------------------
    # Read (compliance reporting)
    # ------------------------------------------------------------------

    def read_entries(
        self,
        agent_id: str | None = None,
        date_str: str | None = None,
        event_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Read audit entries from log files.
        Filters by agent_id, date (YYYYMMDD), and event type.
        Returns up to `limit` entries (most recent first).
        """
        files = self._matching_files(agent_id, date_str)
        entries: list[dict[str, Any]] = []

        for path in files:
            try:
                with open(path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if event_type and entry.get("event") != event_type:
                                continue
                            entries.append(entry)
                        except json.JSONDecodeError:
                            continue
            except OSError:
                continue

        # Sort descending by timestamp, then apply limit
        entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return entries[:limit]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, data: dict[str, Any]) -> None:
        ts = datetime.now(timezone.utc)
        data["timestamp"] = ts.isoformat()
        data["log_version"] = _LOG_FORMAT_VERSION

        line = json.dumps(data, separators=(",", ":")) + "\n"
        path = self._log_path(data.get("agent_id", "system"), ts)

        try:
            with _write_lock:
                with open(path, "a") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
        except OSError as exc:
            # Never raise from audit logger — log to stderr and continue
            logger.error("[AUDIT] Write failed path=%s: %s", path, exc)

    def _log_path(self, agent_id: str, ts: datetime) -> Path:
        date_str = ts.strftime("%Y%m%d")
        safe_id  = agent_id.replace("/", "_").replace(" ", "_")
        return self._log_dir / f"audit_{safe_id}_{date_str}.jsonl"

    def _matching_files(
        self, agent_id: str | None, date_str: str | None
    ) -> list[Path]:
        # Files are named: audit_{agent_id}_{YYYYMMDD}.jsonl
        agent_part = agent_id.replace("/", "_") + "_" if agent_id else "*_"
        date_part  = date_str if date_str else "*"
        pattern = f"audit_{agent_part}{date_part}.jsonl"
        return sorted(self._log_dir.glob(pattern))


# Module-level singleton
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
