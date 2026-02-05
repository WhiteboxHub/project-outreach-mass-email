import csv
import os
import logging
from typing import Set

logger = logging.getLogger(__name__)

class CSVLoader:
    def __init__(self, base_path: str = "."):
        self.base_path = base_path

    def get_eligible_emails(self, filename: str) -> list:
        """
        Returns a list of emails for all rows where:
        unsubscribe_flag == 0 AND bounce_flag == 0 AND complaint_flag == 0
        """
        filepath = os.path.join(self.base_path, filename)
        eligible_emails = []
        seen = set()
        excluded_count = 0
        
        if not os.path.exists(filepath):
            logger.warning(f"CSV file not found: {filepath}")
            return eligible_emails

        try:
            with open(filepath, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    email = None
                    unsub = "0"
                    bounce = "0"
                    complaint = "0"
                    mass_sent = "0"
                    
                    for key, val in row.items():
                        k_low = key.lower()
                        if k_low == 'email':
                            email = val.strip().lower()
                        elif k_low == 'unsubscribe_flag' or k_low == 'massemail_unsubscribe':
                            unsub = str(val).strip()
                        elif k_low == 'bounce_flag':
                            bounce = str(val).strip()
                        elif k_low == 'complaint_flag':
                            complaint = str(val).strip()
                        elif k_low == 'massemail_email_sent':
                            mass_sent = str(val).strip()
                    
                    if email and email not in seen:
                        # Filter out if any flag is '1' (meaning opt-out, bounced, or already sent)
                        if unsub == "0" and bounce == "0" and complaint == "0" and mass_sent == "0":
                            eligible_emails.append(email)
                            seen.add(email)
                        else:
                            excluded_count += 1
                            
            if excluded_count > 0:
                logger.info(f"Excluded {excluded_count} emails based on flags (unsub/bounce/complaint) in {filename}")
                            
        except Exception as e:
            logger.error(f"Error reading CSV {filepath}: {e}")
            
        return eligible_emails
