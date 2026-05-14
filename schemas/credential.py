"""Credentialing schemas — CRED-001"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


CredentialStatus = Literal["pending", "received", "verified", "expired", "missing", "escalated"]

CredentialCategoryType = Literal[
    "identity",
    "licensure",
    "education_training",
    "work_history",
    "malpractice",
    "health_immunizations",
    "background_drug",
]


class CredentialDocument(BaseModel):
    document_id: str
    contact_id: str
    category: CredentialCategoryType
    document_name: str
    status: CredentialStatus = "pending"
    expiration_date: date | None = None
    received_date: date | None = None
    upload_url: str | None = None
    notes: str | None = None
    escalated: bool = False

    @property
    def days_until_expiry(self) -> int | None:
        if self.expiration_date:
            return (self.expiration_date - date.today()).days
        return None


class CredentialChecklist(BaseModel):
    contact_id: str
    identity: list[CredentialDocument] = Field(default_factory=list)
    licensure: list[CredentialDocument] = Field(default_factory=list)
    education_training: list[CredentialDocument] = Field(default_factory=list)
    work_history: list[CredentialDocument] = Field(default_factory=list)
    malpractice: list[CredentialDocument] = Field(default_factory=list)
    health_immunizations: list[CredentialDocument] = Field(default_factory=list)
    background_drug: list[CredentialDocument] = Field(default_factory=list)

    @property
    def completion_pct(self) -> float:
        all_docs = (
            self.identity + self.licensure + self.education_training +
            self.work_history + self.malpractice +
            self.health_immunizations + self.background_drug
        )
        if not all_docs:
            return 0.0
        verified = sum(1 for d in all_docs if d.status == "verified")
        return round(verified / len(all_docs) * 100, 1)

    @property
    def has_missing_mandatory(self) -> bool:
        mandatory_categories = {"identity", "licensure", "background_drug"}
        for cat in mandatory_categories:
            docs = getattr(self, cat)
            if not docs or any(d.status == "missing" for d in docs):
                return True
        return False
