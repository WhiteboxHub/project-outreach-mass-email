"""
dry_run_validation.py
─────────────────────
DRY RUN: Fetches today's recipients for Workflow #1 and runs email validation.
NO EMAILS ARE SENT. This just shows you:
  - How many recipients were fetched from the DB
  - How many passed validation (valid syntax + MX)
  - How many are invalid (would be skipped on a real run)
  - The actual list of invalid emails

Run with:
    python3 dry_run_validation.py
"""

import sys, os
import pathlib

# Make paths dynamic to work on any OS (Mac, Windows, Linux)
SCRIPT_DIR = str(pathlib.Path(__file__).parent.absolute())
sys.path.insert(0, SCRIPT_DIR)
os.chdir(SCRIPT_DIR)

from dotenv import load_dotenv
load_dotenv()

import requests, json
from utils.email_validator_lite import validate_emails

BASE = os.getenv("WBL_BACKEND_URL", "https://api.whitebox-learning.com/api")
WORKFLOW_ID = 1

print("=" * 60)
print("  DRY RUN — Email validation check (no emails will be sent)")
print("=" * 60)

# 1. Fetch workflow to get the recipient SQL
print(f"\n[1] Fetching Workflow #{WORKFLOW_ID}...")
wf = requests.get(f"{BASE}/orchestrator/workflows/{WORKFLOW_ID}").json()
print(f"    Name: {wf.get('name')}")
sql = wf.get("recipient_list_sql", "")
print(f"    SQL:\n{sql}\n")

# 2. Execute the SQL to get recipients
print(f"[2] Executing recipient SQL via API...")
resp = requests.post(
    f"{BASE}/orchestrator/workflows/{WORKFLOW_ID}/execute-recipient-sql",
    json={"sql_query": sql, "parameters": {}}
)
if resp.status_code != 200:
    print(f"    ❌ API error {resp.status_code}: {resp.text[:300]}")
    sys.exit(1)

rows = resp.json()
print(f"    ✔ Got {len(rows)} rows from DB")

# 3. Extract emails
emails = []
for row in rows:
    email = row.get("email") or row.get("recipient_email")
    if email:
        emails.append(email.strip().lower())

print(f"\n[3] Extracted {len(emails)} email addresses from result")

if not emails:
    print("    ⚠ No emails found — nothing to validate.")
    sys.exit(0)

# 4. Run validation
print(f"\n[4] Running validation (syntax + MX check)...")
print(f"    This may take 10-30s for DNS lookups...\n")
valid, invalid = validate_emails(emails, skip_mx=False)

# 5. Report
print("\n" + "=" * 60)
print("  VALIDATION RESULTS")
print("=" * 60)
print(f"  Total fetched  : {len(emails)}")
print(f"  ✔ Valid        : {len(valid)} — will be emailed")
print(f"  ✗ Invalid      : {len(invalid)} — would be SKIPPED")
pct = int(len(valid) / len(emails) * 100) if emails else 0
print(f"  Delivery rate  : {pct}%")

if invalid:
    print(f"\n  Invalid emails (would be skipped):")
    for i, e in enumerate(invalid, 1):
        print(f"    {i:3}. {e}")

print("\n" + "=" * 60)
print("  DRY RUN COMPLETE — No emails were sent.")
print("=" * 60)
