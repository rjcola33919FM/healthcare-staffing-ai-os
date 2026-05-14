"""Sales qualification schemas — SALES-001"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


QualificationScore = Literal["hot", "warm", "cold", "unqualified"]

FacilityType = Literal[
    "hospital",
    "clinic",
    "long_term_care",
    "home_health",
    "behavioral_health",
    "ambulatory_surgery",
    "urgent_care",
    "other",
]


class LeadQualification(BaseModel):
    contact_id: str
    facility_name: str | None = None
    facility_type: FacilityType | None = None
    specialties_needed: list[str] = Field(default_factory=list)
    roles_needed: list[str] = Field(default_factory=list)
    positions_count: int | None = None
    states_markets: list[str] = Field(default_factory=list)
    target_start_date: str | None = None
    decision_maker: str | None = None
    budget_confirmed: bool = False
    authority_confirmed: bool = False
    need_confirmed: bool = False
    timeline_confirmed: bool = False

    @property
    def bant_score(self) -> int:
        """BANT score 0–4. Used to set qualification_score."""
        return sum([
            self.budget_confirmed,
            self.authority_confirmed,
            self.need_confirmed,
            self.timeline_confirmed,
        ])

    @property
    def qualification_score(self) -> QualificationScore:
        score = self.bant_score
        if score >= 3:
            return "hot"
        if score == 2:
            return "warm"
        if score == 1:
            return "cold"
        return "unqualified"


class SalesOpportunity(BaseModel):
    opportunity_id: str
    contact_id: str
    pipeline_stage: str = "new_opportunity"
    qualification: LeadQualification
    notes: list[str] = Field(default_factory=list)
    appointment_booked: bool = False
    disqualified: bool = False
    disqualification_reason: str | None = None
