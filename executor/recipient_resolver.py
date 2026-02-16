from typing import List, Dict, Any
from models.recipient import Recipient
from api_clients.workflow_client import WorkflowClient
import logging

logger = logging.getLogger("outreach_service")

class RecipientResolver:
    """
    Resolves recipients by calling the backend API to execute SQL.
    """
    def __init__(self):
        self.workflow_client = WorkflowClient()

    def resolve(self, workflow_id: int, recipient_sql: str, parameters: Dict[str, Any] = {}) -> List[Recipient]:
        recipients = []
        try:
            # Execute SQL via API
            # Ideally we pass workflow_id so backend can validat/scope queries if needed
            # But here we just use the execute endpoint
            
            # Note: WorkflowClient needs to be updated to support this method we added earlier
            result = self.workflow_client.execute_sql(workflow_id, recipient_sql, parameters)
            
            for data in result:
                # Expect columns: recipient_email, recipient_name (optional), other metadata
                email = data.get("recipient_email") or data.get("email") # Fallback
                name = data.get("recipient_name") or data.get("name") or data.get("contact_name")
                
                # Metadata is everything else
                metadata = data.copy()
                metadata.pop("recipient_email", None)
                # metadata.pop("recipient_name", None) 
                
                if email:
                    recipients.append(Recipient(
                        email=email,
                        name=name,
                        metadata=metadata
                    ))
            
            return recipients
            
        except Exception as e:
            logger.error(f"Error resolving recipients: {e}")
            return []
