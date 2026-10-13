"""
campaigns/preview_service.py
────────────────────────────
Pre-flight safe preview and approval service for mass outreach campaigns.
Validates recipient lists, template variable compatibility, sender quota allocations,
and renders representative sample messages before real execution is initiated.
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import re

from executor.template_renderer import TemplateRenderer
from utils.email_validator_lite import validate_emails
from utils.idempotency import RecipientIdempotencyLedger, IdempotencyKey
from utils.security import build_safe_unsubscribe_url
from job_queue.durable_job_queue import DurableJobQueue

class CampaignPreviewResult(BaseModel):
    workflow_id: int
    total_recipients: int
    valid_recipients_count: int
    invalid_recipients_count: int
    suppressed_count: int
    already_sent_count: int
    net_deliverable_count: int
    sender_capacity_required: int
    primary_capacity_allocated: int
    backup_capacity_allocated: int
    template_variables_found: List[str]
    missing_template_variables: List[str]
    sample_subject: str
    sample_html_rendered: str
    sample_text_rendered: str
    warnings: List[str] = Field(default_factory=list)
    can_proceed: bool = True

class CampaignPreviewService:
    def __init__(self, queue: Optional[DurableJobQueue] = None):
        self.queue = queue or DurableJobQueue()
        self.template_renderer = TemplateRenderer()
        self.ledger = RecipientIdempotencyLedger()

    def generate_preview(
        self,
        workflow_id: int,
        recipients: List[Dict[str, Any]],
        template_html: str,
        template_subject: str,
        template_text: Optional[str] = None,
        candidate_metadata: Optional[Dict[str, Any]] = None,
        primary_daily_limit: int = 250
    ) -> CampaignPreviewResult:
        candidate_meta = candidate_metadata or {
            "candidate_name": "Sample Candidate",
            "candidate_email": "candidate@example.com",
            "candidate_title": "Senior Data Engineer"
        }

        total_recipients = len(recipients)
        warnings: List[str] = []

        # 1. Email validation
        raw_emails = [r.get("email") or r.get("recipient_email") or "" for r in recipients]
        valid_emails, invalid_emails = validate_emails(raw_emails, skip_mx=True)
        valid_set = set(e.strip().lower() for e in valid_emails)

        # 2. Suppression & Idempotency Check
        suppressed_count = 0
        already_sent_count = 0
        deliverable_recipients: List[Dict[str, Any]] = []

        for r in recipients:
            email = (r.get("email") or r.get("recipient_email") or "").strip().lower()
            if email not in valid_set:
                continue

            if self.ledger.is_suppressed(email) or self.queue.is_email_suppressed(email):
                suppressed_count += 1
                continue

            send_key = IdempotencyKey.compute_recipient_hash(workflow_id, email, candidate_meta.get("candidate_id", 0))
            if self.ledger.is_already_sent(send_key):
                already_sent_count += 1
                continue

            deliverable_recipients.append(r)

        net_deliverable = len(deliverable_recipients)

        # 3. Quota distribution
        primary_allocated = min(net_deliverable, primary_daily_limit)
        backup_allocated = max(0, net_deliverable - primary_daily_limit)

        if backup_allocated > 0:
            warnings.append(f"Campaign volume ({net_deliverable}) exceeds primary candidate limit ({primary_daily_limit}). {backup_allocated} recipients will roll over to backup accounts.")

        # 4. Template variable check
        vars_in_subject = re.findall(r'\{\{\s*([a-zA-Z0-9_]+)\s*\}\}', template_subject)
        vars_in_body = re.findall(r'\{\{\s*([a-zA-Z0-9_]+)\s*\}\}', template_html)
        declared_vars = list(set(vars_in_subject + vars_in_body))

        missing_vars = []
        sample_context = {}
        if recipients:
            sample_r = recipients[0]
            sample_context.update(sample_r)
        sample_context.update(candidate_meta)
        sample_context["unsubscribe_link"] = build_safe_unsubscribe_url(sample_context.get("email", "sample@example.com"))

        for var in declared_vars:
            if var not in sample_context:
                missing_vars.append(var)

        if missing_vars:
            warnings.append(f"Template references variables not provided in recipient context: {missing_vars}")

        # 5. Render representative sample
        try:
            rendered_subject = self.template_renderer.render(template_subject, sample_context)
            rendered_html = self.template_renderer.render(template_html, sample_context)
            rendered_text = self.template_renderer.render(template_text, sample_context) if template_text else ""
        except Exception as e:
            rendered_subject = template_subject
            rendered_html = f"<p>Error rendering sample template: {e}</p>"
            rendered_text = ""
            warnings.append(f"Template rendering failed: {e}")

        # Safety determination
        can_proceed = len(missing_vars) == 0 and net_deliverable > 0

        return CampaignPreviewResult(
            workflow_id=workflow_id,
            total_recipients=total_recipients,
            valid_recipients_count=len(valid_emails),
            invalid_recipients_count=len(invalid_emails),
            suppressed_count=suppressed_count,
            already_sent_count=already_sent_count,
            net_deliverable_count=net_deliverable,
            sender_capacity_required=net_deliverable,
            primary_capacity_allocated=primary_allocated,
            backup_capacity_allocated=backup_allocated,
            template_variables_found=declared_vars,
            missing_template_variables=missing_vars,
            sample_subject=rendered_subject,
            sample_html_rendered=rendered_html,
            sample_text_rendered=rendered_text,
            warnings=warnings,
            can_proceed=can_proceed
        )
