"""
senders/sendgrid_sender.py
──────────────────────────
SendGrid v3 REST API email sender using httpx.AsyncClient.
Classifies SendGrid HTTP response status codes into transient vs permanent delivery errors.
"""

import httpx
import logging
from typing import Dict, Any, Optional

from .base_sender import BaseSender, TransientDeliveryError, PermanentDeliveryError

logger = logging.getLogger("outreach_service")

class SendGridSender(BaseSender):
    API_URL = "https://api.sendgrid.com/v3/mail/send"

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get("api_key")
        self.from_email = config.get("from_email")
        self.from_name = config.get("from_name")
        if not self.api_key:
            raise ValueError("SendGrid requires 'api_key'")

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
        clean_from_email = (from_email or self.from_email).strip()
        clean_to_email = to_email.strip()
        display_name = from_name or self.from_name

        payload: Dict[str, Any] = {
            "personalizations": [
                {
                    "to": [{"email": clean_to_email}],
                    "subject": subject
                }
            ],
            "from": {
                "email": clean_from_email
            }
        }
        if display_name:
            payload["from"]["name"] = display_name

        if reply_to:
            payload["reply_to"] = {"email": reply_to.strip()}

        content_list = []
        if text_body:
            content_list.append({"type": "text/plain", "value": text_body})
        if html_body:
            content_list.append({"type": "text/html", "value": html_body})
        elif not text_body:
            content_list.append({"type": "text/plain", "value": ""})

        payload["content"] = content_list

        if headers:
            payload["headers"] = headers

        req_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(self.API_URL, json=payload, headers=req_headers)
                
                # SendGrid returns 202 Accepted on success
                if resp.status_code in (200, 202):
                    logger.info(f"[SendGrid] Successfully sent email to {clean_to_email}")
                    return True

                status = resp.status_code
                error_body = resp.text[:300]
                logger.error(f"[SendGrid] API error {status} for {clean_to_email}: {error_body}")

                if status == 429 or status >= 500:
                    raise TransientDeliveryError(f"SendGrid Transient ({status}): {error_body}")
                elif 400 <= status < 500:
                    raise PermanentDeliveryError(f"SendGrid Permanent ({status}): {error_body}")
                else:
                    raise TransientDeliveryError(f"SendGrid Unknown status ({status}): {error_body}")

        except (TransientDeliveryError, PermanentDeliveryError):
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            logger.warning(f"[SendGrid] Network/Timeout error sending to {clean_to_email}: {e}")
            raise TransientDeliveryError(f"SendGrid Connection/Timeout: {e}") from e
        except Exception as e:
            logger.error(f"[SendGrid] Unexpected error sending to {clean_to_email}: {e}")
            raise TransientDeliveryError(f"SendGrid Unexpected: {e}") from e
