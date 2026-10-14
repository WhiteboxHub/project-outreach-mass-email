import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Dict, Any
import logging
import asyncio
from .base_sender import BaseSender, TransientDeliveryError, PermanentDeliveryError
import socket

logger = logging.getLogger("outreach_service")

class SMTPSender(BaseSender):
    def __init__(self, config: Dict[str, Any]):
        self.host = config.get("host")
        self.port = config.get("port", 587)
        self.username = config.get("username")
        self.password = config.get("password")
        self.use_tls = config.get("use_tls", True)

    async def send(
        self,
        from_email: str,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str = None,
        from_name: str = None,
        reply_to: str = None,
        headers: Dict[str, str] = None
    ) -> bool:
        # Wrap synchronous SMTP in a thread to keep the service responsive
        return await asyncio.to_thread(
            self._send_sync,
            from_email,
            to_email,
            subject,
            html_body,
            text_body,
            from_name,
            reply_to,
            headers
        )

    def _send_sync(
        self,
        from_email: str,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str = None,
        from_name: str = None,
        reply_to: str = None,
        headers: Dict[str, str] = None
    ) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            
            clean_from_email = from_email.strip() if from_email else ""
            clean_to_email = to_email.strip() if to_email else ""

            if from_name:
                msg["From"] = f"{from_name.strip()} <{clean_from_email}>"
            else:
                msg["From"] = clean_from_email
                
            msg["To"] = clean_to_email
            if reply_to:
                msg["Reply-To"] = reply_to
            
            if headers:
                for key, value in headers.items():
                    msg.add_header(key, value)

            if text_body:
                msg.attach(MIMEText(text_body, "plain"))
            if html_body:
                msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.sendmail(clean_from_email, [clean_to_email], msg.as_string())
            
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"Permanent SMTP Auth failure for {self.username}: {e}")
            raise PermanentDeliveryError(f"SMTP Auth failed: {e}") from e
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as e:
            logger.error(f"Permanent SMTP address refusal for {to_email}: {e}")
            raise PermanentDeliveryError(f"SMTP address refused: {e}") from e
        except smtplib.SMTPResponseException as e:
            if 400 <= e.smtp_code < 500:
                logger.warning(f"Transient SMTP error {e.smtp_code} for {to_email}: {e.smtp_error}")
                raise TransientDeliveryError(f"Transient SMTP {e.smtp_code}: {e.smtp_error}") from e
            else:
                logger.error(f"Permanent SMTP error {e.smtp_code} for {to_email}: {e.smtp_error}")
                raise PermanentDeliveryError(f"Permanent SMTP {e.smtp_code}: {e.smtp_error}") from e
        except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, socket.timeout, OSError) as e:
            logger.warning(f"Transient connection error sending to {to_email}: {e}")
            raise TransientDeliveryError(f"Connection/Timeout: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected SMTP error sending to {to_email}: {e}")
            raise TransientDeliveryError(f"Unexpected error: {e}") from e
