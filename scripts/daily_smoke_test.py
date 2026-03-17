#!/usr/bin/env python3
"""
Daily smoke test for NestCheck evaluation pipeline.

Runs evaluate_property() for a single test address, validates the result
dict structure, and sends an email alert via Resend on failure or warnings.
Exits silently on success.

Usage:
    # Run and print results to stdout (no email):
    python scripts/daily_smoke_test.py

    # Run and send email on failure/warning:
    python scripts/daily_smoke_test.py --email ops@nestcheck.com

Exit codes:
    0 = all checks passed (or warnings only)
    1 = validation failures detected
"""

import argparse
import html as html_mod
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so we can import app modules.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_SCRIPT_DIR))
os.chdir(_PROJECT_ROOT)

from property_evaluator import PropertyListing, evaluate_property
from regression_baseline import TEST_ADDRESSES

logger = logging.getLogger("daily_smoke_test")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FROM_ADDRESS = "NestCheck <reports@nestcheck.com>"

# Use the Bronxville address from the regression baseline set.
_BRONXVILLE = next(
    addr for label, addr in TEST_ADDRESSES if label == "westchester_village"
)
TEST_ADDRESS = _BRONXVILLE

# Keys that must be present and non-None — failure if missing.
REQUIRED_KEYS = [
    "address",
    "coordinates",
    "tier1_checks",
    "presented_checks",
    "tier2_scores",
    "final_score",
    "score_band",
    "verdict",
    "dimension_summaries",
    "structured_summary",
]

# Keys that are expected but nullable — warn if None, don't fail.
WARN_KEYS = [
    "walk_scores",
    "child_schooling_snapshot",
    "urban_access",
    "green_escape",
    "ejscreen_profile",
    "school_district",
    "nearby_schools",
    "demographics",
    "walk_quality",
    "road_noise",
]

# All six expected dimension names in tier2_scores.
EXPECTED_DIMENSIONS = [
    "Primary Green Escape",
    "Third Place",
    "Provisioning",
    "Fitness access",
    "Urban access",
    "Road Noise",
]

# Timing threshold — informational warning, not a failure.
TIMING_WARN_SECONDS = 90


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def run_evaluation(address: str, api_key: str) -> Dict[str, Any]:
    """Run evaluate_property and serialize via result_to_dict.

    Raises on failure — caller handles the exception.
    """
    listing = PropertyListing(address=address)
    eval_result = evaluate_property(listing, api_key)

    from app import result_to_dict
    return result_to_dict(eval_result)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_result(
    result: Dict[str, Any], elapsed_seconds: float,
) -> Tuple[List[str], List[str]]:
    """Validate the result dict.

    Returns (failures, warnings) — both are lists of human-readable strings.
    """
    failures: List[str] = []
    warnings: List[str] = []

    # --- Required keys ---
    for key in REQUIRED_KEYS:
        if key not in result:
            failures.append(f"Required key missing: '{key}'")
        elif result[key] is None:
            failures.append(f"Required key is None: '{key}'")

    # --- Warn-but-don't-fail keys ---
    for key in WARN_KEYS:
        if key not in result or result[key] is None:
            warnings.append(f"Optional key is None: '{key}'")

    # --- Dimension validation ---
    tier2 = result.get("tier2_scores")
    if isinstance(tier2, list):
        present_dims = {s["name"] for s in tier2 if isinstance(s, dict)}
        for dim in EXPECTED_DIMENSIONS:
            if dim not in present_dims:
                failures.append(f"Missing dimension in tier2_scores: '{dim}'")
    # (if tier2_scores is missing entirely, it's already caught by REQUIRED_KEYS)

    # --- Health checks validation ---
    tier1 = result.get("tier1_checks")
    if isinstance(tier1, list):
        if len(tier1) == 0:
            failures.append("tier1_checks is empty (expected non-empty)")
        for i, check in enumerate(tier1):
            if not isinstance(check, dict):
                failures.append(f"tier1_checks[{i}] is not a dict")
            elif "result" not in check:
                failures.append(
                    f"tier1_checks[{i}] ('{check.get('name', '?')}') "
                    f"missing 'result' field"
                )

    presented = result.get("presented_checks")
    if isinstance(presented, list) and len(presented) == 0:
        failures.append("presented_checks is empty (expected non-empty)")

    # --- Timing warning ---
    if elapsed_seconds > TIMING_WARN_SECONDS:
        warnings.append(
            f"Evaluation took {elapsed_seconds:.0f}s "
            f"(threshold: {TIMING_WARN_SECONDS}s)"
        )

    return failures, warnings


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


def _format_html_email(
    failures: List[str],
    warnings: List[str],
    elapsed_seconds: float,
    address: str,
) -> str:
    """Build the HTML email body."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if failures:
        status_color = "#dc2626"
        status_text = f"{len(failures)} check{'s' if len(failures) != 1 else ''} failed"
    else:
        status_color = "#d97706"
        status_text = f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}"

    sections_html = ""

    if failures:
        items = "".join(
            f"<li>{html_mod.escape(f)}</li>" for f in failures
        )
        sections_html += f"""
        <div style="margin: 1rem 0;">
          <p style="font-weight: 600; color: #dc2626;">Failures</p>
          <ul style="margin: 0.25rem 0; padding-left: 1.25rem; font-size: 0.9rem;">{items}</ul>
        </div>"""

    if warnings:
        items = "".join(
            f"<li>{html_mod.escape(w)}</li>" for w in warnings
        )
        sections_html += f"""
        <div style="margin: 1rem 0;">
          <p style="font-weight: 600; color: #d97706;">Warnings</p>
          <ul style="margin: 0.25rem 0; padding-left: 1.25rem; font-size: 0.9rem;">{items}</ul>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: system-ui, sans-serif; line-height: 1.5; color: #1f2937;">
  <div style="max-width: 560px; margin: 0 auto; padding: 1.5rem;">
    <p style="font-size: 1.25rem; font-weight: 600; color: #0f3460;">NestCheck</p>
    <p style="font-size: 0.85rem; color: #6b7280;">{html_mod.escape(now_str)}</p>

    <div style="margin: 1rem 0; padding: 12px 16px; border-radius: 8px; background: {status_color}10; border-left: 4px solid {status_color};">
      <span style="font-weight: 600; color: {status_color};">{html_mod.escape(status_text)}</span>
    </div>

    <p style="font-size: 0.9rem; color: #6b7280;">
      Address: <strong>{html_mod.escape(address)}</strong><br>
      Elapsed: {elapsed_seconds:.0f}s
    </p>

    {sections_html}

    <p style="font-size: 0.8rem; color: #9ca3af; margin-top: 1.5rem;">
      Daily smoke test &mdash; evaluation pipeline health check
    </p>
  </div>
</body>
</html>"""


def send_alert_email(
    to_email: str,
    failures: List[str],
    warnings: List[str],
    elapsed_seconds: float,
    address: str,
) -> bool:
    """Send HTML alert via Resend. Returns True on success. Never raises."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        logger.warning("RESEND_API_KEY not set; cannot send alert email")
        return False

    if failures:
        subject = "NestCheck Smoke Test: FAILURE"
    else:
        subject = "NestCheck Smoke Test: Warnings"

    try:
        import resend

        resend.api_key = api_key
        params = {
            "from": FROM_ADDRESS,
            "to": [to_email],
            "subject": subject,
            "html": _format_html_email(
                failures, warnings, elapsed_seconds, address,
            ),
        }
        resend.Emails.send(params)
        logger.info("Alert email sent to %s***", to_email[:3])
        return True
    except Exception as e:
        logger.warning("Failed to send alert email: %s", e, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Daily smoke test for NestCheck evaluation pipeline"
    )
    parser.add_argument(
        "--email",
        help="Send alert email to this address on failure or warnings",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        logger.error("GOOGLE_MAPS_API_KEY not set")
        sys.exit(1)

    # If --email not passed, check env var.
    notify_email = args.email or os.environ.get("SMOKE_TEST_NOTIFY_EMAIL")

    # --- Run evaluation ---
    logger.info("Smoke test starting: %s", TEST_ADDRESS)
    t0 = time.time()

    try:
        result = run_evaluation(TEST_ADDRESS, api_key)
    except Exception as e:
        elapsed = time.time() - t0
        logger.error("Evaluation crashed after %.0fs: %s", elapsed, e)
        failures = [f"evaluate_property() raised: {type(e).__name__}: {e}"]
        if notify_email:
            send_alert_email(notify_email, failures, [], elapsed, TEST_ADDRESS)
        sys.exit(1)

    elapsed = time.time() - t0
    logger.info("Evaluation completed in %.0fs", elapsed)

    # --- Validate ---
    failures, warnings = validate_result(result, elapsed)

    # --- Report ---
    if failures:
        logger.error("SMOKE TEST FAILED (%d failures, %d warnings)", len(failures), len(warnings))
        for f in failures:
            logger.error("  FAIL: %s", f)
        for w in warnings:
            logger.warning("  WARN: %s", w)
        if notify_email:
            send_alert_email(notify_email, failures, warnings, elapsed, TEST_ADDRESS)
        sys.exit(1)

    if warnings:
        logger.warning("Smoke test passed with %d warning(s)", len(warnings))
        for w in warnings:
            logger.warning("  WARN: %s", w)
        if notify_email:
            send_alert_email(notify_email, [], warnings, elapsed, TEST_ADDRESS)
        sys.exit(0)

    # All clear — one-line success for Railway log viewer.
    logger.info(
        "Smoke test passed — %s — %.0fs — all checks OK", TEST_ADDRESS, elapsed,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
