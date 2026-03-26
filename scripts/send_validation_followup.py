#!/usr/bin/env python3
"""Send follow-up survey emails to testers who already received reports.

Queries evaluation_jobs for completed jobs with email addresses and sends
a short nudge email with just the survey link. Skips testers who have
already submitted a detailed_survey response.

Usage:
    # Preview what would be sent:
    python scripts/send_validation_followup.py --dry-run

    # Send follow-up emails:
    python scripts/send_validation_followup.py

    # Only include jobs from the last 7 days:
    python scripts/send_validation_followup.py --days 7

    # Use a JSON file instead of the database:
    python scripts/send_validation_followup.py --addresses-file data/validation_test_b_addresses.json

Environment variables:
    NESTCHECK_DB_PATH   Path to nestcheck.db (default: nestcheck.db)
    NESTCHECK_BASE_URL  Base URL (default: https://nestcheck.org)
    RESEND_API_KEY      Required for sending emails (unless --dry-run)
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://nestcheck.org"
FROM_ADDRESS = "NestCheck <reports@nestcheck.org>"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_from_db(days: int | None) -> list[dict]:
    """Query evaluation_jobs for done jobs with email + snapshot_id."""
    db_path = os.environ.get("NESTCHECK_DB_PATH", "nestcheck.db")
    if not Path(db_path).exists():
        logger.error("Database not found at %s", db_path)
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            SELECT DISTINCT email_raw AS email, snapshot_id, address
            FROM evaluation_jobs
            WHERE status = 'done'
              AND email_raw IS NOT NULL
              AND email_raw != ''
              AND snapshot_id IS NOT NULL
        """
        params: list = []

        if days is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            query += " AND created_at >= ?"
            params.append(cutoff)

        rows = conn.execute(query, params).fetchall()

        # Find snapshots that already have a detailed_survey response
        surveyed = set()
        try:
            for row in conn.execute(
                "SELECT DISTINCT snapshot_id FROM feedback"
                " WHERE feedback_type = 'detailed_survey'"
            ):
                surveyed.add(row[0])
        except sqlite3.OperationalError:
            pass  # feedback table may not exist

        results = []
        for row in rows:
            if row["snapshot_id"] in surveyed:
                continue
            results.append({
                "email": row["email"],
                "snapshot_id": row["snapshot_id"],
                "address": row["address"],
            })
        return results
    finally:
        conn.close()


def _load_from_file(path: str) -> list[dict]:
    """Load tester data from a JSON file.

    Expected format: [{"email": "...", "snapshot_id": "...", "address": "..."}, ...]
    """
    with open(path) as f:
        data = json.load(f)
    if not data:
        logger.warning("Addresses file is empty: %s", path)
        return []
    return data


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def _send_followup_email(
    email: str, snapshot_id: str, address: str, base_url: str,
) -> bool:
    """Send a survey follow-up nudge email."""
    import html as html_mod

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        logger.warning("RESEND_API_KEY not set — skipping email")
        return False

    try:
        import resend

        resend.api_key = api_key

        survey_url = f"{base_url.rstrip('/')}/feedback/{snapshot_id}"
        safe_address = html_mod.escape(address)

        html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: system-ui, sans-serif; line-height: 1.5; color: #1f2937;">
  <div style="max-width: 480px; margin: 0 auto; padding: 1.5rem;">
    <p style="font-size: 1.25rem; font-weight: 600; color: #0f3460;">NestCheck</p>
    <p>You recently received a NestCheck report for <strong>{safe_address}</strong>.</p>
    <p>We'd love your feedback — you know this address better than anyone. It takes about 2 minutes.</p>
    <p style="margin: 1.5rem 0;">
      <a href="{survey_url}" style="display: inline-block; padding: 0.75rem 1.5rem; background: #0f3460; color: #fff; text-decoration: none; border-radius: 6px; font-weight: 600;">Take the survey</a>
    </p>
    <p style="font-size: 0.875rem; color: #6b7280;">Your feedback helps us improve NestCheck for everyone.</p>
    <p style="font-size: 0.875rem; color: #6b7280;">— NestCheck</p>
  </div>
</body>
</html>
""".strip()

        params = {
            "from": FROM_ADDRESS,
            "to": [email],
            "subject": "Quick feedback on your NestCheck report?",
            "html": html_body,
        }

        resend.Emails.send(params)
        logger.info("  Sent to %s***", email[:3])
        return True

    except Exception as e:
        logger.warning("  Email error for %s***: %s", email[:3], e)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Send follow-up survey emails to testers."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be sent without sending.",
    )
    parser.add_argument(
        "--days", type=int, default=None,
        help="Only include jobs from the last N days.",
    )
    parser.add_argument(
        "--addresses-file", type=str, default=None,
        help="JSON file with tester data instead of querying the DB.",
    )
    parser.add_argument(
        "--base-url", type=str,
        default=os.environ.get("NESTCHECK_BASE_URL", DEFAULT_BASE_URL),
        help="Base URL for survey links.",
    )
    args = parser.parse_args()

    if args.addresses_file:
        testers = _load_from_file(args.addresses_file)
        logger.info("Loaded %d testers from %s", len(testers), args.addresses_file)
    else:
        testers = _load_from_db(args.days)
        logger.info("Found %d testers from DB (excluding already-surveyed)", len(testers))

    if not testers:
        logger.info("No testers to email. Done.")
        return

    sent = 0
    skipped = 0
    for t in testers:
        email = t.get("email")
        snapshot_id = t.get("snapshot_id")
        address = t.get("address", "your address")

        if not email or not snapshot_id:
            logger.warning("  Skipping entry with missing email/snapshot_id: %s", t)
            skipped += 1
            continue

        if args.dry_run:
            logger.info(
                "  [DRY RUN] Would send to %s*** for %s (snapshot %s)",
                email[:3], address, snapshot_id,
            )
            sent += 1
        else:
            if _send_followup_email(email, snapshot_id, address, args.base_url):
                sent += 1
            else:
                skipped += 1

    label = "would send" if args.dry_run else "sent"
    logger.info("Done. %s: %d, skipped: %d", label.capitalize(), sent, skipped)


if __name__ == "__main__":
    main()
