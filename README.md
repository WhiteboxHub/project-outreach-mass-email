# Email Program - Local Worker

A standalone email service that polls the production backend for scheduled email jobs and sends emails via Mailgun/AWS SES.

## Prerequisites

- **Python 3.8+**
- **pip** (Python package manager)
- A stable internet connection.

## Installation

1. Navigate to the `email_program` directory.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Duplicate the `.env` file (if not already present) and configure the following variables:

- `PROD_API_URL`: The URL of your WBL Backend (e.g., `http://your-server-ip:8000`).
- `LOCAL_EMAIL_URL`: Usually `http://localhost:8050/send`.
- `POLL_INTERVAL`: How often to check for new jobs (defualt: 10 seconds).
- `EMAIL_DELAY`: Delay in seconds between each email sent (to prevent spam flags).

## Running the Program

To start the local worker and the internal email service:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure .env file
PROD_API_URL=https://api.whitebox-learning.com
LOCAL_EMAIL_URL=http://localhost:8050/send
POLL_INTERVAL=10
EMAIL_DELAY=20
PUBLIC_UNSUBSCRIBE_URL=<your-candidate-unsubscribe-url>
UNSUBSCRIBE_URL=<your-leads-unsubscribe-url>

# 3. Run the worker
python3 local_worker.py
```

The worker will start polling for jobs automatically. Press `Ctrl+C` to stop.
