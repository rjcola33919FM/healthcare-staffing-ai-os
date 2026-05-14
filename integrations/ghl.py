"""
GoHighLevel CRM Integration
Wraps GHL REST API v2 — contacts, notes, tags, pipeline, tasks.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GHL_BASE_URL = "https://services.leadconnectorhq.com"
GHL_API_KEY = os.environ.get("GHL_API_KEY", "")
GHL_LOCATION_ID = os.environ.get("GHL_LOCATION_ID", "")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {GHL_API_KEY}",
        "Content-Type": "application/json",
        "Version": "2021-07-28",
    }


class GHLClient:
    def __init__(self, api_key: str = GHL_API_KEY, location_id: str = GHL_LOCATION_ID):
        self.api_key = api_key
        self.location_id = location_id
        self.base_url = GHL_BASE_URL

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=15) as client:
            r = client.get(url, headers=_headers(), params=params)
            r.raise_for_status()
            return r.json()

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=15) as client:
            r = client.post(url, headers=_headers(), json=body)
            r.raise_for_status()
            return r.json()

    def _put(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=15) as client:
            r = client.put(url, headers=_headers(), json=body)
            r.raise_for_status()
            return r.json()

    # ── Contacts ──────────────────────────────────────────────────────────────

    def get_contact(self, contact_id: str) -> dict:
        return self._get(f"/contacts/{contact_id}")

    def update_contact(self, contact_id: str, fields: dict[str, Any]) -> dict:
        return self._put(f"/contacts/{contact_id}", fields)

    def add_tags(self, contact_id: str, tags: list[str]) -> dict:
        return self._post(f"/contacts/{contact_id}/tags", {"tags": tags})

    def remove_tags(self, contact_id: str, tags: list[str]) -> dict:
        url = f"{self.base_url}/contacts/{contact_id}/tags"
        with httpx.Client(timeout=15) as client:
            r = client.delete(url, headers=_headers(), json={"tags": tags})
            r.raise_for_status()
            return r.json()

    # ── Notes ─────────────────────────────────────────────────────────────────

    def add_note(self, contact_id: str, body: str, user_id: str = "") -> dict:
        return self._post("/contacts/notes", {
            "contactId": contact_id,
            "body": body,
            "userId": user_id,
        })

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def create_task(
        self,
        contact_id: str,
        title: str,
        due_date: str,
        assignee_id: str = "",
        description: str = "",
    ) -> dict:
        return self._post("/contacts/tasks", {
            "contactId": contact_id,
            "title": title,
            "dueDate": due_date,
            "assignedTo": assignee_id,
            "description": description,
            "completed": False,
        })

    # ── Pipeline / Opportunities ───────────────────────────────────────────────

    def update_opportunity_stage(self, opportunity_id: str, stage_id: str) -> dict:
        return self._put(f"/opportunities/{opportunity_id}", {"stageId": stage_id})

    def create_opportunity(self, contact_id: str, pipeline_id: str, stage_id: str, name: str) -> dict:
        return self._post("/opportunities/", {
            "pipelineId": pipeline_id,
            "locationId": self.location_id,
            "name": name,
            "pipelineStageId": stage_id,
            "contactId": contact_id,
            "status": "open",
        })

    # ── Convenience: apply CRM updates dict from AgentResponse ────────────────

    def apply_crm_updates(self, contact_id: str, updates: dict[str, Any]) -> None:
        """
        Apply a structured crm_updates dict produced by an agent response.
        Keys: tags_add, tags_remove, fields, note, task
        """
        if tags := updates.get("tags_add"):
            self.add_tags(contact_id, tags)
            logger.info("[GHL] Added tags %s to contact %s", tags, contact_id)

        if tags := updates.get("tags_remove"):
            self.remove_tags(contact_id, tags)

        if fields := updates.get("fields"):
            self.update_contact(contact_id, fields)

        if note := updates.get("note"):
            self.add_note(contact_id, note)
            logger.info("[GHL] Added note to contact %s", contact_id)

        if task := updates.get("task"):
            self.create_task(
                contact_id=contact_id,
                title=task["title"],
                due_date=task.get("due_date", ""),
                assignee_id=task.get("assignee_id", ""),
                description=task.get("description", ""),
            )
