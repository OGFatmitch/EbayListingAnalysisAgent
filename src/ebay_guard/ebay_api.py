from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_SCOPE = "https://api.ebay.com/oauth/api_scope"


def parse_legacy_item_id(url: str) -> str | None:
    patterns = [
        r"/itm/(?:[^/?]*/)?(\d{9,15})",
        r"[?&]item=(\d{9,15})",
        r"[?&]item_id=(\d{9,15})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


@dataclass
class EbayAPIClient:
    client_id: str | None
    client_secret: str | None
    base_url: str = "https://api.ebay.com"
    scope: str = DEFAULT_SCOPE
    timeout: int = 12

    _access_token: str | None = None

    @classmethod
    def from_env(cls) -> "EbayAPIClient":
        return cls(
            client_id=os.getenv("EBAY_CLIENT_ID"),
            client_secret=os.getenv("EBAY_CLIENT_SECRET"),
            base_url=os.getenv("EBAY_API_BASE_URL", "https://api.ebay.com"),
            scope=os.getenv("EBAY_API_SCOPE", DEFAULT_SCOPE),
            timeout=int(os.getenv("EBAY_API_TIMEOUT", "12")),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _token(self) -> str:
        if self._access_token:
            return self._access_token

        if not self.is_configured:
            raise RuntimeError("eBay API credentials are not configured")

        raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        basic = base64.b64encode(raw).decode("ascii")

        response = requests.post(
            f"{self.base_url}/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "client_credentials",
                "scope": self.scope,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("eBay token response missing access_token")

        self._access_token = token
        return token

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self._token()
        response = requests.get(
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            params=params or {},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_item_by_legacy_id(self, legacy_item_id: str) -> dict[str, Any]:
        return self._get(
            "/buy/browse/v1/item/get_item_by_legacy_id",
            params={"legacy_item_id": legacy_item_id},
        )

    def search_similar_items(
        self,
        query: str,
        category_ids: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "q": query,
            "limit": min(max(limit, 1), 30),
            "sort": "price",
        }
        if category_ids:
            params["category_ids"] = ",".join(category_ids[:3])

        payload = self._get("/buy/browse/v1/item_summary/search", params=params)
        return payload.get("itemSummaries", [])
