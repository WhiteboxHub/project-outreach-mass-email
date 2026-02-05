# Email Program - Local Worker

A standalone email service that polls the production backend for scheduled email jobs and sends emails via Mailgun/AWS SES.

## What It Does
- Polls the backend API every 10 seconds for due email jobs
- Loads recipient lists from CSV files (`vendors.csv`, `leads.csv`)
- Sends personalized emails using Jinja2 templates
- Reports job completion status back to the backend

## How to Run
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure .env file
PROD_API_URL=https://api.whitebox-learning.com
PUBLIC_UNSUBSCRIBE_URL=<your-candidate-unsubscribe-url>
UNSUBSCRIBE_URL=<your-leads-unsubscribe-url>

# 3. Run the worker
python3 local_worker.py
```

The worker will start polling for jobs automatically. Press `Ctrl+C` to stop.
