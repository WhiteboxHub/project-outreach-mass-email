from typing import Any, Dict, List, Optional
from api_clients.base_client import BaseClient

class ScheduleClient(BaseClient):
    MOCK_DATA = [
        {
            "id": 1,
            "automation_workflow_id": 1,
            "timezone": "America/Los_Angeles",
            "cron_expression": "0 8 * * *",
            "frequency": "daily",
            "interval_value": 1,
            "next_run_at": "2026-02-10 08:00:00",
            "enabled": True
        }
    ]

    def get(self, resource_id: int) -> Optional[Dict[str, Any]]:
        return next((item for item in self.MOCK_DATA if item["id"] == resource_id), None)

    def list(self, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
         return self.MOCK_DATA
