"""Minimal Home Assistant REST client, authenticated with the app's Supervisor token."""

from __future__ import annotations

import os

import httpx


class HomeAssistant:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = base_url or os.environ.get("HA_URL", "http://supervisor/core/api")
        self.token = token or os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HA_TOKEN", "")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30,
        )

    async def get_open_items(self, entity_id: str) -> list[str]:
        r = await self._client.post(
            "/services/todo/get_items?return_response",
            json={"entity_id": entity_id, "status": "needs_action"},
        )
        r.raise_for_status()
        items = r.json().get("service_response", {}).get(entity_id, {}).get("items", [])
        return [i["summary"] for i in items]

    async def add_item(self, entity_id: str, item: str) -> None:
        r = await self._client.post(
            "/services/todo/add_item", json={"entity_id": entity_id, "item": item}
        )
        r.raise_for_status()
