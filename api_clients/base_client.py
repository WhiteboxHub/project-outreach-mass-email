from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class BaseClient(ABC):
    @abstractmethod
    def get(self, resource_id: int) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def list(self, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        pass
