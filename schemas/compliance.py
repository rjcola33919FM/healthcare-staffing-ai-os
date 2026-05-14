"""Compliance monitoring schemas — COMP-001"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


AlertLevel = Literal["red", "yellow", "blue"]


class ComplianceAlert(BaseModel):
    alert_id: str
    contact_id: str
    alert_level: AlertLevel
    credential_type: str
    expiration_date: str | None = None
    days_remaining: int | None = None
    mandatory: bool = False
    description: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False
    escalated: bool = False


class AuditLogEntry(BaseModel):
    """Append-only audit log entry. Never deleted."""
    log_id: str
    agent_id: str
    contact_id: str
    action: str
    detail: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    channel: str = "system"
    escalated: bool = False


class ComplianceRecord(BaseModel):
    contact_id: str
    overall_status: Literal["compliant", "at_risk", "non_compliant", "escalated"] = "at_risk"
    alerts: list[ComplianceAlert] = Field(default_factory=list)
    audit_log: list[AuditLogEntry] = Field(default_factory=list)
    last_reviewed: datetime | None = None
    phi_exposure_detected: bool = False

    @property
    def active_alerts(self) -> list[ComplianceAlert]:
        return [a for a in self.alerts if not a.resolved]

    @property
    def red_alerts(self) -> list[ComplianceAlert]:
        return [a for a in self.active_alerts if a.alert_level == "red"]
