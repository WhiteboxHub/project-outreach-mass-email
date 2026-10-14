"""
campaigns/outcome_analytics.py
──────────────────────────────
Tracks, aggregates, and computes business outcome analytics:
- Deliveries, Bounces, Complaints
- Replies & Positive Recruiter Responses
- Meetings Scheduled & Placements Influenced
- Conversion ROI and performance funnel
"""

import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from job_queue.durable_job_queue import DurableJobQueue

logger = logging.getLogger("outreach_service")

class OutcomeReport(BaseModel):
    workflow_id: Optional[int] = None
    sent: int
    delivered: int
    bounced: int
    replies: int
    positive_replies: int
    meetings: int
    placements: int
    delivery_rate_pct: float
    reply_rate_pct: float
    positive_reply_rate_pct: float
    meeting_conversion_rate_pct: float

class OutcomeAnalyticsService:
    def __init__(self, queue: Optional[DurableJobQueue] = None):
        self.queue = queue or DurableJobQueue()

    def record_event(self, workflow_id: int, event_type: str, count: int = 1):
        """Records an outcome event into the persistent outcome metrics store."""
        self.queue.record_outcome_event(workflow_id, event_type, count)

    def get_funnel_report(self, workflow_id: Optional[int] = None) -> OutcomeReport:
        """Retrieves and calculates outcome funnel performance metrics."""
        raw = self.queue.get_outcome_metrics(workflow_id)
        
        sent = raw.get("sent", 0)
        delivered = raw.get("delivered", 0)
        bounced = raw.get("bounced", 0)
        replies = raw.get("replies", 0)
        pos_replies = raw.get("positive_replies", 0)
        meetings = raw.get("meetings", 0)
        placements = raw.get("placements", 0)

        delivery_rate = (delivered / sent * 100.0) if sent > 0 else 0.0
        reply_rate = (replies / delivered * 100.0) if delivered > 0 else 0.0
        pos_reply_rate = (pos_replies / replies * 100.0) if replies > 0 else 0.0
        meeting_conv_rate = (meetings / pos_replies * 100.0) if pos_replies > 0 else 0.0

        return OutcomeReport(
            workflow_id=workflow_id,
            sent=sent,
            delivered=delivered,
            bounced=bounced,
            replies=replies,
            positive_replies=pos_replies,
            meetings=meetings,
            placements=placements,
            delivery_rate_pct=round(delivery_rate, 2),
            reply_rate_pct=round(reply_rate, 2),
            positive_reply_rate_pct=round(pos_reply_rate, 2),
            meeting_conversion_rate_pct=round(meeting_conv_rate, 2)
        )
