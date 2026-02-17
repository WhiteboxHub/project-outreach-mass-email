from typing import Dict, Any
from api_clients.delivery_engine_client import EngineType
from senders.base_sender import BaseSender
from senders.mock_senders import MailgunSender, SendGridSender, AWSSESSender
from senders.smtp_sender import SMTPSender

class EngineBuilder:
    @staticmethod
    def validate_config(config: Dict[str, Any]):
        """
        Validates engine configuration based on type.
        Raises ValueError if invalid.
        """
        engine_type = config.get("engine_type")
        if not engine_type:
             raise ValueError("Missing 'engine_type' in configuration.")
             
        # Common checks
        if "from_email" not in config:
            raise ValueError("Missing 'from_email' in configuration.")

        # Type-specific checks
        if engine_type == EngineType.AWS_SES:
            required = ["host", "username", "password"]
            missing = [f for f in required if f not in config]
            if missing:
                raise ValueError(f"AWS SES requires {missing}")
                
        elif engine_type == EngineType.SENDGRID:
            if "api_key" not in config:
                raise ValueError("SendGrid requires 'api_key'")
                
        elif engine_type == EngineType.MAILGUN:
            if "api_key" not in config:
                 raise ValueError("Mailgun requires 'api_key'")

    @staticmethod
    def build(engine_config: Dict[str, Any]) -> BaseSender:
        # 1. Validate Status (if field exists, assuming active if missing for legacy compatibility)
        if engine_config.get("status", "active") != "active":
            raise ValueError(f"Engine {engine_config.get('name')} is not active.")

        # 2. Validate Config
        # Normalize engine_type to Enum
        try:
            e_type = engine_config.get("engine_type")
            if isinstance(e_type, str):
                # Try exact match or lower case match
                try:
                    engine_config["engine_type"] = EngineType(e_type)
                except ValueError:
                    engine_config["engine_type"] = EngineType(e_type.lower())
        except ValueError:
            # If invalid enum value, let validation fail or validation logic handle it.
            # But simpler: assume if it's not a valid enum member, the specific checks below might fail or pass default.
            # Ideally we fail here if strictly enforcing enum.
            pass

        EngineBuilder.validate_config(engine_config)

        # 3. Build
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
            return SMTPSender(engine_config)
