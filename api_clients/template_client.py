from typing import Any, Dict, List, Optional
from api_clients.base_client import BaseClient
import logging

logger = logging.getLogger("outreach_service")

class TemplateClient(BaseClient):
    
    def get(self, resource_id: int) -> Optional[Dict[str, Any]]:
        return self._get(f"/orchestrator/email-template/{resource_id}")

    def list(self, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        return [] # TODO if needed
