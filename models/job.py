"""
models/job.py
─────────────
Domain models for durable jobs and recipient-level tasks in Outreach Platform v2.
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field

class JobStatus(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    PROCESSING = "processing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskStatus(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    DELIVERED = "delivered"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    ALREADY_SENT = "already_sent"
    DEFERRED = "deferred"
    CANCELLED = "cancelled"

class RecipientTask(BaseModel):
    task_id: str
    job_id: str
    recipient_email: str
    status: TaskStatus = TaskStatus.QUEUED
    attempts: int = 0
    error: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

class OutreachJob(BaseModel):
    job_id: str
    workflow_id: Optional[int] = None
    workflow_key: Optional[str] = None
    candidate_id: Optional[int] = None
    status: JobStatus = JobStatus.QUEUED
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    parameters: Dict[str, Any] = Field(default_factory=dict)
    error_summary: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    workflow_id: Optional[int] = None
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    created_at: datetime
    updated_at: datetime
    error_summary: Optional[str] = None
