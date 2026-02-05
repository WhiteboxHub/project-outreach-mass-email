import requests
import logging
from typing import Optional
from senders.base_sender import BaseSender

logger = logging.getLogger(__name__)

class SendGridSender(BaseSender):
    def __init__(self, credentials: dict):
        self.api_key = credentials.get("api_key")
        self.url = "https://api.sendgrid.com/v3/mail/send"

    def send(
        self,
        from_email: str,
        reply_to: str,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        headers: Optional[dict] = None
    ) -> bool:
        payload = {
            "personalizations": [{
                "to": [{"email": to_email}],
                "headers": headers or {}
            }],
            "from": {"email": from_email},
            "reply_to": {"email": reply_to},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text_body},
                {"type": "text/html", "value": html_body}
            ]
        }
        
        auth_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(self.url, json=payload, headers=auth_headers)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"SendGrid send failed: {e}")
            return False
