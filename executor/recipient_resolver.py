from typing import List, Dict, Any
from models.recipient import Recipient

class RecipientResolver:
    """
    Mocks the resolution of recipients based on 'SQL' queries.
    In a real scenario, this would execute the SQL against the database.
    Here, we parse the intent or return mock data based on the prompt.
    """
    
    def resolve(self, recipient_sql: str) -> List[Recipient]:
        # Mock logic based on the sample SQL provided in the prompt
        
        if "daily_outreach_flag = 1" in recipient_sql:
            # Mock for Daily Vendor Outreach
            return [
                Recipient(
                    email="vendor1@example.com",
                    name="John Vendor",
                    metadata={
                        "contact_name": "John Vendor",
                        "candidate_name": "Sampath Velupula",
                        "linkedin_url": "https://linkedin.com/in/sampath"
                    }
                ),
                 Recipient(
                    email="vendor2@example.com",
                    name="Jane Supplier",
                    metadata={
                        "contact_name": "Jane Supplier",
                        "candidate_name": "Sampath Velupula",
                        "linkedin_url": "https://linkedin.com/in/sampath"
                    }
                )
            ]
        elif "weekly_outreach_flag = 1" in recipient_sql:
            # Mock for Weekly
            return [
                Recipient(
                    email="recruiter1@agency.com",
                    name="Recruiter Bob",
                    metadata={
                        "contact_name": "Recruiter Bob",
                        "candidate_name": "Sampath Velupula",
                        "linkedin_url": "https://linkedin.com/in/sampath",
                        "specialty_area": "MLOps"
                    }
                )
            ]
        
        return []
