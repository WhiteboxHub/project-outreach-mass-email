import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
import logging
from senders.base_sender import BaseSender

logger = logging.getLogger(__name__)

class SMTPSender(BaseSender):
    def __init__(self, credentials: dict):
        self.host = credentials.get("host")
        self.port = credentials.get("port", 587)
        self.username = credentials.get("username")
        self.password = credentials.get("password")
        self.use_tls = credentials.get("use_tls", True)

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
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_email
            msg["To"] = to_email
            msg["Reply-To"] = reply_to
            
            if headers:
                for key, value in headers.items():
                    msg.add_header(key, value)

            # --- Anti-Spam / Deliverability Headers ---
            msg.add_header("X-Priority", "3")  # 3 = Normal priority (avoid 1/High which flags spam)
            msg.add_header("X-Mailer", "WBL-Mailer-v1") # Identify the mailer cleanly
            # Most important: Ensure 'To' is strictly just the email address to avoid aliases triggering filters
            del msg['To']
            msg.add_header('To', to_email) 

            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(self.host, self.port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.username, self.password)
                server.sendmail(from_email, [to_email], msg.as_string())  # envelope recipient is strictly the primary email
            
            return True
        except Exception as e:
            logger.error(f"SMTP send failed: {e}")
            return False
