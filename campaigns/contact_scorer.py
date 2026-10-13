"""
campaigns/contact_scorer.py
───────────────────────────
Confidence-scored contact intelligence and operator review queue.
Evaluates extracted contacts with a 0.0–1.0 score. High-confidence contacts
are approved for outreach, while low-confidence contacts are placed in a review
queue instead of being silently dropped.
"""

import re
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from job_queue.durable_job_queue import DurableJobQueue

logger = logging.getLogger("outreach_service")

FREE_WEBMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "aol.com", "icloud.com", "mail.com", "protonmail.com"
}

RECRUITER_KEYWORDS = {
    "recruiter", "talent", "staffing", "sourcer", "acquisition",
    "hr", "human resources", "hiring", "headhunter", "account manager"
}

class ScoredContact(BaseModel):
    email: str
    name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    confidence_score: float
    is_eligible: bool
    reasons: List[str]
    contact_id: Optional[str] = None

class ContactConfidenceScorer:
    def __init__(self, queue: Optional[DurableJobQueue] = None, confidence_threshold: float = 0.6):
        self.queue = queue or DurableJobQueue()
        self.threshold = confidence_threshold

    def score_contact(self, contact: Dict[str, Any], auto_enqueue_low_confidence: bool = True) -> ScoredContact:
        email = (contact.get("email") or contact.get("recipient_email") or "").strip().lower()
        name = contact.get("name") or contact.get("full_name") or ""
        title = contact.get("title") or contact.get("job_title") or contact.get("position") or ""
        company = contact.get("company") or contact.get("vendor_name") or ""

        score = 0.0
        reasons = []

        # 1. Email format check (+0.25)
        if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            score += 0.25
            reasons.append("Valid email format (+0.25)")
        else:
            reasons.append("Invalid or missing email syntax (+0.0)")

        # 2. Corporate domain vs free webmail (+0.25)
        if "@" in email:
            domain = email.split("@")[1].lower()
            if domain not in FREE_WEBMAIL_DOMAINS and "." in domain:
                score += 0.25
                reasons.append(f"Corporate business domain @{domain} (+0.25)")
            else:
                reasons.append(f"Free webmail domain @{domain} (+0.0)")

        # 3. Complete Name Verification (+0.25)
        clean_name = name.strip()
        if clean_name and clean_name.lower() not in ("none", "unknown", "n/a"):
            score += 0.25
            reasons.append(f"Named contact: '{clean_name}' (+0.25)")
        else:
            reasons.append("Missing or unverified recipient name (+0.0)")

        # 4. Target role / staffing keyword match (+0.25)
        clean_title = title.strip().lower()
        if any(kw in clean_title for kw in RECRUITER_KEYWORDS):
            score += 0.25
            reasons.append(f"Target staffing/recruiter keyword in title: '{title}' (+0.25)")
        elif clean_title:
            score += 0.10
            reasons.append(f"Non-staffing title present: '{title}' (+0.10)")
        else:
            reasons.append("Missing title or role information (+0.0)")

        confidence = round(min(1.0, score), 2)
        is_eligible = confidence >= self.threshold

        contact_id = None
        if not is_eligible and auto_enqueue_low_confidence:
            # Route to review queue rather than dropping
            contact_id = self.queue.add_contact_for_review(
                email=email,
                name=name,
                title=title,
                confidence_score=confidence,
                reasons=reasons
            )
            logger.info(f"[ContactScorer] Low confidence contact ({confidence} < {self.threshold}) routed to review queue: {email}")

        return ScoredContact(
            email=email,
            name=name or None,
            title=title or None,
            company=company or None,
            confidence_score=confidence,
            is_eligible=is_eligible,
            reasons=reasons,
            contact_id=contact_id
        )

    def score_batch(self, contacts: List[Dict[str, Any]]) -> List[ScoredContact]:
        return [self.score_contact(c) for c in contacts]

    def approve_contact(self, contact_id: str) -> bool:
        return self.queue.update_contact_review_status(contact_id, "approved")

    def reject_contact(self, contact_id: str) -> bool:
        return self.queue.update_contact_review_status(contact_id, "rejected")

    def get_pending_reviews(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.queue.get_contact_reviews(status="pending", limit=limit)
