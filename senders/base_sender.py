from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class BaseSender(ABC):
    @abstractmethod
    async def send(self, 
             from_email: str, 
             to_email: str, 
             subject: str, 
             html_body: str, 
             text_body: str = None, 
             from_name: str = None,
             reply_to: str = None,
             headers: Dict[str, str] = None) -> bool:
        pass
