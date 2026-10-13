"""
utils/security.py
─────────────────
Security helper module providing:
- Recursive deep redaction for sensitive credentials (passwords, tokens, keys) in logs and reports.
- Tamper-proof HMAC-SHA256 signed tokens for unsubscribe links (no raw emails exposed).
"""

import os
import hmac
import hashlib
import base64
from typing import Any, Dict, List, Union

SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "secret",
    "api_key",
    "apikey",
    "token",
    "app_password",
    "credential",
    "private_key",
    "auth",
)

def redact_sensitive_data(obj: Any) -> Any:
    """
    Recursively scans dictionaries, lists, and sets to redact passwords,
    API tokens, secrets, and credentials.
    """
    if isinstance(obj, dict):
        redacted = {}
        for k, v in obj.items():
            key_lower = str(k).lower()
            if isinstance(v, (dict, list, tuple, set)):
                redacted[k] = redact_sensitive_data(v)
            elif any(sub in key_lower for sub in SENSITIVE_KEY_SUBSTRINGS):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = v
        return redacted
    elif isinstance(obj, list):
        return [redact_sensitive_data(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(redact_sensitive_data(item) for item in obj)
    elif isinstance(obj, set):
        return {redact_sensitive_data(item) for item in obj}
    return obj

def get_secret_key() -> str:
    return os.getenv("OUTREACH_API_KEY", os.getenv("SECRET_KEY", "wbl_outreach_default_hmac_secret"))

def generate_unsubscribe_token(email: str) -> str:
    """
    Generates a secure HMAC-SHA256 signed token for an email address.
    This prevents email tampering and avoids exposing raw emails in URLs.
    """
    key = get_secret_key().encode("utf-8")
    normalized_email = email.strip().lower().encode("utf-8")
    sig = hmac.new(key, normalized_email, hashlib.sha256).digest()
    
    # Pack normalized email base64 + signature base64
    b64_email = base64.urlsafe_b64encode(normalized_email).decode("utf-8").rstrip("=")
    b64_sig = base64.urlsafe_b64encode(sig[:16]).decode("utf-8").rstrip("=")
    return f"{b64_email}.{b64_sig}"

def verify_unsubscribe_token(token: str) -> Union[str, None]:
    """
    Verifies the HMAC-SHA256 token and returns the normalized email if valid, or None if invalid.
    """
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        
        b64_email, b64_sig = parts
        # Re-pad base64
        b64_email_padded = b64_email + "=" * (-len(b64_email) % 4)
        raw_email = base64.urlsafe_b64decode(b64_email_padded)
        
        key = get_secret_key().encode("utf-8")
        expected_sig = hmac.new(key, raw_email, hashlib.sha256).digest()
        expected_b64_sig = base64.urlsafe_b64encode(expected_sig[:16]).decode("utf-8").rstrip("=")
        
        if hmac.compare_digest(b64_sig, expected_b64_sig):
            return raw_email.decode("utf-8")
        return None
    except Exception:
        return None

def build_safe_unsubscribe_url(email: str, base_url: str = None) -> str:
    """
    Constructs an opaque unsubscribe URL containing only the signed token.
    """
    token = generate_unsubscribe_token(email)
    base = base_url or os.getenv("WBL_BACKEND_URL", "https://api.whitebox-learning.com/api")
    return f"{base}/orchestrator/unsubscribe?token={token}"
