from typing import Any, Dict, List, Optional
from api_clients.base_client import BaseClient
from models.workflow import WorkflowType, WorkflowStatus

class WorkflowClient(BaseClient):
    # Mock Data from prompt
    MOCK_DATA = [
        {
            "id": 1,
            "workflow_key": "daily_vendor_outreach",
            "name": "Daily Vendor Outreach (Candidate-Led)",
            "workflow_type": WorkflowType.EMAIL_SENDER,
            "status": WorkflowStatus.ACTIVE,
            "email_template_id": 1,
            "delivery_engine_id": 4, # Using Google SMTP Personal for demo
            "recipient_list_sql": "SELECT cm.email as from_email, v.contact_name, v.email as recipient_email, c.full_name as candidate_name, c.linkedin_url FROM candidate_marketing cm JOIN candidate c ON cm.candidate_id = c.id JOIN extracted_vendors v ON v.candidate_id = c.id WHERE cm.daily_outreach_flag = 1 AND v.is_emailed = 0",
            "parameters_config": {"success_reset_sql": "UPDATE candidate_marketing SET daily_outreach_flag = 0 WHERE candidate_id = :candidate_id"}
        },
        {
            "id": 3,
            "workflow_key": "weekly_vendor_outreach",
            "name": "Weekly Detailed Vendor Outreach",
            "workflow_type": WorkflowType.EMAIL_SENDER,
            "status": WorkflowStatus.ACTIVE,
            "email_template_id": 2,
            "delivery_engine_id": 1, # Mailgun
            "recipient_list_sql": "SELECT v.email as recipient_email, v.contact_name, c.full_name as candidate_name, c.linkedin_url FROM candidate_marketing cm JOIN candidate c ON cm.candidate_id = c.id JOIN extracted_vendors v ON v.candidate_id = c.id WHERE cm.weekly_outreach_flag = 1",
            "parameters_config": {"success_reset_sql": "UPDATE candidate_marketing SET weekly_outreach_flag = 0 WHERE candidate_id = :candidate_id"}
        }
    ]

    def get(self, resource_id: int) -> Optional[Dict[str, Any]]:
        return next((item for item in self.MOCK_DATA if item["id"] == resource_id), None)

    def get_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        return next((item for item in self.MOCK_DATA if item["workflow_key"] == key), None)

    def list(self, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        return self.MOCK_DATA
