#!/usr/bin/env python3
"""
Validate schools ground-truth against the actual evaluator functions.

Loads ground-truth JSON from the generator, runs get_school_district()
and get_nearby_schools() for each test coordinate, and compares
actual vs. expected results.

No API calls — uses only spatial.db via SpatialDataStore.

Usage:
    python scripts/validate_ground_truth_schools.py
    python scripts/validate_ground_truth_schools.py --input data/ground_truth/schools.json
    python scripts/validate_ground_truth_schools.py --verbose
    python scripts/validate_ground_truth_schools.py --output data/validation_results_schools.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from property_evaluator import get_school_district, get_nearby_schools
from spatial_data import SpatialDataStore


def _validate_district_containment(entry, spatial_store):
    """Validate a district_containment test case.

    Returns (status, details_dict).
    status: "MATCH", "MISMATCH", or "ERROR"
    """
    lat = entry["coordinates"]["lat"]
    lng = entry["coordinates"]["lng"]
    expected = entry["expected"]

    try:
        result = get_school_district(lat, lng, spatial_store)
    except Exception as e:
        return "ERROR", {"error": str(e)}

    actual_found = result is not None
    expected_found = expected["district_found"]

    if actual_found != expected_found:
        return "MISMATCH", {
            "reason": "district_found mismatch",
            "expected_found": expected_found,
            "actual_found": actual_found,
            "actual_geoid": result.geoid if result else None,
        }

    if actual_found and expected_found:
        # Check GEOID match
        if result.geoid != expected["geoid"]:
            return "MISMATCH", {
                "reason": "geoid mismatch",
                "expected_geoid": expected["geoid"],
                "actual_geoid": result.geoid,
            }

        # Check performance data enrichment
        actual_has_perf = (
            result.graduation_rate_pct is not None
            or result.ela_proficiency_pct is not None
            or result.math_proficiency_pct is not None
        )
        expected_has_perf = expected["has_performance_data"]
        if actual_has_perf != expected_has_perf:
            return "MISMATCH", {
                "reason": "performance_data mismatch",
                "expected_has_perf": expected_has_perf,
                "actual_has_perf": actual_has_perf,
                "actual_geoid": result.geoid,
            }

    return "MATCH", {
        "actual_found": actual_found,
        "actual_geoid": result.geoid if result else None,
        "actual_name": result.district_name if result else None,
    }


def _validate_nearby_schools(entry, spatial_store):
    """Validate a nearby_schools test case.

    Returns (status, details_dict).
    status: "MATCH", "MISMATCH", or "ERROR"
    """
    lat = entry["coordinates"]["lat"]
    lng = entry["coordinates"]["lng"]
    expected = entry["expected"]

    try:
        results = get_nearby_schools(lat, lng, spatial_store)
    except Exception as e:
        return "ERROR", {"error": str(e)}

    if results is None:
        results = []

    result_ncessch_ids = {s.ncessch for s in results}
    source_ncessch = expected["source_ncessch"]
    actual_in_results = source_ncessch in result_ncessch_ids
    expected_in_results = expected["source_school_in_results"]

    if actual_in_results != expected_in_results:
        return "MISMATCH", {
            "reason": "school_in_results mismatch",
            "expected_in_results": expected_in_results,
            "actual_in_results": actual_in_results,
            "source_ncessch": source_ncessch,
            "result_count": len(results),
        }

    return "MATCH", {
        "actual_in_results": actual_in_results,
        "result_count": len(results),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate schools ground-truth against evaluator"
    )
    parser.add_argument(
        "--input", type=str, default="data/ground_truth/schools.json",
        help="Ground-truth JSON file (default: data/ground_truth/schools.json)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Write full results JSON to this path",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show per-test-case details",
    )
    args = parser.parse_args()

    # Resolve input path
    input_path = args.input
    if not os.path.isabs(input_path):
        project_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        input_path = os.path.join(project_root, input_path)

    if not os.path.exists(input_path):
        print(f"Error: Ground-truth file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path) as f:
        gt_data = json.load(f)

    test_cases = gt_data.get("test_cases", [])
    if not test_cases:
        print("Error: No test cases in ground-truth file.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(test_cases)} test cases from {input_path}")
    print(f"Schema version: {gt_data.get('_schema_version', '?')}")
    print(f"Generated at: {gt_data.get('_generated_at', '?')}")
    print()

    # Initialize spatial store
    spatial_store = SpatialDataStore()
    if not spatial_store.is_available():
        print("Error: SpatialDataStore is not available.", file=sys.stderr)
        print("Ensure spatial.db and SpatiaLite are accessible.", file=sys.stderr)
        sys.exit(1)

    # Run validation
    results = []
    matches = 0
    mismatches = 0
    errors = 0

    # Per-category tracking
    by_category = {}  # test_type -> {match, mismatch, error, total}

    for entry in test_cases:
        test_id = entry["id"]
        test_type = entry["test_type"]

        if test_type == "district_containment":
            status, details = _validate_district_containment(entry, spatial_store)
        elif test_type == "nearby_schools":
            status, details = _validate_nearby_schools(entry, spatial_store)
        else:
            status = "ERROR"
            details = {"error": f"Unknown test_type: {test_type}"}

        if status == "MATCH":
            matches += 1
        elif status == "MISMATCH":
            mismatches += 1
        else:
            errors += 1

        # Track by category
        cat = test_type
        if cat not in by_category:
            by_category[cat] = {"match": 0, "mismatch": 0, "error": 0, "total": 0}
        by_category[cat]["total"] += 1
        by_category[cat][status.lower()] += 1

        result_entry = {
            "id": test_id,
            "test_type": test_type,
            "coordinates": entry["coordinates"],
            "expected": entry["expected"],
            "status": status,
            "details": details,
        }
        results.append(result_entry)

        if args.verbose:
            marker = {
                "MATCH": "  OK",
                "MISMATCH": "MISS",
                "ERROR": " ERR",
            }[status]
            print(f"[{marker}] {test_id}: {test_type}")
            if status == "MISMATCH":
                reason = details.get("reason", "unknown")
                print(f"       Reason: {reason}")
                for k, v in details.items():
                    if k != "reason":
                        print(f"       {k}: {v}")
            elif status == "ERROR":
                print(f"       Error: {details.get('error', 'unknown')}")

    # Summary
    total = len(results)
    scored = matches + mismatches  # exclude errors from accuracy calc
    accuracy = (matches / scored * 100) if scored > 0 else 0.0

    print()
    print("=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)
    print(f"Total test cases:  {total}")
    print(f"Matches:           {matches}")
    print(f"Mismatches:        {mismatches}")
    print(f"Errors:            {errors}")
    print(f"Accuracy:          {accuracy:.1f}% ({matches}/{scored})")
    print()

    print("Per-category breakdown:")
    for cat in ["district_containment", "nearby_schools"]:
        if cat in by_category:
            c = by_category[cat]
            cat_scored = c["match"] + c["mismatch"]
            cat_acc = (c["match"] / cat_scored * 100) if cat_scored > 0 else 0.0
            print(
                f"  {cat:24s}: {c['match']}/{cat_scored} correct "
                f"({cat_acc:.0f}%), {c['error']} errors"
            )
    print()

    # List mismatches
    mismatch_entries = [r for r in results if r["status"] == "MISMATCH"]
    if mismatch_entries:
        print(f"MISMATCHES ({len(mismatch_entries)}):")
        for m in mismatch_entries[:20]:
            reason = m["details"].get("reason", "unknown")
            print(f"  {m['id']}: {reason}")
            for k, v in m["details"].items():
                if k != "reason":
                    print(f"    {k}: {v}")
        if len(mismatch_entries) > 20:
            print(f"  ... and {len(mismatch_entries) - 20} more")
    print()

    # Write output if requested
    if args.output:
        out_path = args.output
        if not os.path.isabs(out_path):
            project_root = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )
            out_path = os.path.join(project_root, out_path)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        output = {
            "_validated_at": datetime.now(timezone.utc).isoformat(),
            "_ground_truth_file": args.input,
            "_ground_truth_generated_at": gt_data.get("_generated_at"),
            "summary": {
                "total": total,
                "matches": matches,
                "mismatches": mismatches,
                "errors": errors,
                "accuracy_pct": round(accuracy, 2),
                "by_category": by_category,
            },
            "results": results,
        }
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Full results written to: {out_path}")

    # Exit non-zero on mismatches (CI-friendly)
    if mismatches > 0 or errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
