"""
utils/idempotency.py
────────────────────
Provides deterministic deduplication keys and recipient-level idempotency checking
to prevent duplicate emails from being dispatched during crashes, re-triggers, or retries.
"""

import hashlib
import logging
from datetime import date
from typing import Optional, Set
from threading import Lock
from api_clients.log_client import LogClient

logger = logging.getLogger("outreach_service")

class IdempotencyKey:
    @staticmethod
    def compute_hash(workflow_id: int, workflow_key: str, run_date: str) -> str:
        """
        Computes a deterministic hash for deduplication.
        For scheduled runs, this might typically be workflow_id + date.
        """
        raw = f"{workflow_id}:{workflow_key}:{run_date}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def compute_recipient_hash(workflow_id: int, recipient_email: str, candidate_id: int = 0, send_date: str = None) -> str:
        """
        Computes a recipient-level deterministic hash:
        sha256(workflow_id : normalized_email : candidate_id : date)
        """
        d = send_date or date.today().isoformat()
        norm_email = recipient_email.strip().lower()
        raw = f"{workflow_id}:{norm_email}:{candidate_id}:{d}"
        return hashlib.sha256(raw.encode()).hexdigest()


class IdempotencyChecker:
    def __init__(self):
        self.log_client = LogClient()

    def is_already_processed(self, run_id: str) -> bool:
        """
        Checks if a run_id has already been processed or is currently running.
        """
        try:
            logs = self.log_client.list()
            if not logs:
                return False
            for log in logs:
                if log.get("run_id") == run_id:
                    logger.info(f"Idempotency check: Run ID {run_id} already exists.")
                    return True
        except Exception as e:
            logger.warning(f"Error checking run_id idempotency: {e}")
        return False


class RecipientIdempotencyLedger:
    """
    Thread-safe in-memory and stateful ledger for recipient sends.
    Ensures zero duplicate sends within the same window.
    """
    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(RecipientIdempotencyLedger, cls).__new__(cls)
                cls._instance._processed_keys = set()
                cls._instance._suppressed_emails = set()
        return cls._instance

    def is_already_sent(self, key: str) -> bool:
        with self._lock:
            return key in self._processed_keys

    def record_sent(self, key: str):
        with self._lock:
            self._processed_keys.add(key)

    def is_suppressed(self, email: str) -> bool:
        with self._lock:
            return email.strip().lower() in self._suppressed_emails

    def add_suppression(self, email: str):
        with self._lock:
            self._suppressed_emails.add(email.strip().lower())

    def clear(self):
        with self._lock:
            self._processed_keys.clear()
            self._suppressed_emails.clear()
