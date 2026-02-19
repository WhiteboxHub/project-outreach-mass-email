"""
utils/report_mailer.py
──────────────────────
Sends a beautifully designed HTML summary email after each workflow run.
Reads SMTP config from environment variables (REPORT_* prefix).

Sensitive fields are automatically redacted before being included.
"""

import os
import smtplib
import logging
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any, Optional

logger = logging.getLogger("outreach_service")

_REDACT = {
    "imap_password", "password", "smtp_password", "linkedin_url",
    "email_password", "app_password", "secret", "token", "key",
    "linkedin_passwd", "linkedin_username", "linkedin_password",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _redact(ctx: dict) -> dict:
    if not ctx:
        return {}
    return {k: ("***" if k.lower() in _REDACT else v) for k, v in ctx.items()}


def _meta(status: str):
    s = status.lower()
    if s == "success":         return "#4ade80", "✅", "Completed"
    if s == "partial_success": return "#fbbf24", "⚠️",  "Partial Success"
    if s == "failed":          return "#f87171", "❌", "Failed"
    if s == "timed_out":       return "#fb923c", "⏱",  "Timed Out"
    return "#94a3b8", "ℹ️", status.replace("_", " ").title()


def _dur(t0: datetime, t1: datetime) -> str:
    d = int((t1 - t0).total_seconds())
    return f"{d}s" if d < 60 else f"{d // 60}m {d % 60}s"


def _pct(val: int, total: int) -> int:
    return int(val / total * 100) if total > 0 else 0


def _bar_td(pct: int, color: str) -> str:
    return f'<td width="{pct}%" style="background:{color};height:10px;"></td>' if pct > 0 else ""


def _ctx_rows(ctx: dict) -> str:
    rows = ""
    for k, v in ctx.items():
        label = k.replace("_", " ").title()
        rows += (
            f"<tr>"
            f'<td style="padding:7px 14px;font-size:12px;color:#94a3b8;width:160px;border-bottom:1px solid #1e293b;">{label}</td>'
            f'<td style="padding:7px 14px;font-size:12px;color:#e2e8f0;border-bottom:1px solid #1e293b;word-break:break-all;">{v}</td>'
            f"</tr>"
        )
    return rows


def _sent_table(sent_results: List[Dict], limit: int = 50) -> str:
    """Table showing only the emails that were actually attempted (sent/failed)."""
    if not sent_results:
        return ""
    shown = sent_results[:limit]
    rows = ""
    for r in shown:
        status = r.get("status", "unknown")
        email  = r.get("email", "—")
        if status == "success":
            bg, fg, icon = "#065f46", "#4ade80", "✓"
        else:
            bg, fg, icon = "#450a0a", "#f87171", "✗"
        err = r.get("error", "")
        err_cell = (
            f'<td style="padding:6px 12px;font-size:11px;color:#f87171;border-bottom:1px solid #1e293b;">{err[:80]}</td>'
            if err else
            '<td style="padding:6px 12px;border-bottom:1px solid #1e293b;"></td>'
        )
        rows += (
            f"<tr>"
            f'<td style="padding:6px 12px;font-size:12px;color:#e2e8f0;border-bottom:1px solid #1e293b;">{email}</td>'
            f'<td style="padding:6px 12px;border-bottom:1px solid #1e293b;">'
            f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:9999px;font-size:10px;font-weight:700;">'
            f"{icon} {status.title()}</span></td>"
            f"{err_cell}"
            f"</tr>"
        )
    extra = ""
    if len(sent_results) > limit:
        extra = (
            f'<tr><td colspan="3" style="padding:8px 12px;font-size:11px;color:#64748b;text-align:center;">'
            f"… and {len(sent_results) - limit} more not shown</td></tr>"
        )
    return f"""
    <div style="background:#0f172a;border:1px solid #1e293b;border-radius:12px;overflow:hidden;margin-bottom:24px;">
      <div style="padding:11px 16px;background:#1e293b;border-bottom:1px solid #1e293b;">
        <p style="margin:0;font-size:10px;font-weight:800;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;">
          📬 Sending Results ({len(sent_results)} recipients)
        </p>
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <th style="padding:7px 12px;font-size:10px;color:#475569;text-align:left;border-bottom:1px solid #1e293b;">Email</th>
          <th style="padding:7px 12px;font-size:10px;color:#475569;text-align:left;border-bottom:1px solid #1e293b;">Status</th>
          <th style="padding:7px 12px;font-size:10px;color:#475569;text-align:left;border-bottom:1px solid #1e293b;">Error</th>
        </tr>
        {rows}{extra}
      </table>
    </div>"""


def _invalid_table(skipped: List[Dict]) -> str:
    """Dedicated section for emails that were rejected BEFORE sending (invalid)."""
    if not skipped:
        return ""

    rows = ""
    for r in skipped:
        email  = r.get("email", "—")
        reason = r.get("reason", "invalid email")
        rows += (
            f"<tr>"
            f'<td style="padding:7px 14px;font-size:12px;color:#fca5a5;border-bottom:1px solid #3b0f0f;">{email}</td>'
            f'<td style="padding:7px 14px;font-size:11px;color:#f87171;border-bottom:1px solid #3b0f0f;">{reason}</td>'
            f"</tr>"
        )

    return f"""
    <div style="background:#1a0808;border:2px solid #7f1d1d;border-radius:12px;overflow:hidden;margin-bottom:24px;">
      <div style="padding:12px 16px;background:#450a0a;border-bottom:1px solid #7f1d1d;">
        <p style="margin:0;font-size:10px;font-weight:800;color:#fca5a5;text-transform:uppercase;letter-spacing:1.5px;">
          ⚠ Invalid Emails — Skipped Before Sending ({len(skipped)})
        </p>
        <p style="margin:4px 0 0;font-size:11px;color:#f87171;">
          These addresses failed syntax or MX validation and were <strong>never attempted</strong>.
        </p>
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <th style="padding:7px 14px;font-size:10px;color:#b91c1c;text-align:left;border-bottom:1px solid #3b0f0f;">Email Address</th>
          <th style="padding:7px 14px;font-size:10px;color:#b91c1c;text-align:left;border-bottom:1px solid #3b0f0f;">Reason</th>
        </tr>
        {rows}
      </table>
    </div>"""


def _build_html(
    workflow_name: str,
    run_id: str,
    schedule_id: Optional[int],
    final_status: str,
    ok: int,
    fail: int,
    skip: int,
    total: int,
    t0: datetime,
    t1: datetime,
    ctx: dict,
    sent_results: List[Dict],
    skipped_results: List[Dict],
    error_summary: Optional[str],
    candidate_name: Optional[str],
) -> str:
    color, emoji, label = _meta(final_status)
    dur  = _dur(t0, t1)
    gen  = datetime.utcnow().strftime("%d %b %Y %H:%M UTC")

    sched_row = (
        f"<tr><td style='padding:7px 14px;font-size:12px;color:#94a3b8;border-bottom:1px solid #1e293b;'>Schedule</td>"
        f"<td style='padding:7px 14px;font-size:12px;color:#e2e8f0;border-bottom:1px solid #1e293b;'>ID #{schedule_id}</td></tr>"
    ) if schedule_id else ""

    candidate_row = (
        f"<tr><td style='padding:7px 14px;font-size:12px;color:#94a3b8;border-bottom:1px solid #1e293b;'>Sent As</td>"
        f"<td style='padding:7px 14px;font-size:12px;color:#e2e8f0;border-bottom:1px solid #1e293b;'>{candidate_name}</td></tr>"
    ) if candidate_name else ""

    ok_pct   = _pct(ok,   total)
    fail_pct = _pct(fail, total)
    skip_pct = _pct(skip, total)
    bar = _bar_td(ok_pct, "#4ade80") + _bar_td(fail_pct, "#f87171") + _bar_td(skip_pct, "#a78bfa")

    err_html = ""
    if error_summary:
        err_html = f"""
        <div style="background:#1a0808;border:1px solid #7f1d1d;border-radius:10px;padding:14px 16px;margin-bottom:20px;">
          <p style="margin:0 0 4px;font-size:10px;font-weight:700;color:#f87171;text-transform:uppercase;">⚠ Error</p>
          <p style="margin:0;font-size:12px;color:#fca5a5;font-family:monospace;">{error_summary}</p>
        </div>"""

    ctx_rows      = _ctx_rows({k: v for k, v in ctx.items() if k not in _REDACT})
    sent_html     = _sent_table(sent_results)
    invalid_html  = _invalid_table(skipped_results)

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>WBL Run Report</title></head>
<body style="margin:0;padding:0;background:#020617;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#020617;padding:32px 0;">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0"
       style="background:#0f172a;border:1px solid #1e293b;border-radius:16px;overflow:hidden;max-width:620px;">

  <!-- Header -->
  <tr><td style="background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);padding:32px 32px 24px;">
    <p style="margin:0 0 4px;font-size:10px;font-weight:700;color:#4ade80;
              text-transform:uppercase;letter-spacing:2px;">WBL Automation</p>
    <h1 style="margin:0 0 6px;font-size:22px;font-weight:800;color:#f8fafc;">{emoji} {label}</h1>
    <p style="margin:0;font-size:14px;color:#94a3b8;">{workflow_name}</p>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:28px 32px;">

    <p style="margin:0 0 28px;font-size:12px;color:#64748b;text-align:center;">
      Run ID &nbsp;·&nbsp;
      <code style="color:#94a3b8;background:#1e293b;padding:2px 7px;border-radius:4px;">{run_id}</code>
    </p>

    <!-- KPI cards -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
      <tr>
        <td style="background:#0d2818;border:1px solid #166534;border-radius:12px;padding:16px 8px;text-align:center;">
          <p style="margin:0;font-size:34px;font-weight:900;color:#4ade80;">{ok}</p>
          <p style="margin:5px 0 0;font-size:9px;font-weight:700;color:#86efac;text-transform:uppercase;letter-spacing:1px;">✓ Sent</p>
        </td>
        <td width="3%"></td>
        <td style="background:#1a0808;border:1px solid #7f1d1d;border-radius:12px;padding:16px 8px;text-align:center;">
          <p style="margin:0;font-size:34px;font-weight:900;color:#f87171;">{fail}</p>
          <p style="margin:5px 0 0;font-size:9px;font-weight:700;color:#fca5a5;text-transform:uppercase;letter-spacing:1px;">✗ SMTP Failed</p>
        </td>
        <td width="3%"></td>
        <td style="background:#1a0808;border:2px solid #7f1d1d;border-radius:12px;padding:16px 8px;text-align:center;">
          <p style="margin:0;font-size:34px;font-weight:900;color:#f97316;">{skip}</p>
          <p style="margin:5px 0 0;font-size:9px;font-weight:700;color:#fdba74;text-transform:uppercase;letter-spacing:1px;">⊘ Invalid Email</p>
        </td>
        <td width="3%"></td>
        <td style="background:#0c1a3a;border:1px solid #1e3a8a;border-radius:12px;padding:16px 8px;text-align:center;">
          <p style="margin:0;font-size:34px;font-weight:900;color:#60a5fa;">{total}</p>
          <p style="margin:5px 0 0;font-size:9px;font-weight:700;color:#93c5fd;text-transform:uppercase;letter-spacing:1px;">⚡ Fetched</p>
        </td>
      </tr>
    </table>

    <!-- Stats row -->
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
      <tr>
        <td style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:13px 16px;">
          <p style="margin:0 0 2px;font-size:10px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:1px;">⏱ Duration</p>
          <p style="margin:0;font-size:18px;font-weight:800;color:#e2e8f0;">{dur}</p>
        </td>
        <td width="4%"></td>
        <td style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:13px 16px;">
          <p style="margin:0 0 2px;font-size:10px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:1px;">📊 Delivery Rate</p>
          <p style="margin:0;font-size:18px;font-weight:800;color:#e2e8f0;">{_pct(ok, total - skip)}% of valid</p>
        </td>
        <td width="4%"></td>
        <td style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:13px 16px;">
          <p style="margin:0 0 2px;font-size:10px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:1px;">✅ Valid Rate</p>
          <p style="margin:0;font-size:18px;font-weight:800;color:#e2e8f0;">{_pct(total - skip, total)}% of fetched</p>
        </td>
      </tr>
    </table>

    <!-- Progress bar -->
    <div style="background:#1e293b;border-radius:9999px;height:10px;overflow:hidden;margin-bottom:6px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="height:10px;border-collapse:collapse;">
        <tr>{bar}</tr>
      </table>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
      <tr>
        <td style="font-size:10px;color:#4ade80;">■ {ok_pct}% sent</td>
        <td align="center" style="font-size:10px;color:#f87171;">■ {fail_pct}% failed</td>
        <td align="right" style="font-size:10px;color:#f97316;">■ {skip_pct}% invalid (skipped)</td>
      </tr>
    </table>

    <!-- Run Details -->
    <div style="background:#0f172a;border:1px solid #1e293b;border-radius:12px;overflow:hidden;margin-bottom:24px;">
      <div style="padding:11px 16px;background:#1e293b;">
        <p style="margin:0;font-size:10px;font-weight:800;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;">📋 Run Details</p>
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td style="padding:7px 14px;font-size:12px;color:#94a3b8;width:150px;border-bottom:1px solid #1e293b;">Status</td>
            <td style="padding:7px 14px;border-bottom:1px solid #1e293b;">
              <span style="background:{color};color:#fff;padding:2px 9px;border-radius:9999px;font-size:10px;font-weight:700;">{label}</span>
            </td></tr>
        {candidate_row}
        {sched_row}
        <tr><td style="padding:7px 14px;font-size:12px;color:#94a3b8;border-bottom:1px solid #1e293b;">Started</td>
            <td style="padding:7px 14px;font-size:12px;color:#e2e8f0;border-bottom:1px solid #1e293b;">{t0.strftime('%d %b %Y, %I:%M:%S %p')}</td></tr>
        <tr><td style="padding:7px 14px;font-size:12px;color:#94a3b8;border-bottom:1px solid #1e293b;">Finished</td>
            <td style="padding:7px 14px;font-size:12px;color:#e2e8f0;border-bottom:1px solid #1e293b;">{t1.strftime('%d %b %Y, %I:%M:%S %p')}</td></tr>
        <tr><td style="padding:7px 14px;font-size:12px;color:#94a3b8;">Duration</td>
            <td style="padding:7px 14px;font-size:12px;color:#e2e8f0;font-weight:700;">{dur}</td></tr>
      </table>
    </div>

    {err_html}

    <!-- ⚠ Invalid Emails Section (prominent, before sent results) -->
    {invalid_html}

    <!-- Sent Results Table -->
    {sent_html}

    <!-- Execution Context -->
    <div style="background:#0f172a;border:1px solid #1e293b;border-radius:12px;overflow:hidden;margin-bottom:24px;">
      <div style="padding:11px 16px;background:#1e293b;">
        <p style="margin:0;font-size:10px;font-weight:800;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;">⚙️ Execution Context</p>
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">{ctx_rows}</table>
    </div>

  </td></tr>

  <!-- Footer -->
  <tr><td style="padding:20px 32px;background:#0a0f1e;text-align:center;border-top:1px solid #1e293b;">
    <p style="margin:0;font-size:11px;color:#334155;">
      WBL Outreach Automation &nbsp;·&nbsp; {gen} &nbsp;·&nbsp; Do not reply
    </p>
  </td></tr>

</table>
</td></tr></table>
</body></html>"""


# ── Public API ────────────────────────────────────────────────────────────────

def send_run_report(
    workflow_name: str,
    run_id: str,
    final_status: str,
    success_count: int,
    failed_count: int,
    started_at: datetime,
    finished_at: datetime,
    recipient_results: Optional[List[Dict[str, Any]]] = None,
    execution_context: Optional[Dict[str, Any]] = None,
    schedule_id: Optional[int] = None,
    error_summary: Optional[str] = None,
) -> bool:
    """
    Send a beautifully-designed HTML run-summary email to REPORT_EMAIL_TO.
    Splits results into:
      - sent_results   : emails that were actually attempted (success / failed)
      - skipped_results: emails rejected by the validator BEFORE sending
    """
    to_addr   = os.getenv("REPORT_EMAIL_TO")
    from_addr = os.getenv("REPORT_EMAIL_FROM")
    host      = os.getenv("REPORT_SMTP_HOST", "smtp.gmail.com")
    port      = int(os.getenv("REPORT_SMTP_PORT", "587"))
    user      = os.getenv("REPORT_SMTP_USER")
    pwd       = os.getenv("REPORT_SMTP_PASSWORD")

    if not all([to_addr, from_addr, user, pwd]):
        logger.warning("Run report skipped — REPORT_* env vars not set.")
        return False

    results         = recipient_results or []
    skipped_results = [r for r in results if r.get("status") == "skipped"]
    sent_results    = [r for r in results if r.get("status") != "skipped"]

    skip_count  = len(skipped_results)
    total       = success_count + failed_count + skip_count

    ctx_safe       = _redact(execution_context or {})
    candidate_name = ctx_safe.pop("candidate_name", None)

    _, emoji, label = _meta(final_status)
    dur     = _dur(started_at, finished_at)
    subject = (
        f"[WBL] {emoji} {label} — {workflow_name} "
        f"| ✔{success_count} sent | ✗{failed_count} failed | ⊘{skip_count} invalid | {dur}"
    )

    body = _build_html(
        workflow_name=workflow_name,
        run_id=run_id,
        schedule_id=schedule_id,
        final_status=final_status,
        ok=success_count,
        fail=failed_count,
        skip=skip_count,
        total=total,
        t0=started_at,
        t1=finished_at,
        ctx=ctx_safe,
        sent_results=sent_results,
        skipped_results=skipped_results,
        error_summary=error_summary,
        candidate_name=candidate_name,
    )

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"WBL Outreach <{from_addr}>"
        msg["To"]      = to_addr
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(user, pwd)
            s.sendmail(from_addr, [to_addr], msg.as_string())

        logger.info(
            f"✅ Run report sent to {to_addr} — "
            f"✔{success_count} sent | ✗{failed_count} failed | ⊘{skip_count} invalid"
        )
        return True
    except Exception as e:
        logger.error(f"Run report email failed: {e}")
        return False
