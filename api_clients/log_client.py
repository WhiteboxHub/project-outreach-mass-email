from typing import Any, Dict, List, Optional
from api_clients.base_client import BaseClient

class LogClient(BaseClient):
    # In-memory storage for logs
    LOGS = []

    def get(self, resource_id: int) -> Optional[Dict[str, Any]]:
        return next((item for item in self.LOGS if item.get("id") == resource_id), None)

    def list(self, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        return self.LOGS

    def create(self, log_entry: Dict[str, Any]) -> Dict[str, Any]:
        log_entry["id"] = len(self.LOGS) + 1
        self.LOGS.append(log_entry)
        return log_entry
    
    def update(self, log_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for log in self.LOGS:
            if log["id"] == log_id:
                log.update(updates)
                return log
        return None
