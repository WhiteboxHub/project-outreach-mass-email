"""
inbox/event_handler.py
──────────────────────
Normalizes and processes webhook delivery events from SendGrid, Mailgun, and AWS SES.
Enforces automatic suppression on hard bounces, spam complaints, and unsubscribe events.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from utils.idempotency import RecipientIdempotencyLedger
from job_queue.durable_job_queue import DurableJobQueue

logger = logging.getLogger("outreach_service")

class NormalizedEmailEvent(BaseModel):
    event_id: str
    provider: str
    event_type: str  # bounce, complaint, unsubscribe, delivered, reply, dropped
    recipient_email: str
    reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    raw_payload: Dict[str, Any] = Field(default_factory=dict)

class WebhookEventHandler:
    def __init__(self, queue: Optional[DurableJobQueue] = None):
        self.queue = queue or DurableJobQueue()
        self.ledger = RecipientIdempotencyLedger()

    def process_sendgrid_events(self, events: List[Dict[str, Any]]) -> List[NormalizedEmailEvent]:
        """
        Processes SendGrid Event Webhook JSON list.
        Events: bounce, dropped, spamreport, unsubscribe, delivered, open, click.
        """
        normalized: List[NormalizedEmailEvent] = []
        for ev in events:
            ev_type = ev.get("event", "unknown").lower()
            email = (ev.get("email") or "").strip().lower()
            sg_id = str(ev.get("sg_event_id") or ev.get("sg_message_id") or "")
            reason = ev.get("reason") or ev.get("status")

            if not email:
                continue

            mapped_type = "other"
            if ev_type in ("bounce", "dropped"):
                mapped_type = "bounce"
            elif ev_type in ("spamreport",):
                mapped_type = "complaint"
            elif ev_type in ("unsubscribe", "group_unsubscribe"):
                mapped_type = "unsubscribe"
            elif ev_type == "delivered":
                mapped_type = "delivered"

            norm_ev = NormalizedEmailEvent(
                event_id=sg_id or f"sg_{datetime.now().timestamp()}",
                provider="sendgrid",
                event_type=mapped_type,
                recipient_email=email,
                reason=str(reason) if reason else None,
                timestamp=datetime.now(),
                raw_payload=ev
            )
            self._handle_normalized_event(norm_ev)
            normalized.append(norm_ev)

        return normalized

    def process_mailgun_events(self, payload: Dict[str, Any]) -> List[NormalizedEmailEvent]:
        """
        Processes Mailgun Event Webhook JSON.
        Format: {"event-data": {"event": "failed|complained|unsubscribed|delivered", "recipient": "...", "reason": "..."}}
        """
        normalized: List[NormalizedEmailEvent] = []
        ev_data = payload.get("event-data") or payload
        ev_type = (ev_data.get("event") or "").lower()
        email = (ev_data.get("recipient") or "").strip().lower()
        mg_id = str(ev_data.get("id") or "")
        
        reason = None
        delivery_status = ev_data.get("delivery-status", {})
        if delivery_status:
            reason = delivery_status.get("description") or delivery_status.get("message")

        if not email:
            return normalized

        mapped_type = "other"
        if ev_type in ("failed", "rejected"):
            mapped_type = "bounce"
        elif ev_type == "complained":
            mapped_type = "complaint"
        elif ev_type == "unsubscribed":
            mapped_type = "unsubscribe"
        elif ev_type == "delivered":
            mapped_type = "delivered"

        norm_ev = NormalizedEmailEvent(
            event_id=mg_id or f"mg_{datetime.now().timestamp()}",
            provider="mailgun",
            event_type=mapped_type,
            recipient_email=email,
            reason=str(reason) if reason else None,
            timestamp=datetime.now(),
            raw_payload=payload
        )
        self._handle_normalized_event(norm_ev)
        normalized.append(norm_ev)
        return normalized

    def process_ses_sns_notification(self, payload: Dict[str, Any]) -> List[NormalizedEmailEvent]:
        """
        Processes AWS SES SNS Notification (Bounce, Complaint, Delivery).
        """
        normalized: List[NormalizedEmailEvent] = []
        # Check if wrapped in SNS 'Message'
        msg_str = payload.get("Message")
        if msg_str and isinstance(msg_str, str):
            try:
                data = json.loads(msg_str)
            except Exception:
                data = payload
        else:
            data = payload

        notif_type = (data.get("notificationType") or data.get("eventType") or "").lower()
        mail = data.get("mail", {})
        destinations = mail.get("destination", [])

        if notif_type == "bounce":
            bounce = data.get("bounce", {})
            bounced_recips = bounce.get("bouncedRecipients", [])
            for r in bounced_recips:
                email = (r.get("emailAddress") or "").strip().lower()
                diag = r.get("diagnosticCode") or bounce.get("bounceType")
                norm_ev = NormalizedEmailEvent(
                    event_id=f"ses_b_{datetime.now().timestamp()}",
                    provider="aws_ses",
                    event_type="bounce",
                    recipient_email=email,
                    reason=diag,
                    timestamp=datetime.now(),
                    raw_payload=data
                )
                self._handle_normalized_event(norm_ev)
                normalized.append(norm_ev)

        elif notif_type == "complaint":
            comp = data.get("complaint", {})
            comp_recips = comp.get("complainedRecipients", [])
            for r in comp_recips:
                email = (r.get("emailAddress") or "").strip().lower()
                norm_ev = NormalizedEmailEvent(
                    event_id=f"ses_c_{datetime.now().timestamp()}",
                    provider="aws_ses",
                    event_type="complaint",
                    recipient_email=email,
                    reason=comp.get("complaintFeedbackType"),
                    timestamp=datetime.now(),
                    raw_payload=data
                )
                self._handle_normalized_event(norm_ev)
                normalized.append(norm_ev)

        elif notif_type == "delivery":
            for d in destinations:
                email = d.strip().lower()
                norm_ev = NormalizedEmailEvent(
                    event_id=f"ses_d_{datetime.now().timestamp()}",
                    provider="aws_ses",
                    event_type="delivered",
                    recipient_email=email,
                    timestamp=datetime.now(),
                    raw_payload=data
                )
                self._handle_normalized_event(norm_ev)
                normalized.append(norm_ev)

        return normalized

    def _handle_normalized_event(self, event: NormalizedEmailEvent):
        """
        Applies business logic for a normalized event:
        - Adds bounce, complaint, unsubscribe to suppression ledger and durable database table.
        - Persists event in durable database for audit trail.
        """
        # 1. Enforce automatic suppression
        if event.event_type in ("bounce", "complaint", "unsubscribe"):
            logger.warning(
                f"[WebhookEventHandler] Auto-suppressing {event.recipient_email} "
                f"(Event: {event.event_type}, Reason: {event.reason})"
            )
            self.ledger.add_suppression(event.recipient_email)
            try:
                self.queue.add_suppressed_email(
                    email=event.recipient_email,
                    reason=f"{event.event_type}: {event.reason or 'webhook'}",
                    source=event.provider
                )
            except Exception as e:
                logger.error(f"[WebhookEventHandler] Failed to store suppression in DB: {e}")

        # 2. Persist event in durable database
        try:
            self.queue.record_inbox_event(
                event_id=event.event_id,
                provider=event.provider,
                event_type=event.event_type,
                recipient_email=event.recipient_email,
                reason=event.reason,
                payload=event.raw_payload
            )
        except Exception as e:
            logger.error(f"[WebhookEventHandler] Failed to persist inbox event: {e}")
