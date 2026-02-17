import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Dict, Any
import logging
import asyncio
from .base_sender import BaseSender

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
            
            if from_name:
                msg["From"] = f"{from_name} <{from_email}>"
            else:
                msg["From"] = from_email
                
            msg["To"] = to_email
            if reply_to:
                msg["Reply-To"] = reply_to
            
            if headers:
                for key, value in headers.items():
                    msg.add_header(key, value)

            # Deliverability Headers
            msg.add_header("X-Priority", "3")
            msg.add_header("X-Mailer", "WBL-Outreach-v1")

            if text_body:
                msg.attach(MIMEText(text_body, "plain"))
            if html_body:
                msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.sendmail(from_email, [to_email], msg.as_string())
            
            return True
        except Exception as e:
            logger.error(f"SMTP send failed to {to_email}: {e}")
            return False
