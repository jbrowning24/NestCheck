#!/usr/bin/env python3
"""
Regression baseline comparison for NestCheck evaluations.

Runs a fixed set of test addresses through the evaluation pipeline,
compares each output field against saved baseline snapshots, and
emails a diff summary when regressions are detected.

Usage:
    python scripts/regression_baseline.py                  # compare against baselines
    python scripts/regression_baseline.py --update-baselines  # save new baselines
    python scripts/regression_baseline.py --dry-run        # compare but don't email

Baselines are JSON files in data/regression_baselines/.
After an intentional scoring change, re-run with --update-baselines.

Exit codes:
    0 = all addresses match baselines (within thresholds)
    1 = regressions detected or errors occurred
    2 = no baselines exist yet (run --update-baselines first)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so we can import app modules.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))
os.chdir(_PROJECT_ROOT)

from property_evaluator import PropertyListing, evaluate_property
from health_monitor import get_status as get_health_status

logger = logging.getLogger("regression_baseline")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASELINES_DIR = _PROJECT_ROOT / "data" / "regression_baselines"

# Score drift threshold: flag if a dimension score changed by more than this.
SCORE_DRIFT_THRESHOLD = 2

# Test addresses — geographically diverse across the tri-state coverage area.
# Each entry: (label, address_string)
TEST_ADDRESSES: List[Tuple[str, str]] = [
    ("westchester_suburban", "100 Fisher Ave, White Plains, NY 10606"),
    ("westchester_village", "15 Kraft Ave, Bronxville, NY 10708"),
    ("ct_suburban", "45 Tokeneke Rd, Darien, CT 06820"),
    ("nj_suburban", "200 Glen Ave, Glen Rock, NJ 07452"),
    ("nyc_urban", "350 E 62nd St, New York, NY 10065"),
    ("hudson_valley", "10 Academy St, Cold Spring, NY 10516"),
    ("li_suburban", "125 Stewart Ave, Garden City, NY 11530"),
]

# Fields to compare for regressions.
# Dimension scores: points changed by > SCORE_DRIFT_THRESHOLD.
# Health checks: status changed (pass/fail/warning).
# Final score: changed by > SCORE_DRIFT_THRESHOLD.

# Fields that are expected to vary between runs (timestamps, latency, etc.)
# and should be excluded from comparison.
IGNORED_FIELDS = {
    "_trace",
    "evaluated_at",
    "snapshot_id",
}


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def run_evaluation(address: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Run a single evaluation and return the result dict, or None on error."""
    try:
        listing = PropertyListing(address=address)
        eval_result = evaluate_property(listing, api_key)

        # Use the same serialization as the production path.
        from app import result_to_dict
        result = result_to_dict(eval_result)
        return result
    except Exception as e:
        logger.error("Evaluation failed for %s: %s", address, e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Baseline I/O
# ---------------------------------------------------------------------------

def _baseline_path(label: str) -> Path:
    return BASELINES_DIR / f"{label}.json"


def load_baseline(label: str) -> Optional[Dict[str, Any]]:
    path = _baseline_path(label)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_baseline(label: str, result: Dict[str, Any]) -> None:
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    path = _baseline_path(label)
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info("Saved baseline: %s", path)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

class Regression:
    """A single detected regression."""
    __slots__ = ("address", "label", "field", "baseline_value", "current_value", "severity")

    def __init__(self, address, label, field, baseline_value, current_value, severity):
        self.address = address
        self.label = label
        self.field = field
        self.baseline_value = baseline_value
        self.current_value = current_value
        self.severity = severity

    def __repr__(self):
        return (
            f"Regression({self.field!r}: {self.baseline_value!r} → "
            f"{self.current_value!r}, severity={self.severity!r})"
        )


def _extract_dimension_scores(result: Dict) -> Dict[str, Optional[int]]:
    """Extract dimension name → points mapping from tier2_scores."""
    scores = {}
    for s in result.get("tier2_scores", []):
        scores[s["name"]] = s.get("points")
    return scores


def _extract_health_checks(result: Dict) -> Dict[str, str]:
    """Extract health check name → result status mapping."""
    checks = {}
    for c in result.get("tier1_checks", []):
        checks[c["name"]] = c.get("result", "unknown")
    return checks


def compare_results(
    label: str,
    address: str,
    baseline: Dict[str, Any],
    current: Dict[str, Any],
) -> List[Regression]:
    """Compare current result against baseline, return list of regressions."""
    regressions = []

    # --- Dimension scores ---
    baseline_scores = _extract_dimension_scores(baseline)
    current_scores = _extract_dimension_scores(current)

    all_dims = set(baseline_scores.keys()) | set(current_scores.keys())
    for dim in sorted(all_dims):
        b_val = baseline_scores.get(dim)
        c_val = current_scores.get(dim)

        if dim not in baseline_scores:
            regressions.append(Regression(
                address, label, f"tier2[{dim}]",
                None, c_val, "field_added",
            ))
            continue

        if dim not in current_scores:
            regressions.append(Regression(
                address, label, f"tier2[{dim}]",
                b_val, None, "field_missing",
            ))
            continue

        # Both None (suppressed) — no regression.
        if b_val is None and c_val is None:
            continue

        # One suppressed, other not.
        if (b_val is None) != (c_val is None):
            regressions.append(Regression(
                address, label, f"tier2[{dim}]",
                b_val, c_val, "score_drift",
            ))
            continue

        if abs(b_val - c_val) > SCORE_DRIFT_THRESHOLD:
            regressions.append(Regression(
                address, label, f"tier2[{dim}]",
                b_val, c_val, "score_drift",
            ))

    # --- Health checks (tier1) ---
    baseline_checks = _extract_health_checks(baseline)
    current_checks = _extract_health_checks(current)

    all_checks = set(baseline_checks.keys()) | set(current_checks.keys())
    for check in sorted(all_checks):
        b_status = baseline_checks.get(check)
        c_status = current_checks.get(check)

        if check not in baseline_checks:
            regressions.append(Regression(
                address, label, f"tier1[{check}]",
                None, c_status, "field_added",
            ))
            continue

        if check not in current_checks:
            regressions.append(Regression(
                address, label, f"tier1[{check}]",
                b_status, None, "field_missing",
            ))
            continue

        if b_status != c_status:
            regressions.append(Regression(
                address, label, f"tier1[{check}]",
                b_status, c_status, "health_status_change",
            ))

    # --- Final composite score ---
    b_final = baseline.get("final_score")
    c_final = current.get("final_score")
    if b_final is not None and c_final is not None:
        if abs(b_final - c_final) > SCORE_DRIFT_THRESHOLD:
            regressions.append(Regression(
                address, label, "final_score",
                b_final, c_final, "score_drift",
            ))

    # --- passed_tier1 flag ---
    if baseline.get("passed_tier1") != current.get("passed_tier1"):
        regressions.append(Regression(
            address, label, "passed_tier1",
            baseline.get("passed_tier1"), current.get("passed_tier1"),
            "health_status_change",
        ))

    return regressions


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_report(
    all_regressions: Dict[str, List[Regression]],
    errors: List[str],
    run_time: str,
) -> str:
    """Format a human-readable regression report."""
    lines = []
    lines.append("=" * 60)
    lines.append("NestCheck Regression Baseline Report")
    lines.append(f"Run: {run_time}")
    lines.append("=" * 60)

    if not all_regressions and not errors:
        lines.append("")
        lines.append("All addresses match baselines. No regressions detected.")
        lines.append("")
        return "\n".join(lines)

    if errors:
        lines.append("")
        lines.append("ERRORS:")
        for err in errors:
            lines.append(f"  - {err}")

    total_regressions = sum(len(r) for r in all_regressions.values())
    lines.append("")
    lines.append(f"REGRESSIONS DETECTED: {total_regressions}")
    lines.append("-" * 60)

    for label, regressions in sorted(all_regressions.items()):
        if not regressions:
            continue
        addr = regressions[0].address
        lines.append("")
        lines.append(f"  {label} ({addr})")
        for r in regressions:
            icon = "!!" if r.severity in ("score_drift", "health_status_change") else "??"
            lines.append(f"    [{icon}] {r.field}: {r.baseline_value} → {r.current_value}")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def send_regression_email(report_text: str, to_email: Optional[str] = None) -> bool:
    """Email the regression report via Resend."""
    api_key = os.environ.get("RESEND_API_KEY")
    notify_email = to_email or os.environ.get("REGRESSION_NOTIFY_EMAIL")
    if not api_key or not notify_email:
        logger.warning(
            "RESEND_API_KEY or REGRESSION_NOTIFY_EMAIL not set; skipping email"
        )
        return False

    try:
        import resend
        resend.api_key = api_key

        params = {
            "from": "NestCheck <reports@nestcheck.com>",
            "to": [notify_email],
            "subject": "NestCheck Regression Alert",
            "text": report_text,
        }
        resend.Emails.send(params)
        logger.info("Regression report emailed to %s", notify_email)
        return True
    except Exception as e:
        logger.warning("Failed to send regression email: %s", e)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="NestCheck regression baseline comparison")
    parser.add_argument(
        "--update-baselines", action="store_true",
        help="Run evaluations and save results as new baselines",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compare against baselines but don't send email",
    )
    parser.add_argument(
        "--email",
        help="Send regression report to this address (overrides REGRESSION_NOTIFY_EMAIL)",
    )
    parser.add_argument(
        "--addresses", nargs="*",
        help="Run only specific address labels (default: all)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        logger.error("GOOGLE_MAPS_API_KEY not set")
        sys.exit(1)

    # Filter addresses if specific labels requested.
    addresses = TEST_ADDRESSES
    if args.addresses:
        addresses = [(l, a) for l, a in TEST_ADDRESSES if l in args.addresses]
        if not addresses:
            logger.error("No matching address labels: %s", args.addresses)
            sys.exit(1)

    run_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if args.update_baselines:
        print(f"Updating baselines for {len(addresses)} addresses...")
        for label, address in addresses:
            print(f"  Evaluating: {label} ({address})")
            result = run_evaluation(address, api_key)
            if result is None:
                print(f"    FAILED — skipping baseline save")
                continue
            save_baseline(label, result)
            print(f"    Saved.")
        print("Done. Baselines saved to data/regression_baselines/")
        sys.exit(0)

    # --- Compare mode ---
    if not BASELINES_DIR.exists() or not list(BASELINES_DIR.glob("*.json")):
        print("No baselines found. Run with --update-baselines first.")
        sys.exit(2)

    all_regressions: Dict[str, List[Regression]] = {}
    errors: List[str] = []

    for label, address in addresses:
        baseline = load_baseline(label)
        if baseline is None:
            errors.append(f"No baseline for {label} — run --update-baselines")
            continue

        print(f"Evaluating: {label} ({address})...", end=" ", flush=True)
        t0 = time.time()
        current = run_evaluation(address, api_key)
        elapsed = time.time() - t0

        if current is None:
            errors.append(f"Evaluation failed for {label}")
            print(f"FAILED ({elapsed:.0f}s)")
            continue

        regressions = compare_results(label, address, baseline, current)
        all_regressions[label] = regressions

        if regressions:
            print(f"{len(regressions)} regression(s) ({elapsed:.0f}s)")
        else:
            print(f"OK ({elapsed:.0f}s)")

    # --- Report ---
    report = format_report(all_regressions, errors, run_time)
    print()
    print(report)

    has_regressions = any(r for r in all_regressions.values()) or errors

    if has_regressions and not args.dry_run:
        send_regression_email(report, to_email=args.email)

    sys.exit(1 if has_regressions else 0)


if __name__ == "__main__":
    main()
