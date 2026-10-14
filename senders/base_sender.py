from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class DeliveryError(Exception):
    """Base class for all delivery errors."""
    pass

class TransientDeliveryError(DeliveryError):
    """Temporary failure (network drop, timeout, rate limit) that should be retried."""
    pass

class PermanentDeliveryError(DeliveryError):
    """Fatal failure (invalid credentials, recipient rejected, 5xx) that should NOT be retried."""
    pass

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
