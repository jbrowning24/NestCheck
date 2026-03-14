"""Validate UST proximity ground-truth against the actual evaluator.

Loads a ground-truth JSON file (from generate_ground_truth_ust.py),
runs check_ust_proximity() for each test coordinate, and compares
actual vs. expected results.

Usage:
    python scripts/validate_ground_truth_ust.py
    python scripts/validate_ground_truth_ust.py --input data/ground_truth_ust.json
    python scripts/validate_ground_truth_ust.py --verbose
    python scripts/validate_ground_truth_ust.py --output data/validation_results_ust.json
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from property_evaluator import CheckResult, check_ust_proximity
from spatial_data import SpatialDataStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _result_str(check_result: CheckResult) -> str:
    """Convert CheckResult enum to the string used in ground-truth JSON."""
    return check_result.value  # "PASS", "FAIL", "WARNING", "UNKNOWN"


def validate(
    input_path: str = "data/ground_truth_ust.json",
    verbose: bool = False,
) -> dict:
    """Run validation and return results dict.

    Returns:
        {
            "summary": {...},
            "mismatches": [...],
            "unknowns": [...],
            "all_results": [...],  # only if verbose
        }
    """
    if not os.path.exists(input_path):
        logger.error("Ground-truth file not found: %s", input_path)
        sys.exit(1)

    with open(input_path) as f:
        ground_truth = json.load(f)

    addresses = ground_truth.get("addresses", [])
    if not addresses:
        logger.error("No test addresses in ground-truth file")
        sys.exit(1)

    logger.info(
        "Loaded %d test points from %s (schema %s)",
        len(addresses),
        input_path,
        ground_truth.get("_schema_version", "unknown"),
    )

    spatial_store = SpatialDataStore()
    if not spatial_store.is_available():
        logger.error(
            "SpatialDataStore not available — cannot validate. "
            "Ensure spatial.db exists and SpatiaLite is installed."
        )
        sys.exit(1)

    matches = 0
    mismatches = []
    unknowns = []
    all_results = []
    pass_match = 0
    pass_total = 0
    warn_match = 0
    warn_total = 0
    fail_match = 0
    fail_total = 0

    t0 = time.time()

    for addr in addresses:
        test_id = addr["id"]
        lat = addr["coordinates"]["lat"]
        lng = addr["coordinates"]["lng"]
        expected = addr["tier1_health_checks"]["ust_proximity"]
        expected_result = expected["expected_result"]
        expected_pass = expected["expected_pass"]

        actual_check = check_ust_proximity(lat, lng, spatial_store)
        actual_result = _result_str(actual_check.result)
        actual_pass = actual_result == "PASS"

        # Track per-category accuracy
        if expected_result == "PASS":
            pass_total += 1
        elif expected_result == "WARNING":
            warn_total += 1
        elif expected_result == "FAIL":
            fail_total += 1

        entry = {
            "id": test_id,
            "coordinates": addr["coordinates"],
            "expected_result": expected_result,
            "expected_pass": expected_pass,
            "actual_result": actual_result,
            "actual_pass": actual_pass,
            "actual_distance_m": actual_check.value,
            "source_facility": addr.get("source_facility", {}),
        }

        if actual_result == "UNKNOWN":
            unknowns.append(entry)
        elif actual_result == expected_result:
            matches += 1
            if expected_result == "PASS":
                pass_match += 1
            elif expected_result == "WARNING":
                warn_match += 1
            elif expected_result == "FAIL":
                fail_match += 1
        else:
            entry["notes"] = expected.get("notes", "")
            mismatches.append(entry)
            if verbose:
                logger.warning(
                    "MISMATCH %s: expected=%s actual=%s distance=%.1fm "
                    "facility=%s",
                    test_id,
                    expected_result,
                    actual_result,
                    actual_check.value or 0,
                    addr.get("source_facility", {}).get("name", "?"),
                )

        if verbose:
            all_results.append(entry)

    elapsed = time.time() - t0
    scored = matches + len(mismatches)  # excludes UNKNOWN
    total = len(addresses)

    summary = {
        "total_test_points": total,
        "scored": scored,
        "matches": matches,
        "mismatches": len(mismatches),
        "unknowns": len(unknowns),
        "accuracy": round(matches / scored, 4) if scored else 0,
        "accuracy_pct": f"{matches}/{scored} ({matches / scored * 100:.1f}%)"
        if scored
        else "N/A",
        "pass_accuracy": f"{pass_match}/{pass_total}"
        if pass_total
        else "N/A",
        "warning_accuracy": f"{warn_match}/{warn_total}"
        if warn_total
        else "N/A",
        "fail_accuracy": f"{fail_match}/{fail_total}"
        if fail_total
        else "N/A",
        "binary_pass_fail": _binary_accuracy(addresses, all_results)
        if verbose
        else None,
        "elapsed_seconds": round(elapsed, 2),
        "points_per_second": round(total / elapsed, 1) if elapsed else 0,
    }

    return {
        "summary": summary,
        "mismatches": mismatches,
        "unknowns": unknowns,
        **({"all_results": all_results} if verbose else {}),
    }


def _binary_accuracy(
    addresses: list[dict], all_results: list[dict]
) -> str:
    """Compute simpler pass/fail accuracy (WARNING counted as not-pass)."""
    if not all_results:
        return "N/A"
    match = 0
    scored = 0
    for result in all_results:
        if result["actual_result"] == "UNKNOWN":
            continue
        scored += 1
        if result["expected_pass"] == result["actual_pass"]:
            match += 1
    if not scored:
        return "N/A"
    return f"{match}/{scored} ({match / scored * 100:.1f}%)"


def _print_report(results: dict) -> None:
    """Print a human-readable validation report."""
    s = results["summary"]
    print()
    print("=" * 60)
    print("  UST Proximity Ground-Truth Validation")
    print("=" * 60)
    print()
    print(f"  Total test points:   {s['total_test_points']}")
    print(f"  Scored (non-UNKNOWN): {s['scored']}")
    print(f"  Matches:             {s['matches']}")
    print(f"  Mismatches:          {s['mismatches']}")
    print(f"  Unknown:             {s['unknowns']}")
    print()
    print(f"  3-state accuracy:    {s['accuracy_pct']}")
    print(f"    FAIL accuracy:     {s['fail_accuracy']}")
    print(f"    WARNING accuracy:  {s['warning_accuracy']}")
    print(f"    PASS accuracy:     {s['pass_accuracy']}")
    if s.get("binary_pass_fail"):
        print(f"  Binary pass/fail:    {s['binary_pass_fail']}")
    print()
    print(f"  Elapsed:             {s['elapsed_seconds']}s")
    print(f"  Throughput:          {s['points_per_second']} pts/s")
    print()

    if results["mismatches"]:
        print("-" * 60)
        print("  Mismatches:")
        print("-" * 60)
        for m in results["mismatches"]:
            fac = m.get("source_facility", {})
            print(
                f"  {m['id']}: expected={m['expected_result']} "
                f"actual={m['actual_result']} "
                f"distance={m.get('actual_distance_m', '?')}m "
                f"facility={fac.get('name', '?')} "
                f"gen_dist={fac.get('distance_ft', '?')}ft"
            )
        print()

    if results["unknowns"]:
        print(f"  ({len(results['unknowns'])} UNKNOWN results — "
              f"spatial data gap or query error)")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Validate UST ground-truth against the actual evaluator"
    )
    parser.add_argument(
        "--input",
        type=str,
        default="data/ground_truth_ust.json",
        help="Path to ground-truth JSON (default: data/ground_truth_ust.json)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write validation results JSON (optional)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include all results (not just mismatches) in output",
    )

    args = parser.parse_args()

    results = validate(
        input_path=args.input,
        verbose=args.verbose,
    )

    _print_report(results)

    if args.output:
        output = {
            "_generated_at": datetime.now(timezone.utc).isoformat(),
            "_validator": "validate_ground_truth_ust.py",
            "_input": args.input,
            **results,
        }
        output_dir = os.path.dirname(args.output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        logger.info("Wrote validation results to %s", args.output)

    # Exit with non-zero if any mismatches for CI use
    if results["mismatches"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
