#!/usr/bin/env python3
"""
Run all ground-truth validators and print an aggregate summary.

Discovers validator scripts matching scripts/validate_ground_truth_*.py,
finds matching ground-truth files in data/ground_truth/, and runs each
as a subprocess.

Usage:
    python scripts/validate_all_ground_truth.py
    python scripts/validate_all_ground_truth.py --verbose
    python scripts/validate_all_ground_truth.py --dimension ust
"""

import argparse
import glob
import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
GROUND_TRUTH_DIR = os.path.join(PROJECT_ROOT, "data", "ground_truth")

# Human-readable labels for known dimensions.
# Unknown dimensions fall back to UPPER(key).
_DIMENSION_LABELS = {
    "ust": "UST proximity",
    "hpms": "HPMS high-traffic",
    "coffee": "Coffee scoring (Tier 2)",
    "transit": "Transit access",
}


def _discover_validators():
    """Return list of (dimension_key, validator_path) tuples."""
    pattern = os.path.join(SCRIPTS_DIR, "validate_ground_truth_*.py")
    validators = []
    for path in sorted(glob.glob(pattern)):
        basename = os.path.basename(path)
        # validate_ground_truth_ust.py → ust
        match = re.match(r"validate_ground_truth_(.+)\.py$", basename)
        if match:
            dimension = match.group(1)
            validators.append((dimension, path))
    return validators


def _ground_truth_path(dimension):
    """Return expected ground-truth file path for a dimension."""
    return os.path.join(GROUND_TRUTH_DIR, f"{dimension}.json")


def _parse_matches(stdout):
    """Extract matches and mismatches counts from validator stdout.

    Returns (matches, mismatches) or (None, None) if unparseable.
    """
    matches = None
    mismatches = None
    for line in stdout.splitlines():
        m = re.match(r"\s*Matches:\s+(\d+)", line)
        if m:
            matches = int(m.group(1))
        m = re.match(r"\s*Mismatches:\s+(\d+)", line)
        if m:
            mismatches = int(m.group(1))
    if matches is not None and mismatches is not None:
        return matches, mismatches
    return None, None


def _label(dimension):
    """Human-readable label for a dimension."""
    return _DIMENSION_LABELS.get(dimension, dimension.upper())


def main():
    parser = argparse.ArgumentParser(
        description="Run all ground-truth validators and report aggregate results"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Pass --verbose to each validator",
    )
    parser.add_argument(
        "--dimension", type=str, default=None,
        help="Run only this dimension (e.g., ust, hpms)",
    )
    args = parser.parse_args()

    validators = _discover_validators()
    if not validators:
        print("No validator scripts found.", file=sys.stderr)
        sys.exit(1)

    if args.dimension:
        validators = [(d, p) for d, p in validators if d == args.dimension]
        if not validators:
            print(
                f"No validator found for dimension '{args.dimension}'.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Run each validator that has a ground-truth file
    results = []  # list of (dimension, label, matches, mismatches, error_msg)
    any_failure = False

    for dimension, validator_path in validators:
        gt_path = _ground_truth_path(dimension)
        label = _label(dimension)

        if not os.path.exists(gt_path):
            print(f"Skipping {label}: no ground-truth file at {gt_path}")
            continue

        cmd = [
            sys.executable, validator_path,
            "--input", gt_path,
        ]
        if args.verbose:
            cmd.append("--verbose")

        print(f"Running {label} validator...")
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=PROJECT_ROOT,
            )
        except subprocess.TimeoutExpired:
            results.append((dimension, label, None, None, "TIMEOUT after 300s"))
            any_failure = True
            continue
        except Exception as e:
            results.append((dimension, label, None, None, str(e)))
            any_failure = True
            continue

        if args.verbose and proc.stdout:
            print(proc.stdout)
        if args.verbose and proc.stderr:
            print(proc.stderr, file=sys.stderr)

        matches, mismatches = _parse_matches(proc.stdout)

        if matches is not None and mismatches is not None:
            # Successfully parsed — this is a real validation result
            results.append((dimension, label, matches, mismatches, None))
            if mismatches > 0:
                any_failure = True
        elif proc.returncode != 0:
            # Non-zero exit but couldn't parse results — error/crash
            stderr_summary = (proc.stderr or "").strip().splitlines()
            err_msg = stderr_summary[-1] if stderr_summary else "Unknown error"
            results.append((dimension, label, None, None, err_msg))
            any_failure = True
        else:
            # Exit 0 but couldn't parse — shouldn't happen, treat as error
            results.append((dimension, label, None, None, "Could not parse output"))
            any_failure = True

    if not results:
        print("No ground-truth files found to validate.", file=sys.stderr)
        sys.exit(1)

    # Print aggregate summary
    print()
    print("══════════════════════════════════════")
    print("Ground Truth Validation Summary")
    print("══════════════════════════════════════")

    total_matches = 0
    total_scored = 0
    dimensions_with_mismatches = 0
    dimensions_with_errors = 0

    # Find max label width for alignment
    max_label = max(len(r[1]) for r in results)

    for dimension, label, matches, mismatches, error_msg in results:
        padded = f"{label}:".ljust(max_label + 2)
        if error_msg:
            print(f"  {padded} ERROR — {error_msg}")
            dimensions_with_errors += 1
        else:
            scored = matches + mismatches
            total_matches += matches
            total_scored += scored
            if mismatches == 0:
                print(f"  {padded} {matches}/{scored} ✓")
            else:
                print(f"  {padded} {matches}/{scored} ✗ ({mismatches} mismatches)")
                dimensions_with_mismatches += 1

    print("──────────────────────────────────────")

    if total_scored > 0:
        pct = total_matches / total_scored * 100
        print(f"  {'TOTAL:'.ljust(max_label + 2)} {total_matches}/{total_scored} ({pct:.1f}%)")
    else:
        print(f"  {'TOTAL:'.ljust(max_label + 2)} no scored results")

    if dimensions_with_mismatches > 0 or dimensions_with_errors > 0:
        parts = []
        if dimensions_with_mismatches > 0:
            parts.append(f"{dimensions_with_mismatches} dimension(s) with mismatches")
        if dimensions_with_errors > 0:
            parts.append(f"{dimensions_with_errors} dimension(s) with errors")
        print(f"  RESULT: FAIL — {', '.join(parts)}")
    else:
        print("  RESULT: PASS")

    print("══════════════════════════════════════")

    sys.exit(1 if any_failure else 0)


if __name__ == "__main__":
    main()
