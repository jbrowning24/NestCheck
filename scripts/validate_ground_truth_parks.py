#!/usr/bin/env python3
"""
Validate parks & green space scoring ground-truth against actual functions.

Loads ground-truth JSON from the generator, runs compute_park_score() and
individual subscore functions for each test case, and compares actual vs
expected results.

No API calls, no spatial.db — pure scoring function tests.

Usage:
    python scripts/validate_ground_truth_parks.py
    python scripts/validate_ground_truth_parks.py --input data/ground_truth/parks.json
    python scripts/validate_ground_truth_parks.py --verbose
    python scripts/validate_ground_truth_parks.py --output data/validation_results_parks.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from green_space import (
    _score_walk_time,
    _score_size_loop,
    _score_quality,
    _score_nature_feel,
    _evaluate_criteria,
    compute_park_score,
)

TOLERANCE = 0.001


def _validate_walk_time(case):
    """Validate _score_walk_time subscore."""
    wt = case["inputs"]["walk_time_min"]
    expected = case["expected"]["walk_time_score"]
    actual, _ = _score_walk_time(wt)

    if abs(actual - expected) < TOLERANCE:
        return "MATCH", actual, None
    return "MISMATCH", actual, f"expected={expected}, actual={actual}"


def _validate_size_enriched(case):
    """Validate _score_size_loop with enriched data."""
    inp = case["inputs"]
    expected_score = case["expected"]["size_loop_score"]
    expected_est = case["expected"]["is_estimate"]

    osm_enriched = (
        inp.get("osm_area_sqm") is not None
        or inp.get("osm_path_count", 0) > 0
        or inp.get("osm_has_trail", False)
    )
    osm_data = {
        "enriched": osm_enriched,
        "area_sqm": inp.get("osm_area_sqm"),
        "path_count": inp.get("osm_path_count", 0),
        "has_trail": inp.get("osm_has_trail", False),
        "nature_tags": [],
    }

    actual, _, is_estimate = _score_size_loop(
        osm_data,
        inp.get("rating"),
        inp.get("reviews", 0),
        inp.get("name", ""),
        parkserve_acres=inp.get("park_acres"),
    )

    errors = []
    if abs(actual - expected_score) >= TOLERANCE:
        errors.append(f"score: expected={expected_score}, actual={actual}")
    if is_estimate != expected_est:
        errors.append(f"is_estimate: expected={expected_est}, actual={is_estimate}")

    if not errors:
        return "MATCH", {"score": actual, "is_estimate": is_estimate}, None
    return (
        "MISMATCH",
        {"score": actual, "is_estimate": is_estimate},
        "; ".join(errors),
    )


def _validate_size_fallback(case):
    """Validate _score_size_loop fallback path."""
    inp = case["inputs"]
    expected_score = case["expected"]["size_loop_score"]
    expected_est = case["expected"]["is_estimate"]

    osm_data = {
        "enriched": False, "area_sqm": None, "path_count": 0,
        "has_trail": False, "nature_tags": [],
    }

    actual, _, is_estimate = _score_size_loop(
        osm_data,
        inp.get("rating"),
        inp.get("reviews", 0),
        inp.get("name", ""),
    )

    errors = []
    if abs(actual - expected_score) >= TOLERANCE:
        errors.append(f"score: expected={expected_score}, actual={actual}")
    if is_estimate != expected_est:
        errors.append(f"is_estimate: expected={expected_est}, actual={is_estimate}")

    if not errors:
        return "MATCH", {"score": actual, "is_estimate": is_estimate}, None
    return (
        "MISMATCH",
        {"score": actual, "is_estimate": is_estimate},
        "; ".join(errors),
    )


def _validate_quality(case):
    """Validate _score_quality subscore."""
    inp = case["inputs"]
    expected = case["expected"]["quality_score"]
    actual, _ = _score_quality(inp.get("rating"), inp.get("reviews", 0))

    if abs(actual - expected) < TOLERANCE:
        return "MATCH", actual, None
    return "MISMATCH", actual, f"expected={expected}, actual={actual}"


def _validate_nature_feel(case):
    """Validate _score_nature_feel subscore."""
    inp = case["inputs"]
    expected = case["expected"]["nature_feel_score"]

    osm_data = {
        "enriched": len(inp.get("osm_nature_tags", [])) > 0,
        "area_sqm": None,
        "path_count": 0,
        "has_trail": False,
        "nature_tags": inp.get("osm_nature_tags", []),
    }
    actual, _ = _score_nature_feel(
        osm_data, inp.get("name", ""), inp.get("types", []),
        parkserve_type=inp.get("parkserve_type"),
    )

    if abs(actual - expected) < TOLERANCE:
        return "MATCH", actual, None
    return "MISMATCH", actual, f"expected={expected}, actual={actual}"


def _validate_composite(case):
    """Validate compute_park_score end-to-end with intermediate subscores."""
    inp = case["inputs"]
    expected = case["expected"]

    # Build kwargs for compute_park_score
    kwargs = {
        "walk_time_min": inp["walk_time_min"],
        "rating": inp.get("rating"),
        "reviews": inp.get("reviews", 0),
        "name": inp.get("name", ""),
        "types": inp.get("types"),
        "park_acres": inp.get("park_acres"),
        "parkserve_type": inp.get("parkserve_type"),
        "osm_area_sqm": inp.get("osm_area_sqm"),
        "osm_path_count": inp.get("osm_path_count", 0),
        "osm_has_trail": inp.get("osm_has_trail", False),
        "osm_nature_tags": inp.get("osm_nature_tags"),
    }
    # Remove None values so defaults apply
    kwargs = {k: v for k, v in kwargs.items() if v is not None}

    actual_total = compute_park_score(**kwargs)

    # Also compute and check individual subscores
    errors = []
    actual_data = {"final_score": actual_total}

    if "walk_time_score" in expected:
        wt_actual, _ = _score_walk_time(inp["walk_time_min"])
        actual_data["walk_time_score"] = wt_actual
        if abs(wt_actual - expected["walk_time_score"]) >= TOLERANCE:
            errors.append(
                f"walk_time: expected={expected['walk_time_score']}, actual={wt_actual}"
            )

    if "size_loop_score" in expected:
        osm_enriched = (
            inp.get("osm_area_sqm") is not None
            or inp.get("osm_path_count", 0) > 0
            or inp.get("osm_has_trail", False)
            or len(inp.get("osm_nature_tags", [])) > 0
        )
        osm_data = {
            "enriched": osm_enriched,
            "area_sqm": inp.get("osm_area_sqm"),
            "path_count": inp.get("osm_path_count", 0),
            "has_trail": inp.get("osm_has_trail", False),
            "nature_tags": inp.get("osm_nature_tags", []),
        }
        sz_actual, _, _ = _score_size_loop(
            osm_data, inp.get("rating"), inp.get("reviews", 0),
            inp.get("name", ""), parkserve_acres=inp.get("park_acres"),
        )
        actual_data["size_loop_score"] = sz_actual
        if abs(sz_actual - expected["size_loop_score"]) >= TOLERANCE:
            errors.append(
                f"size_loop: expected={expected['size_loop_score']}, actual={sz_actual}"
            )

    if "quality_score" in expected:
        q_actual, _ = _score_quality(inp.get("rating"), inp.get("reviews", 0))
        actual_data["quality_score"] = q_actual
        if abs(q_actual - expected["quality_score"]) >= TOLERANCE:
            errors.append(
                f"quality: expected={expected['quality_score']}, actual={q_actual}"
            )

    if "nature_feel_score" in expected:
        nf_osm = {
            "enriched": len(inp.get("osm_nature_tags", [])) > 0,
            "area_sqm": None, "path_count": 0, "has_trail": False,
            "nature_tags": inp.get("osm_nature_tags", []),
        }
        nf_actual, _ = _score_nature_feel(
            nf_osm, inp.get("name", ""), inp.get("types", []),
            parkserve_type=inp.get("parkserve_type"),
        )
        actual_data["nature_feel_score"] = nf_actual
        if abs(nf_actual - expected["nature_feel_score"]) >= TOLERANCE:
            errors.append(
                f"nature_feel: expected={expected['nature_feel_score']}, actual={nf_actual}"
            )

    if abs(actual_total - expected["final_score"]) >= TOLERANCE:
        errors.append(
            f"final_score: expected={expected['final_score']}, actual={actual_total}"
        )

    if not errors:
        return "MATCH", actual_data, None
    return "MISMATCH", actual_data, "; ".join(errors)


def _validate_composite_cap(case):
    """Validate total is capped at 10.0."""
    inp = case["inputs"]
    expected_max = case["expected"]["final_score_max"]
    expected_score = case["expected"]["final_score"]

    kwargs = {
        "walk_time_min": inp["walk_time_min"],
        "rating": inp.get("rating"),
        "reviews": inp.get("reviews", 0),
        "name": inp.get("name", ""),
        "types": inp.get("types"),
        "park_acres": inp.get("park_acres"),
        "parkserve_type": inp.get("parkserve_type"),
        "osm_area_sqm": inp.get("osm_area_sqm"),
        "osm_path_count": inp.get("osm_path_count", 0),
        "osm_has_trail": inp.get("osm_has_trail", False),
        "osm_nature_tags": inp.get("osm_nature_tags"),
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}

    actual = compute_park_score(**kwargs)

    errors = []
    if actual > expected_max + TOLERANCE:
        errors.append(f"score {actual} exceeds cap {expected_max}")
    if abs(actual - expected_score) >= TOLERANCE:
        errors.append(f"expected={expected_score}, actual={actual}")

    if not errors:
        return "MATCH", actual, None
    return "MISMATCH", actual, "; ".join(errors)


def _validate_monotonicity(case):
    """Validate score(t1) >= score(t2) when t1 < t2."""
    inp = case["inputs"]
    t_a = inp["walk_time_a"]
    t_b = inp["walk_time_b"]
    base_kwargs = inp["base_kwargs"]

    score_a = compute_park_score(walk_time_min=t_a, **base_kwargs)
    score_b = compute_park_score(walk_time_min=t_b, **base_kwargs)

    if score_a >= score_b - TOLERANCE:
        return "MATCH", {"score_a": score_a, "score_b": score_b}, None
    return (
        "MISMATCH",
        {"score_a": score_a, "score_b": score_b},
        f"score({t_a})={score_a} < score({t_b})={score_b} — monotonicity violation",
    )


def _validate_criteria(case):
    """Validate PASS/BORDERLINE/FAIL classification."""
    inp = case["inputs"]
    expected_status = case["expected"]["criteria_status"]

    actual_status, _ = _evaluate_criteria(
        inp["total"],
        inp["walk_time_score"],
        inp["size_loop_score"],
        inp["walk_time_min"],
    )

    if actual_status == expected_status:
        return "MATCH", actual_status, None
    return (
        "MISMATCH",
        actual_status,
        f"expected={expected_status}, actual={actual_status}",
    )


def _validate_walk_time_ceiling(case):
    """Validate graduated walk-time ceiling on Daily Value."""
    inp = case["inputs"]
    expected = case["expected"]

    kwargs = {
        "walk_time_min": inp["walk_time_min"],
        "rating": inp.get("rating"),
        "reviews": inp.get("reviews", 0),
        "name": inp.get("name", ""),
        "types": inp.get("types"),
        "park_acres": inp.get("park_acres"),
        "osm_path_count": inp.get("osm_path_count", 0),
        "osm_has_trail": inp.get("osm_has_trail", False),
        "osm_nature_tags": inp.get("osm_nature_tags"),
    }
    kwargs = {k: v for k, v in kwargs.items() if v is not None}

    actual_score = compute_park_score(**kwargs)

    errors = []

    # Check final score
    if abs(actual_score - expected["final_score"]) >= TOLERANCE:
        errors.append(
            f"final_score: expected={expected['final_score']}, actual={actual_score}"
        )

    # Check capped flag: if ceiling is not None, score should be <= ceiling
    expected_capped = expected["capped"]
    ceiling = expected["ceiling"]

    if ceiling is not None:
        actual_capped = actual_score <= ceiling + TOLERANCE
    else:
        actual_capped = False

    # Verify capped flag matches
    if expected_capped != actual_capped:
        errors.append(
            f"capped: expected={expected_capped}, actual={actual_capped}"
        )

    if not errors:
        return "MATCH", {"final_score": actual_score, "capped": actual_capped}, None
    return (
        "MISMATCH",
        {"final_score": actual_score, "capped": actual_capped},
        "; ".join(errors),
    )


# Dispatch table
_VALIDATORS = {
    "walk_time": lambda case, ctx: _validate_walk_time(case),
    "size_enriched": lambda case, ctx: _validate_size_enriched(case),
    "size_fallback": lambda case, ctx: _validate_size_fallback(case),
    "quality": lambda case, ctx: _validate_quality(case),
    "nature_feel": lambda case, ctx: _validate_nature_feel(case),
    "composite": lambda case, ctx: _validate_composite(case),
    "composite_cap": lambda case, ctx: _validate_composite_cap(case),
    "walk_time_ceiling": lambda case, ctx: _validate_walk_time_ceiling(case),
    "monotonicity": lambda case, ctx: _validate_monotonicity(case),
    "criteria": lambda case, ctx: _validate_criteria(case),
}


def main():
    parser = argparse.ArgumentParser(
        description="Validate parks ground-truth against scoring functions"
    )
    parser.add_argument(
        "--input", type=str, default="data/ground_truth/parks.json",
        help="Ground-truth JSON file (default: data/ground_truth/parks.json)",
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
    try:
        from scoring_config import SCORING_MODEL
        if gt_data.get("_scoring_model_version") != SCORING_MODEL.version:
            print(
                f"\nWARNING: Ground truth was generated with model version "
                f"{gt_data.get('_scoring_model_version')}, but current model is "
                f"{SCORING_MODEL.version}. Consider regenerating."
            )
    except ImportError:
        pass
    print()

    # Run validation
    results = []
    matches = 0
    mismatches = 0
    by_type = {}

    for case in test_cases:
        test_id = case["id"]
        test_type = case["test_type"]

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

        status, actual, error_msg = validator(case, {})

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
            "_scoring_model_version": gt_data.get("_scoring_model_version"),
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
