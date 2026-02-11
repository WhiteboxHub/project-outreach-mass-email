from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from enum import Enum
from datetime import datetime

class LogStatus(str, Enum):
    QUEUED = "queued"
    INITIALIZING = "initializing"
    RESOLVING_RECIPIENTS = "resolving_recipients"
    SENDING = "sending"
    POST_PROCESSING = "post_processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"

class AutomationWorkflowLog(BaseModel):
    id: Optional[int] = None
    workflow_id: int
    schedule_id: Optional[int] = None
    run_id: str
    status: LogStatus = LogStatus.QUEUED
    parameters_used: Optional[Dict[str, Any]] = None
    execution_metadata: Optional[Dict[str, Any]] = None
    records_processed: int = 0
    records_failed: int = 0
    error_summary: Optional[str] = None
    error_details: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
