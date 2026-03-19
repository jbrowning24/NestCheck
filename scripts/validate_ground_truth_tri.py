#!/usr/bin/env python3
"""
Validate TRI proximity ground-truth against the actual evaluator.

Loads ground-truth JSON from the generator, runs check_tri_proximity()
for each test coordinate, and compares actual vs. expected results.

No API calls — uses only spatial.db via SpatialDataStore.

Usage:
    python scripts/validate_ground_truth_tri.py
    python scripts/validate_ground_truth_tri.py --input data/ground_truth/tri.json
    python scripts/validate_ground_truth_tri.py --verbose
    python scripts/validate_ground_truth_tri.py --output data/validation_results_tri.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from property_evaluator import check_tri_proximity
from spatial_data import SpatialDataStore


def main():
    parser = argparse.ArgumentParser(
        description="Validate TRI ground-truth against evaluator"
    )
    parser.add_argument(
        "--input", type=str, default="data/ground_truth/tri.json",
        help="Ground-truth JSON file (default: data/ground_truth/tri.json)",
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

    addresses = gt_data.get("addresses", [])
    if not addresses:
        print("Error: No test addresses in ground-truth file.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(addresses)} test cases from {input_path}")
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
    unknowns = 0

    # Per-category tracking
    by_category = {}  # expected_result -> {match, mismatch, unknown, total}

    for entry in addresses:
        test_id = entry["id"]
        lat = entry["coordinates"]["lat"]
        lng = entry["coordinates"]["lng"]
        tri_expected = entry["tier1_health_checks"]["tri_proximity"]
        expected_result = tri_expected["expected_result"]

        # Run the actual check
        tier1 = check_tri_proximity(lat, lng, spatial_store)
        actual_result = tier1.result.value  # "PASS", "WARNING", "UNKNOWN"

        # Classify
        if actual_result == "UNKNOWN":
            status = "UNKNOWN"
            unknowns += 1
        elif actual_result == expected_result:
            status = "MATCH"
            matches += 1
        else:
            status = "MISMATCH"
            mismatches += 1

        # Track by expected category
        cat = expected_result
        if cat not in by_category:
            by_category[cat] = {"match": 0, "mismatch": 0, "unknown": 0, "total": 0}
        by_category[cat]["total"] += 1
        if status == "MATCH":
            by_category[cat]["match"] += 1
        elif status == "MISMATCH":
            by_category[cat]["mismatch"] += 1
        else:
            by_category[cat]["unknown"] += 1

        result_entry = {
            "id": test_id,
            "coordinates": entry["coordinates"],
            "expected_result": expected_result,
            "actual_result": actual_result,
            "status": status,
            "actual_details": tier1.details,
            "actual_distance_m": tier1.value,
            "source_facility": entry.get("source_facility", {}),
        }
        results.append(result_entry)

        if args.verbose:
            marker = {
                "MATCH": "  OK",
                "MISMATCH": "MISS",
                "UNKNOWN": " UNK",
            }[status]
            dist_str = (
                f"{tier1.value:.1f}m" if tier1.value is not None else "N/A"
            )
            print(
                f"[{marker}] {test_id}: expected={expected_result} "
                f"actual={actual_result} dist={dist_str}"
            )
            if status == "MISMATCH":
                src = entry.get("source_facility", {})
                print(
                    f"       Generated {src.get('distance_ft', '?')}ft from "
                    f"'{src.get('name', '?')}' | actual nearest: {dist_str}"
                )

    # Summary
    total = len(results)
    scored = matches + mismatches  # exclude UNKNOWN from accuracy calc
    accuracy = (matches / scored * 100) if scored > 0 else 0.0

    print()
    print("=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)
    print(f"Total test cases:  {total}")
    print(f"Matches:           {matches}")
    print(f"Mismatches:        {mismatches}")
    print(f"Unknown:           {unknowns}")
    print(f"Accuracy:          {accuracy:.1f}% ({matches}/{scored})")
    print()

    print("Per-category breakdown:")
    for cat in ["WARNING", "PASS"]:
        if cat in by_category:
            c = by_category[cat]
            cat_scored = c["match"] + c["mismatch"]
            cat_acc = (c["match"] / cat_scored * 100) if cat_scored > 0 else 0.0
            print(
                f"  {cat:8s}: {c['match']}/{cat_scored} correct "
                f"({cat_acc:.0f}%), {c['unknown']} unknown"
            )
    print()

    # List mismatches
    mismatch_entries = [r for r in results if r["status"] == "MISMATCH"]
    if mismatch_entries:
        print(f"MISMATCHES ({len(mismatch_entries)}):")
        for m in mismatch_entries[:20]:  # Cap at 20
            src = m.get("source_facility", {})
            print(
                f"  {m['id']}: expected={m['expected_result']} "
                f"actual={m['actual_result']} "
                f"dist={m['actual_distance_m']}m "
                f"(generated {src.get('distance_ft', '?')}ft from "
                f"'{src.get('name', '?')}')"
            )
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
                "unknowns": unknowns,
                "accuracy_pct": round(accuracy, 2),
                "by_category": by_category,
            },
            "results": results,
        }
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Full results written to: {out_path}")

    # Exit non-zero on mismatches (CI-friendly)
    if mismatches > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
