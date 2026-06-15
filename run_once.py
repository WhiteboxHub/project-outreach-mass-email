import sys, os
import asyncio
import pathlib

# Ensure we are in the correct directory regardless of how this is called
SCRIPT_DIR = str(pathlib.Path(__file__).parent.absolute())
sys.path.insert(0, SCRIPT_DIR)
os.chdir(SCRIPT_DIR)

from dotenv import load_dotenv
import os
import logging
load_dotenv()
# Also load backend env for database settings if it exists
backend_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "wbl-backend", ".env"))
if os.path.exists(backend_env):
    load_dotenv(backend_env)

# Configure logging so we can see all outreach service messages
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)


from executor.workflow_executor import WorkflowExecutor
from scheduler.schedule_runner import ScheduleRunner

async def main():
    print("Starting One-Off Execution...")
    # Using ScheduleRunner is better because it updates the "next_run_at" 
    # to the next day in the database and handles lock/unlock correctly.
    runner = ScheduleRunner()
    
    # We pass schedule_id=1. 
    # If it is due, it will run the workflow and advance the next_run_at date.
    await runner.run_schedule(schedule_id=1)
    
    print("Finished One-Off Execution. Closing now.")

if __name__ == "__main__":
    asyncio.run(main())
