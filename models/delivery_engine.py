from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from enum import Enum
from datetime import datetime

class EngineType(str, Enum):
    SMTP = "smtp"
    MAILGUN = "mailgun"
    SENDGRID = "sendgrid"
    AWS_SES = "aws_ses"
    OUTLOOK_API = "outlook_api"

class DeliveryEngine(BaseModel):
    id: int
    name: str
    engine_type: EngineType
    host: Optional[str] = None
    port: Optional[int] = None
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    from_email: str
    from_name: Optional[str] = None
    max_recipients_per_run: Optional[int] = None
    batch_size: int = 50
    rate_limit_per_minute: int = 60
    dedupe_window_minutes: Optional[int] = None
    retry_policy: Optional[Dict[str, Any]] = None
    max_retries: int = 3
    timeout_seconds: int = 600
    status: str = "active"
