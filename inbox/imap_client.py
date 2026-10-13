"""
inbox/imap_client.py
────────────────────
Provider-agnostic IMAP client for candidate inboxes (Gmail, Outlook, custom IMAP).
Fetches and classifies incoming messages, detecting human replies, out-of-office auto-replies,
and bounce notifications with thread header matching.
"""

import imaplib
import email
from email.header import decode_header
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

logger = logging.getLogger("outreach_service")

class ParsedInboxReply(BaseModel):
    sender_email: str
    recipient_email: str
    subject: str
    message_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    reply_type: str = "human_reply"  # human_reply, auto_reply, bounce
    body_snippet: str = ""
    received_at: datetime = Field(default_factory=datetime.now)

class IMAPReplyPoller:
    def __init__(self, host: str, port: int = 993, username: str = "", password: str = "", use_ssl: bool = True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl

    def _decode_str(self, header_value: Any) -> str:
        if not header_value:
            return ""
        decoded_list = decode_header(header_value)
        parts = []
        for text, encoding in decoded_list:
            if isinstance(text, bytes):
                try:
                    parts.append(text.decode(encoding or "utf-8", errors="replace"))
                except Exception:
                    parts.append(text.decode("utf-8", errors="replace"))
            else:
                parts.append(str(text))
        return "".join(parts)

    def _classify_message(self, from_addr: str, subject: str, body: str) -> str:
        sub_lower = subject.lower()
        body_lower = body.lower()
        from_lower = from_addr.lower()

        # Check bounce
        if any(w in sub_lower for w in ["delivery status notification", "failure notice", "undeliverable", "returned to sender"]) or \
           any(w in from_lower for w in ["mailer-daemon", "postmaster"]):
            return "bounce"

        # Check auto-reply / out of office
        if any(w in sub_lower for w in ["out of office", "automatic reply", "autoreply", "vacation"]) or \
           any(w in body_lower[:200] for w in ["out of office", "auto-generated", "automated response"]):
            return "auto_reply"

        return "human_reply"

    def _extract_body(self, msg: email.message.Message) -> str:
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdispo = str(part.get("Content-Disposition"))
                if ctype == "text/plain" and "attachment" not in cdispo:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        return payload.decode(charset, errors="replace")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return body

    def fetch_replies_sync(self, folder: str = "INBOX", limit: int = 50, days_back: int = 2) -> List[ParsedInboxReply]:
        """Synchronously connects to IMAP, searches recent messages, and parses replies."""
        results: List[ParsedInboxReply] = []
        mail = None
        try:
            if self.use_ssl:
                mail = imaplib.IMAP4_SSL(self.host, self.port)
            else:
                mail = imaplib.IMAP4(self.host, self.port)

            mail.login(self.username, self.password)
            mail.select(folder, readonly=True)

            since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
            status, search_data = mail.search(None, f'(SINCE "{since_date}")')
            
            if status != "OK" or not search_data or not search_data[0]:
                return results

            msg_ids = search_data[0].split()
            # Most recent first
            msg_ids = msg_ids[-limit:][::-1]

            for mid in msg_ids:
                res, data = mail.fetch(mid, "(RFC822)")
                if res != "OK" or not data:
                    continue
                raw_email = data[0][1]
                msg = email.message_from_bytes(raw_email)

                from_addr = self._decode_str(msg.get("From", ""))
                to_addr = self._decode_str(msg.get("To", ""))
                subject = self._decode_str(msg.get("Subject", ""))
                msg_id = msg.get("Message-ID", "")
                in_reply_to = msg.get("In-Reply-To", "")
                references = msg.get("References", "")
                body_text = self._extract_body(msg)

                reply_type = self._classify_message(from_addr, subject, body_text)

                # Parse clean email address
                import re
                sender_match = re.search(r'[\w\.-]+@[\w\.-]+', from_addr)
                clean_sender = sender_match.group(0).lower() if sender_match else from_addr.strip().lower()

                results.append(ParsedInboxReply(
                    sender_email=clean_sender,
                    recipient_email=self.username,
                    subject=subject,
                    message_id=msg_id,
                    in_reply_to=in_reply_to,
                    references=references,
                    reply_type=reply_type,
                    body_snippet=body_text[:300].strip(),
                    received_at=datetime.now()
                ))

            return results
        except Exception as e:
            logger.error(f"[IMAP] Error polling inbox {self.username}@{self.host}: {e}")
            return results
        finally:
            if mail:
                try:
                    mail.logout()
                except Exception:
                    pass

    async def fetch_replies(self, folder: str = "INBOX", limit: int = 50, days_back: int = 2) -> List[ParsedInboxReply]:
        """Asynchronously executes fetch_replies_sync in thread pool."""
        return await asyncio.to_thread(self.fetch_replies_sync, folder=folder, limit=limit, days_back=days_back)
