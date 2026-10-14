"""
campaigns/sequence_manager.py
─────────────────────────────
Orchestrates multi-step outreach sequences with automated stop conditions.
Automatically terminates remaining sequence steps when a recipient replies,
unsubscribes, bounces, or converts.
"""

import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from job_queue.durable_job_queue import DurableJobQueue

logger = logging.getLogger("outreach_service")

class SequenceStepModel(BaseModel):
    step_id: Optional[str] = None
    step_number: int
    delay_days: int
    template_id: Optional[int] = None
    subject: Optional[str] = None
    body_template: Optional[str] = None

class CampaignSequenceModel(BaseModel):
    sequence_id: str
    workflow_id: int
    name: str
    steps: List[SequenceStepModel] = Field(default_factory=list)
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.now)

class CampaignSequenceManager:
    def __init__(self, queue: Optional[DurableJobQueue] = None):
        self.queue = queue or DurableJobQueue()

    def create_sequence(self, workflow_id: int, name: str, steps: List[SequenceStepModel]) -> str:
        """Creates a campaign sequence with declared follow-up steps."""
        seq_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        with self.queue._lock, self.queue._get_connection() as conn:
            conn.execute("""
                INSERT INTO campaign_sequences (sequence_id, workflow_id, name, status, created_at)
                VALUES (?, ?, ?, 'active', ?)
            """, (seq_id, workflow_id, name, now))

            for step in steps:
                st_id = step.step_id or str(uuid.uuid4())
                conn.execute("""
                    INSERT INTO sequence_steps (step_id, sequence_id, step_number, delay_days, template_id, subject, body_template)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (st_id, seq_id, step.step_number, step.delay_days, step.template_id, step.subject, step.body_template))

            conn.commit()

        logger.info(f"[SequenceManager] Created Sequence {seq_id} ('{name}') with {len(steps)} steps.")
        return seq_id

    def enroll_recipients(self, sequence_id: str, emails: List[str]) -> int:
        """Enrolls a batch of recipients into step 1 of the sequence."""
        if not emails:
            return 0
        
        now = datetime.now().isoformat()
        records = []
        for e in emails:
            norm = e.strip().lower()
            recip_id = str(uuid.uuid4())
            records.append((recip_id, sequence_id, norm, 1, 'in_progress', None, now))

        with self.queue._lock, self.queue._get_connection() as conn:
            conn.executemany("""
                INSERT OR IGNORE INTO sequence_recipients (
                    recipient_id, sequence_id, recipient_email, current_step, status, stop_reason, last_sent_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, records)
            conn.commit()

        logger.info(f"[SequenceManager] Enrolled {len(records)} recipients into sequence {sequence_id}")
        return len(records)

    def handle_stop_condition(self, recipient_email: str, trigger_event: str) -> int:
        """
        Stop Condition Enforcement:
        If a recipient replies, unsubscribes, bounces, or converts,
        all active sequences for that recipient are immediately halted.
        """
        norm_email = recipient_email.strip().lower()
        valid_stop_triggers = ("reply", "positive_reply", "bounce", "complaint", "unsubscribe", "conversion")
        
        if trigger_event.lower() not in valid_stop_triggers:
            return 0

        with self.queue._lock, self.queue._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sequence_recipients
                SET status = 'stopped', stop_reason = ?
                WHERE recipient_email = ? AND status = 'in_progress'
            """, (f"Stopped by {trigger_event}", norm_email))
            conn.commit()
            stopped_count = cursor.rowcount

        if stopped_count > 0:
            logger.info(f"[SequenceManager] STOP CONDITION APPLIED: Halted {stopped_count} sequence(s) for {norm_email} (Event: {trigger_event})")
        return stopped_count

    def get_due_recipients_for_step(self, sequence_id: str, step_number: int) -> List[Dict[str, Any]]:
        """
        Returns recipients who are in_progress, on step_number, and whose delay_days have elapsed.
        """
        with self.queue._lock, self.queue._get_connection() as conn:
            cursor = conn.cursor()
            # Fetch step delay
            cursor.execute("""
                SELECT delay_days FROM sequence_steps
                WHERE sequence_id = ? AND step_number = ?
            """, (sequence_id, step_number))
            row = cursor.fetchone()
            if not row:
                return []
            delay_days = row["delay_days"]

            cursor.execute("""
                SELECT recipient_id, recipient_email, current_step, last_sent_at
                FROM sequence_recipients
                WHERE sequence_id = ? AND current_step = ? AND status = 'in_progress'
            """, (sequence_id, step_number))
            recipients = cursor.fetchall()

            due = []
            now = datetime.now()
            for r in recipients:
                last_sent = datetime.fromisoformat(r["last_sent_at"]) if r["last_sent_at"] else now
                if now >= last_sent + timedelta(days=delay_days) or step_number == 1:
                    due.append({
                        "recipient_id": r["recipient_id"],
                        "recipient_email": r["recipient_email"],
                        "current_step": r["current_step"]
                    })
            return due

    def advance_recipient_step(self, recipient_id: str, next_step: int, last_sent_at: Optional[str] = None):
        now = last_sent_at or datetime.now().isoformat()
        with self.queue._lock, self.queue._get_connection() as conn:
            conn.execute("""
                UPDATE sequence_recipients
                SET current_step = ?, last_sent_at = ?
                WHERE recipient_id = ?
            """, (next_step, now, recipient_id))
            conn.commit()
