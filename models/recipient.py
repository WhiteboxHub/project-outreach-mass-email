from pydantic import BaseModel
from typing import Optional, Dict, Any

class Recipient(BaseModel):
    email: str
    name: Optional[str] = None
    metadata: Dict[str, Any] = {}
    unsubscribe_link: Optional[str] = None
