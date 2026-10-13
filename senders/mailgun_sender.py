"""
senders/mailgun_sender.py
─────────────────────────
Mailgun v3 REST API email sender using httpx.AsyncClient.
Classifies Mailgun response status codes into transient vs permanent delivery errors.
"""

import httpx
import logging
from typing import Dict, Any, Optional

from .base_sender import BaseSender, TransientDeliveryError, PermanentDeliveryError

logger = logging.getLogger("outreach_service")

class MailgunSender(BaseSender):
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get("api_key")
        self.domain = config.get("domain") or config.get("mailgun_domain")
        self.from_email = config.get("from_email")
        self.from_name = config.get("from_name")
        self.region = config.get("region", "us").lower()
        
        if not self.api_key:
            raise ValueError("Mailgun requires 'api_key'")

        # If domain isn't explicitly provided, infer from from_email
        if not self.domain and self.from_email and "@" in self.from_email:
            self.domain = self.from_email.split("@")[1]

        base_host = "api.eu.mailgun.net" if self.region == "eu" else "api.mailgun.net"
        self.api_url = f"https://{base_host}/v3/{self.domain}/messages"

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

        from_field = f"{display_name} <{clean_from_email}>" if display_name else clean_from_email

        data = {
            "from": from_field,
            "to": clean_to_email,
            "subject": subject,
        }
        if html_body:
            data["html"] = html_body
        if text_body:
            data["text"] = text_body
        if reply_to:
            data["h:Reply-To"] = reply_to.strip()

        if headers:
            for k, v in headers.items():
                data[f"h:{k}"] = v

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    self.api_url,
                    data=data,
                    auth=("api", self.api_key)
                )

                if resp.status_code == 200:
                    logger.info(f"[Mailgun] Successfully sent email to {clean_to_email}")
                    return True

                status = resp.status_code
                error_body = resp.text[:300]
                logger.error(f"[Mailgun] API error {status} for {clean_to_email}: {error_body}")

                if status == 429 or status >= 500:
                    raise TransientDeliveryError(f"Mailgun Transient ({status}): {error_body}")
                elif 400 <= status < 500:
                    raise PermanentDeliveryError(f"Mailgun Permanent ({status}): {error_body}")
                else:
                    raise TransientDeliveryError(f"Mailgun Unknown status ({status}): {error_body}")

        except (TransientDeliveryError, PermanentDeliveryError):
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            logger.warning(f"[Mailgun] Network/Timeout error sending to {clean_to_email}: {e}")
            raise TransientDeliveryError(f"Mailgun Connection/Timeout: {e}") from e
        except Exception as e:
            logger.error(f"[Mailgun] Unexpected error sending to {clean_to_email}: {e}")
            raise TransientDeliveryError(f"Mailgun Unexpected: {e}") from e
