import requests
import logging
from .base_sender import BaseSender

logger = logging.getLogger(__name__)

class MailgunSender(BaseSender):
    def __init__(self, credentials_json: dict):
        self.domain = credentials_json.get("domain")
        self.api_key = credentials_json.get("api_key")
        self.api_url = f"https://api.mailgun.net/v3/{self.domain}/messages"
        
        if not self.domain or not self.api_key:
            raise ValueError("Mailgun requires 'domain' and 'api_key' in credentials")

    def send(self, from_email: str, reply_to: str, to_email: str, subject: str, 
             html_body: str, text_body: str, headers: dict = None, from_name: str = None):
        """
        Send email via Mailgun API
        
        Args:
            from_email: The email address to send from (e.g., outreach@domain.com)
            reply_to: The reply-to email address (typically candidate's email)
            to_email: Recipient email
            subject: Email subject
            html_body: HTML version of email
            text_body: Plain text version
            headers: Optional custom headers
            from_name: Optional name to display in From field (e.g., "John Doe")
        """
        try:
            # Format the From field with name if provided
            if from_name:
                from_field = f"{from_name} <{from_email}>"
            else:
                from_field = from_email
            
            data = {
                "from": from_field,
                "to": to_email,
                "subject": subject,
                "text": text_body,
                "html": html_body,
            }
            
            if reply_to:
                data["h:Reply-To"] = reply_to
            
            if headers:
                for key, value in headers.items():
                    data[f"h:{key}"] = value
            
            response = requests.post(
                self.api_url,
                auth=("api", self.api_key),
                data=data,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f"Mailgun email sent to {to_email}")
                return True
            else:
                logger.error(f"Mailgun error: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Mailgun send failed: {e}")
            return False
