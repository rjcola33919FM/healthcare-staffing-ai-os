"""
Fusion Scorer — evaluates agent responses against logic, factuality, and tone targets.
Scores are applied from each agent's fusion profile (logic: 0.6, factuality: 0.25, tone: 0.15).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .profiles import FusionProfile

logger = logging.getLogger(__name__)

# Phrases that signal high logic consistency
LOGIC_POSITIVE = [
    "because", "therefore", "as a result", "confirmed", "verified",
    "based on", "according to", "step", "next", "required",
]
# Phrases that signal low logic consistency (hedging, contradiction)
LOGIC_NEGATIVE = [
    "maybe", "might be", "i'm not sure", "possibly", "i think",
    "you could try", "it depends", "not sure",
]

# Phrases that signal factual grounding
FACTUAL_POSITIVE = [
    "your", "contact id", "stage", "checklist", "document", "license",
    "specialist", "recruiter", "pipeline", "uploaded", "confirmed",
]
# Phrases that signal ungrounded speculation
FACTUAL_NEGATIVE = [
    "generally speaking", "usually", "often", "typically", "might vary",
    "in most cases", "for most people",
]

# Tone markers — compliant, neutral, professional
TONE_POSITIVE = [
    "please", "thank you", "your recruiter", "specialist will",
    "i've updated", "we've received", "has been", "next step",
]
TONE_NEGATIVE = [
    "you must", "you need to immediately", "failure to", "violation",
    "i cannot help", "that's not my problem",
]


@dataclass
class FusionScore:
    agent_id: str
    logic_score: float        # 0.0–1.0
    factuality_score: float   # 0.0–1.0
    tone_score: float         # 0.0–1.0
    composite_score: float    # weighted composite
    meets_targets: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.meets_targets and not self.failures


def _score_dimension(text: str, positive: list[str], negative: list[str]) -> float:
    """Simple keyword heuristic scorer for a single dimension. Returns 0.0–1.0."""
    lower = text.lower()
    pos_hits = sum(1 for p in positive if p in lower)
    neg_hits = sum(1 for n in negative if n in lower)
    # Normalise: start at 0.75 baseline, +0.05 per positive, -0.1 per negative
    score = 0.75 + (pos_hits * 0.05) - (neg_hits * 0.10)
    return max(0.0, min(1.0, round(score, 3)))


class FusionScorer:
    """
    Scores an agent response against its fusion profile targets.
    Produces a FusionScore with per-dimension scores and pass/fail.
    """

    def __init__(self, profile: FusionProfile):
        self.profile = profile

    def score(self, response_text: str) -> FusionScore:
        logic = _score_dimension(response_text, LOGIC_POSITIVE, LOGIC_NEGATIVE)
        factuality = _score_dimension(response_text, FACTUAL_POSITIVE, FACTUAL_NEGATIVE)
        tone = _score_dimension(response_text, TONE_POSITIVE, TONE_NEGATIVE)

        p = self.profile
        composite = (
            logic * p.logic_weight
            + factuality * p.factuality_weight
            + tone * p.tone_weight
        )

        failures = []
        warnings = []
        targets = p.quality_targets

        def _check(name: str, value: float) -> None:
            lo, hi = targets.get(name, (0.0, 1.0))
            if value < lo:
                failures.append(f"{name}={value:.3f} below target [{lo},{hi}]")
            elif value < lo + 0.05:
                warnings.append(f"{name}={value:.3f} near lower bound {lo}")

        _check("logic_consistency", logic)
        _check("factual_accuracy", factuality)
        _check("tone_alignment", tone)

        meets_targets = len(failures) == 0

        score = FusionScore(
            agent_id=p.agent_id,
            logic_score=logic,
            factuality_score=factuality,
            tone_score=tone,
            composite_score=round(composite, 4),
            meets_targets=meets_targets,
            failures=failures,
            warnings=warnings,
        )

        logger.debug(
            "[FUSION] score agent=%s logic=%.3f fact=%.3f tone=%.3f composite=%.4f pass=%s",
            p.agent_id, logic, factuality, tone, composite, score.passed,
        )
        return score
