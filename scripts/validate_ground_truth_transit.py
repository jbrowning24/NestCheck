#!/usr/bin/env python3
"""
Validate transit access ground-truth against score_transit_access().

Loads ground-truth JSON from the generator, constructs synthetic dataclass
inputs, calls score_transit_access(), and compares actual vs. expected
scores and confidence levels.

No API calls — uses pre-computed inputs with a mock maps client.

Usage:
    python scripts/validate_ground_truth_transit.py
    python scripts/validate_ground_truth_transit.py --input data/ground_truth/transit.json
    python scripts/validate_ground_truth_transit.py --verbose
    python scripts/validate_ground_truth_transit.py --output data/validation_results_transit.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

# Project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from property_evaluator import (
    score_transit_access,
    PrimaryTransitOption,
    MajorHubAccess,
    UrbanAccessProfile,
    TransitAccessResult,
)


# ---------------------------------------------------------------------------
# Mock maps client — score_transit_access() won't call it when
# urban_access is provided (takes the cached path at line 4739).
# ---------------------------------------------------------------------------

class _MockGoogleMapsClient:
    """Minimal stub for the maps parameter."""
    pass


# ---------------------------------------------------------------------------
# Dataclass reconstruction from JSON
# ---------------------------------------------------------------------------

def _build_urban_access(params: dict) -> UrbanAccessProfile:
    """Reconstruct UrbanAccessProfile from ground-truth JSON params."""
    pt_data = params.get("primary_transit")
    hub_data = params.get("major_hub")

    primary = None
    if pt_data:
        primary = PrimaryTransitOption(
            name=pt_data["name"],
            mode=pt_data["mode"],
            lat=pt_data["lat"],
            lng=pt_data["lng"],
            walk_time_min=pt_data["walk_time_min"],
            drive_time_min=pt_data.get("drive_time_min"),
            user_ratings_total=pt_data.get("user_ratings_total"),
            frequency_class=pt_data.get("frequency_class"),
        )

    hub = None
    if hub_data:
        hub = MajorHubAccess(
            name=hub_data["name"],
            travel_time_min=hub_data["travel_time_min"],
            transit_mode=hub_data["transit_mode"],
            route_summary=hub_data.get("route_summary"),
        )

    return UrbanAccessProfile(primary_transit=primary, major_hub=hub)


def _build_transit_access(params: dict) -> Optional[TransitAccessResult]:
    """Reconstruct TransitAccessResult from ground-truth JSON params.

    Returns None when transit_access is absent, matching the real
    score_transit_access() contract where transit_access=None triggers
    distinct code paths from a default TransitAccessResult().
    """
    ta_data = params.get("transit_access")
    if not ta_data:
        return None
    return TransitAccessResult(
        primary_stop=ta_data.get("primary_stop"),
        walk_minutes=ta_data.get("walk_minutes"),
        mode=ta_data.get("mode"),
        frequency_bucket=ta_data.get("frequency_bucket", "Very low"),
        score_0_10=ta_data.get("score_0_10", 0),
        reasons=ta_data.get("reasons", []),
        nearby_node_count=ta_data.get("nearby_node_count", 0),
        density_node_count=ta_data.get("density_node_count", 0),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate transit ground-truth against score_transit_access()"
    )
    parser.add_argument(
        "--input", type=str, default="data/ground_truth/transit.json",
        help="Ground-truth JSON file (default: data/ground_truth/transit.json)",
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

    mock_maps = _MockGoogleMapsClient()

    # Run validation
    results = []
    matches = 0
    mismatches = 0

    # Per-category tracking
    by_category = {}  # category -> {match, mismatch, total}

    for entry in addresses:
        test_id = entry["id"]
        lat = entry["coordinates"]["lat"]
        lng = entry["coordinates"]["lng"]
        category = entry.get("test_category", "unknown")
        transit_expected = entry["tier2_scored_dimensions"]["urban_access"]
        expected_score = transit_expected["expected_score"]
        expected_confidence = transit_expected["expected_confidence"]

        # Reconstruct inputs from JSON
        params = entry["transit_params"]
        urban_access = _build_urban_access(params)
        transit_access = _build_transit_access(params)

        # Run the actual scoring function
        tier2 = score_transit_access(
            mock_maps, lat, lng,
            transit_access=transit_access,
            urban_access=urban_access,
        )

        actual_score = tier2.points
        actual_confidence = tier2.data_confidence

        # Compare both score and confidence
        score_match = actual_score == expected_score
        conf_match = actual_confidence == expected_confidence

        if score_match and conf_match:
            status = "MATCH"
            matches += 1
        else:
            status = "MISMATCH"
            mismatches += 1

        # Track by category
        if category not in by_category:
            by_category[category] = {"match": 0, "mismatch": 0, "total": 0}
        by_category[category]["total"] += 1
        if status == "MATCH":
            by_category[category]["match"] += 1
        else:
            by_category[category]["mismatch"] += 1

        result_entry = {
            "id": test_id,
            "category": category,
            "expected_score": expected_score,
            "actual_score": actual_score,
            "expected_confidence": expected_confidence,
            "actual_confidence": actual_confidence,
            "status": status,
            "actual_details": tier2.details,
            "notes": transit_expected.get("notes", ""),
        }
        results.append(result_entry)

        if args.verbose:
            marker = "  OK" if status == "MATCH" else "MISS"
            print(
                f"[{marker}] {test_id}: "
                f"expected={expected_score}/{expected_confidence} "
                f"actual={actual_score}/{actual_confidence}"
            )
            if status == "MISMATCH":
                mismatch_parts = []
                if not score_match:
                    mismatch_parts.append(
                        f"score {expected_score}→{actual_score}"
                    )
                if not conf_match:
                    mismatch_parts.append(
                        f"confidence {expected_confidence}→{actual_confidence}"
                    )
                print(f"       MISMATCH: {', '.join(mismatch_parts)}")
                print(f"       Details: {tier2.details}")

    # Summary — format must match validate_all_ground_truth.py _parse_matches()
    total = len(results)
    accuracy = (matches / total * 100) if total > 0 else 0.0

    print()
    print("=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)
    print(f"Total test cases:  {total}")
    print(f"Matches:           {matches}")
    print(f"Mismatches:        {mismatches}")
    print(f"Accuracy:          {accuracy:.1f}% ({matches}/{total})")
    print()

    print("Per-category breakdown:")
    for cat in [
        "monotonicity_walk", "hub_commute_scaling", "frequency",
        "drive_fallback", "no_transit_floor", "confidence_cap", "cap_at_10",
    ]:
        if cat in by_category:
            c = by_category[cat]
            cat_acc = (c["match"] / c["total"] * 100) if c["total"] > 0 else 0.0
            print(
                f"  {cat:25s}: {c['match']}/{c['total']} correct "
                f"({cat_acc:.0f}%)"
            )
    # Also print any unexpected categories
    for cat in sorted(by_category):
        if cat not in {
            "monotonicity_walk", "hub_commute_scaling", "frequency",
            "drive_fallback", "no_transit_floor", "confidence_cap", "cap_at_10",
        }:
            c = by_category[cat]
            print(f"  {cat:25s}: {c['match']}/{c['total']}")
    print()

    # List mismatches
    mismatch_entries = [r for r in results if r["status"] == "MISMATCH"]
    if mismatch_entries:
        print(f"MISMATCHES ({len(mismatch_entries)}):")
        for m in mismatch_entries[:20]:
            print(
                f"  {m['id']}: expected={m['expected_score']}/{m['expected_confidence']} "
                f"actual={m['actual_score']}/{m['actual_confidence']} "
                f"({m['notes']})"
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
