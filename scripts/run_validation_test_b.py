#!/usr/bin/env python3
"""Test B validation runner — evaluate tester-provided addresses and send reports.

Reads addresses from data/validation_test_b_addresses.json, submits each to the
NestCheck endpoint, polls for completion, optionally sends report + survey emails
to each tester, and outputs a summary table.

Usage:
    # Run evaluations and send emails:
    python scripts/run_validation_test_b.py

    # Run evaluations without sending emails:
    python scripts/run_validation_test_b.py --dry-run

    # Run against a local dev server:
    python scripts/run_validation_test_b.py --base-url http://localhost:5001 --dry-run

    # Show progress summary:
    python scripts/run_validation_test_b.py --status

Environment variables:
    NESTCHECK_URL       Base URL (default: https://nestcheck.org)
    BUILDER_SECRET      Builder mode key (bypasses payment gate)
    RESEND_API_KEY      Required for sending emails (unless --dry-run)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"

sys.path.insert(0, str(_PROJECT_ROOT))

# --- Paths ---
ADDRESSES_FILE = _DATA_DIR / "validation_test_b_addresses.json"
STATE_FILE = _DATA_DIR / "validation_test_b_state.json"

# --- Defaults ---
DEFAULT_BASE_URL = "https://nestcheck.org"
POLL_INTERVAL = 3.0
POLL_TIMEOUT = 180.0
INTER_EVAL_DELAY = 2.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State management (resumable)
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"evaluations": {}, "started_at": None, "last_run": None}


def _save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(STATE_FILE)


def _addr_key(address: str) -> str:
    return address.strip().lower()


# ---------------------------------------------------------------------------
# Scoring config freeze check
# ---------------------------------------------------------------------------

def _check_scoring_config_frozen() -> bool:
    """Prompt user to confirm scoring dimensions are frozen."""
    print("\n" + "=" * 60)
    print("SCORING CONFIG FREEZE CHECK")
    print("=" * 60)
    print()
    print("Test B requires that the dimension list and scoring weights")
    print("are frozen before running evaluations. Changes to scoring_config.py")
    print("after evaluations start will invalidate tester comparisons.")
    print()
    try:
        answer = input("Are scoring dimensions frozen and ready? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


# ---------------------------------------------------------------------------
# API interaction (reused from seed_evaluation_sprint.py pattern)
# ---------------------------------------------------------------------------

HEALTH_CHECK_RETRIES = 3
HEALTH_CHECK_PAUSE = 60.0


def _check_server_health(base_url: str, session: requests.Session) -> bool:
    try:
        resp = session.get(f"{base_url}/", timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def _wait_for_healthy_server(
    base_url: str, session: requests.Session, state: dict,
) -> bool:
    for attempt in range(1, HEALTH_CHECK_RETRIES + 1):
        logger.warning(
            "Server unhealthy — pausing %ds before retry (%d/%d)",
            int(HEALTH_CHECK_PAUSE), attempt, HEALTH_CHECK_RETRIES,
        )
        time.sleep(HEALTH_CHECK_PAUSE)
        if _check_server_health(base_url, session):
            logger.info("Server healthy again")
            return True
    logger.error("Server unresponsive — stopping run")
    _save_state(state)
    return False


def _create_session(base_url: str, builder_secret: str | None) -> requests.Session:
    session = requests.Session()
    session.headers["Accept"] = "application/json"
    session.headers["Referer"] = base_url + "/"

    if builder_secret:
        domain = base_url.split("//")[1].split("/")[0].split(":")[0]
        session.cookies.set("nc_builder", builder_secret, domain=domain)

    try:
        resp = session.get(f"{base_url}/csrf-token", timeout=10)
        resp.raise_for_status()
        csrf_token = resp.json().get("csrf_token", "")
        if csrf_token:
            session.headers["X-CSRFToken"] = csrf_token
            logger.info("CSRF token acquired")
        else:
            logger.warning("No CSRF token returned — POSTs may fail")
    except Exception as e:
        logger.warning("Failed to fetch CSRF token: %s", e)

    return session


def _submit_evaluation(
    session: requests.Session, base_url: str, address: str,
    email: str | None = None, *, _csrf_retried: bool = False,
) -> dict:
    data = {"address": address}
    if email:
        data["email"] = email

    resp = session.post(
        f"{base_url}/",
        data=data,
        timeout=30,
        allow_redirects=False,
    )

    if resp.status_code in (301, 302):
        location = resp.headers.get("Location", "")
        snapshot_id = location.split("/s/")[-1] if "/s/" in location else None
        if snapshot_id:
            return {"snapshot_id": snapshot_id, "cached": True}

    if resp.status_code == 200:
        try:
            return resp.json()
        except (ValueError, KeyError):
            pass

    if resp.status_code == 400 and not _csrf_retried:
        body = {}
        try:
            body = resp.json()
        except ValueError:
            pass
        if body.get("error_code") == "csrf_expired":
            try:
                csrf_resp = session.get(f"{base_url}/csrf-token", timeout=10)
                csrf_resp.raise_for_status()
                new_token = csrf_resp.json().get("csrf_token", "")
                if new_token:
                    session.headers["X-CSRFToken"] = new_token
                    logger.info("CSRF token refreshed, retrying")
                    return _submit_evaluation(
                        session, base_url, address, email, _csrf_retried=True,
                    )
            except Exception:
                pass

    raise RuntimeError(f"POST / returned {resp.status_code}: {resp.text[:200]}")


def _poll_job(session: requests.Session, base_url: str, job_id: str) -> dict:
    start = time.monotonic()
    last_stage = None

    while time.monotonic() - start < POLL_TIMEOUT:
        try:
            resp = session.get(f"{base_url}/job/{job_id}", timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Poll error for %s: %s", job_id, e)
            time.sleep(POLL_INTERVAL)
            continue

        status = data.get("status")
        stage = data.get("current_stage")

        if stage and stage != last_stage:
            logger.info("  Stage: %s", stage)
            last_stage = stage

        if status == "done":
            return data
        if status == "failed":
            return data

        time.sleep(POLL_INTERVAL)

    return {"status": "timeout", "error": f"Timed out after {POLL_TIMEOUT}s"}


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def _send_tester_email(
    tester_email: str, snapshot_id: str, address: str, base_url: str,
) -> bool:
    """Send report + survey links to the tester.

    Uses a custom email body that includes both the report link and survey
    link, unlike the standard send_report_email which only has the report.
    """
    import html as html_mod

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        logger.warning("  RESEND_API_KEY not set — skipping email")
        return False

    try:
        import resend

        from email_service import FROM_ADDRESS, _resend_key_set
        if not _resend_key_set:
            resend.api_key = api_key
            import email_service
            email_service._resend_key_set = True

        report_url = f"{base_url.rstrip('/')}/s/{snapshot_id}"
        survey_url = f"{base_url.rstrip('/')}/feedback/{snapshot_id}"
        safe_address = html_mod.escape(address)

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
    <p>We'd love your feedback — you know this address better than anyone.</p>
    <p style="margin: 1rem 0;">
      <a href="{survey_url}" style="display: inline-block; padding: 0.6rem 1.2rem; background: #fff; color: #0f3460; text-decoration: none; border-radius: 6px; font-weight: 600; border: 2px solid #0f3460;">Take the survey</a>
    </p>
    <p style="font-size: 0.875rem; color: #6b7280;">— NestCheck</p>
  </div>
</body>
</html>
""".strip()

        params = {
            "from": FROM_ADDRESS,
            "to": [tester_email],
            "subject": "Your NestCheck Report + Feedback Survey",
            "html": html_body,
        }

        resend.Emails.send(params)
        logger.info("  Email sent to %s***", tester_email[:3])
        return True

    except Exception as e:
        logger.warning("  Email error for %s***: %s", tester_email[:3], e)
        return False


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

def run_validation(
    base_url: str,
    builder_secret: str | None,
    dry_run: bool = False,
) -> None:
    if not ADDRESSES_FILE.exists():
        logger.error("Address file not found: %s", ADDRESSES_FILE)
        logger.error("Add tester addresses to data/validation_test_b_addresses.json")
        sys.exit(1)

    with open(ADDRESSES_FILE) as f:
        addresses = json.load(f)

    if not addresses:
        logger.error("No addresses in %s", ADDRESSES_FILE)
        sys.exit(1)

    # Scoring config freeze check
    if not _check_scoring_config_frozen():
        logger.error("Scoring config not confirmed frozen — aborting")
        sys.exit(1)

    state = _load_state()
    if not state["started_at"]:
        state["started_at"] = datetime.now(timezone.utc).isoformat()

    session = _create_session(base_url, builder_secret)

    # Determine pending addresses
    pending = []
    for entry in addresses:
        key = _addr_key(entry["address"])
        existing = state["evaluations"].get(key)
        if existing and existing.get("status") == "done":
            continue
        pending.append(entry)

    total = len(addresses)
    done_count = sum(1 for v in state["evaluations"].values() if v.get("status") == "done")

    logger.info("Test B: %d/%d done, %d pending", done_count, len(pending), total)

    if not pending:
        logger.info("All addresses evaluated. Use --status to see results.")
        _print_summary(state, base_url)
        return

    if not dry_run:
        resend_key = os.environ.get("RESEND_API_KEY")
        if not resend_key:
            logger.warning("RESEND_API_KEY not set — emails will be skipped")

    for i, entry in enumerate(pending):
        addr = entry["address"]
        key = _addr_key(addr)
        tester_name = entry.get("tester_name", "Unknown")
        tester_email = entry.get("tester_email", "")

        logger.info("[%d/%d] %s (%s)", done_count + i + 1, total, addr, tester_name)

        eval_record = {
            "address": addr,
            "tester_name": tester_name,
            "tester_email": tester_email,
            "relationship": entry.get("relationship", ""),
            "years_at_address": entry.get("years_at_address"),
            "notes": entry.get("notes", ""),
            "status": "submitting",
            "last_attempt": datetime.now(timezone.utc).isoformat(),
        }

        try:
            submit_result = _submit_evaluation(session, base_url, addr, tester_email)

            if submit_result.get("snapshot_id"):
                snapshot_id = submit_result["snapshot_id"]
                logger.info("  Cached snapshot: %s", snapshot_id)
                eval_record["status"] = "done"
                eval_record["snapshot_id"] = snapshot_id
                eval_record["cached"] = True
            elif submit_result.get("job_id"):
                job_id = submit_result["job_id"]
                logger.info("  Job queued: %s", job_id)
                eval_record["job_id"] = job_id
                eval_record["status"] = "polling"

                job_result = _poll_job(session, base_url, job_id)

                if job_result.get("status") == "done":
                    snapshot_id = job_result["snapshot_id"]
                    logger.info("  Done: /s/%s", snapshot_id)
                    eval_record["status"] = "done"
                    eval_record["snapshot_id"] = snapshot_id
                else:
                    error = job_result.get("error", "Unknown failure")
                    logger.warning("  Failed: %s", error)
                    eval_record["status"] = "failed"
                    eval_record["error"] = error
            else:
                logger.warning("  Unexpected response: %s", submit_result)
                eval_record["status"] = "failed"
                eval_record["error"] = f"Unexpected: {json.dumps(submit_result)[:200]}"

        except Exception as e:
            logger.exception("  Error evaluating %s", addr)
            eval_record["status"] = "failed"
            eval_record["error"] = str(e)[:300]

        # Send emails for completed evaluations
        if eval_record["status"] == "done" and eval_record.get("snapshot_id"):
            if not dry_run and tester_email:
                email_sent = _send_tester_email(
                    tester_email, eval_record["snapshot_id"], addr, base_url,
                )
                eval_record["email_sent"] = email_sent
            elif dry_run:
                logger.info("  [DRY RUN] Would email %s***", tester_email[:3] if tester_email else "???")
                eval_record["email_sent"] = False

        # Save after every evaluation
        state["evaluations"][key] = eval_record
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)

        # Health check after failures
        if eval_record["status"] == "failed":
            if not _check_server_health(base_url, session):
                if not _wait_for_healthy_server(base_url, session, state):
                    return

        # Delay between evaluations
        if i < len(pending) - 1:
            time.sleep(INTER_EVAL_DELAY)

    # Final summary
    _print_summary(state, base_url)


# ---------------------------------------------------------------------------
# Summary output
# ---------------------------------------------------------------------------

def _print_summary(state: dict, base_url: str) -> None:
    evals = state.get("evaluations", {})
    done = [v for v in evals.values() if v.get("status") == "done"]
    failed = [v for v in evals.values() if v.get("status") == "failed"]

    print()
    print("=" * 80)
    print("TEST B VALIDATION SUMMARY")
    print("=" * 80)
    print(f"  Completed: {len(done)}  |  Failed: {len(failed)}  |  Total: {len(evals)}")
    print()

    if done:
        # Header
        print(f"{'Tester':<15} {'Address':<40} {'Snapshot':<14} {'Email':>5}")
        print("-" * 80)

        for v in done:
            tester = v.get("tester_name", "?")[:14]
            addr = v.get("address", "?")[:39]
            sid = v.get("snapshot_id", "?")[:13]
            emailed = "yes" if v.get("email_sent") else "no"
            print(f"{tester:<15} {addr:<40} {sid:<14} {emailed:>5}")

        print()
        print("Report & Survey Links:")
        print("-" * 80)
        for v in done:
            sid = v.get("snapshot_id", "")
            tester = v.get("tester_name", "?")
            print(f"  {tester}:")
            print(f"    Report: {base_url}/s/{sid}")
            print(f"    Survey: {base_url}/feedback/{sid}")
            print()

    if failed:
        print("Failed:")
        print("-" * 80)
        for v in failed:
            print(f"  {v.get('address', '?')} — {v.get('error', 'unknown')[:80]}")
        print()


def show_status() -> None:
    state = _load_state()
    evals = state.get("evaluations", {})

    if not evals:
        print("No evaluations recorded yet.")
        return

    base_url = DEFAULT_BASE_URL
    _print_summary(state, base_url)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="NestCheck Test B validation runner"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("NESTCHECK_URL", DEFAULT_BASE_URL),
        help="NestCheck base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--builder-secret",
        default=os.environ.get("BUILDER_SECRET"),
        help="Builder mode secret (default: from BUILDER_SECRET env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run evaluations but skip sending emails",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show progress summary and exit",
    )

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if not args.builder_secret:
        logger.error("BUILDER_SECRET is required (env var or --builder-secret)")
        sys.exit(1)

    run_validation(
        base_url=args.base_url.rstrip("/"),
        builder_secret=args.builder_secret,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
