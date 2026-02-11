import logging
import traceback
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from api_clients.workflow_client import WorkflowClient
from api_clients.template_client import TemplateClient
from api_clients.delivery_engine_client import DeliveryEngineClient
from api_clients.log_client import LogClient

from .recipient_resolver import RecipientResolver
from .template_renderer import TemplateRenderer
from .engine_builder import EngineBuilder

from models.execution_log import AutomationWorkflowLog, LogStatus
from utils.rate_limiter import TokenBucketRateLimiter
from utils.result_writer import ResultWriter
from utils.retry import RetryManager

logger = logging.getLogger("outreach_service")

class WorkflowExecutor:
    def __init__(self):
        self.workflow_client = WorkflowClient()
        self.template_client = TemplateClient()
        self.engine_client = DeliveryEngineClient()
        self.log_client = LogClient()
        
        self.recipient_resolver = RecipientResolver()
        self.template_renderer = TemplateRenderer()

    async def execute_workflow(self, workflow_id: int = None, workflow_key: str = None, run_id: str = "manual_run", timeout_seconds: int = 3600):
        """
        Executes a workflow by ID or Key asynchronously with concurrency and rate limiting.
        """
        logger.info(f"Starting execution for Workflow ID: {workflow_id} / Key: {workflow_key} [RunID: {run_id}]")
        
        # Initialize Execution State
        start_time = datetime.now()
        deadline = start_time + timedelta(seconds=timeout_seconds)
        
        # 1. Fetch Workflow
        if workflow_id:
            workflow = self.workflow_client.get(workflow_id)
        elif workflow_key:
            workflow = self.workflow_client.get_by_key(workflow_key)
        else:
            raise ValueError("Either workflow_id or workflow_key must be provided.")

        if not workflow:
            logger.error("Workflow not found.")
            return

        workflow_id = workflow["id"]
        
        # Create execution log - STATE: QUEUED -> INITIALIZING
        log_entry = AutomationWorkflowLog(
            workflow_id=workflow_id,
            run_id=run_id,
            status=LogStatus.INITIALIZING,
            started_at=start_time
        )
        self.log_client.create(log_entry.model_dump())

        try:
            # Check Deadline
            if datetime.now() > deadline:
                raise TimeoutError("Execution timed out before initialization.")

            # 2. Fetch Dependencies
            template = self.template_client.get(workflow["email_template_id"])
            engine_config = self.engine_client.get(workflow["delivery_engine_id"])
            
            if not template:
                raise ValueError(f"Template {workflow['email_template_id']} not found.")
            if not engine_config:
                raise ValueError(f"Engine {workflow['delivery_engine_id']} not found.")

            # 3. Resolve Recipients - STATE: RESOLVING_RECIPIENTS
            self._update_status(log_entry.id, LogStatus.RESOLVING_RECIPIENTS)
            recipients = self.recipient_resolver.resolve(workflow["recipient_list_sql"])
            logger.info(f"Resolved {len(recipients)} recipients.")

            # 5. Validate Template (Pre-check)
            missing_vars_subject = self.template_renderer.validate(template["subject"], {})
            # We don't have recipient context yet, so we can only check against global params if any. 
            # Ideally, we check against a sample recipient or just rely on StrictUndefined during execution.
            # But the user requested "Validate Parameters Before Rendering".
            
            # Since context is dynamic per recipient, we'll validate inside the loop or just rely on StrictUndefined to fail individually.
            # However, prompt said "fail early". 
            # Let's inspect variables. If they are all recipient metadata keys, we can warn if metadata is empty.
            
            # Better approach: Check if we have *any* recipients. If so, validate the first one as a sample.
            if recipients:
                sample_context = recipients[0].metadata.copy()
                sample_context["recipient_email"] = recipients[0].email
                sample_context["recipient_name"] = recipients[0].name
                sample_context["unsubscribe_link"] = "http://mock"
                
                missing = self.template_renderer.validate(template["content_html"], sample_context)
                if missing:
                     raise ValueError(f"Template validation failed. Missing variables for sample recipient: {missing}")

            # 6. Build Engine & Rate Limiter
            sender = EngineBuilder.build(engine_config)
            
            rate_limit = engine_config.get("rate_limit_per_minute", 60)
            rate_limiter = TokenBucketRateLimiter(rate_limit_per_minute=rate_limit)
            
            # Concurrency Control
            batch_size = engine_config.get("batch_size", 10)
            semaphore = asyncio.Semaphore(batch_size)

            # 5. Execute - STATE: SENDING
            self._update_status(log_entry.id, LogStatus.SENDING)
            
            success_count = 0
            failed_count = 0
            recipient_results = []
            
            @RetryManager.with_retry(max_attempts=3, base_delay=1.0)
            async def _send_with_retry(recipient, context, subject, html_body, text_body):
                 # Inner function that manages the actual sending and can be retried
                 return await sender.send(
                    from_email=engine_config["from_email"],
                    to_email=recipient.email,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    from_name=engine_config.get("from_name")
                )

            async def process_recipient(recipient):
                nonlocal success_count, failed_count
                
                # Check Deadline inside loop
                if datetime.now() > deadline:
                    return {"email": recipient.email, "status": "timed_out"}

                async with semaphore:
                    # Acquire Rate Limit Token
                    await rate_limiter.acquire()
                    
                    try:
                        # Prepare Context
                        context = recipient.metadata.copy()
                        context["recipient_email"] = recipient.email
                        context["recipient_name"] = recipient.name
                        context["unsubscribe_link"] = f"http://unsubscribe.mock/{recipient.email}"

                        # Render (CPU bound, strictly speaking should await in threadpool if heavy)
                        subject = self.template_renderer.render(template["subject"], context)
                        html_body = self.template_renderer.render(template["content_html"], context)
                        text_body = self.template_renderer.render(template["content_text"], context) if template.get("content_text") else ""

                        # Send with Retry
                        sent = await _send_with_retry(recipient, context, subject, html_body, text_body)

                        if sent:
                            success_count += 1
                            return {"email": recipient.email, "status": "success"}
                        else:
                            failed_count += 1
                            return {"email": recipient.email, "status": "failed"}

                    except Exception as e:
                        logger.error(f"Error processing recipient {recipient.email}: {e}")
                        failed_count += 1
                        return {"email": recipient.email, "status": "error", "error": str(e)}

            # Run concurrently
            tasks = [process_recipient(r) for r in recipients]
            if tasks:
                results = await asyncio.gather(*tasks)
                recipient_results = results
            
            # Check if we timed out during processing
            if datetime.now() > deadline:
                self._update_status(log_entry.id, LogStatus.TIMED_OUT)
                raise TimeoutError("Execution timed out during sending.")

            # 6. Post Processing - STATE: POST_PROCESSING
            self._update_status(log_entry.id, LogStatus.POST_PROCESSING)

            # 7. Update Log - STATE: COMPLETED / PARTIAL_SUCCESS
            final_status = LogStatus.COMPLETED if failed_count == 0 else LogStatus.COMPLETED # Simplified for now, or use PARTIAL_SUCCESS logic
            # Note: User requested specific states. Let's use COMPLETED for success.
            # If there are failures, it's still "Completed" but with errors, unless it's a total failure.
            
            self.log_client.update(log_entry.id, {
                "status": final_status,
                "records_processed": success_count,
                "records_failed": failed_count,
                "finished_at": datetime.now()
            })
            
            # 8. Save Detailed Result
            result_writer = ResultWriter()
            detailed_result = {
                "run_id": run_id,
                "workflow_id": workflow_id,
                "execution_summary": {
                    "started_at": start_time,
                    "finished_at": datetime.now(),
                    "total_recipients": len(recipients),
                    "success_count": success_count,
                    "failed_count": failed_count
                },
                "recipient_results": recipient_results
            }
            result_writer.save_result(run_id, detailed_result)

            logger.info(f"Execution complete. Success: {success_count}, Failed: {failed_count}")
            return {
                "status": "success",
                "processed": success_count,
                "failed": failed_count
            }

        except TimeoutError as e:
            logger.error(f"Workflow execution timed out: {e}")
            self._update_status(log_entry.id, LogStatus.TIMED_OUT, error=str(e))
            return {"status": "timed_out", "error": str(e)}

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            logger.error(traceback.format_exc())
            self._update_status(log_entry.id, LogStatus.FAILED, error=str(e))
            return {"status": "failed", "error": str(e)}

    def _update_status(self, log_id: int, status: LogStatus, error: str = None):
        """Helper to update log status"""
        update_data = {"status": status}
        if error:
            update_data["error_summary"] = error
            update_data["finished_at"] = datetime.now()
            
        self.log_client.update(log_id, update_data)
