"""
Compliance Reporter — generates HIPAA audit reports from the append-only audit log.
Supports daily summaries, escalation tallies, PHI event reports, and credential expiry reports.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


class ComplianceReporter:
    """
    Reads from AuditLogger and produces structured compliance summaries.

    Usage:
        reporter = ComplianceReporter(audit_logger)
        report = reporter.daily_summary("2026-05-14")
        report = reporter.phi_event_report(days=30)
        report = reporter.escalation_report(days=7)
    """

    def __init__(self, audit_logger=None):
        # Lazy import to avoid circular dependency
        if audit_logger is None:
            from audit_log.audit import get_audit_logger
            audit_logger = get_audit_logger()
        self._audit = audit_logger

    # ------------------------------------------------------------------
    # Report: daily summary
    # ------------------------------------------------------------------

    def daily_summary(self, date_str: str | None = None) -> dict[str, Any]:
        """
        Aggregate all audit entries for a given date (YYYYMMDD).
        Defaults to today.
        """
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

        entries = self._audit.read_entries(date_str=date_str, limit=10_000)

        by_event: dict[str, int] = {}
        by_agent: dict[str, int] = {}
        phi_events = []
        escalations = []

        for e in entries:
            event = e.get("event", "unknown")
            agent = e.get("agent_id", "system")
            by_event[event] = by_event.get(event, 0) + 1
            by_agent[agent] = by_agent.get(agent, 0) + 1

            if event == "phi_detection":
                phi_events.append({
                    "ts": e.get("timestamp"),
                    "agent_id": agent,
                    "contact_id": e.get("contact_id"),
                    "phi_pattern": e.get("phi_pattern"),
                    "action_taken": e.get("action_taken"),
                })
            elif event == "escalation":
                escalations.append({
                    "ts": e.get("timestamp"),
                    "agent_id": agent,
                    "contact_id": e.get("contact_id"),
                    "reason": e.get("reason"),
                    "severity": e.get("severity"),
                })

        return {
            "report_type": "daily_summary",
            "date": date_str,
            "total_entries": len(entries),
            "by_event_type": by_event,
            "by_agent": by_agent,
            "phi_events": phi_events,
            "phi_event_count": len(phi_events),
            "escalations": escalations,
            "escalation_count": len(escalations),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Report: PHI events (rolling window)
    # ------------------------------------------------------------------

    def phi_event_report(self, days: int = 30) -> dict[str, Any]:
        """All PHI detection events in the last N days."""
        entries = self._read_window(days=days, event_type="phi_detection")
        by_pattern: dict[str, int] = {}
        by_agent: dict[str, int] = {}

        for e in entries:
            p = e.get("phi_pattern", "unknown")
            a = e.get("agent_id", "system")
            by_pattern[p] = by_pattern.get(p, 0) + 1
            by_agent[a]   = by_agent.get(a, 0) + 1

        return {
            "report_type": "phi_events",
            "window_days": days,
            "total_phi_events": len(entries),
            "by_pattern": by_pattern,
            "by_agent": by_agent,
            "events": entries,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Report: escalations
    # ------------------------------------------------------------------

    def escalation_report(self, days: int = 7) -> dict[str, Any]:
        """All escalation events in the last N days, grouped by severity."""
        entries = self._read_window(days=days, event_type="escalation")
        by_severity: dict[str, int] = {}
        by_agent: dict[str, int] = {}

        for e in entries:
            sev   = e.get("severity", "normal")
            agent = e.get("agent_id", "system")
            by_severity[sev]  = by_severity.get(sev, 0) + 1
            by_agent[agent]   = by_agent.get(agent, 0) + 1

        return {
            "report_type": "escalations",
            "window_days": days,
            "total_escalations": len(entries),
            "by_severity": by_severity,
            "by_agent": by_agent,
            "events": entries,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Report: credential events
    # ------------------------------------------------------------------

    def credential_event_report(
        self, days: int = 30, event_type: str | None = None
    ) -> dict[str, Any]:
        """Credential upload, expiry, and reminder events."""
        entries = self._read_window(days=days, event_type="credential_event")
        if event_type:
            entries = [e for e in entries if e.get("event_type") == event_type]

        by_category: dict[str, int] = {}
        by_event_type: dict[str, int] = {}
        for e in entries:
            cat  = e.get("category", "unknown")
            evtt = e.get("event_type", "unknown")
            by_category[cat]   = by_category.get(cat, 0) + 1
            by_event_type[evtt] = by_event_type.get(evtt, 0) + 1

        return {
            "report_type": "credential_events",
            "window_days": days,
            "filter_event_type": event_type,
            "total_events": len(entries),
            "by_category": by_category,
            "by_event_type": by_event_type,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_window(
        self, days: int, event_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Read audit entries across the last N calendar days."""
        results: list[dict[str, Any]] = []
        today = datetime.now(timezone.utc)
        for i in range(days):
            day = today - timedelta(days=i)
            date_str = day.strftime("%Y%m%d")
            entries = self._audit.read_entries(
                date_str=date_str, event_type=event_type, limit=10_000
            )
            results.extend(entries)
        return results
