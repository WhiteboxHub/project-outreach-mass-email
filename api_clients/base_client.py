import requests
from typing import Any, Dict, List, Optional
import os
import logging

logger = logging.getLogger("outreach_service")

class BaseClient:
    def __init__(self):
        self.base_url = os.getenv("WBL_BACKEND_URL", "http://localhost:8000/api")
        self.session = requests.Session()
        # In a real scenario, add API Key header
        # self.session.headers.update({"X-API-Key": "secret"})

    def _get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        try:
            resp = self.session.get(f"{self.base_url}{endpoint}", params=params)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"GET {endpoint} failed: {e}")
            return None

    def _post(self, endpoint: str, json: Dict = None) -> Optional[Dict]:
        try:
            resp = self.session.post(f"{self.base_url}{endpoint}", json=json)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"POST {endpoint} failed: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            return None

    def _put(self, endpoint: str, json: Dict = None) -> Optional[Dict]:
        try:
            resp = self.session.put(f"{self.base_url}{endpoint}", json=json)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"PUT {endpoint} failed: {e}")
            return None

    def get(self, resource_id: int) -> Optional[Dict[str, Any]]:
        # Default implementation assumes strict REST resource
        # Override if needed
        pass

    def list(self, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        pass
