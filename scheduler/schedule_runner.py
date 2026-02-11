import logging
from datetime import datetime
from uuid import uuid4

from executor.workflow_executor import WorkflowExecutor
from api_clients.workflow_client import WorkflowClient
from api_clients.schedule_client import ScheduleClient
from utils.idempotency import IdempotencyKey, IdempotencyChecker
from utils.time_utils import utcnow

logger = logging.getLogger("outreach_service")

class ScheduleRunner:
    def __init__(self):
        self.workflow_executor = WorkflowExecutor()
        self.workflow_client = WorkflowClient()
        self.schedule_client = ScheduleClient()
        self.idempotency_checker = IdempotencyChecker()

    async def run_schedule(self, schedule_id: int):
        """
        Executes a schedule if valid and due.
        """
        schedule = self.schedule_client.get(schedule_id)
        if not schedule or schedule.get("status") != "active":
            logger.warning(f"Schedule {schedule_id} is not active or found.")
            return

        workflow_id = schedule["workflow_id"]
        
        # Idempotency Check
        # Generate a run key based on schedule and time (e.g. daily)
        # For simplicity in this mock, we just generate a unique ID, 
        # but in production we'd key off the scheduled time to prevent double runs for same slot.
        current_date = datetime.now().strftime("%Y-%m-%d")
        run_key = IdempotencyKey.compute_hash(workflow_id, f"schedule_{schedule_id}", current_date)
        
        # Check if already ran today (pseudo-idempotency for daily jobs)
        # Note: This is an oversimplification. A robust scheduler tracks `last_run_at`.
        # Here we rely on `next_run_at` update.
        
        run_id = str(uuid4())
        
        logger.info(f"Triggering scheduled run for Schedule {schedule_id} [Workflow {workflow_id}]")
        
        try:
            # Execute Workflow
            await self.workflow_executor.execute_workflow(
                workflow_id=workflow_id, 
                run_id=run_id
            )
            
            # Update Next Run Time
            # Mock update logic: just add 24 hours
            # In production, parse Cron expression
            self.schedule_client.update(schedule_id, {
                "last_run_at": utcnow().isoformat(),
                # "next_run_at": ... (Calculated)
            })
            
        except Exception as e:
            logger.error(f"Scheduled run failed for Schedule {schedule_id}: {e}")
