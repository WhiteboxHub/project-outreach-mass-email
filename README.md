# Outreach Service

A robust, async-first email outreach service built with **FastAPI**, **Python 3.13**, and **Pydantic**. Designed for high-throughput, reliable mass email delivery with strict safety controls.

## Features

### Core Architecture
- **Async Execution**: Powered by `asyncio` for non-blocking I/O.
- **Concurrency Control**: Semaphores limit parallel execution per batch.
- **Rate Limiting**: Token Bucket algorithm ensures compliance with provider limits.
- **State Machine**: granular execution states (`QUEUED`, `INITIALIZING`, `SENDING`, `COMPLETED`, `FAILED`).

### Reliability & Safety
- **Smart Retries**: Exponential backoff with jitter for transient errors (network, 429s).
- **Template Safety**: Strict Jinja2 rendering (fails on missing variables) and pre-validation.
- **Engine Hardening**: Strict validation of sender configuration (SMTP, SendGrid, SES, Mailgun).
- **Global Timeout**: Enforced execution deadlines to prevent hung processes.

### Scheduling
- **Built-in Scheduler**: Background loop to poll and trigger scheduled workflows.
- **Idempotency**: Prevents duplicate executions for the same schedule slot.

### Observability
- **Structured Logging**: Detailed JSON execution logs stored in `output/<date>/<run_id>.json`.
- **Mock Clients**: Simulates backend dependencies for easy testing and development.

## Project Structure

```
├── api_clients/        # Mock API clients (Workflow, Template, Engine, Schedule, Log)
├── executor/           # Core Logic
│   ├── workflow_executor.py  # Main async orchestration
│   ├── engine_builder.py     # Factory for email senders
│   ├── template_renderer.py  # Jinja2 wrapper with validation
│   └── recipient_resolver.py # SQL-to-Recipient resolver
├── models/             # Pydantic data models
├── scheduler/          # Background scheduler
├── senders/            # Email provider implementations (Mocked)
├── tests/              # Pytest suite
├── utils/              # Shared utilities (Retry, RateLimiter, Time, Idempotency)
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
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Running the Application

Start the FastAPI server (and the background scheduler):

```bash
uvicorn app:app --reload
```

- **Health Check**: `GET http://127.0.0.1:8000/health`
- **Trigger Workflow**: `POST http://127.0.0.1:8000/api/v1/trigger`

Example Payload:
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

## Configuration

- **Delivery Engines**: Configured via Mock API (see `api_clients/delivery_engine_client.py`).
- **Schedules**: Configured via Mock API (see `api_clients/schedule_client.py`).
- **Templates**: html/text templates via Mock API (see `api_clients/template_client.py`).

## Logging

Execution results are saved to disk:
`output/YYYY-MM-DD/<run_id>.json`

Each log contains:
- Workflow & Template Metadata
- Execution Summary (Success/Fail counts)
- Engine Configuration (Redacted)
- Recipient-level status (Success/Failed)
