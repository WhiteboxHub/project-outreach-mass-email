from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime

class TemplateStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"

class EmailTemplate(BaseModel):
    id: int
    template_key: str
    name: str
    description: Optional[str] = None
    subject: str
    content_html: str
    content_text: Optional[str] = None
    parameters: Optional[List[str]] = None
    status: TemplateStatus = TemplateStatus.DRAFT
    version: int = 1
    created_time: datetime = Field(default_factory=datetime.now)
    last_mod_time: datetime = Field(default_factory=datetime.now)
