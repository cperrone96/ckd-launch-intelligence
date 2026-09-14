from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient

from api.main import create_app


class DashboardAPIError(RuntimeError):
    """Raised when a versioned API response cannot be consumed safely."""


class DashboardAPI:
    """Small client that keeps dashboard data access behind API responses."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url
        self._local = TestClient(create_app()) if base_url is None else None

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            if self._local is not None:
                response = self._local.get(path, params=params)
            else:
                response = httpx.get(f"{self.base_url}{path}", params=params, timeout=5)
        except Exception as error:
            raise DashboardAPIError("Unable to load evidence from the versioned API.") from error
        if response.status_code != 200:
            raise DashboardAPIError("Unable to load evidence from the versioned API.")
        payload = response.json()
        if not isinstance(payload, dict):
            raise DashboardAPIError("The versioned API returned an invalid response.")
        return payload
