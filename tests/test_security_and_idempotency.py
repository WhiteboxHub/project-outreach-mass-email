"""
tests/test_security_and_idempotency.py
──────────────────────────────────────
Unit tests verifying utils/security.py, utils/idempotency.py, senders/smtp_sender.py,
and executor/recipient_resolver.py (Security, Idempotency, Real Retries, Health).
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app import app
from utils.security import redact_sensitive_data, generate_unsubscribe_token, verify_unsubscribe_token
from utils.idempotency import IdempotencyKey, RecipientIdempotencyLedger
from senders.base_sender import TransientDeliveryError, PermanentDeliveryError
from senders.smtp_sender import SMTPSender
from executor.recipient_resolver import RecipientResolver, UpstreamDependencyError

client = TestClient(app)

def test_redact_sensitive_data_nested():
    """Verify that credentials at any depth are redacted completely."""
    raw = {
        "candidate_id": 101,
        "name": "John Doe",
        "candidate_credentials": {
            "host": "smtp.gmail.com",
            "password": "secret_password_123",
            "app_password": "abcd efgh ijkl mnop",
            "tokens": ["tok_abc", {"api_key": "live_key_xyz"}]
        },
        "safe_info": "visible"
    }
    redacted = redact_sensitive_data(raw)
    assert redacted["candidate_id"] == 101
    assert redacted["name"] == "John Doe"
    assert redacted["candidate_credentials"]["password"] == "[REDACTED]"
    assert redacted["candidate_credentials"]["app_password"] == "[REDACTED]"
    assert redacted["candidate_credentials"]["tokens"][1]["api_key"] == "[REDACTED]"
    assert redacted["safe_info"] == "visible"

def test_unsubscribe_token_signature_and_verification():
    """Verify HMAC signed unsubscribe tokens protect email addresses and verify authenticity."""
    email = "vendor.contact@example.com"
    token = generate_unsubscribe_token(email)
    
    # Token should not contain raw email in plain text
    assert email not in token
    assert "." in token

    # Token must verify and recover normalized email
    verified_email = verify_unsubscribe_token(token)
    assert verified_email == email

    # Tampered token must fail
    tampered_token = token[:-4] + "abcd"
    assert verify_unsubscribe_token(tampered_token) is None

def test_recipient_idempotency_ledger():
    """Verify recipient-level idempotency ledger prevents duplicate sends."""
    ledger = RecipientIdempotencyLedger()
    workflow_id = 1
    recipient_email = "duplicate.test@example.com"
    candidate_id = 55
    date_str = "2026-09-12"

    hash_key = IdempotencyKey.compute_recipient_hash(workflow_id, recipient_email, candidate_id, date_str)
    
    # Initially not sent
    assert not ledger.is_already_sent(hash_key)

    # Record send
    ledger.record_sent(hash_key)
    assert ledger.is_already_sent(hash_key)

    # Suppression testing
    assert not ledger.is_suppressed(recipient_email)
    ledger.add_suppression(recipient_email)
    assert ledger.is_suppressed(recipient_email)

def test_smtp_error_classification():
    """Verify SMTPSender raises appropriate Transient vs Permanent delivery errors."""
    sender = SMTPSender({"host": "invalid.smtp.host.test", "port": 587, "username": "u", "password": "p"})

    with pytest.raises(TransientDeliveryError):
        # Trying to send to invalid host will raise socket/connection error -> TransientDeliveryError
        sender._send_sync(
            from_email="test@example.com",
            to_email="recip@example.com",
            subject="Hi",
            html_body="<p>Test</p>"
        )

def test_trigger_api_key_auth(monkeypatch):
    """Verify POST /api/v1/trigger requires valid X-API-Key."""
    monkeypatch.setenv("OUTREACH_API_KEY", "test_secret_key_123")

    # 1. Missing header -> 401
    resp = client.post("/api/v1/trigger", json={"workflow_id": 1})
    assert resp.status_code == 401
    assert "Unauthorized" in resp.json()["detail"]

    # 2. Invalid header -> 401
    resp = client.post(
        "/api/v1/trigger",
        json={"workflow_id": 1},
        headers={"X-API-Key": "wrong_key"}
    )
    assert resp.status_code == 401

    # 3. Valid header -> 200
    with patch("app.WorkflowExecutor.execute_workflow"):
        resp = client.post(
            "/api/v1/trigger",
            json={"workflow_id": 1},
            headers={"X-API-Key": "test_secret_key_123"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

def test_health_endpoints():
    """Verify /health/live and /health/ready."""
    resp_live = client.get("/health/live")
    assert resp_live.status_code == 200
    assert resp_live.json()["status"] == "alive"

    resp_ready = client.get("/health/ready")
    assert resp_ready.status_code == 200
    assert "status" in resp_ready.json()

def test_upstream_dependency_error():
    """Verify recipient resolver distinguishes backend failure from empty recipient list."""
    resolver = RecipientResolver()
    with patch.object(resolver.workflow_client, "execute_sql", return_value=None):
        with pytest.raises(UpstreamDependencyError):
            resolver.resolve(1, "SELECT * FROM test", {})
