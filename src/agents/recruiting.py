"""REC-001 — Candidate Recruiting Agent"""

import anthropic
from .base import BaseAgent


class RecruitingAgent(BaseAgent):
    def __init__(self, client: anthropic.Anthropic):
        super().__init__("REC-001", client)
