from typing import Any, Dict, List, Optional
from api_clients.base_client import BaseClient

class TemplateClient(BaseClient):
    # Mock Data from prompt
    MOCK_DATA = [
        {
            "id": 1,
            "template_key": "daily_vendor_outreach",
            "name": "Daily Candidate Introduction",
            "subject": "Introduction: {{candidate_name}} | Principal ML Engineer",
            "content_html": "<html><body><p>Hi {{contact_name}},</p><p>I am reaching out to introduce myself. I am a Principal Machine Learning Engineer currently exploring new opportunities. I saw your recent postings and believe my background in AI/ML would be a great fit for your clients.</p><p>You can view my full profile here: <a href=\"{{linkedin_url}}\">{{linkedin_url}}</a></p><p>Best regards,<br>{{candidate_name}}</p></body></html>",
            "content_text": "Hi {{contact_name}}, I am {{candidate_name}}, a Principal ML Engineer exploring new opportunities. View my profile: {{linkedin_url}}",
            "parameters": ["contact_name", "candidate_name", "linkedin_url"],
            "status": "active"
        },
        {
            "id": 2,
            "template_key": "weekly_vendor_outreach",
            "name": "Detailed Weekly Candidate Profile",
            "subject": "ML Engineering Talent - {{candidate_name}} - Project Portfolio",
            "content_html": "<html><body><p>Hello {{contact_name}},</p><p>I wanted to follow up and share more detail regarding my technical expertise. I specialize in <b>Agentic AI, RAG-based applications, and MLOps</b>.</p><p>I have successfully led projects in {{specialty_area}}, and I am now looking for my next challenge. I would love to discuss how my skills can help your current requirements.</p><p>LinkedIn: {{linkedin_url}}</p><p>Thank you,<br>{{candidate_name}}</p></body></html>",
            "content_text": "Hello {{contact_name}}, I specialize in Agentic AI and RAG. I am looking for new roles. LinkedIn: {{linkedin_url}}",
            "parameters": ["contact_name", "candidate_name", "linkedin_url", "specialty_area"],
            "status": "active"
        }
    ]

    def get(self, resource_id: int) -> Optional[Dict[str, Any]]:
        return next((item for item in self.MOCK_DATA if item["id"] == resource_id), None)

    def list(self, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        return self.MOCK_DATA
