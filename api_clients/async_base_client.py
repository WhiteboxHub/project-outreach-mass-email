"""
api_clients/async_base_client.py
────────────────────────────────
Asynchronous HTTP client foundation for Outreach Platform v2.
Built on httpx.AsyncClient with connection pooling, explicit timeouts, and circuit breakers.
"""

import httpx
from typing import Any, Dict, List, Optional
import os
import logging
import uuid

logger = logging.getLogger("outreach_service")

class AsyncBaseClient:
    def __init__(self, base_url: Optional[str] = None, timeout_seconds: float = 15.0):
        self.base_url = base_url or os.getenv("WBL_BACKEND_URL", "https://api.whitebox-learning.com/api")
        self.timeout = httpx.Timeout(
            timeout_seconds,
            connect=5.0,
            read=timeout_seconds,
            write=10.0,
            pool=10.0
        )
        self.limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        """Lazily initializes the reusable AsyncClient connection pool."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=self.limits,
                headers={"X-Correlation-ID": str(uuid.uuid4())}
            )
        return self._client

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        client = await self.get_client()
        url = f"{self.base_url}{endpoint}"
        try:
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"[AsyncClient] GET {endpoint} HTTP error {e.response.status_code}: {e.response.text[:300]}")
            return None
        except Exception as e:
            logger.error(f"[AsyncClient] GET {endpoint} failed: {e}")
            return None

    async def _post(self, endpoint: str, json_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        client = await self.get_client()
        url = f"{self.base_url}{endpoint}"
        try:
            resp = await client.post(url, json=json_data)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"[AsyncClient] POST {endpoint} HTTP error {e.response.status_code}: {e.response.text[:300]}")
            return None
        except Exception as e:
            logger.error(f"[AsyncClient] POST {endpoint} failed: {e}")
            return None

    async def _put(self, endpoint: str, json_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        client = await self.get_client()
        url = f"{self.base_url}{endpoint}"
        try:
            resp = await client.put(url, json=json_data)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"[AsyncClient] PUT {endpoint} HTTP error {e.response.status_code}: {e.response.text[:300]}")
            return None
        except Exception as e:
            logger.error(f"[AsyncClient] PUT {endpoint} failed: {e}")
            return None

    async def close(self):
        """Cleanly releases network sockets."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
