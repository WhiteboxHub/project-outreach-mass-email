from typing import Dict, Any
from api_clients.delivery_engine_client import EngineType
from senders.base_sender import BaseSender
from senders.smtp_sender import SMTPSender
from senders.ses_sender import AWSSESSender
from senders.sendgrid_sender import SendGridSender
from senders.mailgun_sender import MailgunSender


class EngineBuilder:

    @staticmethod
    def validate_config(config: Dict[str, Any]):
        """Validates engine configuration. Raises ValueError if invalid."""
        engine_type = config.get("engine_type")
        if not engine_type:
            raise ValueError("Missing 'engine_type' in configuration.")

        if "from_email" not in config:
            raise ValueError("Missing 'from_email' in configuration.")

        if engine_type == EngineType.AWS_SES:
            has_creds = (
                ("username" in config and "password" in config) or
                ("aws_access_key_id" in config and "aws_secret_access_key" in config) or
                ("region_name" in config or "aws_region" in config)
            )
            if not has_creds:
                raise ValueError("AWS SES requires credentials (aws_access_key_id/secret or username/password) or region")
        elif engine_type == EngineType.SENDGRID:
            if "api_key" not in config:
                raise ValueError("SendGrid requires 'api_key'")
        elif engine_type == EngineType.MAILGUN:
            if "api_key" not in config:
                raise ValueError("Mailgun requires 'api_key'")

    @staticmethod
    def build(engine_config: Dict[str, Any]) -> BaseSender:
        # Reject inactive engines
        if engine_config.get("status", "active") != "active":
            raise ValueError(f"Engine '{engine_config.get('name')}' is not active.")

        # Normalise engine_type string to Enum
        e_type = engine_config.get("engine_type")
        if isinstance(e_type, str):
            try:
                engine_config["engine_type"] = EngineType(e_type)
            except ValueError:
                engine_config["engine_type"] = EngineType(e_type.lower())

        EngineBuilder.validate_config(engine_config)

        engine_type = engine_config.get("engine_type")
        if engine_type == EngineType.SMTP:
            return SMTPSender(engine_config)
        elif engine_type == EngineType.MAILGUN:
            return MailgunSender(engine_config)
        elif engine_type == EngineType.SENDGRID:
            return SendGridSender(engine_config)
        elif engine_type == EngineType.AWS_SES:
            return AWSSESSender(engine_config)
        else:
            # Default: treat as SMTP (covers candidate_smtp mode)
            return SMTPSender(engine_config)
