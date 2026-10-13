"""
campaigns/classifier_router.py
──────────────────────────────
Resilient 3-tier classification routing strategy for email and opportunity categorization:
1. Preferred Hosted Model (Primary API)
2. Approved Secondary / Local Fallback (on rate limit or API error)
3. Deterministic Rule-based Fallback (guaranteed execution)
"""

import time
import logging
import re
from typing import Dict, Any, Optional, Callable, Awaitable
from pydantic import BaseModel, Field

logger = logging.getLogger("outreach_service")

class ClassificationDecision(BaseModel):
    category: str
    is_relevant: bool
    confidence: float
    route_used: str  # "primary", "secondary", "rule_fallback"
    reason: str
    latency_ms: float
    timestamp: float = Field(default_factory=time.time)

class ResilientClassifierRouter:
    def __init__(
        self,
        primary_fn: Optional[Callable[[str, str], Awaitable[Dict[str, Any]]]] = None,
        secondary_fn: Optional[Callable[[str, str], Awaitable[Dict[str, Any]]]] = None
    ):
        self.primary_fn = primary_fn
        self.secondary_fn = secondary_fn

    def _rule_based_classify(self, subject: str, body: str) -> Dict[str, Any]:
        """Deterministic regex and keyword rule fallback."""
        combined = f"{subject}\n{body}".lower()

        # Job opportunity patterns
        job_signals = [
            "c2c", "w2", "corp to corp", "rate:", "hourly rate",
            "position:", "job title:", "job description", "client:", "location:",
            "urgent requirement", "immediate need", "looking for candidates"
        ]
        job_matches = sum(1 for s in job_signals if s in combined)

        # Spam / noise patterns
        spam_signals = [
            "unsubscribe from our newsletter", "viagra", "crypto", "casino",
            "congratulations you won", "claim your prize", "survey"
        ]
        spam_matches = sum(1 for s in spam_signals if s in combined)

        if spam_matches > 0:
            return {
                "category": "spam_noise",
                "is_relevant": False,
                "confidence": 0.85,
                "reason": f"Matched {spam_matches} spam/promotional keywords"
            }

        if job_matches >= 2:
            return {
                "category": "job_opportunity",
                "is_relevant": True,
                "confidence": 0.75 + min(0.2, job_matches * 0.05),
                "reason": f"Matched {job_matches} staffing/requirement keyword patterns"
            }
        elif job_matches == 1:
            return {
                "category": "vendor_inquiry",
                "is_relevant": True,
                "confidence": 0.60,
                "reason": "Single staffing signal detected; marked as vendor inquiry"
            }

        return {
            "category": "general",
            "is_relevant": False,
            "confidence": 0.50,
            "reason": "No explicit staffing opportunity keywords matched"
        }

    async def classify(self, subject: str, body: str) -> ClassificationDecision:
        t0 = time.perf_counter()

        # 1. Attempt Tier 1 (Primary Model)
        if self.primary_fn:
            try:
                res = await self.primary_fn(subject, body)
                latency = (time.perf_counter() - t0) * 1000
                logger.info(f"[ClassifierRouter] Tier 1 (Primary) succeeded in {latency:.1f}ms")
                return ClassificationDecision(
                    category=res.get("category", "general"),
                    is_relevant=res.get("is_relevant", False),
                    confidence=res.get("confidence", 0.90),
                    route_used="primary",
                    reason=res.get("reason", "Primary model prediction"),
                    latency_ms=round(latency, 2)
                )
            except Exception as e:
                logger.warning(f"[ClassifierRouter] Tier 1 failed ({e}). Falling back to Tier 2...")

        # 2. Attempt Tier 2 (Secondary / Local Model)
        if self.secondary_fn:
            try:
                res = await self.secondary_fn(subject, body)
                latency = (time.perf_counter() - t0) * 1000
                logger.info(f"[ClassifierRouter] Tier 2 (Secondary) succeeded in {latency:.1f}ms")
                return ClassificationDecision(
                    category=res.get("category", "general"),
                    is_relevant=res.get("is_relevant", False),
                    confidence=res.get("confidence", 0.75),
                    route_used="secondary",
                    reason=res.get("reason", "Secondary fallback prediction"),
                    latency_ms=round(latency, 2)
                )
            except Exception as e:
                logger.warning(f"[ClassifierRouter] Tier 2 failed ({e}). Falling back to Tier 3...")

        # 3. Tier 3: Deterministic Rule-Based Fallback
        res = self._rule_based_classify(subject, body)
        latency = (time.perf_counter() - t0) * 1000
        logger.info(f"[ClassifierRouter] Tier 3 (Rule Fallback) finished in {latency:.1f}ms")
        return ClassificationDecision(
            category=res["category"],
            is_relevant=res["is_relevant"],
            confidence=res["confidence"],
            route_used="rule_fallback",
            reason=res["reason"],
            latency_ms=round(latency, 2)
        )
