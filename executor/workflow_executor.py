import logging
import traceback
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from api_clients.workflow_client import WorkflowClient
from api_clients.template_client import TemplateClient
from api_clients.delivery_engine_client import DeliveryEngineClient
from api_clients.log_client import LogClient

from .recipient_resolver import RecipientResolver
from .template_renderer import TemplateRenderer
from .engine_builder import EngineBuilder

from models.execution_log import LogStatus
from utils.rate_limiter import TokenBucketRateLimiter
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

    async def execute_workflow(self, workflow_id: int = None, workflow_key: str = None, run_id: str = "manual_run", schedule_id: int = None, timeout_seconds: int = 3600, execution_context: Dict[str, Any] = {}):
        """
        Executes a workflow by ID or Key asynchronously with concurrency and rate limiting.
        """
        if execution_context is None:
            execution_context = {}
        logger.info(f"Starting execution for Workflow ID: {workflow_id} / Key: {workflow_key} [RunID: {run_id}] Context: {execution_context}")
        
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
            return {"status": "failed", "error": "Workflow not found"}

        workflow_id = workflow["id"]
        
        # Normalize parameters_config if string
        params_config = workflow.get("parameters_config")
        if isinstance(params_config, str):
             try:
                 params_config = json.loads(params_config)
             except:
                 params_config = {}
        elif params_config is None:
             params_config = {}
        
        # Create execution log - STATE: QUEUED -> INITIALIZING
        log_entry = {
            "workflow_id": workflow_id,
            "schedule_id": schedule_id,
            "run_id": run_id,
            "status": "queued",
            "started_at": start_time.isoformat(),
            "parameters_used": execution_context # Pass as dict, backend handles JSON
        }
        log_id = self.log_client.create(log_entry)
        
        if not log_id:
            logger.error("Failed to create log entry.")
            return {"status": "failed", "error": "Failed to create log entry"}

        try:
            # Check Deadline
            if datetime.now() > deadline:
                raise TimeoutError("Execution timed out before initialization.")
            
            self._update_status(log_id, "running")

            # 2. Fetch Candidate Metadata (if present)
            if "candidate_id" in execution_context:
                try:
                    c_id = execution_context["candidate_id"]
                    c_data = self.engine_client.get_candidate_credentials(c_id)
                    if c_data:
                        execution_context["candidate_email"] = c_data.get("email")
                        execution_context["candidate_name"] = c_data.get("candidate_name") or "Candidate"
                        execution_context["linkedin_url"] = c_data.get("linkedin_url") or ""
                        execution_context["candidate_credentials"] = c_data # Store for engine config
                        logger.info(f"Loaded metadata for Candidate {c_id}: {execution_context['candidate_name']}")
                except Exception as e:
                    logger.warning(f"Failed to fetch candidate metadata for ID {execution_context['candidate_id']}: {e}")

            # 3. Determine Engine
            engine_config = None
            use_candidate_smtp = params_config.get("engine") == "candidate_smtp"
            
            if use_candidate_smtp:
                cand_data = execution_context.get("candidate_credentials")
                if not cand_data:
                    raise ValueError("No active marketing record credentials found/cached for candidate.")
                
                # Map to Engine Config
                engine_config = {
                    "engine_type": "smtp",
                    "host": "smtp.gmail.com", 
                    "port": 587,
                    "username": cand_data.get("email"),
                    "password": cand_data.get("imap_password") or cand_data.get("password"),
                    "from_email": cand_data.get("email"),
                    "from_name": execution_context.get("candidate_name"),
                    "rate_limit_per_minute": 15,
                    "batch_size": 1
                }
                
                # Simple host detection
                email_addr = cand_data.get("email", "").lower()
                if "outlook" in email_addr or "hotmail" in email_addr:
                    engine_config["host"] = "smtp-mail.outlook.com"
                elif "yahoo" in email_addr:
                    engine_config["host"] = "smtp.mail.yahoo.com"
                else:
                    engine_config["host"] = "smtp.gmail.com"

            else:
                # Use standard Delivery Engine
                if workflow.get("delivery_engine_id"):
                    engine_config = self.engine_client.get(workflow["delivery_engine_id"])
                
            if not engine_config:
                raise ValueError("No valid engine configuration found.")

            # 3. Fetch Template
            if workflow.get("email_template_id"):
                template = self.template_client.get(workflow["email_template_id"])
                if not template:
                    raise ValueError(f"Template {workflow['email_template_id']} not found.")
            else:
                 raise ValueError("Workflow missing email_template_id.")

            # 4. Resolve Recipients
            recipient_sql = workflow.get("recipient_list_sql")
            if not recipient_sql:
                 raise ValueError("Workflow missing recipient_list_sql.")
            
            recipients = self.recipient_resolver.resolve(workflow_id, recipient_sql, execution_context)
            logger.info(f"Resolved {len(recipients)} recipients.")

            if not recipients:
                 logger.info("No recipients found. Workflow completes successfully (nothing to do).")
                 self._update_status(log_id, "success", processed=0, failed=0)
                 return {"status": "success", "processed": 0, "failed": 0}

            # 5. Build Engine & Rate Limiter
            sender = EngineBuilder.build(engine_config)
            
            rate_limit = engine_config.get("rate_limit_per_minute", 60)
            rate_limiter = TokenBucketRateLimiter(rate_limit_per_minute=rate_limit)
            
            batch_size = engine_config.get("batch_size", 10)
            semaphore = asyncio.Semaphore(batch_size)

            # 6. Execute Sending
            success_count = 0
            failed_count = 0
            recipient_results = []
            
            from utils.retry import RetryManager 
            
            @RetryManager.with_retry(max_attempts=3, base_delay=1.0)
            async def _send_with_retry(recipient, context, subject, html_body, text_body, reply_to):
                 return await sender.send(
                    from_email=engine_config["from_email"],
                    to_email=recipient.email,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    from_name=engine_config.get("from_name"),
                    reply_to=reply_to
                )

            async def process_recipient(recipient):
                nonlocal success_count, failed_count
                
                if datetime.now() > deadline:
                    return {"email": recipient.email, "status": "timed_out"}

                async with semaphore:
                    await rate_limiter.acquire()
                    try:
                        context = recipient.metadata.copy()
                        context.update(execution_context)
                        
                        context["recipient_email"] = recipient.email
                        context["recipient_name"] = recipient.name
                        context["unsubscribe_link"] = f"http://unsubscribe.mock/{recipient.email}" 

                        # Determine reply-to for this specific send
                        current_reply_to = context.get("candidate_email") or context.get("reply_to") or engine_config.get("from_email")

                        subject = self.template_renderer.render(template["subject"], context)
                        html_body = self.template_renderer.render(template["content_html"], context)
                        text_body = self.template_renderer.render(template["content_text"], context) if template.get("content_text") else ""

                        logger.info(f"   [SMTP] Sending email to {recipient.email}...")
                        sent = await _send_with_retry(recipient, context, subject, html_body, text_body, current_reply_to)
                        
                        # Add a small delay to avoid SMTP throttling
                        await asyncio.sleep(2.0)

                        if sent:
                            logger.info(f"   [SMTP] Success: {recipient.email}")
                            success_count += 1
                        else:
                            failed_count += 1

                        # Periodic progress update to the DB (every 5 recipients)
                        if (success_count + failed_count) % 5 == 0:
                            try:
                                self._update_status(log_id, "running", processed=success_count, failed=failed_count)
                            except:
                                pass

                        if sent:
                            # Execute per-recipient update SQL if configured
                            recipient_update_sql = params_config.get("recipient_update_sql")
                            if recipient_update_sql:
                                try:
                                    # We use the recipient's metadata as parameters for the update
                                    self.workflow_client.execute_reset_sql(workflow_id, recipient_update_sql, context)
                                except Exception as e:
                                    logger.warning(f"Failed to execute per-recipient update SQL for {recipient.email}: {e}")
                            
                            return {"email": recipient.email, "status": "success"}
                        else:
                            return {"email": recipient.email, "status": "failed"}

                    except Exception as e:
                        logger.error(f"Error processing recipient {recipient.email}: {e}")
                        failed_count += 1
                        return {"email": recipient.email, "status": "error", "error": str(e)}

            tasks = [process_recipient(r) for r in recipients]
            if tasks:
                logger.info(f"Starting async sending for {len(tasks)} recipients...")
                results = await asyncio.gather(*tasks)
                recipient_results = results
            
            logger.info(f"Workflow execution finished. Success: {success_count}, Failed: {failed_count}")
            
            if datetime.now() > deadline:
                 self._update_status(log_id, "timed_out", error="Execution timed out during sending")
                 raise TimeoutError("Execution timed out during sending.")

            # 7. Post Processing / Reset Logic
            final_status = "success" if failed_count == 0 else "partial_success"
            if failed_count == len(recipients):
                final_status = "failed" 

            # Execute Success Reset SQL if configured
            reset_sql = params_config.get("success_reset_sql")
            if reset_sql and success_count > 0: 
                try:
                    self.workflow_client.execute_reset_sql(workflow_id, reset_sql, execution_context)
                    logger.info("Executed success reset SQL via API.")
                except Exception as e:
                    logger.error(f"Failed to execute reset SQL via API: {e}")

            # 8. Update Log
            try:
                self.log_client.update(log_id, {
                    "status": final_status,
                    "records_processed": success_count,
                    "records_failed": failed_count,
                    "finished_at": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Failed to update final log status: {e}")

            return {
                "status": "success",
                "processed": success_count,
                "failed": failed_count
            }

        except TimeoutError as e:
            logger.error(f"Workflow execution timed out: {e}")
            self._update_status(log_id, "timed_out", error=str(e))
            return {"status": "timed_out", "error": str(e)}

        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            logger.error(traceback.format_exc())
            self._update_status(log_id, "failed", error=str(e))
            return {"status": "failed", "error": str(e)}

    def _update_status(self, log_id: int, status: str, error: str = None, processed: int = None, failed: int = None):
        """Helper to update log status"""
        update_data = {"status": status}
        if error is not None:
            update_data["error_summary"] = str(error)[:250]
            update_data["finished_at"] = datetime.now().isoformat()
        
        if processed is not None: update_data["records_processed"] = processed
        if failed is not None: update_data["records_failed"] = failed
            
        self.log_client.update(log_id, update_data)
