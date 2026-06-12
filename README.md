# Outreach Service

A robust, async-first email outreach service built with **FastAPI**, **Python 3.13**, and **Pydantic**. Designed for high-throughput, reliable mass email delivery with strict safety controls.

## Features

### Core Architecture
- **Async Execution**: Powered by `asyncio` for non-blocking I/O.
- **Concurrency Control**: Semaphores limit parallel execution per batch.
- **Rate Limiting**: Token Bucket algorithm ensures compliance with provider limits.
- **State Machine**: Granular execution states (`QUEUED`, `INITIALIZING`, `SENDING`, `COMPLETED`, `FAILED`).

### Reliability & Safety
- **Smart Retries**: Exponential backoff with jitter for transient errors (network, 429s).
- **Template Safety**: Strict Jinja2 rendering (fails on missing variables) and pre-validation.
- **Engine Hardening**: Strict validation of sender configuration (SMTP, SendGrid, SES, Mailgun).
- **Email Validation**: Pre-flight checks ensure emails have valid syntax and MX records before attempting delivery.

## Project Structure

```
├── api_clients/        # Internal API clients (Workflow, Template, Engine, Schedule, Log)
├── executor/           # Core Logic
│   ├── workflow_executor.py  # Main async orchestration
│   ├── engine_builder.py     # Factory for email senders
│   ├── template_renderer.py  # Jinja2 wrapper with validation
│   └── recipient_resolver.py # SQL-to-Recipient resolver
├── models/             # Pydantic data models
├── scheduler/          # Background scheduler
├── senders/            # Email provider implementations
├── tests/              # Pytest suite
├── utils/              # Shared utilities (Retry, RateLimiter, Validation)
├── app.py              # FastAPI application entry point
└── requirements.txt    # Dependencies
```

## Getting Started

### Prerequisites
- Python 3.13+
- Virtual Environment recommended

### Installation

```bash
# Create venv
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables (`.env`)
You must create a `.env` file in the root directory. This configures the backend connection and the SMTP account used to send the **Summary Reports** (not the actual outreach emails, which are configured in the DB).

Create a file named `.env` and configure it like this:

```env
WBL_BACKEND_URL=https://api.whitebox-learning.com/api
LOG_LEVEL=INFO

# --- Run Report Email Configuration ---
# The address that will receive the final summary report
REPORT_EMAIL_TO=your_email@domain.com

# The authenticated SMTP account that sends the report
REPORT_EMAIL_FROM=report_sender@domain.com
REPORT_SMTP_HOST=smtp.gmail.com
REPORT_SMTP_PORT=587
REPORT_SMTP_USER=report_sender@domain.com
REPORT_SMTP_PASSWORD=your_16_digit_app_password
```

## Running the Application

### 1. Dry Run Validation (Previewing a Campaign)
Before sending real emails, you can simulate a run. This fetches today's recipients from the database and runs validation (Syntax + MX Record checks) to show you exactly who will receive the email and who has an invalid email address. 

**No emails are actually sent during this process.**

```bash
python dry_run_validation.py
```

### 2. Run a One-Off Execution (`run_once.py`)
If you want to manually trigger the automated outreach schedule without standing up the full API server, you can use the `run_once.py` script. This script executes `ScheduleRunner`, checks if the designated schedule (e.g., Schedule ID 1) is due, runs the corresponding workflow, and automatically advances the "Next Run At" date in the database.

```bash
python run_once.py
```

### 3. Start the API Server & Background Scheduler
Start the FastAPI server (which also boots up the background polling scheduler to execute scheduled outreach runs).

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

- **Health Check**: `GET http://127.0.0.1:8000/health`
- **Manual Trigger**: `POST http://127.0.0.1:8000/api/v1/trigger`

Example Trigger Payload:
```json
{
  "workflow_id": 1
}
```

### Running Tests

Execute the full test suite with `pytest`:

```bash
python -m pytest
```
