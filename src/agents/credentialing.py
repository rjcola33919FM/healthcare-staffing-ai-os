"""CRED-001 — Medical Credentialing Agent"""

import anthropic
from .base import BaseAgent


class CredentialingAgent(BaseAgent):
    def __init__(self, client: anthropic.Anthropic):
        super().__init__("CRED-001", client)
