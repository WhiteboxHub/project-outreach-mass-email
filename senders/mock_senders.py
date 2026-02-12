from .base_sender import BaseSender
from typing import Dict, Any
import logging

logger = logging.getLogger("outreach_service")

class MockSender(BaseSender):
    def __init__(self, provider_name: str, config: Dict[str, Any]):
        self.provider_name = provider_name
        self.config = config

    async def send(self, from_email, to_email, subject, html_body, text_body=None, from_name=None, reply_to=None, headers=None) -> bool:
        logger.info(f"[{self.provider_name}] Sending email...")
        logger.info(f"   From: {from_name} <{from_email}>")
        logger.info(f"   To: {to_email}")
        logger.info(f"   Subject: {subject}")
        # Simulate network latency
        import asyncio
        await asyncio.sleep(0.1) 
        return True

class SMTPSender(MockSender):
    def __init__(self, config):
        super().__init__("SMTP", config)

class MailgunSender(MockSender):
    def __init__(self, config):
        super().__init__("Mailgun", config)

class SendGridSender(MockSender):
    def __init__(self, config):
        super().__init__("SendGrid", config)

class AWSSESSender(MockSender):
    def __init__(self, config):
        super().__init__("AWS_SES", config)
