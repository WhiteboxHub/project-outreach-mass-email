"""
campaigns/ab_testing.py
───────────────────────
A/B testing and template experimentation engine.
Provides deterministic recipient hashing to assign variants consistently across retries,
and tracks response and conversion metrics per template variant.
"""

import hashlib
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("outreach_service")

class TemplateVariant(BaseModel):
    variant_id: str  # e.g. "A", "B", "C"
    subject: str
    html_body: str
    text_body: Optional[str] = None
    weight: int = 50  # percentage weight (e.g. 50/50)

class TemplateExperimentEngine:
    def __init__(self, experiment_id: str, variants: List[TemplateVariant]):
        if not variants:
            raise ValueError("TemplateExperimentEngine requires at least one variant.")
        self.experiment_id = experiment_id
        self.variants = variants
        self._normalize_weights()

    def _normalize_weights(self):
        total_weight = sum(v.weight for v in self.variants)
        if total_weight <= 0:
            equal_weight = 100 // len(self.variants)
            for v in self.variants:
                v.weight = equal_weight

    def select_variant_for_recipient(self, recipient_email: str) -> TemplateVariant:
        """
        Deterministically selects a variant for a recipient using:
        sha256(experiment_id : normalized_email) modulo total_weight.
        Guarantees that a recipient always receives the identical variant during replays/retries.
        """
        norm_email = recipient_email.strip().lower()
        seed = f"{self.experiment_id}:{norm_email}"
        digest_int = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)

        total_weight = sum(v.weight for v in self.variants)
        bucket = digest_int % total_weight

        current = 0
        for variant in self.variants:
            current += variant.weight
            if bucket < current:
                return variant

        return self.variants[0]

    def record_metrics_summary(self, variant_results: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
        """
        Computes deliverability and reply performance per variant.
        Format: {"A": {"sent": 100, "replies": 12}, "B": {"sent": 100, "replies": 18}}
        """
        summary = {}
        for vid, stats in variant_results.items():
            sent = stats.get("sent", 0)
            replies = stats.get("replies", 0)
            rate = (replies / sent * 100.0) if sent > 0 else 0.0
            summary[vid] = {
                "sent": sent,
                "replies": replies,
                "reply_rate_pct": round(rate, 2)
            }
        return summary
