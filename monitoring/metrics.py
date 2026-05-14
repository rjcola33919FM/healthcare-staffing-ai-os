"""
Application-level metrics aggregator.
Collects agent performance, escalation rates, and throughput in-process.
Exposes a /metrics snapshot endpoint and feeds into OTEL + Langfuse.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentMetrics:
    agent_id: str
    total_calls: int = 0
    total_escalations: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_duration_ms: int = 0
    error_count: int = 0
    last_call_ts: float = 0.0

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.total_calls if self.total_calls else 0.0

    @property
    def escalation_rate(self) -> float:
        return self.total_escalations / self.total_calls if self.total_calls else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_calls": self.total_calls,
            "total_escalations": self.total_escalations,
            "escalation_rate": round(self.escalation_rate, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "error_count": self.error_count,
        }


class MetricsCollector:
    """
    Thread-safe in-process metrics store.
    One singleton per process; exported via /metrics or OTEL push.

    Usage:
        metrics = MetricsCollector.get()
        metrics.record_call("REC-001", duration_ms=340, input_tokens=800, output_tokens=220)
        metrics.record_escalation("COMP-001", reason="phi_exposure", severity="critical")
        snapshot = metrics.snapshot()
    """

    _instance: "MetricsCollector | None" = None
    _lock: Lock = Lock()

    def __init__(self):
        self._agents: dict[str, AgentMetrics] = {}
        self._mu = Lock()

    @classmethod
    def get(cls) -> "MetricsCollector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    def record_call(
        self,
        agent_id: str,
        duration_ms: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        escalated: bool = False,
        error: bool = False,
    ) -> None:
        with self._mu:
            m = self._get_or_create(agent_id)
            m.total_calls += 1
            m.total_duration_ms += duration_ms
            m.total_input_tokens += input_tokens
            m.total_output_tokens += output_tokens
            m.last_call_ts = time.time()
            if escalated:
                m.total_escalations += 1
            if error:
                m.error_count += 1

    def record_escalation(self, agent_id: str, reason: str, severity: str) -> None:
        with self._mu:
            m = self._get_or_create(agent_id)
            m.total_escalations += 1
        logger.info("[METRICS] escalation agent=%s reason=%s severity=%s", agent_id, reason, severity)

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._mu:
            return {
                "agents": [m.to_dict() for m in self._agents.values()],
                "total_agents_active": len(self._agents),
                "snapshot_ts": time.time(),
            }

    def agent_stats(self, agent_id: str) -> dict[str, Any] | None:
        with self._mu:
            m = self._agents.get(agent_id)
            return m.to_dict() if m else None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create(self, agent_id: str) -> AgentMetrics:
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentMetrics(agent_id=agent_id)
        return self._agents[agent_id]
