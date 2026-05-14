"""SALES-001 — Client Sales Qualification Agent"""

import anthropic
from .base import BaseAgent


class SalesAgent(BaseAgent):
    def __init__(self, client: anthropic.Anthropic):
        super().__init__("SALES-001", client)
