from typing import Any, Dict, List, Optional
from api_clients.base_client import BaseClient
from models.delivery_engine import EngineType

class DeliveryEngineClient(BaseClient):
    # Mock Data from prompt
    MOCK_DATA = [
        {
            "id": 1,
            "name": "Mailgun-Marketing",
            "engine_type": EngineType.MAILGUN,
            "host": "api.mailgun.net",
            "port": 443,
            "api_key": "key-market", # Mocked
            "from_email": "marketing@whiteboxlearning.com",
            "from_name": "Whitebox Learning",
            "batch_size": 100,
            "rate_limit_per_minute": 300
        },
        {
            "id": 2,
            "name": "SendGrid-Transactional",
            "engine_type": EngineType.SENDGRID,
            "host": "api.sendgrid.com",
            "api_key": "key-sg", # Mocked
            "from_email": "alerts@whiteboxlearning.com",
            "from_name": "Whitebox Systems",
            "batch_size": 50,
            "rate_limit_per_minute": 100
        },
        {
            "id": 3,
            "name": "AWS-SES-Production",
            "engine_type": EngineType.AWS_SES,
            "host": "email-smtp.us-east-1.amazonaws.com",
            "username": "SES_SMTP_USER_ID",
            "password": "SES_SMTP_PASSWORD", # Mocked
            "from_email": "outreach@whiteboxlearning.com",
            "from_name": "Sampath Velupula",
            "batch_size": 200,
            "rate_limit_per_minute": 500
        },
         {
            "id": 4,
            "name": "Google-SMTP-Personal",
            "engine_type": EngineType.SMTP,
            "host": "smtp.gmail.com",
            "port": 587,
            "username": "your-email@gmail.com",
            "password": "app-password", # Mocked
            "from_email": "your-email@gmail.com",
            "from_name": "Sampath Velupula",
            "batch_size": 10,
            "rate_limit_per_minute": 5
        }
    ]

    def get(self, resource_id: int) -> Optional[Dict[str, Any]]:
        return next((item for item in self.MOCK_DATA if item["id"] == resource_id), None)

    def list(self, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        return self.MOCK_DATA
