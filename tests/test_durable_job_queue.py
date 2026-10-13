"""
tests/test_durable_job_queue.py
───────────────────────────────
Unit tests verifying job_queue/durable_job_queue.py, job_queue/job_worker.py,
and api_clients/async_base_client.py (Durable Queue, Crash Recovery, Worker, Async HTTP).
"""

import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app import app, job_queue
from job_queue.durable_job_queue import DurableJobQueue
from job_queue.job_worker import JobWorker
from models.job import JobStatus, TaskStatus
from api_clients.async_base_client import AsyncBaseClient

client = TestClient(app)

@pytest.fixture
def temp_queue(tmp_path):
    db_file = str(tmp_path / "test_jobs.db")
    q = DurableJobQueue(db_path=db_file)
    return q

def test_durable_job_enqueue_and_claim(temp_queue):
    """Verify enqueuing a job, adding recipient tasks, claiming, and updating task status."""
    job_id = temp_queue.enqueue_job(workflow_id=1, parameters={"type": "daily"})
    assert job_id is not None

    job = temp_queue.get_job(job_id)
    assert job.status == JobStatus.QUEUED
    assert job.workflow_id == 1

    # Add recipient tasks
    added = temp_queue.add_recipient_tasks(job_id, [
        {"email": "recip1@test.com", "name": "R1"},
        {"email": "recip2@test.com", "name": "R2"}
    ])
    assert added == 2

    # Verify updated job totals
    job = temp_queue.get_job(job_id)
    assert job.total_tasks == 2

    # Claim next job
    claimed_job = temp_queue.claim_next_job()
    assert claimed_job.job_id == job_id
    assert claimed_job.status == JobStatus.CLAIMED

    # Claim tasks
    tasks = temp_queue.claim_next_tasks(job_id, limit=1)
    assert len(tasks) == 1
    assert tasks[0].recipient_email == "recip1@test.com"
    assert tasks[0].status == TaskStatus.CLAIMED

    # Complete task
    temp_queue.update_task_status(tasks[0].task_id, TaskStatus.DELIVERED)
    job = temp_queue.get_job(job_id)
    assert job.completed_tasks == 1

def test_durable_job_crash_recovery(temp_queue):
    """Simulate process crash with tasks in 'claimed' state and verify automatic recovery."""
    job_id = temp_queue.enqueue_job(workflow_id=2)
    temp_queue.add_recipient_tasks(job_id, [
        {"email": "active1@test.com"},
        {"email": "active2@test.com"}
    ])

    # Claim job and task (simulating interrupted in-flight run)
    temp_queue.claim_next_job()
    temp_queue.claim_next_tasks(job_id, limit=2)

    # Verify both are in claimed state
    with temp_queue._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM recipient_tasks WHERE status = 'claimed'")
        assert cursor.fetchone()[0] == 2
        cursor.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,))
        assert cursor.fetchone()[0] == "claimed"

    # Run Crash Recovery
    recovered = temp_queue.recover_abandoned_jobs()
    assert recovered == 1

    # Verify job and tasks were safely returned to 'queued' state for worker to resume
    job = temp_queue.get_job(job_id)
    assert job.status == JobStatus.QUEUED

    with temp_queue._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM recipient_tasks WHERE status = 'queued'")
        assert cursor.fetchone()[0] == 2

@pytest.mark.asyncio
async def test_async_base_client_methods():
    """Verify AsyncBaseClient correctly makes requests and manages connections."""
    async_client = AsyncBaseClient(base_url="https://api.test.com")
    
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        res = await async_client._get("/health")
        assert res == {"status": "ok"}

    await async_client.close()

def test_trigger_and_job_status_endpoints(monkeypatch):
    """Verify POST /api/v1/trigger enqueues a durable job and GET /api/v1/jobs/{job_id} returns status."""
    api_key = "test_key_m2"
    monkeypatch.setenv("OUTREACH_API_KEY", api_key)

    # 1. Trigger
    resp = client.post(
        "/api/v1/trigger",
        json={"workflow_id": 99},
        headers={"X-API-Key": api_key}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    job_id = data["job_id"]

    # 2. Query Job Status Endpoint
    status_resp = client.get(
        f"/api/v1/jobs/{job_id}",
        headers={"X-API-Key": api_key}
    )
    assert status_resp.status_code == 200
    job_data = status_resp.json()
    assert job_data["job_id"] == job_id
    assert job_data["workflow_id"] == 99
    assert job_data["status"] == "queued"

    # 3. Query Non-Existent Job -> 404
    not_found = client.get(
        "/api/v1/jobs/non-existent-uuid",
        headers={"X-API-Key": api_key}
    )
    assert not_found.status_code == 404

@pytest.mark.asyncio
async def test_job_worker_process_one_job(temp_queue):
    """Verify JobWorker claims and executes a job through to completion."""
    worker = JobWorker(queue=temp_queue)
    
    job_id = temp_queue.enqueue_job(workflow_id=1, parameters={"test": True})
    
    with patch.object(worker.executor, "execute_workflow", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"status": "success", "processed": 5, "failed": 0}

        did_work = await worker.process_one_job()
        assert did_work is True

        job = temp_queue.get_job(job_id)
        assert job.status == JobStatus.COMPLETED
