"""
Fusion Profile Registry — loads and caches per-agent fusion configs.
Single source: fusion/{AGENT_ID}.json files.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FUSION_DIR = Path(__file__).parent

AGENT_IDS = ["ORCH-001", "REC-001", "CRED-001", "COMP-001", "SALES-001", "CRM-001"]


@dataclass(frozen=True)
class FusionProfile:
    agent_id: str
    module_name: str
    version: str
    logic_weight: float
    factuality_weight: float
    tone_weight: float
    adaptive_mode: str
    update_frequency: str
    quality_targets: dict[str, tuple[float, float]]

    @property
    def weights_valid(self) -> bool:
        return abs(self.logic_weight + self.factuality_weight + self.tone_weight - 1.0) < 1e-9


def _parse_profile(agent_id: str, raw: dict[str, Any]) -> FusionProfile:
    bias = raw["scoring_bias"]
    targets_raw = raw["quality_targets"]
    targets = {k: tuple(v) for k, v in targets_raw.items()}
    return FusionProfile(
        agent_id=agent_id,
        module_name=raw["module_name"],
        version=raw["version"],
        logic_weight=bias["logic_weight"],
        factuality_weight=bias["factuality_weight"],
        tone_weight=bias["tone_weight"],
        adaptive_mode=raw["adaptive_behavior"]["mode"],
        update_frequency=raw["adaptive_behavior"]["update_frequency"],
        quality_targets=targets,
    )


class FusionProfileRegistry:
    """Loads all agent fusion profiles at startup and caches them."""

    def __init__(self) -> None:
        self._profiles: dict[str, FusionProfile] = {}
        self._load_all()

    def _load_all(self) -> None:
        for agent_id in AGENT_IDS:
            path = FUSION_DIR / f"{agent_id}.json"
            try:
                raw = json.loads(path.read_text())
                profile = _parse_profile(agent_id, raw)
                if not profile.weights_valid:
                    logger.error(
                        "[FUSION] Profile %s has invalid weights (sum != 1.0)", agent_id
                    )
                self._profiles[agent_id] = profile
                logger.debug("[FUSION] Loaded profile %s", agent_id)
            except Exception as e:
                logger.error("[FUSION] Failed to load profile %s: %s", agent_id, e)

    def get(self, agent_id: str) -> FusionProfile:
        profile = self._profiles.get(agent_id)
        if not profile:
            raise KeyError(f"No fusion profile for agent_id='{agent_id}'")
        return profile

    def all_profiles(self) -> dict[str, FusionProfile]:
        return dict(self._profiles)

    def reload(self) -> None:
        self._profiles.clear()
        self._load_all()


# Module-level singleton
_registry: FusionProfileRegistry | None = None


def get_profile(agent_id: str) -> FusionProfile:
    global _registry
    if _registry is None:
        _registry = FusionProfileRegistry()
    return _registry.get(agent_id)
