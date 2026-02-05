from abc import ABC, abstractmethod
from typing import List, Optional

class BaseSender(ABC):
    @abstractmethod
    def send(
        self,
        from_email: str,
        reply_to: str,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        headers: Optional[dict] = None,
        from_name: Optional[str] = None
    ) -> bool:
        """
        Sends an email. Returns True if successful, False otherwise.
        """
        pass
