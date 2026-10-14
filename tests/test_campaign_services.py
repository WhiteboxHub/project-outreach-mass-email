"""
tests/test_campaign_services.py
────────────────────────────────
Unit tests verifying the campaigns/ package (sequence_manager.py, preview_service.py,
contact_scorer.py, classifier_router.py, ab_testing.py, outcome_analytics.py).
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app import app
from job_queue.durable_job_queue import DurableJobQueue
from campaigns.sequence_manager import CampaignSequenceManager, SequenceStepModel
from campaigns.preview_service import CampaignPreviewService
from campaigns.contact_scorer import ContactConfidenceScorer
from campaigns.classifier_router import ResilientClassifierRouter
from campaigns.ab_testing import TemplateExperimentEngine, TemplateVariant
from campaigns.outcome_analytics import OutcomeAnalyticsService

client = TestClient(app)

@pytest.fixture
def test_queue(tmp_path):
    db_file = str(tmp_path / "test_milestone_d.db")
    return DurableJobQueue(db_path=db_file)

# 1. Campaign Sequences and Stop Conditions
def test_campaign_sequence_and_stop_conditions(test_queue):
    seq_mgr = CampaignSequenceManager(queue=test_queue)

    steps = [
        SequenceStepModel(step_number=1, delay_days=0, subject="Intro", body_template="<p>Hi</p>"),
        SequenceStepModel(step_number=2, delay_days=3, subject="Follow-up 1", body_template="<p>Follow up</p>"),
        SequenceStepModel(step_number=3, delay_days=7, subject="Break-up", body_template="<p>Final</p>")
    ]

    seq_id = seq_mgr.create_sequence(workflow_id=10, name="Senior Python Sequence", steps=steps)
    assert seq_id is not None

    enrolled = seq_mgr.enroll_recipients(seq_id, ["recip1@vendor.com", "recip2@vendor.com"])
    assert enrolled == 2

    # Step 1 should be immediately due
    due = seq_mgr.get_due_recipients_for_step(seq_id, step_number=1)
    assert len(due) == 2

    # Stop Condition: recip1 replies!
    stopped = seq_mgr.handle_stop_condition("recip1@vendor.com", "reply")
    assert stopped == 1

    # Check due for Step 2 after advancing: recip1 should NOT be present
    from datetime import datetime, timedelta
    past_date = (datetime.now() - timedelta(days=4)).isoformat()
    seq_mgr.advance_recipient_step(due[1]["recipient_id"], next_step=2, last_sent_at=past_date)
    due_step2 = seq_mgr.get_due_recipients_for_step(seq_id, step_number=2)
    emails_due = [d["recipient_email"] for d in due_step2]
    assert "recip1@vendor.com" not in emails_due
    assert "recip2@vendor.com" in emails_due

# 2. Safe Preview & Approval Workflow
def test_campaign_preview_service(test_queue):
    preview_service = CampaignPreviewService(queue=test_queue)

    recipients = [
        {"email": "valid1@company.com", "name": "Alice"},
        {"email": "valid2@company.com", "name": "Bob"},
        {"email": "invalid-email-address", "name": "Charlie"}
    ]

    result = preview_service.generate_preview(
        workflow_id=1,
        recipients=recipients,
        template_html="<p>Hello {{ name }}, from {{ candidate_name }}</p>",
        template_subject="Re: {{ candidate_title }}",
        candidate_metadata={"candidate_name": "John Doe", "candidate_title": "Backend Dev"}
    )

    assert result.total_recipients == 3
    assert result.valid_recipients_count == 2
    assert result.invalid_recipients_count == 1
    assert result.net_deliverable_count == 2
    assert "candidate_name" in result.template_variables_found
    assert len(result.missing_template_variables) == 0
    assert result.can_proceed is True
    assert "Hello Alice, from John Doe" in result.sample_html_rendered

# 3. Contact Confidence Scoring & Review Queue
def test_contact_confidence_scoring(test_queue):
    scorer = ContactConfidenceScorer(queue=test_queue, confidence_threshold=0.6)

    # High confidence: corporate email + recruiter title + name -> score 1.0 (>= 0.6)
    c_high = {
        "email": "sarah.connor@tekstaffing.com",
        "name": "Sarah Connor",
        "title": "Senior Technical Recruiter",
        "company": "TekStaffing"
    }
    res_high = scorer.score_contact(c_high)
    assert res_high.confidence_score >= 0.75
    assert res_high.is_eligible is True
    assert res_high.contact_id is None

    # Low confidence: free webmail + no title + no name -> score 0.25 (< 0.6)
    c_low = {
        "email": "mystery99@gmail.com",
        "name": "",
        "title": ""
    }
    res_low = scorer.score_contact(c_low)
    assert res_low.confidence_score < 0.6
    assert res_low.is_eligible is False
    assert res_low.contact_id is not None

    # Verify routed to review queue in DB
    pending = scorer.get_pending_reviews()
    assert len(pending) >= 1
    assert pending[0]["contact_id"] == res_low.contact_id

    # Test approving contact
    assert scorer.approve_contact(res_low.contact_id) is True

# 4. Resilient 3-Tier Classification Router
@pytest.mark.asyncio
async def test_resilient_classifier_router_fallback():
    # Simulate Primary Tier failing (e.g. rate limit 429)
    async def mock_failing_primary(sub, body):
        raise ConnectionError("Primary LLM Rate limited")

    # Secondary succeeds
    async def mock_secondary(sub, body):
        return {"category": "job_opportunity", "is_relevant": True, "confidence": 0.85, "reason": "Secondary LLM match"}

    router = ResilientClassifierRouter(primary_fn=mock_failing_primary, secondary_fn=mock_secondary)
    decision = await router.classify("Senior Java Developer Requirement", "C2C Hourly rate $75/hr")

    assert decision.route_used == "secondary"
    assert decision.category == "job_opportunity"
    assert decision.is_relevant is True

    # When both Primary and Secondary fail -> Tier 3 Rule Fallback takes over
    async def mock_failing_secondary(sub, body):
        raise TimeoutError("Secondary LLM timed out")

    router_fallback = ResilientClassifierRouter(primary_fn=mock_failing_primary, secondary_fn=mock_failing_secondary)
    decision_rule = await router_fallback.classify("C2C Position: React Engineer", "Urgent requirement for client")
    
    assert decision_rule.route_used == "rule_fallback"
    assert decision_rule.category == "job_opportunity"
    assert decision_rule.is_relevant is True

# 5. A/B Testing & Deterministic Variant Assignment
def test_ab_testing_deterministic_variants():
    variants = [
        TemplateVariant(variant_id="A", subject="Subject A", html_body="<p>Body A</p>", weight=50),
        TemplateVariant(variant_id="B", subject="Subject B", html_body="<p>Body B</p>", weight=50)
    ]
    engine = TemplateExperimentEngine(experiment_id="exp_01", variants=variants)

    email1 = "candidate1@targetcorp.com"
    email2 = "candidate2@targetcorp.com"

    # Deterministic consistency
    var1_run1 = engine.select_variant_for_recipient(email1)
    var1_run2 = engine.select_variant_for_recipient(email1)
    assert var1_run1.variant_id == var1_run2.variant_id

    # Performance summary
    summary = engine.record_metrics_summary({
        "A": {"sent": 100, "replies": 14},
        "B": {"sent": 100, "replies": 21}
    })
    assert summary["A"]["reply_rate_pct"] == 14.0
    assert summary["B"]["reply_rate_pct"] == 21.0

# 6. Outcome Analytics & Conversion Reporting
def test_outcome_analytics_service(test_queue):
    analytics = OutcomeAnalyticsService(queue=test_queue)

    analytics.record_event(workflow_id=5, event_type="sent", count=100)
    analytics.record_event(workflow_id=5, event_type="delivered", count=95)
    analytics.record_event(workflow_id=5, event_type="bounce", count=5)
    analytics.record_event(workflow_id=5, event_type="reply", count=20)
    analytics.record_event(workflow_id=5, event_type="positive_reply", count=10)
    analytics.record_event(workflow_id=5, event_type="meeting", count=4)
    analytics.record_event(workflow_id=5, event_type="placement", count=1)

    report = analytics.get_funnel_report(workflow_id=5)
    assert report.sent == 100
    assert report.delivered == 95
    assert report.bounced == 5
    assert report.replies == 20
    assert report.positive_replies == 10
    assert report.meetings == 4
    assert report.placements == 1
    assert report.delivery_rate_pct == 95.0
    assert report.reply_rate_pct == 21.05
    assert report.positive_reply_rate_pct == 50.0

# 7. Milestone D API Endpoints
def test_milestone_d_api_endpoints(monkeypatch):
    api_key = "test_key_m_d"
    monkeypatch.setenv("OUTREACH_API_KEY", api_key)

    # 1. Preview endpoint
    preview_req = {
        "workflow_id": 1,
        "recipients": [{"email": "recip@test.com", "name": "John"}],
        "template_html": "<p>Hi {{ name }}</p>",
        "template_subject": "Hello {{ name }}"
    }
    resp = client.post("/api/v1/campaigns/preview", json=preview_req, headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    assert resp.json()["can_proceed"] is True

    # 2. Campaign approve endpoint
    resp_approve = client.post("/api/v1/campaigns/camp_123/approve", headers={"X-API-Key": api_key})
    assert resp_approve.status_code == 200
    assert resp_approve.json()["status"] == "approved"

    # 3. Outcome Analytics endpoint
    resp_analytics = client.get("/api/v1/analytics/outcomes", headers={"X-API-Key": api_key})
    assert resp_analytics.status_code == 200
    assert "delivery_rate_pct" in resp_analytics.json()
