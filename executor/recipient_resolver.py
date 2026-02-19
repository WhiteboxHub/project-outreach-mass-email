from typing import List, Dict, Any, Tuple
from models.recipient import Recipient
from api_clients.workflow_client import WorkflowClient
from utils.email_validator_lite import validate_emails
import logging

logger = logging.getLogger("outreach_service")

class RecipientResolver:
    """
    Resolves recipients by calling the backend API to execute SQL,
    then filters out invalid email addresses (bad syntax or no MX record)
    before returning the final recipient list to the sending engine.

    resolve() returns a Tuple:
      [0] valid_recipients  – Recipient objects ready to be emailed
      [1] invalid_emails    – raw email strings that failed validation (skipped)

    The caller (WorkflowExecutor) uses invalid_emails to include the skipped
    count in the run-report email.
    """

    def __init__(self):
        self.workflow_client = WorkflowClient()

    def resolve(
        self,
        workflow_id: int,
        recipient_sql: str,
        parameters: Dict[str, Any] = {},
    ) -> Tuple[List[Recipient], List[str]]:
        """
        Returns (valid_recipients, invalid_emails).
        """
        raw_recipients: List[Recipient] = []
        try:
            result = self.workflow_client.execute_sql(workflow_id, recipient_sql, parameters)

            for data in result:
                email = data.get("recipient_email") or data.get("email")
                name  = data.get("recipient_name") or data.get("name") or data.get("contact_name")

                metadata = data.copy()
                metadata.pop("recipient_email", None)

                if email:
                    raw_recipients.append(Recipient(
                        email=email.strip().lower(),
                        name=name,
                        metadata=metadata,
                    ))

        except Exception as e:
            logger.error(f"Error resolving recipients: {e}")
            return [], []

        if not raw_recipients:
            return [], []

        # ── Email Validation (Syntax + MX) ────────────────────────────────────
        raw_emails = [r.email for r in raw_recipients]
        logger.info(f"[Validator] Validating {len(raw_emails)} recipient emails before sending...")

        valid_emails_list, invalid_list = validate_emails(raw_emails, skip_mx=False)
        valid_set = set(valid_emails_list)

        if invalid_list:
            logger.warning(
                f"[Validator] ⚠ Skipping {len(invalid_list)} invalid email(s): "
                + ", ".join(invalid_list[:10])
                + (" ..." if len(invalid_list) > 10 else "")
            )

        valid_recipients = [r for r in raw_recipients if r.email in valid_set]
        logger.info(
            f"[Validator] ✔ {len(valid_recipients)} valid | "
            f"✗ {len(invalid_list)} invalid (skipped before sending)"
        )
        return valid_recipients, invalid_list
