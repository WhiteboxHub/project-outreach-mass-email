from typing import Any, Dict, List, Optional
from enum import Enum
from api_clients.base_client import BaseClient
import logging

class EngineType(str, Enum):
    SMTP = "smtp"
    MAILGUN = "mailgun"
    SENDGRID = "sendgrid"
    AWS_SES = "aws_ses"

logger = logging.getLogger("outreach_service")

class DeliveryEngineClient(BaseClient):
    
    def get(self, resource_id: int) -> Optional[Dict[str, Any]]:
        return self._get(f"/orchestrator/delivery-engine/{resource_id}")

    def get_candidate_credentials(self, candidate_id: int) -> Optional[Dict[str, Any]]:
        return self._get(f"/orchestrator/candidate-credentials/{candidate_id}")

    def list(self, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        return [] 
