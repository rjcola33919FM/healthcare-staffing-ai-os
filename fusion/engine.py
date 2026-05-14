"""
Fusion Engine — applies fusion scoring to agent responses and gates output quality.

Per the build kit:
  - logic_weight: 0.60
  - factuality_weight: 0.25
  - tone_weight: 0.15
  - adaptive: dynamic, updates every 10 synthesis cycles
  - quality targets: clarity 0.9–1.0, logic 0.85–0.95, factual 0.9–1.0, tone 0.85–0.95
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .profiles import FusionProfile, FusionProfileRegistry, get_profile
from .scorer import FusionScore, FusionScorer

logger = logging.getLogger(__name__)


@dataclass
class FusionResult:
    agent_id: str
    original_response: str
    score: FusionScore
    approved: bool
    revised_response: str | None = None  # set if response was revised
    revision_reason: str = ""
    cycle_count: int = 0


class FusionEngine:
    """
    Applies fusion scoring to agent responses.
    If a response fails quality targets, attempts one revision via the scorer's
    feedback loop before escalating or passing through with a warning.

    Adaptive behavior: tracks cycle counts and logs drift every 10 cycles.
    """

    def __init__(self, registry: FusionProfileRegistry | None = None):
        self._registry = registry or FusionProfileRegistry()
        self._cycle_counts: dict[str, int] = {}

    def evaluate(self, agent_id: str, response_text: str) -> FusionResult:
        """
        Score a response against its agent's fusion profile.
        Returns a FusionResult with approval status and optional revision.
        """
        profile = self._registry.get(agent_id)
        scorer = FusionScorer(profile)
        score = scorer.score(response_text)

        self._cycle_counts[agent_id] = self._cycle_counts.get(agent_id, 0) + 1
        cycle = self._cycle_counts[agent_id]

        # Adaptive logging every 10 cycles
        if cycle % 10 == 0:
            logger.info(
                "[FUSION] Adaptive checkpoint agent=%s cycle=%d composite=%.4f",
                agent_id, cycle, score.composite_score,
            )

        if score.passed:
            return FusionResult(
                agent_id=agent_id,
                original_response=response_text,
                score=score,
                approved=True,
                cycle_count=cycle,
            )

        # Response failed — attempt revision hint
        revised = self._revise(response_text, score, profile)
        revised_score = scorer.score(revised)

        logger.warning(
            "[FUSION] Response failed quality gate agent=%s failures=%s composite=%.4f",
            agent_id, score.failures, score.composite_score,
        )

        return FusionResult(
            agent_id=agent_id,
            original_response=response_text,
            score=revised_score,
            approved=revised_score.passed,
            revised_response=revised if revised != response_text else None,
            revision_reason="; ".join(score.failures),
            cycle_count=cycle,
        )

    def _revise(
        self,
        text: str,
        score: FusionScore,
        profile: FusionProfile,
    ) -> str:
        """
        Apply lightweight text revisions to lift a response toward quality targets.
        Operates on the text without an LLM call for speed and determinism.
        """
        revised = text

        # Tone failure — strip hedging language
        if any("tone" in f for f in score.failures):
            hedges = ["maybe", "might be", "possibly", "i think", "you could try"]
            for hedge in hedges:
                revised = revised.replace(hedge, "")
            revised = revised.strip()

        # Logic failure — append a next-step instruction if missing
        if any("logic" in f for f in score.failures):
            if "next step" not in revised.lower() and "will" not in revised.lower():
                revised += " Your recruiter will follow up with the next steps."

        # Factuality failure — add grounding note
        if any("factual" in f for f in score.failures):
            if "specialist" not in revised.lower() and "recruiter" not in revised.lower():
                revised += " Please contact your recruiter to confirm these details."

        return revised.strip()

    def batch_evaluate(
        self, agent_id: str, responses: list[str]
    ) -> list[FusionResult]:
        """Evaluate a batch of responses — used for QA regression testing."""
        return [self.evaluate(agent_id, r) for r in responses]

    def get_cycle_count(self, agent_id: str) -> int:
        return self._cycle_counts.get(agent_id, 0)

    def reset_cycles(self, agent_id: str | None = None) -> None:
        if agent_id:
            self._cycle_counts.pop(agent_id, None)
        else:
            self._cycle_counts.clear()
