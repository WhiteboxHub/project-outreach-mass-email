"""
campaigns package
─────────────────
Provides advanced outreach capabilities:
- Campaign sequences with automatic stop conditions
- Pre-flight safe preview and validation gate
- Contact confidence scoring and review queue
- Resilient 3-tier classification routing
- A/B testing and template experimentation
- Real outcome analytics (replies, meetings, placements)
"""

from .sequence_manager import CampaignSequenceManager, SequenceStepModel
from .preview_service import CampaignPreviewService, CampaignPreviewResult
from .contact_scorer import ContactConfidenceScorer, ScoredContact
from .classifier_router import ResilientClassifierRouter, ClassificationDecision
from .ab_testing import TemplateExperimentEngine, TemplateVariant
from .outcome_analytics import OutcomeAnalyticsService

__all__ = [
    "CampaignSequenceManager",
    "SequenceStepModel",
    "CampaignPreviewService",
    "CampaignPreviewResult",
    "ContactConfidenceScorer",
    "ScoredContact",
    "ResilientClassifierRouter",
    "ClassificationDecision",
    "TemplateExperimentEngine",
    "TemplateVariant",
    "OutcomeAnalyticsService",
]
