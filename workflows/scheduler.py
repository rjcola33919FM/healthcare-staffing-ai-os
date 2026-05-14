"""
Credential Expiry Scheduler — runs the 30/14/7-day reminder sweep.
Called from the /internal/expiry-check FastAPI endpoint (triggered by external cron or APScheduler).

Fetches all contacts with credentials expiring within the reminder windows,
dispatches WorkflowEvent(compliance.expiry_check) per contact.

In production: trigger via:
  - AWS EventBridge rule → POST /internal/expiry-check (daily at 08:00 UTC)
  - APScheduler (if running single-process)
  - GHL custom workflow → webhook
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from config.hipaa import REMINDER_SCHEDULE_DAYS
from .executor import WorkflowEvent, WorkflowExecutor, WorkflowResult

logger = logging.getLogger(__name__)


class ExpiryScheduler:
    """
    Fetches expiring credentials and fires WorkflowEvents for each contact.

    Usage:
        scheduler = ExpiryScheduler(executor=wf_executor, cred_repo=cred_repo)
        results = await scheduler.run_daily_sweep()
    """

    def __init__(self, executor: WorkflowExecutor, cred_repo=None):
        self.executor  = executor
        self.cred_repo = cred_repo  # db.repositories.CredentialRepository

    async def run_daily_sweep(self) -> dict[str, Any]:
        """
        Check all reminder windows (30, 14, 7 days).
        Returns a summary of contacts processed and reminders sent.
        """
        max_days = max(REMINDER_SCHEDULE_DAYS)
        expiring = await self._fetch_expiring(days_ahead=max_days)

        total_processed = 0
        total_reminders = 0
        errors = []

        # Group by contact so each contact gets one event
        by_contact: dict[str, list] = {}
        for record in expiring:
            by_contact.setdefault(record.contact_id, []).append(record)

        for contact_id, records in by_contact.items():
            try:
                result = self.executor.run(WorkflowEvent(
                    event_type="compliance.expiry_check",
                    contact_id=contact_id,
                    agent_id="COMP-001",
                    data={
                        "expiring_categories": [r.category for r in records],
                    },
                ))
                total_processed += 1
                total_reminders += len(
                    [a for a in result.actions_taken if a.startswith("reminder_sent")]
                )
            except Exception as exc:
                errors.append({"contact_id": contact_id, "error": str(exc)})
                logger.error("[SCHED] Expiry sweep error contact=%s: %s", contact_id, exc)

        summary = {
            "sweep_ts": datetime.now(timezone.utc).isoformat(),
            "reminder_windows_days": REMINDER_SCHEDULE_DAYS,
            "contacts_with_expiring": len(by_contact),
            "contacts_processed": total_processed,
            "reminders_sent": total_reminders,
            "errors": errors,
        }

        logger.info(
            "[SCHED] Daily expiry sweep complete processed=%d reminders=%d errors=%d",
            total_processed, total_reminders, len(errors),
        )
        return summary

    async def _fetch_expiring(self, days_ahead: int) -> list:
        if self.cred_repo:
            return await self.cred_repo.get_expiring(days_ahead=days_ahead)
        # No DB — return empty list (safe default; log warning)
        logger.warning("[SCHED] No credential repository configured — expiry sweep skipped.")
        return []
