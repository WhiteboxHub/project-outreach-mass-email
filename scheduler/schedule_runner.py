import logging
from datetime import datetime, timedelta
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
        
        import json
        run_params = schedule.get("run_parameters")
        if run_params and isinstance(run_params, str):
            try:
                run_params = json.loads(run_params)
            except Exception as e:
                logger.error(f"Failed to parse run_parameters for schedule {schedule_id}: {e}")
                run_params = {}
        
        if run_params is None:
            run_params = {}
        
        # Atomically lock schedule
        if not self.schedule_client.lock_schedule(schedule_id):
            logger.warning(f"Failed to acquire lock for schedule {schedule_id}. It might be running already.")
            return

        logger.info(f"Triggering scheduled run for Schedule {schedule_id} [Workflow {workflow_id}] with params: {run_params}")
        
        try:
            # Execute Workflow
            result = await self.workflow_executor.execute_workflow(
                workflow_id=workflow_id, 
                run_id=run_id,
                schedule_id=schedule_id,
                execution_context=run_params
            )
            
            # Update Next Run Time
            updates = {
                "last_run_at": utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                "is_running": 0
            }

            # Clear run-specific parameters if explicitly requested (Success case)
            if result and result.get("status") == "success":
                updates["run_parameters"] = None
            
            # Calculate next run based on frequency
            current_next = schedule.get("next_run_at")
            if current_next:
                current_next_dt = datetime.fromisoformat(current_next) if isinstance(current_next, str) else current_next
                freq = schedule.get("frequency", "daily").lower()
                
                # Base delta
                delta = timedelta(days=1)
                if freq == "weekly":
                    delta = timedelta(weeks=1)
                elif freq == "monthly":
                    delta = timedelta(days=30) # approximation, better logic would be calendrical
                
                # ADVANCE TO FUTURE: To prevent catch-up loops, move to the next valid slot >= NOW
                now = datetime.now()
                while current_next_dt <= now:
                    current_next_dt += delta
                
                updates["next_run_at"] = current_next_dt.strftime('%Y-%m-%d %H:%M:%S')

            self.schedule_client.update(schedule_id, updates)
            
        except Exception as e:
            logger.error(f"Scheduled run failed for Schedule {schedule_id}: {e}")
            self.schedule_client.update(schedule_id, {"is_running": 0})
        finally:
            # Final safety check to unlock if not updated by client
            try:
                # We fetch again to check if it's still locked
                latest = self.schedule_client.get(schedule_id)
                if latest and latest.get("is_running"):
                    self.schedule_client.update(schedule_id, {"is_running": 0})
            except:
                pass
