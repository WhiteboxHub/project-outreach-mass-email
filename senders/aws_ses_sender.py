import logging
from typing import Optional
from senders.base_sender import BaseSender

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None

logger = logging.getLogger(__name__)

class AWSSESSender(BaseSender):
    def __init__(self, credentials: dict):
        self.region = credentials.get("region", "us-east-1")
        self.access_key = credentials.get("aws_access_key_id")
        self.secret_key = credentials.get("aws_secret_access_key")
        
        if boto3:
            self.client = boto3.client(
                'ses',
                region_name=self.region,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key
            )
        else:
            self.client = None
            logger.error("boto3 not installed. AWSSESSender will not work.")

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
        if not self.client:
            return False
            
        try:
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_email
            msg["To"] = to_email
            msg["Reply-To"] = reply_to
            
            # Anti-spam headers
            # msg.add_header("Precedence", "bulk")
            msg.add_header("X-Priority", "3")
            
            if headers:
                for key, value in headers.items():
                    # Avoid duplicate headers
                    if key not in msg:
                        msg.add_header(key, value)

            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            response = self.client.send_raw_email(
                Source=from_email,
                Destinations=[to_email],
                RawMessage={'Data': msg.as_string()}
            )
            return True
        except Exception as e:
            logger.error(f"AWS SES send failed: {e}")
            return False
