from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from enum import Enum
from datetime import datetime

class WorkflowType(str, Enum):
    EMAIL_SENDER = "email_sender"
    EXTRACTOR = "extractor"
    TRANSFORMER = "transformer"
    WEBHOOK = "webhook"
    SYNC = "sync"

class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    INACTIVE = "inactive"

class AutomationWorkflow(BaseModel):
    id: int
    workflow_key: str
    name: str
    description: Optional[str] = None
    workflow_type: WorkflowType
    owner_id: Optional[int] = None
    status: WorkflowStatus = WorkflowStatus.DRAFT
    
    email_template_id: Optional[int] = None
    delivery_engine_id: Optional[int] = None
    
    credentials_list_sql: Optional[str] = None
    recipient_list_sql: Optional[str] = None
    parameters_config: Optional[Dict[str, Any]] = None
    
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
