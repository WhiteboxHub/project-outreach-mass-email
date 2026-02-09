import requests
import time
import logging
import os
import json
import asyncio
import multiprocessing
import uvicorn
from dotenv import load_dotenv
from csv_loader import CSVLoader
import traceback
from app import app  # Import the FastAPI app

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('worker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("local_orchestrator")

# Configuration
PROD_API_URL = os.getenv("PROD_API_URL", "")
LOCAL_EMAIL_URL = os.getenv("LOCAL_EMAIL_URL", "")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
CSV_ROOT = os.path.dirname(os.path.abspath(__file__))

loader = CSVLoader(CSV_ROOT)

def run_email_service():
    """Runs the FastAPI email service logic in a separate process"""
    logger.info("Starting Email Service API on port 8050...")
    uvicorn.run(app, host="0.0.0.0", port=8050, log_level="warning")

def process_job(job_info):
    schedule_id = job_info['id']
    logger.info(f"Processing Job Schedule: {schedule_id}")
    
    try:
        # 1. Fetch Full Context (Parameters)
        resp = requests.get(f"{PROD_API_URL}/api/remote/schedules/{schedule_id}/context", timeout=30)
        resp.raise_for_status()
        context = resp.json()
        
        job_run_id = context['job_run_id']
        job_type = context['job_type']
        
        # 2. Determine Recipients
        config = context.get('config_json', {})
        # Robust source detection
        raw_source = config.get("recipient_source", "CSV")
        recipient_source = str(raw_source).strip().upper()
        
        logger.info(f"Source Check: Raw='{raw_source}', Cleaned='{recipient_source}'")
        
        batch_recipients = []
        csv_offset = config.get('csv_offset', 0)
        
        if recipient_source == "OUTREACH_DB":
            db_recipients = context.get('db_recipients', [])
            logger.info(f"Mode: OUTREACH_DB - Using {len(db_recipients)} contacts from database")
            batch_recipients = db_recipients
            csv_offset = 0 # Offset doesn't apply to DB-sourced batches yet
        else:
            # CSV Logic
            batch_size = config.get('batch_size', 200)
            csv_filename = config.get("csv_filename")
            if not csv_filename:
                csv_filename = "vendors.csv" if job_type in ["MASS_EMAIL", "VENDOR_OUTREACH"] else "leads.csv"
            
            logger.info(f"Mode: CSV - Loading {csv_filename} at offset {csv_offset}")
            
            try:
                all_emails = loader.get_eligible_emails(csv_filename)
                start = csv_offset
                end = csv_offset + batch_size
                batch_recipients = all_emails[start:end]
                logger.info(f"Extracted {len(batch_recipients)} emails from CSV")
            except Exception as e:
                logger.error(f"CSV Error: {e}")
                return
        
        if not batch_recipients:
            logger.warning("No recipients found for this run.")
            return

        prepared_recipients = []
        for email in batch_recipients:
            prepared_recipients.append({"email": email})
            
        payload = {
            "job_run_id": job_run_id,
            "job_type": job_type,
            "candidate_info": context['candidate_info'],
            "recipients": prepared_recipients,
            "engine": context['engine'],
            "config_json": config
        }
        
        # 4. Dispatch to Local API (Self-hosted)
        logger.info(f"Dispatching {len(batch_recipients)} emails to service...")
        send_resp = requests.post(LOCAL_EMAIL_URL, json=payload, timeout=300)
        send_resp.raise_for_status()
        send_result = send_resp.json()
        
        # 5. Report Results to Production API
        # If it was CSV, we calculate new offset. If DB, offset stays same or as is.
        new_offset = csv_offset + len(batch_recipients) if recipient_source == "CSV" else csv_offset
        
        completion_data = {
            "job_run_id": job_run_id,
            "items_total": send_result.get("items_total", 0),
            "items_succeeded": send_result.get("items_succeeded", 0),
            "items_failed": send_result.get("items_failed", 0),
            "new_offset": new_offset
        }
        
        update_resp = requests.post(
            f"{PROD_API_URL}/api/remote/schedules/{schedule_id}/complete", 
            json=completion_data,
            timeout=30
        )
        update_resp.raise_for_status()
        logger.info(f"Job {schedule_id} reported complete.")

    except Exception as e:
        logger.error(f"Worker Error: {e}")

def poll_loop():
    """Main loop that polls the production API for due jobs"""
    logger.info(f"Polling: {PROD_API_URL}")
    while True:
        try:
            resp = requests.get(f"{PROD_API_URL}/api/remote/schedules/due", timeout=10)
            if resp.status_code == 200:
                jobs = resp.json()
                for job in jobs:
                    process_job(job)
        except Exception as e:
            logger.error(f"Poll Error: {e}")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    # Start Email Service logic in background
    service_process = multiprocessing.Process(target=run_email_service)
    service_process.start()
    
    try:
        time.sleep(2) 
        poll_loop()
    except KeyboardInterrupt:
        logger.info("Stopping...")
        service_process.terminate()
        service_process.join(timeout=3)
        if service_process.is_alive():
            logger.warning("Email service didn't stop. Forcing kill...")
            service_process.kill()
        logger.info("Stopped.")
