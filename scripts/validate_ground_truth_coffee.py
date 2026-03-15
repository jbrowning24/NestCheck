#!/usr/bin/env python3
"""
Validate coffee/third-place scoring ground-truth against actual functions.

Loads ground-truth JSON from the generator, runs apply_piecewise() and
_compute_quality_ceiling() for each test case, and compares actual vs
expected results.

No API calls, no spatial.db — pure scoring function tests.

Usage:
    python scripts/validate_ground_truth_coffee.py
    python scripts/validate_ground_truth_coffee.py --input data/ground_truth/coffee.json
    python scripts/validate_ground_truth_coffee.py --verbose
    python scripts/validate_ground_truth_coffee.py --output data/validation_results_coffee.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_config import SCORING_MODEL, apply_piecewise
from property_evaluator import _compute_quality_ceiling, _apply_confidence_cap

TOLERANCE = 0.001


def _validate_knot_boundary(case, knots):
    """Validate exact knot value tests."""
    walk_time = case["inputs"]["walk_time_min"]
    expected = case["expected"]["final_score_exact"]
    actual = apply_piecewise(knots, walk_time)

    if abs(actual - expected) < TOLERANCE:
        return "MATCH", actual, None
    return "MISMATCH", actual, f"expected={expected}, actual={actual}"


def _validate_interpolation(case, knots):
    """Validate midpoint interpolation tests."""
    walk_time = case["inputs"]["walk_time_min"]
    expected = case["expected"]["final_score_exact"]
    actual = apply_piecewise(knots, walk_time)

    if abs(actual - expected) < TOLERANCE:
        return "MATCH", actual, None
    return "MISMATCH", actual, f"expected={expected}, actual={actual}"


def _validate_monotonicity(case, knots):
    """Validate that score(t1) >= score(t2) when t1 < t2."""
    t_a = case["inputs"]["walk_time_a"]
    t_b = case["inputs"]["walk_time_b"]
    score_a = apply_piecewise(knots, t_a)
    score_b = apply_piecewise(knots, t_b)

    if score_a >= score_b - TOLERANCE:
        return "MATCH", {"score_a": score_a, "score_b": score_b}, None
    return (
        "MISMATCH",
        {"score_a": score_a, "score_b": score_b},
        f"score({t_a})={score_a} < score({t_b})={score_b} — monotonicity violation",
    )


def _validate_clamping(case, knots):
    """Validate clamping outside knot range."""
    walk_time = case["inputs"]["walk_time_min"]
    expected = case["expected"]["final_score_exact"]
    actual = apply_piecewise(knots, walk_time)

    if abs(actual - expected) < TOLERANCE:
        return "MATCH", actual, None
    return "MISMATCH", actual, f"expected={expected}, actual={actual}"


def _validate_floor(case, knots, floor):
    """Validate that score >= floor for extreme walk times."""
    walk_time = case["inputs"]["walk_time_min"]
    expected_min = case["expected"]["final_score_min"]
    raw = apply_piecewise(knots, walk_time)
    final = max(floor, raw)

    if final >= expected_min - TOLERANCE:
        return "MATCH", {"raw": raw, "final": final}, None
    return (
        "MISMATCH",
        {"raw": raw, "final": final},
        f"final={final} < floor={expected_min}",
    )


def _validate_quality_ceiling(case, ceiling_config):
    """Validate _compute_quality_ceiling() output."""
    places = case["inputs"]["eligible_places"]
    bucket_count = case["inputs"].get("social_bucket_count", 0)
    expected = case["expected"]["quality_ceiling"]

    actual = _compute_quality_ceiling(
        places, ceiling_config, social_bucket_count=bucket_count
    )

    if actual == expected:
        return "MATCH", actual, None
    return "MISMATCH", actual, f"expected ceiling={expected}, actual={actual}"


def _validate_ceiling_max(case, knots, ceiling_config):
    """Validate maximal-diversity ceiling reaches 10."""
    walk_time = case["inputs"]["walk_time_min"]
    places = case["inputs"]["eligible_places"]
    bucket_count = case["inputs"].get("social_bucket_count", 0)
    expected_score = case["expected"]["final_score_exact"]

    proximity = apply_piecewise(knots, walk_time)
    ceiling = _compute_quality_ceiling(
        places, ceiling_config, social_bucket_count=bucket_count
    )
    final = min(proximity, ceiling)

    if abs(final - expected_score) < TOLERANCE:
        return "MATCH", {"proximity": proximity, "ceiling": ceiling, "final": final}, None
    return (
        "MISMATCH",
        {"proximity": proximity, "ceiling": ceiling, "final": final},
        f"expected={expected_score}, actual={final}",
    )


def _validate_ceiling_caps(case, knots, ceiling_config):
    """Validate ceiling < proximity → final = ceiling."""
    walk_time = case["inputs"]["walk_time_min"]
    places = case["inputs"]["eligible_places"]
    bucket_count = case["inputs"].get("social_bucket_count", 0)
    expected_score = case["expected"]["final_score_exact"]
    expected_ceiling = case["expected"]["quality_ceiling"]

    proximity = apply_piecewise(knots, walk_time)
    ceiling = _compute_quality_ceiling(
        places, ceiling_config, social_bucket_count=bucket_count
    )
    final = min(proximity, ceiling)

    errors = []
    if ceiling != expected_ceiling:
        errors.append(f"ceiling: expected={expected_ceiling}, actual={ceiling}")
    if abs(final - expected_score) >= TOLERANCE:
        errors.append(f"final: expected={expected_score}, actual={final}")

    if not errors:
        return (
            "MATCH",
            {"proximity": proximity, "ceiling": ceiling, "final": final},
            None,
        )
    return (
        "MISMATCH",
        {"proximity": proximity, "ceiling": ceiling, "final": final},
        "; ".join(errors),
    )


def _validate_pipeline_composition(case, knots, floor, ceiling_config):
    """Validate the full scoring pipeline composition.

    Replicates the exact order of operations from score_third_place_access():
    piecewise → min(score, ceiling) → confidence_cap → max(floor, score) → round

    Catches double-ceiling regressions (NES-222): if a second ceiling mechanism
    is introduced, the intermediate or final values will diverge.
    """
    walk_time = case["inputs"]["walk_time_min"]
    places = case["inputs"]["eligible_places"]
    buckets = case["inputs"].get("social_bucket_count", 0)
    confidence = case["inputs"]["confidence"]
    expected = case["expected"]

    # Run the pipeline
    proximity = apply_piecewise(knots, walk_time)
    ceiling = _compute_quality_ceiling(
        places, ceiling_config, social_bucket_count=buckets
    )
    after_ceiling = min(proximity, ceiling)
    after_confidence = _apply_confidence_cap(after_ceiling, confidence)
    after_floor = max(floor, after_confidence)
    final_points = int(after_floor + 0.5)

    # Check each stage
    errors = []
    if abs(proximity - expected["piecewise_score"]) >= TOLERANCE:
        errors.append(f"piecewise: expected={expected['piecewise_score']}, actual={proximity}")
    if ceiling != expected["quality_ceiling"]:
        errors.append(f"ceiling: expected={expected['quality_ceiling']}, actual={ceiling}")
    if abs(after_ceiling - expected["after_ceiling"]) >= TOLERANCE:
        errors.append(f"after_ceiling: expected={expected['after_ceiling']}, actual={after_ceiling}")
    if abs(after_confidence - expected["after_confidence"]) >= TOLERANCE:
        errors.append(f"after_confidence: expected={expected['after_confidence']}, actual={after_confidence}")
    if abs(after_floor - expected["after_floor"]) >= TOLERANCE:
        errors.append(f"after_floor: expected={expected['after_floor']}, actual={after_floor}")
    if final_points != expected["final_points"]:
        errors.append(f"final_points: expected={expected['final_points']}, actual={final_points}")

    actual = {
        "proximity": proximity,
        "ceiling": ceiling,
        "after_ceiling": after_ceiling,
        "after_confidence": after_confidence,
        "after_floor": after_floor,
        "final_points": final_points,
    }

    if not errors:
        return "MATCH", actual, None
    return "MISMATCH", actual, "; ".join(errors)


# Dispatch table: test_type → validator function signature
_VALIDATORS = {
    "knot_boundary": lambda case, ctx: _validate_knot_boundary(case, ctx["knots"]),
    "interpolation": lambda case, ctx: _validate_interpolation(case, ctx["knots"]),
    "monotonicity": lambda case, ctx: _validate_monotonicity(case, ctx["knots"]),
    "clamping": lambda case, ctx: _validate_clamping(case, ctx["knots"]),
    "floor": lambda case, ctx: _validate_floor(case, ctx["knots"], ctx["floor"]),
    "quality_ceiling": lambda case, ctx: _validate_quality_ceiling(case, ctx["ceiling_config"]),
    "ceiling_max": lambda case, ctx: _validate_ceiling_max(case, ctx["knots"], ctx["ceiling_config"]),
    "ceiling_caps": lambda case, ctx: _validate_ceiling_caps(case, ctx["knots"], ctx["ceiling_config"]),
    "pipeline_composition": lambda case, ctx: _validate_pipeline_composition(case, ctx["knots"], ctx["floor"], ctx["ceiling_config"]),
}


def main():
    parser = argparse.ArgumentParser(
        description="Validate coffee ground-truth against scoring functions"
    )
    parser.add_argument(
        "--input", type=str, default="data/ground_truth/coffee.json",
        help="Ground-truth JSON file (default: data/ground_truth/coffee.json)",
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
    print(f"Scoring model version: {gt_data.get('_scoring_model_version', '?')}")
    print(f"Generated at: {gt_data.get('_generated_at', '?')}")

    # Check model version match
    if gt_data.get("_scoring_model_version") != SCORING_MODEL.version:
        print(
            f"\nWARNING: Ground truth was generated with model version "
            f"{gt_data.get('_scoring_model_version')}, but current model is "
            f"{SCORING_MODEL.version}. Consider regenerating."
        )
    print()

    # Build validation context
    cfg = SCORING_MODEL.coffee
    ctx = {
        "knots": cfg.knots,
        "floor": cfg.floor,
        "ceiling_config": cfg.quality_ceiling,
    }

    # Run validation
    results = []
    matches = 0
    mismatches = 0
    by_type = {}  # test_type → {match, mismatch, total}

    for case in test_cases:
        test_id = case["id"]
        test_type = case["test_type"]

        # Track by type
        if test_type not in by_type:
            by_type[test_type] = {"match": 0, "mismatch": 0, "total": 0}
        by_type[test_type]["total"] += 1

        validator = _VALIDATORS.get(test_type)
        if not validator:
            result_entry = {
                "id": test_id,
                "test_type": test_type,
                "status": "UNKNOWN",
                "error": f"No validator for test type '{test_type}'",
            }
            results.append(result_entry)
            if args.verbose:
                print(f"[ UNK] {test_id}: unknown test type '{test_type}'")
            continue

        status, actual, error_msg = validator(case, ctx)

        if status == "MATCH":
            matches += 1
            by_type[test_type]["match"] += 1
        else:
            mismatches += 1
            by_type[test_type]["mismatch"] += 1

        result_entry = {
            "id": test_id,
            "test_type": test_type,
            "status": status,
            "actual": actual,
        }
        if error_msg:
            result_entry["error"] = error_msg
        results.append(result_entry)

        if args.verbose:
            marker = "  OK" if status == "MATCH" else "MISS"
            print(f"[{marker}] {test_id}: {case.get('description', '')}")
            if status == "MISMATCH":
                print(f"       {error_msg}")

    # Summary
    total = len(results)
    scored = matches + mismatches
    accuracy = (matches / scored * 100) if scored > 0 else 0.0

    print()
    print("=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)
    print(f"Total test cases:  {total}")
    print(f"Matches:           {matches}")
    print(f"Mismatches:        {mismatches}")
    print(f"Accuracy:          {accuracy:.1f}% ({matches}/{scored})")
    print()

    print("Per-type breakdown:")
    for test_type in sorted(by_type.keys()):
        t = by_type[test_type]
        t_scored = t["match"] + t["mismatch"]
        t_acc = (t["match"] / t_scored * 100) if t_scored > 0 else 0.0
        status_mark = "pass" if t["mismatch"] == 0 else "FAIL"
        print(
            f"  {test_type:20s}: {t['match']}/{t_scored} correct "
            f"({t_acc:.0f}%) [{status_mark}]"
        )
    print()

    # List mismatches
    mismatch_entries = [r for r in results if r["status"] == "MISMATCH"]
    if mismatch_entries:
        print(f"MISMATCHES ({len(mismatch_entries)}):")
        for m in mismatch_entries[:20]:
            print(f"  {m['id']}: {m.get('error', '?')}")
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
            "_scoring_model_version": SCORING_MODEL.version,
            "summary": {
                "total": total,
                "matches": matches,
                "mismatches": mismatches,
                "accuracy_pct": round(accuracy, 2),
                "by_type": by_type,
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
