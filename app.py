from fastapi import FastAPI, BackgroundTasks, HTTPException, Security, Depends
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
import logging
from typing import Optional, List, Dict, Any, Union
import uuid
from dotenv import load_dotenv
import os
import requests

load_dotenv()
# Also load backend env for database settings if it exists
backend_env = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "wbl-backend", ".env"))
if os.path.exists(backend_env):
    load_dotenv(backend_env)

from executor.workflow_executor import WorkflowExecutor
from utils.logger import setup_logger

# Setup Logger
setup_logger()
logger = logging.getLogger("outreach_service")

from scheduler.scheduler_loop import SchedulerLoop
from job_queue.durable_job_queue import DurableJobQueue
from job_queue.job_worker import JobWorker
from models.job import JobStatusResponse
from inbox.event_handler import WebhookEventHandler
from campaigns.preview_service import CampaignPreviewService, CampaignPreviewResult
from campaigns.contact_scorer import ContactConfidenceScorer
from campaigns.outcome_analytics import OutcomeAnalyticsService
import asyncio

from contextlib import asynccontextmanager

# Global Instances
scheduler = SchedulerLoop(interval_seconds=60)
job_queue = DurableJobQueue()
job_worker = JobWorker(queue=job_queue)
webhook_handler = WebhookEventHandler(queue=job_queue)
preview_service = CampaignPreviewService(queue=job_queue)
contact_scorer = ContactConfidenceScorer(queue=job_queue)
analytics_service = OutcomeAnalyticsService(queue=job_queue)

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def verify_api_key(api_key: Optional[str] = Security(api_key_header)):
    expected_key = os.getenv("OUTREACH_API_KEY")
    if expected_key:
        if not api_key or api_key != expected_key:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Invalid or missing X-API-Key header"
            )
    return api_key

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start background scheduler and durable job queue worker
    scheduler_task = asyncio.create_task(scheduler.start())
    worker_task = asyncio.create_task(job_worker.start())
    yield
    # Shutdown: Stop workers and await completion
    scheduler.stop()
    job_worker.stop()
    await scheduler_task
    await worker_task

app = FastAPI(title="Outreach Service", version="2.0.0", lifespan=lifespan)

class TriggerWorkflowRequest(BaseModel):
    workflow_id: Optional[int] = None
    workflow_key: Optional[str] = None
    run_id: Optional[str] = None

@app.post("/api/v1/trigger", dependencies=[Depends(verify_api_key)])
async def trigger_workflow(request: TriggerWorkflowRequest):
    if not request.workflow_id and not request.workflow_key:
        raise HTTPException(status_code=400, detail="Must provide either workflow_id or workflow_key")

    run_id = request.run_id or str(uuid.uuid4())
    
    # Enqueue in durable persistent queue
    job_id = job_queue.enqueue_job(
        workflow_id=request.workflow_id,
        workflow_key=request.workflow_key,
        job_id=run_id
    )

    return {
        "message": "Workflow enqueued successfully in durable queue",
        "job_id": job_id,
        "run_id": job_id,
        "status": "queued"
    }

@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(verify_api_key)], response_model=JobStatusResponse)
def get_job_status(job_id: str):
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        workflow_id=job.workflow_id,
        total_tasks=job.total_tasks,
        completed_tasks=job.completed_tasks,
        failed_tasks=job.failed_tasks,
        created_at=job.created_at,
        updated_at=job.updated_at,
        error_summary=job.error_summary
    )

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/health/live")
def liveness_probe():
    return {"status": "alive"}

@app.get("/health/ready")
def readiness_probe():
    backend_url = os.getenv("WBL_BACKEND_URL", "https://api.whitebox-learning.com/api")
    backend_ok = True
    try:
        resp = requests.get(f"{backend_url}/orchestrator/workflows/1", timeout=5)
        if resp.status_code >= 500:
            backend_ok = False
    except Exception:
        backend_ok = False

    return {
        "status": "ready" if backend_ok else "degraded",
        "scheduler_running": scheduler.running,
        "worker_running": job_worker._running,
        "backend_connected": backend_ok,
        "durable_queue": "ready"
    }

# ─── OPERATOR CONTROLS (MILESTONE C) ──────────────────────────────────
@app.post("/api/v1/jobs/{job_id}/pause", dependencies=[Depends(verify_api_key)])
def pause_job(job_id: str):
    success = job_queue.pause_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Could not pause job. It may not exist or is already completed/cancelled.")
    return {"message": f"Job {job_id} successfully paused", "status": "paused"}

@app.post("/api/v1/jobs/{job_id}/resume", dependencies=[Depends(verify_api_key)])
def resume_job(job_id: str):
    success = job_queue.resume_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Could not resume job. It may not be in paused state.")
    return {"message": f"Job {job_id} successfully resumed", "status": "queued"}

@app.post("/api/v1/jobs/{job_id}/cancel", dependencies=[Depends(verify_api_key)])
def cancel_job(job_id: str):
    success = job_queue.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Could not cancel job. It may already be completed or cancelled.")
    return {"message": f"Job {job_id} successfully cancelled", "status": "cancelled"}

@app.post("/api/v1/jobs/{job_id}/retry-failed", dependencies=[Depends(verify_api_key)])
def retry_failed_job(job_id: str):
    retried_count = job_queue.retry_failed_tasks(job_id)
    return {"message": f"Retried {retried_count} failed tasks for job {job_id}", "retried_count": retried_count}

# ─── WEBHOOK INGESTION (MILESTONE C) ──────────────────────────────────
@app.post("/api/v1/events/webhooks/{provider}")
async def ingest_webhook(provider: str, payload: Union[Dict[str, Any], List[Dict[str, Any]]]):
    prov = provider.lower()
    if prov == "sendgrid":
        events = payload if isinstance(payload, list) else [payload]
        processed = webhook_handler.process_sendgrid_events(events)
    elif prov == "mailgun":
        data = payload if isinstance(payload, dict) else (payload[0] if payload else {})
        processed = webhook_handler.process_mailgun_events(data)
    elif prov in ("aws_ses", "ses"):
        data = payload if isinstance(payload, dict) else (payload[0] if payload else {})
        processed = webhook_handler.process_ses_sns_notification(data)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported provider webhook: {provider}")

    return {
        "status": "processed",
        "provider": prov,
        "events_count": len(processed),
        "events": [p.model_dump() for p in processed]
    }

# ─── HEALTH DASHBOARD (MILESTONE C) ───────────────────────────────────
@app.get("/api/v1/health/dashboard", dependencies=[Depends(verify_api_key)])
def get_health_dashboard():
    metrics = job_queue.get_system_dashboard_metrics()
    metrics["scheduler_running"] = scheduler.running
    metrics["worker_running"] = job_worker._running
    return metrics

# ─── CAMPAIGN PREVIEW & APPROVAL (MILESTONE D) ────────────────────────
class CampaignPreviewRequest(BaseModel):
    workflow_id: int
    recipients: List[Dict[str, Any]]
    template_html: str
    template_subject: str
    template_text: Optional[str] = None
    candidate_metadata: Optional[Dict[str, Any]] = None
    primary_daily_limit: int = 250

@app.post("/api/v1/campaigns/preview", dependencies=[Depends(verify_api_key)], response_model=CampaignPreviewResult)
def preview_campaign(request: CampaignPreviewRequest):
    return preview_service.generate_preview(
        workflow_id=request.workflow_id,
        recipients=request.recipients,
        template_html=request.template_html,
        template_subject=request.template_subject,
        template_text=request.template_text,
        candidate_metadata=request.candidate_metadata,
        primary_daily_limit=request.primary_daily_limit
    )

@app.post("/api/v1/campaigns/{campaign_id}/approve", dependencies=[Depends(verify_api_key)])
def approve_campaign(campaign_id: str):
    return {
        "campaign_id": campaign_id,
        "status": "approved",
        "message": f"Campaign {campaign_id} approved for execution."
    }

# ─── CONTACT REVIEWS (MILESTONE D) ────────────────────────────────────
class ReviewActionRequest(BaseModel):
    action: str  # "approve" or "reject"

@app.get("/api/v1/contacts/review-queue", dependencies=[Depends(verify_api_key)])
def list_review_queue(limit: int = 50):
    return contact_scorer.get_pending_reviews(limit=limit)

@app.post("/api/v1/contacts/{contact_id}/review", dependencies=[Depends(verify_api_key)])
def review_contact(contact_id: str, request: ReviewActionRequest):
    if request.action == "approve":
        success = contact_scorer.approve_contact(contact_id)
    elif request.action == "reject":
        success = contact_scorer.reject_contact(contact_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Must be 'approve' or 'reject'")

    if not success:
        raise HTTPException(status_code=404, detail="Contact review record not found.")
    return {"contact_id": contact_id, "action": request.action, "status": "updated"}

# ─── OUTCOME ANALYTICS (MILESTONE D) ──────────────────────────────────
@app.get("/api/v1/analytics/outcomes", dependencies=[Depends(verify_api_key)])
def get_outcomes(workflow_id: Optional[int] = None):
    return analytics_service.get_funnel_report(workflow_id=workflow_id)

