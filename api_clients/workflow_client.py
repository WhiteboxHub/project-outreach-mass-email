from typing import Any, Dict, List, Optional
from api_clients.base_client import BaseClient
import logging

logger = logging.getLogger("outreach_service")

class WorkflowClient(BaseClient):
    
    def get(self, resource_id: int) -> Optional[Dict[str, Any]]:
        return self._get(f"/orchestrator/workflows/{resource_id}")

    def get_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        return self._get(f"/orchestrator/workflows/key/{key}")

    def list(self, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        # Just use standard backend list endpoint
        return self._get(f"/automation-workflow/") or []

    def execute_sql(self, workflow_id: int, sql: str, params: Dict[str, Any] = {}) -> List[Dict[str, Any]]:
        """Call backend to execute recipient SQL safely."""
        resp = self._post(f"/orchestrator/workflows/{workflow_id}/execute-recipient-sql", json={"sql_query": sql, "parameters": params})
        return resp if resp is not None else []

    def execute_reset_sql(self, workflow_id: int, sql: str, params: Dict[str, Any] = {}) -> bool:
        """Call backend to execute reset SQL."""
        resp = self._post(f"/orchestrator/workflows/{workflow_id}/execute-reset-sql", json={"sql_query": sql, "parameters": params})
        return resp.get("success", False) if resp else False
