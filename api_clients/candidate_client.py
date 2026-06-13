from typing import Any, Dict, List, Optional
from api_clients.base_client import BaseClient
import logging

logger = logging.getLogger("outreach_service")

class CandidateClient(BaseClient):
    
    def get_outreach_candidates(self) -> List[Dict[str, Any]]:
        """Fetch all eligible primary and backup candidates for daily outreach."""
        result = self._get("/orchestrator/candidates/outreach")
        return result if result else []

    def update_candidate_metrics(self, candidate_id: int, sent_count: int) -> bool:
        """Call backend to update candidate fcount, total outreach count, and next date."""
        resp = self._post(
            f"/orchestrator/candidates/{candidate_id}/metrics",
            json={"sent_count": sent_count}
        )
        return resp.get("success", False) if resp else False
