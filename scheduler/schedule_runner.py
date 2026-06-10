import logging
import asyncio
from datetime import datetime, timedelta, date
from uuid import uuid4

from executor.workflow_executor import WorkflowExecutor
from api_clients.workflow_client import WorkflowClient
from api_clients.schedule_client import ScheduleClient
from utils.idempotency import IdempotencyKey, IdempotencyChecker
from utils.time_utils import utcnow

logger = logging.getLogger("outreach_service")

class ScheduleRunner:
    def __init__(self):
        self.workflow_executor = WorkflowExecutor()
        self.workflow_client = WorkflowClient()
        self.schedule_client = ScheduleClient()
        self.idempotency_checker = IdempotencyChecker()

    async def run_schedule(self, schedule_id: int):
        """
        Executes a schedule if valid and due.
        """
        schedule = self.schedule_client.get(schedule_id)
        if not schedule or schedule.get("status") != "active":
            logger.warning(f"Schedule {schedule_id} is not active or not found.")
            return

        workflow_id = schedule["workflow_id"]
        
        # Atomically lock schedule
        if not self.schedule_client.lock_schedule(schedule_id):
            logger.warning(f"Failed to acquire lock for schedule {schedule_id}. It might be running already.")
            return

        run_id = str(uuid4())
        
        import json
        run_params = schedule.get("run_parameters")
        if run_params and isinstance(run_params, str):
            try:
                run_params = json.loads(run_params)
            except Exception as e:
                logger.error(f"Failed to parse run_parameters for schedule {schedule_id}: {e}")
                run_params = {}
        
        if run_params is None:
            run_params = {}

        logger.info(f"Triggering scheduled run for Schedule {schedule_id} [Workflow {workflow_id}] with params: {run_params}")

        # Check if daily vendor outreach workflow
        is_daily_outreach = schedule.get("workflow_key") == "daily_vendor_outreach" or run_params.get("trigger_type") == "daily"
        
        try:
            if is_daily_outreach:
                # Load primary and backup candidates based on outreach flags and credentials
                candidates = await self._load_candidates(schedule_id)
                primary, backups = self._pick_primary_and_backups(candidates)
                
                if not primary:
                    logger.warning("No primary candidate scheduled for today.")
                    self._update_schedule_next_run(schedule_id, schedule)
                    return
                
                # Fetch workflow details to get recipient SQL
                workflow = self.workflow_client.get(workflow_id)
                if not workflow:
                    raise ValueError(f"Workflow {workflow_id} not found.")
                
                recipient_sql = workflow.get("recipient_list_sql")
                if not recipient_sql:
                    raise ValueError("Workflow missing recipient_list_sql.")
                
                # Resolve full recipient list
                all_emails = self.workflow_client.execute_sql(workflow_id, recipient_sql, run_params)
                
                if not all_emails:
                    logger.info("No recipients found for daily outreach workflow.")
                    self._update_schedule_next_run(schedule_id, schedule)
                    return
                
                # Split into chunks: primary candidate gets first daily_outreach_limit (default 250)
                primary_limit = primary.get("daily_outreach_limit", 250)
                backup_ids = [c["id"] for c in backups]
                
                candidate_chunks = self._chunk_emails(all_emails, primary["id"], backup_ids, primary_limit)
                
                # Format primary and backups information for report mailer
                primary_name = primary.get("candidate_name") or primary.get("full_name") or f"ID #{primary['id']}"
                primary_str = f"{primary_name} ({primary.get('email')})"
                
                backup_strings = []
                for bc in backups:
                    bc_name = bc.get("candidate_name") or bc.get("full_name") or f"ID #{bc['id']}"
                    backup_strings.append(f"{bc_name} ({bc.get('email')})")
                backups_str = ", ".join(backup_strings) if backup_strings else "None"

                # Run outreach for each candidate chunk concurrently
                tasks = []
                chunk_candidates = []
                for cid, chunk in candidate_chunks.items():
                    if not chunk:
                        continue
                    
                    c_ctx = run_params.copy()
                    c_ctx["candidate_id"] = cid
                    c_ctx["primary_candidate"] = primary_str
                    c_ctx["backup_candidates"] = backups_str
                    
                    try:
                        c_creds = self.workflow_executor.engine_client.get_candidate_credentials(cid)
                        c_ctx["candidate_credentials"] = c_creds
                        c_ctx["candidate_name"] = c_creds.get("candidate_name")
                        c_ctx["candidate_email"] = c_creds.get("email")
                    except Exception as e:
                        logger.error(f"Failed to fetch credentials for candidate {cid}: {e}")
                        continue
                    
                    chunk_candidates.append((cid, len(chunk)))
                    tasks.append(
                        self.workflow_executor.execute_workflow(
                            workflow_id=workflow_id,
                            run_id=f"{run_id}_{cid}",
                            schedule_id=schedule_id,
                            execution_context=c_ctx,
                            override_recipients=chunk
                        )
                    )
                
                if tasks:
                    logger.info(f"Launching daily outreach chunks concurrently for: {chunk_candidates}")
                    results = await asyncio.gather(*tasks)
                    # Update metrics for successful runs
                    for res, (cid, chunk_len) in zip(results, chunk_candidates):
                        if res and res.get("status") == "success":
                            sent_count = res.get("processed", 0)
                            self._update_candidate_metrics(cid, sent_count)
                
                primary_sent = 0
                if 'results' in locals() and results:
                    for res, (cid, chunk_len) in zip(results, chunk_candidates):
                        if cid == primary["id"] and res and res.get("status") == "success":
                            primary_sent = res.get("processed", 0)
                
                primary_info = {
                    "candidate_id": primary["id"],
                    "candidate_name": primary.get("candidate_name") or primary.get("full_name") or "Candidate",
                    "email": primary.get("email"),
                    "daily_outreach_limit": primary_limit,
                    "fcount": primary.get("fcount", 0) + 1,
                    "total_outreach_count": primary.get("total_outreach_count", 0) + primary_sent
                }
                self._update_schedule_next_run(schedule_id, schedule, run_params=primary_info)
                
            else:
                # Regular schedule run
                result = await self.workflow_executor.execute_workflow(
                    workflow_id=workflow_id,
                    run_id=run_id,
                    schedule_id=schedule_id,
                    execution_context=run_params
                )
                self._update_schedule_next_run(schedule_id, schedule, success=(result and result.get("status") == "success"))
                
        except Exception as e:
            logger.error(f"Scheduled run failed for Schedule {schedule_id}: {e}")
            self.schedule_client.update(schedule_id, {"is_running": 0})
        finally:
            # Final safety check to unlock if not updated by client
            try:
                latest = self.schedule_client.get(schedule_id)
                if latest and latest.get("is_running"):
                    self.schedule_client.update(schedule_id, {"is_running": 0})
            except:
                pass

    def _update_schedule_next_run(self, schedule_id: int, schedule: dict, success: bool = True, run_params: dict = None):
        updates = {
            "last_run_at": utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            "is_running": 0
        }

        if run_params is not None:
            updates["run_parameters"] = run_params
        elif success:
            updates["run_parameters"] = None
        
        # Calculate next run based on frequency
        current_next = schedule.get("next_run_at")
        if current_next:
            current_next_dt = datetime.fromisoformat(current_next) if isinstance(current_next, str) else current_next
            freq = schedule.get("frequency", "daily").lower()
            delta = timedelta(days=1)
            if freq == "weekly":
                delta = timedelta(weeks=1)
            elif freq == "monthly":
                delta = timedelta(days=30)
            now_utc = utcnow().replace(tzinfo=None)
            while current_next_dt <= now_utc:
                current_next_dt += delta
            updates["next_run_at"] = current_next_dt.strftime('%Y-%m-%d %H:%M:%S')
            
        self.schedule_client.update(schedule_id, updates)

    def _update_candidate_metrics(self, candidate_id: int, sent_count: int):
        import sys
        import os
        backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "wbl-backend"))
        if backend_path not in sys.path:
            sys.path.append(backend_path)
            
        from fapi.db.database import SessionLocal
        from fapi.db.models import CandidateMarketingORM
        
        db = SessionLocal()
        try:
            marketing = db.query(CandidateMarketingORM).filter(
                CandidateMarketingORM.candidate_id == candidate_id,
                CandidateMarketingORM.status == "active"
            ).first()
            if marketing:
                marketing.fcount += 1
                marketing.total_outreach_count += sent_count
                
                # Advance outreach_date to tomorrow
                marketing.outreach_date = date.today() + timedelta(days=1)
                
                # Check if max limit reached
                if marketing.total_outreach_count >= marketing.max_outreach_limit:
                    marketing.run_daily_workflow = False
                    logger.info(f"Candidate {candidate_id} reached max outreach limit ({marketing.max_outreach_limit}). Disabled daily program.")
                
                db.commit()
                logger.info(f"Updated Candidate {candidate_id} metrics: fcount={marketing.fcount}, total_outreach={marketing.total_outreach_count}, next_date={marketing.outreach_date}")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update metrics for candidate {candidate_id}: {e}")
        finally:
            db.close()

    async def _load_candidates(self, schedule_id: int):
        """Load primary and backup candidates for outreach."""
        import sys
        import os
        backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "wbl-backend"))
        if backend_path not in sys.path:
            sys.path.append(backend_path)
            
        from fapi.utils.candidate_utils import get_candidates_for_outreach, get_backup_candidates
        primary_candidates = get_candidates_for_outreach()
        primary_ids = [c["id"] for c in primary_candidates]
        backups = get_backup_candidates(exclude_ids=primary_ids)
        return primary_candidates + backups

    def _pick_primary_and_backups(self, candidates):
        """Separate primary candidate and backup list (max 5 backups)."""
        primary = None
        backups = []
        for c in candidates:
            if c.get("run_daily_workflow") and primary is None:
                primary = c
            else:
                backups.append(c)
        backups = backups[:5]
        return primary, backups

    def _chunk_emails(self, all_emails, primary_id, backup_ids, primary_limit):
        """Allocate primary_limit emails to primary and split remainder among backups."""
        allocation = {primary_id: []}
        for bid in backup_ids:
            allocation[bid] = []
            
        primary_emails = all_emails[:primary_limit]
        allocation[primary_id] = primary_emails
        remaining = all_emails[primary_limit:]
        
        if backup_ids and remaining:
            per_backup = len(remaining) // len(backup_ids)
            extra = len(remaining) % len(backup_ids)
            idx = 0
            for bid in backup_ids:
                count = per_backup + (1 if idx < extra else 0)
                allocation[bid] = remaining[:count]
                remaining = remaining[count:]
                idx += 1
        return allocation
