"""
senders/ses_sender.py
─────────────────────
AWS SES email delivery sender using boto3 SES client.
Classifies AWS SES exceptions into TransientDeliveryError vs PermanentDeliveryError.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError, BotoCoreError

from .base_sender import BaseSender, TransientDeliveryError, PermanentDeliveryError

logger = logging.getLogger("outreach_service")

class AWSSESSender(BaseSender):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.from_email = config.get("from_email")
        self.region_name = config.get("region_name") or config.get("aws_region", "us-east-1")
        self.aws_access_key_id = config.get("aws_access_key_id") or config.get("username")
        self.aws_secret_access_key = config.get("aws_secret_access_key") or config.get("password")
        self._client = None

    def _get_client(self):
        if self._client is None:
            kwargs = {"region_name": self.region_name}
            if self.aws_access_key_id and self.aws_secret_access_key:
                kwargs["aws_access_key_id"] = self.aws_access_key_id
                kwargs["aws_secret_access_key"] = self.aws_secret_access_key
            self._client = boto3.client("ses", **kwargs)
        return self._client

    def _send_sync(
        self,
        from_email: str,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> bool:
        client = self._get_client()
        source = f"{from_name} <{from_email}>" if from_name else from_email
        
        body_dict: Dict[str, Any] = {}
        if html_body:
            body_dict["Html"] = {"Charset": "UTF-8", "Data": html_body}
        if text_body:
            body_dict["Text"] = {"Charset": "UTF-8", "Data": text_body}
        elif not html_body:
            body_dict["Text"] = {"Charset": "UTF-8", "Data": ""}

        destination = {"ToAddresses": [to_email.strip()]}
        message = {
            "Subject": {"Charset": "UTF-8", "Data": subject},
            "Body": body_dict
        }

        kwargs: Dict[str, Any] = {
            "Source": source,
            "Destination": destination,
            "Message": message
        }
        if reply_to:
            kwargs["ReplyToAddresses"] = [reply_to.strip()]

        try:
            resp = client.send_email(**kwargs)
            message_id = resp.get("MessageId")
            logger.info(f"[AWS SES] Successfully sent email to {to_email} (MessageId: {message_id})")
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            msg = e.response.get("Error", {}).get("Message", str(e))
            logger.error(f"[AWS SES] ClientError ({code}) sending to {to_email}: {msg}")
            
            # Transient error codes (Throttling, service issues)
            if code in ("ThrottlingException", "Throttling", "ServiceUnavailable", "RequestExpired"):
                raise TransientDeliveryError(f"AWS SES Transient [{code}]: {msg}") from e
            # Permanent error codes (Account suspended, bad email address, unverified identity)
            elif code in ("MessageRejected", "MailboxDoesNotExist", "AccountSendingPausedException", "ConfigurationSetDoesNotExist"):
                raise PermanentDeliveryError(f"AWS SES Permanent [{code}]: {msg}") from e
            else:
                raise PermanentDeliveryError(f"AWS SES Error [{code}]: {msg}") from e
        except (BotoCoreError, TimeoutError, OSError) as e:
            logger.warning(f"[AWS SES] Transient connection/network error sending to {to_email}: {e}")
            raise TransientDeliveryError(f"AWS SES Network Error: {e}") from e
        except Exception as e:
            logger.error(f"[AWS SES] Unexpected failure sending to {to_email}: {e}")
            raise TransientDeliveryError(f"AWS SES Unexpected Error: {e}") from e

    async def send(
        self,
        from_email: str,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> bool:
        return await asyncio.to_thread(
            self._send_sync,
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            from_name=from_name,
            reply_to=reply_to,
            headers=headers
        )
