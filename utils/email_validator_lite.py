"""
utils/email_validator_lite.py
─────────────────────────────
Lightweight email validator used inside the workflow executor to filter out
invalid recipients before any SMTP sending begins.

Checks performed (in order, fast-to-slow):
  1. Syntax check  – regex (instant)
  2. MX check      – DNS lookup, cached per domain, run concurrently

SMTP mailbox verification (slow, ~5s per email) is intentionally NOT done
here to avoid slowing down every run. Use dry_run_validation.py for that.
"""

import re
import logging
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

logger = logging.getLogger("outreach_service")

# ── Regex ──────────────────────────────────────────────────────────────────────
_EMAIL_REGEX = re.compile(
    r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$'
)

# ── Domain MX cache (shared across all calls in one process) ───────────────────
_mx_cache: dict[str, bool] = {}


def _syntax_ok(email: str) -> bool:
    return bool(_EMAIL_REGEX.match(email))


def _has_mx(domain: str) -> bool:
    """Returns True if `domain` has valid MX records. Result is cached."""
    if domain in _mx_cache:
        return _mx_cache[domain]

    # Try dnspython first (most accurate)
    try:
        import dns.resolver
        dns.resolver.resolve(domain, "MX")
        _mx_cache[domain] = True
        return True
    except Exception:
        pass  # fall through to socket fallback

    # Socket fallback: try resolving the domain at port 25
    try:
        socket.setdefaulttimeout(3)
        socket.getaddrinfo(domain, 25)
        _mx_cache[domain] = True
        return True
    except Exception:
        _mx_cache[domain] = False
        return False


def validate_emails(
    emails: List[str],
    skip_mx: bool = False,
    max_workers: int = 30,
) -> Tuple[List[str], List[str]]:
    """
    Validate a list of email addresses.

    Returns
    -------
    valid   : emails that passed all checks → will be sent to
    invalid : emails that failed at least one check → will be skipped

    Parameters
    ----------
    emails      : raw email list
    skip_mx     : if True, only syntax is checked (faster, less accurate)
    max_workers : thread-pool size for concurrent DNS lookups
    """
    total = len(emails)
    valid: List[str]   = []
    invalid: List[str] = []

    logger.info("")
    logger.info("─────────────────────────────────────────────────────")
    logger.info(f"  🔍 VALIDATING {total} recipient email(s)")
    logger.info("─────────────────────────────────────────────────────")

    # ── Step 1: Syntax check ──────────────────────────────────────────────────
    logger.info("  Step 1/2 — Syntax check (regex)...")
    syntax_ok:   List[str] = []
    syntax_fail: List[str] = []

    for email in emails:
        email = email.strip().lower()
        if _syntax_ok(email):
            syntax_ok.append(email)
        else:
            syntax_fail.append(email)
            logger.warning(f"  ✗ [Syntax] Bad format: {email}")

    logger.info(
        f"  Syntax result: ✔ {len(syntax_ok)} valid  |  "
        f"✗ {len(syntax_fail)} bad format"
    )
    invalid.extend(syntax_fail)

    if skip_mx:
        logger.info("  Skipping MX check (skip_mx=True)")
        valid = syntax_ok
        _log_summary(total, valid, invalid)
        return valid, invalid

    # ── Step 2: MX record check (concurrent DNS) ──────────────────────────────
    logger.info("")
    domain_emails: dict[str, List[str]] = {}
    for email in syntax_ok:
        domain = email.split("@")[-1]
        domain_emails.setdefault(domain, []).append(email)

    unique_domains = list(domain_emails.keys())
    cached = [d for d in unique_domains if d in _mx_cache]
    to_check = [d for d in unique_domains if d not in _mx_cache]

    logger.info(
        f"  Step 2/2 — MX record check: "
        f"{len(unique_domains)} unique domains  "
        f"({len(cached)} from cache, {len(to_check)} need DNS lookup)"
    )

    # Run concurrent DNS lookups
    mx_done = 0
    domain_results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_has_mx, d): d for d in unique_domains}
        for future in as_completed(futures):
            domain = futures[future]
            try:
                result = future.result()
            except Exception:
                result = False
            domain_results[domain] = result
            mx_done += 1
            status = "✔" if result else "✗"
            source = "(cached)" if domain in cached else ""
            logger.info(
                f"  [{mx_done}/{len(unique_domains)}] {status} MX: {domain}  {source}"
            )

    # Classify emails based on domain result
    mx_pass = 0
    mx_fail = 0
    for domain, emails_for_domain in domain_emails.items():
        if domain_results.get(domain, False):
            valid.extend(emails_for_domain)
            mx_pass += len(emails_for_domain)
        else:
            invalid.extend(emails_for_domain)
            mx_fail += len(emails_for_domain)
            for e in emails_for_domain:
                logger.warning(f"  ✗ [MX] No mail server for domain: {domain} → {e}")

    logger.info(
        f"  MX result:     ✔ {mx_pass} valid domain(s)  |  "
        f"✗ {mx_fail} email(s) on dead domain(s)"
    )

    _log_summary(total, valid, invalid)
    return valid, invalid


def _log_summary(total: int, valid: List[str], invalid: List[str]):
    pct = int(len(valid) / total * 100) if total else 0
    logger.info("")
    logger.info("─────────────────────────────────────────────────────")
    logger.info(
        f"  ✅ VALIDATION DONE  "
        f"✔ {len(valid)} will be sent  |  "
        f"✗ {len(invalid)} skipped  |  "
        f"{pct}% deliverable"
    )
    logger.info("─────────────────────────────────────────────────────")
    logger.info("")
