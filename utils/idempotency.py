import hashlib
import logging
from typing import Optional
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

class IdempotencyChecker:
    def __init__(self):
        self.log_client = LogClient()

    def is_already_processed(self, run_id: str) -> bool:
        """
        Checks if a run_id has already been processed or is currently running.
        """
        # In a real DB, we would query: SELECT 1 FROM logs WHERE run_id = ?
        # For our mock LogClient, we iterate.
        logs = self.log_client.list()
        for log in logs:
            if log.get("run_id") == run_id:
                logger.info(f"Idempotency check: Run ID {run_id} already exists.")
                return True
        return False
