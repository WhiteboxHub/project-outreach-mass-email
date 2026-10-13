"""
queue/job_worker.py
───────────────────
Background worker that consumes jobs from DurableJobQueue and executes
outreach campaigns with graceful shutdown and crash recovery.
"""

import asyncio
import logging
from typing import Optional
from job_queue.durable_job_queue import DurableJobQueue
from models.job import JobStatus
from executor.workflow_executor import WorkflowExecutor

logger = logging.getLogger("outreach_service")

class JobWorker:
    def __init__(self, queue: Optional[DurableJobQueue] = None, poll_interval_seconds: float = 2.0):
        self.queue = queue or DurableJobQueue()
        self.poll_interval = poll_interval_seconds
        self.executor = WorkflowExecutor()
        self._running = False
        self._current_task: Optional[asyncio.Task] = None

    async def start(self):
        """Starts worker loop."""
        self._running = True
        logger.info("[JobWorker] Starting durable job queue worker loop...")
        
        # Run crash recovery on startup
        try:
            self.queue.recover_abandoned_jobs()
        except Exception as e:
            logger.error(f"[JobWorker] Error during startup job recovery: {e}")

        while self._running:
            try:
                processed = await self.process_one_job()
                if not processed:
                    await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[JobWorker] Unexpected error in worker loop: {e}")
                await asyncio.sleep(self.poll_interval)

        logger.info("[JobWorker] Worker loop stopped.")

    def stop(self):
        """Signals worker to stop."""
        self._running = False

    async def process_one_job(self) -> bool:
        """Claims and executes a single job from the queue. Returns True if work was done."""
        job = self.queue.claim_next_job()
        if not job:
            return False

        # Verify job was not paused or cancelled immediately prior
        current_state = self.queue.get_job(job.job_id)
        if current_state and current_state.status in (JobStatus.PAUSED, JobStatus.CANCELLED):
            logger.info(f"[JobWorker] Skipping Job {job.job_id} because state is {current_state.status.value}")
            return False

        logger.info(f"[JobWorker] Processing Job {job.job_id} (Workflow: {job.workflow_id or job.workflow_key})")
        
        try:
            result = await self.executor.execute_workflow(
                workflow_id=job.workflow_id,
                workflow_key=job.workflow_key,
                run_id=job.job_id,
                execution_context=job.parameters,
                send_report=True
            )
            
            # Check if job was cancelled mid-flight by operator
            latest_state = self.queue.get_job(job.job_id)
            if latest_state and latest_state.status == JobStatus.CANCELLED:
                logger.info(f"[JobWorker] Job {job.job_id} was cancelled by operator; preserving CANCELLED state.")
                return True

            final_status = JobStatus.COMPLETED if result.get("status") in ("success", "partial_success") else JobStatus.FAILED
            self.queue.complete_job(job.job_id, status=final_status, error=result.get("error"))
            return True
        except Exception as e:
            logger.error(f"[JobWorker] Execution failed for Job {job.job_id}: {e}")
            self.queue.complete_job(job.job_id, status=JobStatus.FAILED, error=str(e))
            return True
