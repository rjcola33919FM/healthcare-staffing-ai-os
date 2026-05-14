"""
Per-agent configuration registry.
Maps AgentID → model, temperature, tooling, and escalation config.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    name: str
    temperature: float
    top_p: float
    max_tokens: int
    tooling: list[str]
    human_review_triggers: list[str]


AGENT_CONFIGS: dict[str, AgentConfig] = {
    "ORCH-001": AgentConfig(
        agent_id="ORCH-001",
        name="Healthcare Staffing Orchestrator Agent",
        temperature=0.05,
        top_p=0.1,
        max_tokens=1024,
        tooling=["GoHighLevel workflows", "calendar", "tags", "pipeline", "task creation", "webhook router"],
        human_review_triggers=[
            "compliance exceptions",
            "credential approval",
            "candidate rejection",
            "client contract decisions",
        ],
    ),
    "REC-001": AgentConfig(
        agent_id="REC-001",
        name="Candidate Recruiting Agent",
        temperature=0.05,
        top_p=0.1,
        max_tokens=1024,
        tooling=["GoHighLevel SMS", "AI voice", "forms", "calendar booking", "pipeline stage updates"],
        human_review_triggers=[
            "compensation negotiations",
            "final screening decisions",
            "candidate disqualification",
        ],
    ),
    "CRED-001": AgentConfig(
        agent_id="CRED-001",
        name="Medical Credentialing Agent",
        temperature=0.05,
        top_p=0.1,
        max_tokens=1024,
        tooling=["GoHighLevel email/SMS", "secure upload links", "checklist status", "task reminders"],
        human_review_triggers=[
            "credential sufficiency",
            "authenticity concerns",
            "privileging",
            "license interpretation",
            "final file approval",
        ],
    ),
    "COMP-001": AgentConfig(
        agent_id="COMP-001",
        name="Compliance Monitoring Agent",
        temperature=0.05,
        top_p=0.1,
        max_tokens=1024,
        tooling=["GoHighLevel tasks", "alerts", "pipeline movement", "compliance tags", "reporting dashboard"],
        human_review_triggers=[
            "adverse compliance flags",
            "missing mandatory credentials",
            "PHI exposure",
            "audit exceptions",
        ],
    ),
    "SALES-001": AgentConfig(
        agent_id="SALES-001",
        name="Client Sales Qualification Agent",
        temperature=0.05,
        top_p=0.1,
        max_tokens=1024,
        tooling=["GoHighLevel forms", "chat", "SMS", "calendar booking", "opportunity pipeline"],
        human_review_triggers=[
            "pricing exceptions",
            "contract terms",
            "MSP/RPO commitments",
            "custom service commitments",
        ],
    ),
    "CRM-001": AgentConfig(
        agent_id="CRM-001",
        name="CRM Operations Agent",
        temperature=0.05,
        top_p=0.1,
        max_tokens=1024,
        tooling=["GoHighLevel CRM", "opportunities", "tags", "notes", "tasks", "webhooks", "reporting"],
        human_review_triggers=[
            "merge conflicts",
            "deletion requests",
            "integration failures",
            "ambiguous identity matching",
        ],
    ),
}


def get_agent_config(agent_id: str) -> AgentConfig:
    config = AGENT_CONFIGS.get(agent_id)
    if not config:
        raise KeyError(f"No config registered for agent_id='{agent_id}'")
    return config
