"""
tests/test_multi_provider_senders.py
────────────────────────────────────
Unit tests verifying senders/ (ses_sender.py, sendgrid_sender.py, mailgun_sender.py),
inbox/ (event_handler.py, imap_client.py), and app.py operator controls.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from botocore.exceptions import ClientError

from app import app
from job_queue.durable_job_queue import DurableJobQueue
from models.job import JobStatus, TaskStatus
from senders.base_sender import TransientDeliveryError, PermanentDeliveryError
from senders.ses_sender import AWSSESSender
from senders.sendgrid_sender import SendGridSender
from senders.mailgun_sender import MailgunSender
from inbox.imap_client import IMAPReplyPoller
from utils.idempotency import RecipientIdempotencyLedger

client = TestClient(app)

@pytest.fixture
def test_queue(tmp_path):
    db_file = str(tmp_path / "test_milestone_c.db")
    return DurableJobQueue(db_path=db_file)

# 1. AWS SES Sender Tests
def test_ses_sender_error_classification():
    config = {
        "engine_type": "aws_ses",
        "from_email": "sender@example.com",
        "aws_access_key_id": "mock_key",
        "aws_secret_access_key": "mock_secret",
        "region_name": "us-east-1"
    }
    sender = AWSSESSender(config)

    with patch.object(sender, "_get_client") as mock_ses_client:
        mock_boto = MagicMock()
        mock_ses_client.return_value = mock_boto

        # Test Throttling -> TransientDeliveryError
        mock_boto.send_email.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "SendEmail"
        )
        with pytest.raises(TransientDeliveryError):
            sender._send_sync("from@test.com", "to@test.com", "Sub", "Body")

        # Test MessageRejected -> PermanentDeliveryError
        mock_boto.send_email.side_effect = ClientError(
            {"Error": {"Code": "MessageRejected", "Message": "Email address not verified"}},
            "SendEmail"
        )
        with pytest.raises(PermanentDeliveryError):
            sender._send_sync("from@test.com", "to@test.com", "Sub", "Body")

# 2. SendGrid Sender Tests
@pytest.mark.asyncio
async def test_sendgrid_sender_responses():
    config = {
        "engine_type": "sendgrid",
        "from_email": "sender@test.com",
        "api_key": "SG.test_key_123"
    }
    sender = SendGridSender(config)

    # 202 Success
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_post.return_value = mock_resp

        result = await sender.send("sender@test.com", "recip@test.com", "Sub", "<p>Body</p>")
        assert result is True

    # 429 Rate Limit -> TransientDeliveryError
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Too many requests"
        mock_post.return_value = mock_resp

        with pytest.raises(TransientDeliveryError):
            await sender.send("sender@test.com", "recip@test.com", "Sub", "<p>Body</p>")

    # 401 Unauthorized -> PermanentDeliveryError
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Bad API key"
        mock_post.return_value = mock_resp

        with pytest.raises(PermanentDeliveryError):
            await sender.send("sender@test.com", "recip@test.com", "Sub", "<p>Body</p>")

# 3. Mailgun Sender Tests
@pytest.mark.asyncio
async def test_mailgun_sender_responses():
    config = {
        "engine_type": "mailgun",
        "from_email": "sender@mg.test.com",
        "api_key": "key-mailgun-123",
        "domain": "mg.test.com"
    }
    sender = MailgunSender(config)

    # 200 Success
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        result = await sender.send("sender@mg.test.com", "recip@test.com", "Sub", "<p>Body</p>")
        assert result is True

    # 500 Server Error -> TransientDeliveryError
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_post.return_value = mock_resp

        with pytest.raises(TransientDeliveryError):
            await sender.send("sender@mg.test.com", "recip@test.com", "Sub", "<p>Body</p>")

# 4. Operator Controls (Pause, Resume, Cancel, Retry-Failed)
def test_operator_controls_lifecycle(test_queue):
    job_id = test_queue.enqueue_job(workflow_id=1)
    test_queue.add_recipient_tasks(job_id, [
        {"email": "r1@test.com"},
        {"email": "r2@test.com"}
    ])

    # 1. Pause
    assert test_queue.pause_job(job_id) is True
    job = test_queue.get_job(job_id)
    assert job.status == JobStatus.PAUSED

    # 2. Resume
    assert test_queue.resume_job(job_id) is True
    job = test_queue.get_job(job_id)
    assert job.status == JobStatus.QUEUED

    # 3. Mark one task failed
    tasks = test_queue.claim_next_tasks(job_id, limit=2)
    test_queue.update_task_status(tasks[0].task_id, TaskStatus.FAILED, error="Connection timeout")
    test_queue.update_task_status(tasks[1].task_id, TaskStatus.DELIVERED)

    # 4. Retry Failed Tasks
    retried = test_queue.retry_failed_tasks(job_id)
    assert retried == 1
    job = test_queue.get_job(job_id)
    assert job.status == JobStatus.QUEUED

    # 5. Cancel
    assert test_queue.cancel_job(job_id) is True
    job = test_queue.get_job(job_id)
    assert job.status == JobStatus.CANCELLED

# 5. Webhook Ingestion & Automatic Suppression
def test_webhook_ingestion_and_auto_suppression():
    ledger = RecipientIdempotencyLedger()
    bounced_email = "bounced_user_99@test.com"

    # Ensure not currently suppressed
    assert not ledger.is_suppressed(bounced_email)

    sendgrid_payload = [
        {
            "event": "bounce",
            "email": bounced_email,
            "reason": "550 5.1.1 User unknown",
            "sg_event_id": "sg_ev_test_1"
        }
    ]

    resp = client.post("/api/v1/events/webhooks/sendgrid", json=sendgrid_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"
    assert data["events_count"] == 1

    # Verify email was automatically suppressed
    assert ledger.is_suppressed(bounced_email)

# 6. Health Dashboard Endpoint
def test_health_dashboard_endpoint(monkeypatch):
    api_key = "dashboard_key_123"
    monkeypatch.setenv("OUTREACH_API_KEY", api_key)

    resp = client.get("/api/v1/health/dashboard", headers={"X-API-Key": api_key})
    assert resp.status_code == 200
    data = resp.json()
    assert "job_counts" in data
    assert "task_counts" in data
    assert "suppression_count" in data
    assert "bounce_rate_pct" in data
    assert "status" in data

# 7. IMAP Reply Parsing
def test_imap_reply_classification():
    poller = IMAPReplyPoller(host="imap.test.com")
    
    # Bounce
    c1 = poller._classify_message("mailer-daemon@google.com", "Delivery Status Notification (Failure)", "Undeliverable")
    assert c1 == "bounce"

    # Auto reply
    c2 = poller._classify_message("recruiter@firm.com", "Automatic reply: Out of Office", "I will be back next Monday.")
    assert c2 == "auto_reply"

    # Human reply
    c3 = poller._classify_message("john.recruiter@staffing.com", "Re: Senior Python Engineer Available", "Thanks, please send over the resume.")
    assert c3 == "human_reply"
