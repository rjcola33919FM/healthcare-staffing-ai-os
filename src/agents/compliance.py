"""COMP-001 — Compliance Monitoring Agent"""

import anthropic
from .base import BaseAgent


class ComplianceAgent(BaseAgent):
    def __init__(self, client: anthropic.Anthropic):
        super().__init__("COMP-001", client)
