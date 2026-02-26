"""
Email delivery via Resend. Report links and magic links.

Email failure must never break evaluations — all send functions
swallow exceptions and return False on failure.
"""

import html
import os
import logging

logger = logging.getLogger(__name__)

FROM_ADDRESS = "NestCheck <reports@nestcheck.com>"


def send_report_email(to_email: str, snapshot_id: str, address: str) -> bool:
    """
    Send the report-ready link to the user after evaluation completes.

    Returns True on success, False on failure. Never raises.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        logger.warning(
            "RESEND_API_KEY not set; skipping report email to %s for snapshot %s",
            to_email[:3] + "***",
            snapshot_id,
        )
        return False

    try:
        import resend

        resend.api_key = api_key

        base_url = os.environ.get("NESTCHECK_BASE_URL", "https://nestcheck.com")
        report_url = f"{base_url.rstrip('/')}/s/{snapshot_id}"
        safe_address = html.escape(address)

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: system-ui, sans-serif; line-height: 1.5; color: #1f2937;">
  <div style="max-width: 480px; margin: 0 auto; padding: 1.5rem;">
    <p style="font-size: 1.25rem; font-weight: 600; color: #0f3460;">NestCheck</p>
    <p>Your evaluation for <strong>{safe_address}</strong> is ready.</p>
    <p style="margin: 1.5rem 0;">
      <a href="{report_url}" style="display: inline-block; padding: 0.75rem 1.5rem; background: #0f3460; color: #fff; text-decoration: none; border-radius: 6px; font-weight: 600;">View your report</a>
    </p>
    <p style="font-size: 0.875rem; color: #6b7280;">— NestCheck</p>
  </div>
</body>
</html>
""".strip()

        params = {
            "from": FROM_ADDRESS,
            "to": [to_email],
            "subject": "Your NestCheck Report is Ready",
            "html": html_body,
        }

        resend.Emails.send(params)
        return True

    except Exception as e:
        logger.warning(
            "Failed to send report email to %s for snapshot %s: %s",
            to_email[:3] + "***",
            snapshot_id,
            e,
            exc_info=True,
        )
        return False


def send_magic_link_email(to_email: str) -> bool:
    """Send magic-link sign-in email for My Reports access. Not yet implemented."""
    # TODO: Phase 3 — magic-link flow
    return False
