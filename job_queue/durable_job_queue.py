"""
queue/durable_job_queue.py
──────────────────────────
Durable, crash-recoverable persistent queue for Outreach Platform v2.
Backed by SQLite for transactional persistence without requiring external brokers.
"""

import sqlite3
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from threading import Lock

from models.job import JobStatus, TaskStatus, OutreachJob, RecipientTask

logger = logging.getLogger("outreach_service")

class DurableJobQueue:
    def __init__(self, db_path: str = "outreach_jobs.db"):
        self.db_path = db_path
        self._lock = Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable Write-Ahead Logging for high concurrent read/write throughput
        if self.db_path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    workflow_id INTEGER,
                    workflow_key TEXT,
                    candidate_id INTEGER,
                    status TEXT NOT NULL,
                    total_tasks INTEGER DEFAULT 0,
                    completed_tasks INTEGER DEFAULT 0,
                    failed_tasks INTEGER DEFAULT 0,
                    parameters_json TEXT,
                    error_summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recipient_tasks (
                    task_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    recipient_email TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER DEFAULT 0,
                    error TEXT,
                    context_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_job_status ON recipient_tasks(job_id, status)")
            
            # Milestone C Tables: Suppression and Webhook/Inbox Events
            conn.execute("""
                CREATE TABLE IF NOT EXISTS suppression_list (
                    email TEXT PRIMARY KEY,
                    reason TEXT,
                    source TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS inbox_events (
                    event_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    recipient_email TEXT NOT NULL,
                    reason TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON inbox_events(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_email ON inbox_events(recipient_email)")

            # Milestone D Tables: Contact Reviews, Sequences, and Outcome Metrics
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contact_reviews (
                    contact_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    name TEXT,
                    title TEXT,
                    confidence_score REAL NOT NULL,
                    reasons_json TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_contacts_status ON contact_reviews(status)")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS campaign_sequences (
                    sequence_id TEXT PRIMARY KEY,
                    workflow_id INTEGER,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sequence_steps (
                    step_id TEXT PRIMARY KEY,
                    sequence_id TEXT NOT NULL,
                    step_number INTEGER NOT NULL,
                    delay_days INTEGER NOT NULL,
                    template_id INTEGER,
                    subject TEXT,
                    body_template TEXT,
                    FOREIGN KEY(sequence_id) REFERENCES campaign_sequences(sequence_id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sequence_recipients (
                    recipient_id TEXT PRIMARY KEY,
                    sequence_id TEXT NOT NULL,
                    recipient_email TEXT NOT NULL,
                    current_step INTEGER DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'in_progress',
                    stop_reason TEXT,
                    last_sent_at TEXT,
                    FOREIGN KEY(sequence_id) REFERENCES campaign_sequences(sequence_id) ON DELETE CASCADE
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS outcome_metrics (
                    metric_id TEXT PRIMARY KEY,
                    workflow_id INTEGER,
                    metric_date TEXT NOT NULL,
                    sent_count INTEGER DEFAULT 0,
                    delivered_count INTEGER DEFAULT 0,
                    bounced_count INTEGER DEFAULT 0,
                    reply_count INTEGER DEFAULT 0,
                    positive_reply_count INTEGER DEFAULT 0,
                    meeting_count INTEGER DEFAULT 0,
                    placement_count INTEGER DEFAULT 0
                )
            """)
            conn.commit()

    def enqueue_job(
        self,
        workflow_id: Optional[int] = None,
        workflow_key: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        candidate_id: Optional[int] = None,
        job_id: Optional[str] = None
    ) -> str:
        """Persists a new campaign job into the durable queue."""
        jid = job_id or str(uuid.uuid4())
        now = datetime.now().isoformat()
        params_str = json.dumps(parameters or {})

        with self._lock, self._get_connection() as conn:
            conn.execute("""
                INSERT INTO jobs (
                    job_id, workflow_id, workflow_key, candidate_id,
                    status, total_tasks, completed_tasks, failed_tasks,
                    parameters_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?, ?)
            """, (jid, workflow_id, workflow_key, candidate_id, JobStatus.QUEUED.value, params_str, now, now))
            conn.commit()

        logger.info(f"[DurableQueue] Enqueued Job {jid} (Workflow: {workflow_id or workflow_key})")
        return jid

    def add_recipient_tasks(self, job_id: str, recipients: List[Dict[str, Any]]) -> int:
        """Atomically inserts batch of recipient tasks associated with a job."""
        if not recipients:
            return 0

        now = datetime.now().isoformat()
        records = []
        for r in recipients:
            tid = str(uuid.uuid4())
            email = r.get("email") or r.get("recipient_email") or "unknown"
            ctx = json.dumps(r)
            records.append((tid, job_id, email.strip().lower(), TaskStatus.QUEUED.value, 0, ctx, now, now))

        with self._lock, self._get_connection() as conn:
            conn.executemany("""
                INSERT INTO recipient_tasks (
                    task_id, job_id, recipient_email, status, attempts, context_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, records)
            conn.execute("""
                UPDATE jobs 
                SET total_tasks = total_tasks + ?, updated_at = ?
                WHERE job_id = ?
            """, (len(records), now, job_id))
            conn.commit()

        logger.info(f"[DurableQueue] Added {len(records)} recipient tasks for Job {job_id}")
        return len(records)

    def claim_next_job(self) -> Optional[OutreachJob]:
        """Atomically claims the next pending job from the queue."""
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT job_id FROM jobs 
                WHERE status = ? 
                ORDER BY created_at ASC LIMIT 1
            """, (JobStatus.QUEUED.value,))
            row = cursor.fetchone()
            if not row:
                return None

            job_id = row["job_id"]
            cursor.execute("""
                UPDATE jobs 
                SET status = ?, updated_at = ?
                WHERE job_id = ?
            """, (JobStatus.CLAIMED.value, now, job_id))
            conn.commit()

        return self.get_job(job_id)

    def claim_next_tasks(self, job_id: str, limit: int = 10) -> List[RecipientTask]:
        """Atomically claims up to limit pending tasks for a given job."""
        now = datetime.now().isoformat()
        tasks = []
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT task_id, job_id, recipient_email, status, attempts, error, context_json, created_at, updated_at
                FROM recipient_tasks
                WHERE job_id = ? AND status = ?
                LIMIT ?
            """, (job_id, TaskStatus.QUEUED.value, limit))
            rows = cursor.fetchall()
            if not rows:
                return []

            task_ids = [r["task_id"] for r in rows]
            cursor.execute(f"""
                UPDATE recipient_tasks
                SET status = ?, attempts = attempts + 1, updated_at = ?
                WHERE task_id IN ({','.join(['?']*len(task_ids))})
            """, [TaskStatus.CLAIMED.value, now] + task_ids)
            conn.commit()

            for r in rows:
                tasks.append(RecipientTask(
                    task_id=r["task_id"],
                    job_id=r["job_id"],
                    recipient_email=r["recipient_email"],
                    status=TaskStatus.CLAIMED,
                    attempts=r["attempts"] + 1,
                    error=r["error"],
                    context=json.loads(r["context_json"] or "{}"),
                    created_at=datetime.fromisoformat(r["created_at"]),
                    updated_at=datetime.fromisoformat(now),
                ))

        return tasks

    def update_task_status(self, task_id: str, status: TaskStatus, error: Optional[str] = None):
        """Updates individual recipient task state and increments job progress."""
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT job_id FROM recipient_tasks WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                return
            job_id = row["job_id"]

            cursor.execute("""
                UPDATE recipient_tasks
                SET status = ?, error = ?, updated_at = ?
                WHERE task_id = ?
            """, (status.value, error, now, task_id))

            # Update job counts
            if status in (TaskStatus.DELIVERED, TaskStatus.ALREADY_SENT, TaskStatus.SUPPRESSED):
                cursor.execute("""
                    UPDATE jobs 
                    SET completed_tasks = completed_tasks + 1, updated_at = ?
                    WHERE job_id = ?
                """, (now, job_id))
            elif status == TaskStatus.FAILED:
                cursor.execute("""
                    UPDATE jobs 
                    SET failed_tasks = failed_tasks + 1, updated_at = ?
                    WHERE job_id = ?
                """, (now, job_id))

            conn.commit()

    def complete_job(self, job_id: str, status: JobStatus = JobStatus.COMPLETED, error: Optional[str] = None):
        """Marks a job as completed or failed."""
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                UPDATE jobs 
                SET status = ?, error_summary = ?, updated_at = ?
                WHERE job_id = ?
            """, (status.value, error, now, job_id))
            conn.commit()
        logger.info(f"[DurableQueue] Completed Job {job_id} with status: {status.value}")

    def get_job(self, job_id: str) -> Optional[OutreachJob]:
        """Fetches job metadata and live counters."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT job_id, workflow_id, workflow_key, candidate_id,
                       status, total_tasks, completed_tasks, failed_tasks,
                       parameters_json, error_summary, created_at, updated_at
                FROM jobs WHERE job_id = ?
            """, (job_id,))
            r = cursor.fetchone()
            if not r:
                return None

            return OutreachJob(
                job_id=r["job_id"],
                workflow_id=r["workflow_id"],
                workflow_key=r["workflow_key"],
                candidate_id=r["candidate_id"],
                status=JobStatus(r["status"]),
                total_tasks=r["total_tasks"],
                completed_tasks=r["completed_tasks"],
                failed_tasks=r["failed_tasks"],
                parameters=json.loads(r["parameters_json"] or "{}"),
                error_summary=r["error_summary"],
                created_at=datetime.fromisoformat(r["created_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
            )

    def recover_abandoned_jobs(self) -> int:
        """
        Crash-Recovery mechanism:
        Finds any jobs and recipient tasks left in 'claimed' or 'processing'
        state (e.g. from an ungraceful process crash or reboot) and resets
        them back to 'queued' so workers safely resume execution.
        """
        now = datetime.now().isoformat()
        recovered_count = 0
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Reset tasks left in claimed state
            cursor.execute("""
                UPDATE recipient_tasks
                SET status = ?, updated_at = ?
                WHERE status = ?
            """, (TaskStatus.QUEUED.value, now, TaskStatus.CLAIMED.value))

            # 2. Reset jobs left in claimed or processing state
            cursor.execute("""
                SELECT job_id, total_tasks, completed_tasks, failed_tasks 
                FROM jobs 
                WHERE status IN (?, ?)
            """, (JobStatus.CLAIMED.value, JobStatus.PROCESSING.value))
            rows = cursor.fetchall()

            for r in rows:
                jid = r["job_id"]
                # If all tasks were already done, mark completed
                if r["total_tasks"] > 0 and (r["completed_tasks"] + r["failed_tasks"]) >= r["total_tasks"]:
                    cursor.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                                   (JobStatus.COMPLETED.value, now, jid))
                else:
                    cursor.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                                   (JobStatus.QUEUED.value, now, jid))
                    recovered_count += 1

            conn.commit()

        if recovered_count > 0:
            logger.info(f"[DurableQueue] Crash-Recovery: Successfully recovered {recovered_count} interrupted jobs.")
        return recovered_count

    # ─── OPERATOR CONTROLS (MILESTONE C) ──────────────────────────────
    def pause_job(self, job_id: str) -> bool:
        """Pauses a currently queued, claimed, or processing job."""
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs 
                SET status = ?, updated_at = ?
                WHERE job_id = ? AND status IN (?, ?, ?)
            """, (JobStatus.PAUSED.value, now, job_id, JobStatus.QUEUED.value, JobStatus.CLAIMED.value, JobStatus.PROCESSING.value))
            conn.commit()
            success = cursor.rowcount > 0
        if success:
            logger.info(f"[DurableQueue] Operator PAUSED Job {job_id}")
        return success

    def resume_job(self, job_id: str) -> bool:
        """Resumes a paused job back to queued status."""
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs 
                SET status = ?, updated_at = ?
                WHERE job_id = ? AND status = ?
            """, (JobStatus.QUEUED.value, now, job_id, JobStatus.PAUSED.value))
            conn.commit()
            success = cursor.rowcount > 0
        if success:
            logger.info(f"[DurableQueue] Operator RESUMED Job {job_id}")
        return success

    def cancel_job(self, job_id: str) -> bool:
        """Cancels a job and marks unfinished tasks as cancelled."""
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE jobs 
                SET status = ?, updated_at = ?
                WHERE job_id = ? AND status NOT IN (?, ?)
            """, (JobStatus.CANCELLED.value, now, job_id, JobStatus.COMPLETED.value, JobStatus.CANCELLED.value))
            
            # Cancel pending or claimed recipient tasks
            cursor.execute("""
                UPDATE recipient_tasks
                SET status = ?, updated_at = ?
                WHERE job_id = ? AND status IN (?, ?)
            """, (TaskStatus.CANCELLED.value, now, job_id, TaskStatus.QUEUED.value, TaskStatus.CLAIMED.value))
            conn.commit()
            success = cursor.rowcount > 0
        if success:
            logger.info(f"[DurableQueue] Operator CANCELLED Job {job_id}")
        return success

    def retry_failed_tasks(self, job_id: str) -> int:
        """Re-enqueues only failed recipient tasks for a job."""
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM recipient_tasks
                WHERE job_id = ? AND status = ?
            """, (job_id, TaskStatus.FAILED.value))
            failed_count = cursor.fetchone()[0]

            if failed_count == 0:
                return 0

            # Reset tasks to queued
            cursor.execute("""
                UPDATE recipient_tasks
                SET status = ?, error = NULL, updated_at = ?
                WHERE job_id = ? AND status = ?
            """, (TaskStatus.QUEUED.value, now, job_id, TaskStatus.FAILED.value))

            # Reset job status to queued and adjust counters
            cursor.execute("""
                UPDATE jobs
                SET status = ?, failed_tasks = 0, updated_at = ?
                WHERE job_id = ?
            """, (JobStatus.QUEUED.value, now, job_id))
            conn.commit()

        logger.info(f"[DurableQueue] Operator RETRIED {failed_count} failed tasks for Job {job_id}")
        return failed_count

    # ─── SUPPRESSION & WEBHOOK / INBOX EVENTS (MILESTONE C) ───────────
    def add_suppressed_email(self, email: str, reason: str, source: str) -> bool:
        norm_email = email.strip().lower()
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO suppression_list (email, reason, source, created_at)
                VALUES (?, ?, ?, ?)
            """, (norm_email, reason, source, now))
            conn.commit()
        return True

    def is_email_suppressed(self, email: str) -> bool:
        norm_email = email.strip().lower()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM suppression_list WHERE email = ?", (norm_email,))
            return cursor.fetchone() is not None

    def record_inbox_event(
        self,
        event_id: str,
        provider: str,
        event_type: str,
        recipient_email: str,
        reason: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> bool:
        now = datetime.now().isoformat()
        payload_str = json.dumps(payload or {})
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO inbox_events (
                    event_id, provider, event_type, recipient_email, reason, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (event_id, provider, event_type, recipient_email.strip().lower(), reason, payload_str, now))
            conn.commit()
        return True

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT event_id, provider, event_type, recipient_email, reason, created_at
                FROM inbox_events ORDER BY created_at DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    # ─── CONTACT REVIEWS & CONFIDENCE QUEUE (MILESTONE D) ──────────────
    def add_contact_for_review(
        self,
        email: str,
        name: str = "",
        title: str = "",
        confidence_score: float = 0.0,
        reasons: Optional[List[str]] = None
    ) -> str:
        cid = str(uuid.uuid4())
        now = datetime.now().isoformat()
        reasons_json = json.dumps(reasons or [])
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                INSERT INTO contact_reviews (
                    contact_id, email, name, title, confidence_score, reasons_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """, (cid, email.strip().lower(), name, title, confidence_score, reasons_json, now, now))
            conn.commit()
        return cid

    def get_contact_reviews(self, status: str = "pending", limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT contact_id, email, name, title, confidence_score, reasons_json, status, created_at
                FROM contact_reviews WHERE status = ? ORDER BY confidence_score ASC LIMIT ?
            """, (status, limit))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                item["reasons"] = json.loads(item.pop("reasons_json", "[]"))
                results.append(item)
            return results

    def update_contact_review_status(self, contact_id: str, status: str) -> bool:
        now = datetime.now().isoformat()
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE contact_reviews
                SET status = ?, updated_at = ?
                WHERE contact_id = ?
            """, (status, now, contact_id))
            conn.commit()
            return cursor.rowcount > 0

    # ─── OUTCOME ANALYTICS (MILESTONE D) ──────────────────────────────
    def record_outcome_event(self, workflow_id: int, event_type: str, count: int = 1):
        today = datetime.now().date().isoformat()
        mid = f"{workflow_id}_{today}"
        col_map = {
            "sent": "sent_count",
            "delivered": "delivered_count",
            "bounce": "bounced_count",
            "bounced": "bounced_count",
            "reply": "reply_count",
            "positive_reply": "positive_reply_count",
            "meeting": "meeting_count",
            "placement": "placement_count"
        }
        col = col_map.get(event_type.lower(), "sent_count")

        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM outcome_metrics WHERE metric_id = ?", (mid,))
            if not cursor.fetchone():
                conn.execute("""
                    INSERT INTO outcome_metrics (metric_id, workflow_id, metric_date)
                    VALUES (?, ?, ?)
                """, (mid, workflow_id, today))
            
            conn.execute(f"""
                UPDATE outcome_metrics
                SET {col} = {col} + ?
                WHERE metric_id = ?
            """, (count, mid))
            conn.commit()

    def get_outcome_metrics(self, workflow_id: Optional[int] = None) -> Dict[str, Any]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            if workflow_id:
                cursor.execute("""
                    SELECT SUM(sent_count) as total_sent,
                           SUM(delivered_count) as total_delivered,
                           SUM(bounced_count) as total_bounced,
                           SUM(reply_count) as total_replies,
                           SUM(positive_reply_count) as total_positive_replies,
                           SUM(meeting_count) as total_meetings,
                           SUM(placement_count) as total_placements
                    FROM outcome_metrics WHERE workflow_id = ?
                """, (workflow_id,))
            else:
                cursor.execute("""
                    SELECT SUM(sent_count) as total_sent,
                           SUM(delivered_count) as total_delivered,
                           SUM(bounced_count) as total_bounced,
                           SUM(reply_count) as total_replies,
                           SUM(positive_reply_count) as total_positive_replies,
                           SUM(meeting_count) as total_meetings,
                           SUM(placement_count) as total_placements
                    FROM outcome_metrics
                """)
            row = cursor.fetchone()
            return {
                "sent": row["total_sent"] or 0,
                "delivered": row["total_delivered"] or 0,
                "bounced": row["total_bounced"] or 0,
                "replies": row["total_replies"] or 0,
                "positive_replies": row["total_positive_replies"] or 0,
                "meetings": row["total_meetings"] or 0,
                "placements": row["total_placements"] or 0
            }

    # ─── SYSTEM DASHBOARD METRICS (MILESTONE C) ───────────────────────
    def get_system_dashboard_metrics(self) -> Dict[str, Any]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Queue breakdown
            cursor.execute("SELECT status, COUNT(*) as c FROM jobs GROUP BY status")
            job_status_counts = {r["status"]: r["c"] for r in cursor.fetchall()}

            cursor.execute("SELECT status, COUNT(*) as c FROM recipient_tasks GROUP BY status")
            task_status_counts = {r["status"]: r["c"] for r in cursor.fetchall()}

            # Suppression count
            cursor.execute("SELECT COUNT(*) FROM suppression_list")
            suppression_count = cursor.fetchone()[0]

            # Recent 24h bounce & complaint rates
            cursor.execute("""
                SELECT event_type, COUNT(*) as c 
                FROM inbox_events 
                GROUP BY event_type
            """)
            event_counts = {r["event_type"]: r["c"] for r in cursor.fetchall()}

            # Calculate bounce rate
            delivered = event_counts.get("delivered", 0) + task_status_counts.get("delivered", 0)
            bounces = event_counts.get("bounce", 0) + task_status_counts.get("failed", 0)
            total_attempts = delivered + bounces
            bounce_rate = (bounces / total_attempts * 100.0) if total_attempts > 0 else 0.0

            warnings = []
            if bounce_rate > 5.0 and total_attempts >= 20:
                warnings.append(f"Elevated bounce rate ({bounce_rate:.1f}%). Sender reputation at risk.")

            return {
                "job_counts": job_status_counts,
                "task_counts": task_status_counts,
                "suppression_count": suppression_count,
                "event_counts": event_counts,
                "bounce_rate_pct": round(bounce_rate, 2),
                "warnings": warnings,
                "status": "warning" if warnings else "healthy"
            }
