"""
VAPI Integration — AI voice call management
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

VAPI_BASE_URL = "https://api.vapi.ai"
VAPI_API_KEY = os.environ.get("VAPI_API_KEY", "")
VAPI_ASSISTANT_ID = os.environ.get("VAPI_ASSISTANT_ID", "")


class VAPIClient:
    def __init__(self):
        self.base_url = VAPI_BASE_URL
        self.api_key = VAPI_API_KEY
        self.assistant_id = VAPI_ASSISTANT_ID

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def initiate_call(self, phone_number: str, contact_id: str, metadata: dict[str, Any] | None = None) -> dict:
        """Initiate an outbound AI voice call via VAPI."""
        payload: dict[str, Any] = {
            "assistantId": self.assistant_id,
            "customer": {"number": phone_number},
            "metadata": metadata or {},
        }
        payload["metadata"]["contact_id"] = contact_id

        with httpx.Client(timeout=15) as client:
            r = client.post(f"{self.base_url}/call/phone", headers=self._headers(), json=payload)
            r.raise_for_status()
            data = r.json()
            logger.info("[VAPI] Call initiated, call_id=%s", data.get("id"))
            return data

    def get_call(self, call_id: str) -> dict:
        with httpx.Client(timeout=15) as client:
            r = client.get(f"{self.base_url}/call/{call_id}", headers=self._headers())
            r.raise_for_status()
            return r.json()

    def get_transcript(self, call_id: str) -> str | None:
        call = self.get_call(call_id)
        return call.get("transcript")
