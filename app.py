from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict
import os
import json
import logging
import time
from csv_loader import CSVLoader
from email_factory import EmailFactory

import traceback
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging to file and console
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('email.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("email_program")

logger.info("=" * 80)
logger.info("EMAIL SERVICE STARTING")
logger.info("=" * 80)

app = FastAPI(title="Standalone Email Program")

class Recipient(BaseModel):
    email: str
    unsubscribe_link: Optional[str] = None

class EmailEngine(BaseModel):
    provider: str
    credentials_json: Dict

class EmailProgramPayload(BaseModel):
    job_run_id: int
    job_type: str
    candidate_info: dict
    recipients: Optional[List[Recipient]] = []
    engine: EmailEngine
    config_json: dict = {}

# Initialize components
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
email_factory = EmailFactory(TEMPLATE_DIR)
csv_loader = CSVLoader(os.path.dirname(os.path.abspath(__file__)))

@app.post("/send")
async def send_emails(payload: EmailProgramPayload):
    job_type = payload.job_type.upper()
    logger.info("=" * 80)
    logger.info(f"RECEIVED SEND REQUEST")
    logger.info(f"   Job Run ID: {payload.job_run_id}")
    logger.info(f"   Job Type: {payload.job_type}")
    logger.info(f"   Recipients Count: {len(payload.recipients)}")
    logger.info("=" * 80)
    
    try:
        # 1. Determine Recipient Source
        recipient_source = payload.config_json.get("recipient_source", "CSV").upper()
        logger.info(f"Detected Recipient Source: {recipient_source}")
        
        if recipient_source == "CSV":
            logger.info(f"Step 1: Loading recipients from CSV")
            csv_file = payload.config_json.get("csv_filename")
            
            if not csv_file:
                if job_type in ["MASS_EMAIL", "VENDOR_OUTREACH"]:
                    csv_file = "vendors.csv"
                elif job_type in ["LEADS", "NEWSLETTER", "LEAD_GENERATION"]:
                    csv_file = "leads.csv"
                else:
                    csv_file = "vendors.csv"
            
            logger.info(f"[Email Service] Sending from CSV: {csv_file}")
            
            try:
                eligible_recipients = csv_loader.get_eligible_emails(csv_file)
                logger.info(f"CSV loaded: {len(eligible_recipients) if eligible_recipients else 0} eligible recipients")
                
                if not eligible_recipients:
                    logger.warning(f"No eligible emails found in {csv_file}")
                    return {
                        "status": "SUCCESS",
                        "message": "No eligible recipients found in CSV",
                        "items_total": 0,
                        "items_succeeded": 0,
                        "items_failed": 0
                    }
                
                # IMPORTANT: Convert string list to Recipient objects and update payload
                payload.recipients = [Recipient(email=email) for email in eligible_recipients]
                logger.info(f"Updated payload with {len(payload.recipients)} recipients from CSV")
                
            except Exception as e:
                logger.error(f"CSV loading failed: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                return {
                    "status": "FAILED",
                    "message": f"CSV error: {str(e)}",
                    "items_total": 0,
                    "items_succeeded": 0,
                    "items_failed": 0
                }
        else:
            logger.info(f"[Email Service] Using recipients from Outreach Database (Count: {len(payload.recipients)})")
        
        # 2. Get sender
        logger.info(f"Step 2: Initializing email sender")
        logger.info(f"   Provider: {payload.engine.provider}")
        
        try:
            sender = email_factory.get_sender(payload.engine.provider, payload.engine.credentials_json)
            logger.info(f"Sender initialized: {payload.engine.provider}")
        except Exception as e:
            logger.error(f"Sender initialization failed: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "status": "FAILED",
                "message": f"Invalid engine configuration: {str(e)}",
                "items_total": len(payload.recipients),
                "items_succeeded": 0,
                "items_failed": len(payload.recipients)
            }

        # 3. Determine recipients
        recipients_to_process = payload.recipients
        items_total = len(recipients_to_process)
        items_succeeded = 0
        items_failed = 0
        
        logger.info(f"Step 3: Processing {items_total} recipients")
        
        # 4. Process provided recipients
        for idx, recipient in enumerate(recipients_to_process):
            # --- REAL-TIME STOP CHECK ---
            try:
                prod_url = os.getenv("PROD_API_URL")
                if prod_url:
                    status_resp = requests.get(f"{prod_url}/api/remote/runs/{payload.job_run_id}/status", timeout=5)
                    if status_resp.status_code == 200:
                        status_data = status_resp.json()
                        current_status = status_data.get("status")
                        if current_status not in ["RUNNING", "PENDING"]:
                            logger.warning(f"!!! Job {payload.job_run_id} status changed to {current_status}. Stopping execution immediately.")
                            break
            except Exception as se:
                logger.warning(f"Could not verify job status: {se}. Continuing...")

            email_addr = recipient.email.strip().lower()
            logger.debug(f"   [{idx+1}/{items_total}] Processing: {email_addr}")
            
            try:
                # Construct unsubscribe link if not provided or override from local env
                unsub_link = recipient.unsubscribe_link
                env_unsub_url = os.getenv("PUBLIC_UNSUBSCRIBE_URL")
                
                if env_unsub_url:
                    unsub_link = f"{env_unsub_url}?email={email_addr}"
                elif not unsub_link:
                    unsub_link = f"/solutions/unsubscribe-success?email={email_addr}"

                # Prepare context for template
                context = {
                    "full_name": payload.candidate_info.get("full_name", ""),
                    "candidate_intro": payload.candidate_info.get("candidate_intro", ""),
                    "candidate_email": payload.candidate_info.get("candidate_email", ""),
                    "linkedin_id": payload.candidate_info.get("linkedin_id", ""),
                    "unsubscribe_link": unsub_link,
                    "recipient_email": email_addr
                }
                
                # Determine folder based on job type
                folder = "mass_email"
                if job_type in ["LEADS", "NEWSLETTER", "LEAD_GENERATION"]:
                    folder = "leads"
                
                logger.debug(f"       → Rendering templates from folder: {folder}")
                
                subject = email_factory.render_template(folder, "subject.txt", context)
                body_html = email_factory.render_template(folder, "body.html.j2", context)
                body_txt = email_factory.render_template(folder, "body.txt.j2", context)
                
                logger.debug(f"       → Templates rendered successfully")
                
                headers = {}
                # if recipient.unsubscribe_link:
                #     headers["List-Unsubscribe"] = f"<{recipient.unsubscribe_link}>"
                #     headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

                logger.debug(f"       → Sending via {payload.engine.provider}...")
                try:
                    success = sender.send(
                        from_email=payload.engine.credentials_json.get("from_email", "noreply@example.com"),
                        from_name=payload.candidate_info.get("full_name", ""),
                        reply_to=payload.candidate_info.get("reply_to_email", ""),
                        to_email=email_addr,
                        subject=subject,
                        html_body=body_html,
                        text_body=body_txt,
                        headers=headers
                    )
                    
                    if success:
                        items_succeeded += 1
                        logger.info(f"       Email sent to {email_addr}")
                    else:
                        items_failed += 1
                        logger.error(f"       Failed to send email to {email_addr}")
                except Exception as send_err:
                    items_failed += 1
                    logger.error(f"       Error sending to {email_addr}: {send_err}")

            except Exception as e:
                items_failed += 1
                logger.error(f"       Unexpected error for {email_addr}: {e}")
                logger.error(traceback.format_exc())

            # Add delay between emails if there are more to send
            email_delay = int(os.getenv("EMAIL_DELAY", "10"))
            if idx < items_total - 1:
                logger.debug(f"Waiting {email_delay} seconds before next email...")
                time.sleep(email_delay)

        logger.info("=" * 80)
        logger.info(f"SEND COMPLETE")
        logger.info(f"   Total: {items_total}")
        logger.info(f"   Succeeded: {items_succeeded}")
        logger.info(f"   Failed: {items_failed}")
        logger.info("=" * 80)
        
        return {
            "status": "SUCCESS",
            "message": f"Processed {items_total} recipients",
            "items_total": items_total,
            "items_succeeded": items_succeeded,
            "items_failed": items_failed,
            "run_status": "COMPLETED"
        }

    except Exception as e:
        logger.error(f"Global send error: {e}")
        logger.error(traceback.format_exc())
        return {
            "status": "FAILED",
            "message": str(e),
            "items_total": 0,
            "items_succeeded": 0,
            "items_failed": 0
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)
