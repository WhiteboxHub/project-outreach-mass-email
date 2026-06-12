"""
senders/mock_senders.py
────────────────────────
Stub senders for non-SMTP providers (Mailgun, SendGrid, AWS SES).
These are placeholders — production traffic uses SMTPSender.
They log the send attempt but do not actually deliver the email.
"""

from .base_sender import BaseSender
from typing import Dict, Any
import logging

logger = logging.getLogger("outreach_service")


class MailgunSender(BaseSender):
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    async def send(self, from_email, to_email, subject, html_body,
                   text_body=None, from_name=None, reply_to=None, headers=None) -> bool:
        logger.warning(
            f"[Mailgun] Stub sender — not configured for production. "
            f"To: {to_email}"
        )
        return False


class SendGridSender(BaseSender):
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    async def send(self, from_email, to_email, subject, html_body,
                   text_body=None, from_name=None, reply_to=None, headers=None) -> bool:
        logger.warning(
            f"[SendGrid] Stub sender — not configured for production. "
            f"To: {to_email}"
        )
        return False


class AWSSESSender(BaseSender):
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    async def send(self, from_email, to_email, subject, html_body,
                   text_body=None, from_name=None, reply_to=None, headers=None) -> bool:
        logger.warning(
            f"[AWS SES] Stub sender — not configured for production. "
            f"To: {to_email}"
        )
        return False
