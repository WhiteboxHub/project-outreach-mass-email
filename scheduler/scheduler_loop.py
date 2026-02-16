import asyncio
import logging
from datetime import datetime
from api_clients.schedule_client import ScheduleClient
from scheduler.schedule_runner import ScheduleRunner

logger = logging.getLogger("outreach_service")

class SchedulerLoop:
    def __init__(self, interval_seconds: int = 60):
        self.interval = interval_seconds
        self.running = False
        self.schedule_client = ScheduleClient()
        self.runner = ScheduleRunner()

    async def start(self):
        """Starts the scheduler polling loop."""
        if self.running:
            return
        
        self.running = True
        logger.info("Scheduler started.")
        
        while self.running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Scheduler tick failed: {e}")
            
            await asyncio.sleep(self.interval)

    def stop(self):
        self.running = False
        logger.info("Scheduler stopped.")

    async def _tick(self):
        """Process one tick of the scheduler."""
        # fetch due schedules
        if hasattr(self.schedule_client, 'list_due'):
             schedules = self.schedule_client.list_due()
        else:
             schedules = self.schedule_client.list({"status": "active"})
        
        now = datetime.now() 
        
        for schedule in schedules:
            next_run = schedule.get("next_run_at")
            if next_run:
                try:
                    # simplistic parsing for mock string '2023-10-27T09:00:00'
                    next_run_dt = datetime.fromisoformat(next_run)
                    
                    if next_run_dt <= now:
                        # Prevent immediate re-triggering in mock by checking last_run or lock
                        # For this demo, we assume the runner updates next_run_at immediately or we launch tasks
                        
                        logger.info(f"Schedule {schedule['id']} is due (Next run: {next_run}). Launching...")
                        
                        # Run async
                        # In a real app we might want to track this task
                        asyncio.create_task(self.runner.run_schedule(schedule["id"]))
                        
                except ValueError:
                    logger.error(f"Invalid date format for schedule {schedule['id']}: {next_run}")
