from typing import Any, Dict, List, Optional
from api_clients.base_client import BaseClient
import logging

logger = logging.getLogger("outreach_service")

class LogClient(BaseClient):
    
    def create(self, data: Dict[str, Any]) -> int:
        try:
            # We call the backend orchestrator endpoint
            resp = self._post("/orchestrator/logs", json=data)
            if resp and "id" in resp:
                return resp["id"]
            return None
        except Exception as e:
            logger.error(f"Error creating log via API: {e}")
            return None

    def update(self, log_id: int, updates: Dict[str, Any]) -> bool:
        if not log_id:
            return False
            
        try:
            # We call the backend orchestrator endpoint
            resp = self._put(f"/orchestrator/logs/{log_id}", json=updates)
            return resp.get("success", False) if resp else False
        except Exception as e:
            logger.error(f"Error updating log {log_id} via API: {e}")
            return False
