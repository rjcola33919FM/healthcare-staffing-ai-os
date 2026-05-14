"""Candidate recruiting schemas — REC-001"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class CandidateIntake(BaseModel):
    contact_id: str
    first_name: str
    last_name: str
    email: EmailStr | None = None
    phone: str | None = None
    specialty: str
    license_state: str = Field(..., min_length=2, max_length=2)
    npi_number: str | None = None
    availability_date: date | None = None
    desired_locations: list[str] = Field(default_factory=list)
    shift_preference: Literal["days", "nights", "evenings", "flex"] | None = None
    years_experience: int | None = None
    source: str | None = None  # sms | voice | form | chat


class CandidateProfile(CandidateIntake):
    pipeline_stage: str = "intake_in_progress"
    intake_complete: bool = False
    credentialing_started: bool = False
    recruiter_assigned: str | None = None
    notes: list[str] = Field(default_factory=list)
