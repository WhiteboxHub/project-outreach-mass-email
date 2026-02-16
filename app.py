from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import logging
from typing import Optional
import uuid
from dotenv import load_dotenv

load_dotenv()

from executor.workflow_executor import WorkflowExecutor
from utils.logger import setup_logger

# Setup Logger
setup_logger()
logger = logging.getLogger("outreach_service")

from scheduler.scheduler_loop import SchedulerLoop
import asyncio

app = FastAPI(title="Outreach Service", version="1.0.0")

from contextlib import asynccontextmanager

# Global Scheduler Instance
scheduler = SchedulerLoop(interval_seconds=60)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start scheduler
    task = asyncio.create_task(scheduler.start())
    yield
    # Shutdown: Stop scheduler
    scheduler.stop()
    await task

app = FastAPI(title="Outreach Service", version="1.0.0", lifespan=lifespan)

class TriggerWorkflowRequest(BaseModel):
    workflow_id: Optional[int] = None
    workflow_key: Optional[str] = None
    run_id: Optional[str] = None

@app.post("/api/v1/trigger")
async def trigger_workflow(request: TriggerWorkflowRequest, background_tasks: BackgroundTasks):
    if not request.workflow_id and not request.workflow_key:
        raise HTTPException(status_code=400, detail="Must provide either workflow_id or workflow_key")

    run_id = request.run_id or str(uuid.uuid4())
    
    executor = WorkflowExecutor()
    
    # Run in background
    # Since background_tasks.add_task supports async functions, we can pass it directly.
    background_tasks.add_task(
        executor.execute_workflow,
        workflow_id=request.workflow_id,
        workflow_key=request.workflow_key,
        run_id=run_id
    )

    return {
        "message": "Workflow triggered successfully",
        "run_id": run_id,
        "status": "queued"
    }

@app.get("/health")
def health_check():
    return {"status": "ok"}
