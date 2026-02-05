from jinja2 import Environment, FileSystemLoader
import os
import logging
from senders.smtp_sender import SMTPSender
from senders.aws_ses_sender import AWSSESSender
from senders.sendgrid_sender import SendGridSender
from senders.mailgun_sender import MailgunSender

logger = logging.getLogger(__name__)

class EmailFactory:
    def __init__(self, template_dir: str):
        self.env = Environment(loader=FileSystemLoader(template_dir))

    def get_sender(self, provider: str, credentials_json: dict):
        provider = provider.lower()
        if provider == "smtp":
            return SMTPSender(credentials_json)
        elif provider == "aws_ses":
            return AWSSESSender(credentials_json)
        elif provider == "sendgrid":
            return SendGridSender(credentials_json)
        elif provider == "mailgun":
            return MailgunSender(credentials_json)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    def render_template(self, job_type: str, template_name: str, context: dict):
        """
        job_type: leads or newsletter
        template_name: subject.txt, body.html.j2, body.txt.j2
        """
        template_path = os.path.join(job_type.lower(), template_name)
        logger.info(f"Loading template: {template_path}")
        try:
            template = self.env.get_template(template_path)
            return template.render(context)
        except Exception as e:
            logger.error(f"Failed to load template {template_path}: {e}")
            raise e
