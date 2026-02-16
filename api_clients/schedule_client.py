from typing import Any, Dict, List, Optional
from api_clients.base_client import BaseClient
import logging

logger = logging.getLogger("outreach_service")

class ScheduleClient(BaseClient):
    
    def list_due(self) -> List[Dict[str, Any]]:
        # Call orchestration endpoint
        result = self._get("/orchestrator/schedules/due")
        return result if result else []

    def get(self, resource_id: int) -> Optional[Dict[str, Any]]:
        # Call orchestration endpoint
        try:
             return self._get(f"/orchestrator/schedules/{resource_id}")
        except Exception as e:
             logger.error(f"Error getting schedule {resource_id}: {e}")
             return None

    def lock_schedule(self, resource_id: int) -> bool:
        resp = self._post(f"/orchestrator/schedules/{resource_id}/lock")
        return resp.get("success", False) if resp else False

    def update(self, resource_id: int, updates: Dict[str, Any]) -> bool:
        # Use orchestrator update as it handles dynamic updates more gracefully than standard PUT usually which expects full object
        # Or check if automation-workflow-schedule PUT supports partial update (it did exclude_unset=True).
        # Orchestrator update specifically crafted for this service.
        resp = self._put(f"/orchestrator/schedules/{resource_id}", json=updates)
        return resp.get("success", False) if resp else False
