#!/usr/bin/env python3
"""
Generate ground-truth test cases for coffee/third-place scoring (Tier 2).

Unlike Tier 1 generators (UST, HPMS) which create synthetic coordinates
against spatial.db, this generator tests the scoring *function* in
isolation with synthetic inputs.  No API calls, no spatial.db.

Test types:
  - knot_boundary:   exact knot x-values → exact y-values
  - interpolation:   midpoints between knots → linearly interpolated scores
  - monotonicity:    ordered walk-time pairs → score(t1) >= score(t2)
  - clamping:        values outside knot range → clamped to first/last y
  - floor:           walk times beyond curve → score >= floor
  - ceiling_max:     maximal diversity → ceiling = 10
  - quality_ceiling: synthetic venue sets → expected ceiling values
  - ceiling_caps:    ceiling < proximity → final score = ceiling
  - pipeline_composition: full pipeline (piecewise → ceiling → cap → floor → round)

Usage:
    python scripts/generate_ground_truth_coffee.py
    python scripts/generate_ground_truth_coffee.py --seed 42
    python scripts/generate_ground_truth_coffee.py --output data/ground_truth/coffee.json
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone

# Project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_config import SCORING_MODEL, apply_piecewise

# Import private functions for ceiling test generation
try:
    from property_evaluator import _compute_quality_ceiling
    EVALUATOR_AVAILABLE = True
except ImportError:
    EVALUATOR_AVAILABLE = False
    print("WARNING: Could not import from property_evaluator (Flask side-effects).")
    print("Ceiling tests will use config-derived expectations only.")


def _make_place(sub_type, reviews=50):
    """Create a minimal place dict for ceiling tests.

    Mirrors the pattern from tests/test_quality_ceiling.py.
    """
    type_map = {
        "bakery": ["bakery", "food"],
        "cafe": ["cafe", "food"],
        "coffee_shop": ["food"],  # no bakery/cafe → falls through to coffee_shop
    }
    return {
        "types": type_map.get(sub_type, ["food"]),
        "user_ratings_total": reviews,
    }


def _generate_knot_boundary_tests(knots, floor):
    """Test cases at each knot x-value.  Expected = knot y-value."""
    cases = []
    for i, knot in enumerate(knots):
        cases.append({
            "id": f"gt-coffee-knot-{i + 1:02d}",
            "test_type": "knot_boundary",
            "description": f"Exact knot at walk_time={knot.x} → score={knot.y}",
            "inputs": {
                "walk_time_min": knot.x,
            },
            "expected": {
                "piecewise_score": knot.y,
                "quality_ceiling": None,
                "final_score_min": None,
                "final_score_max": None,
                "final_score_exact": knot.y,
            },
        })
    return cases


def _generate_interpolation_tests(knots):
    """Test cases at midpoints between adjacent knots."""
    cases = []
    idx = 0
    for i in range(1, len(knots)):
        k0, k1 = knots[i - 1], knots[i]
        # Skip flat segments (same y) — interpolation is trivially the same value
        if k0.y == k1.y:
            continue
        mid_x = (k0.x + k1.x) / 2.0
        mid_y = (k0.y + k1.y) / 2.0
        idx += 1
        cases.append({
            "id": f"gt-coffee-interp-{idx:02d}",
            "test_type": "interpolation",
            "description": (
                f"Midpoint between ({k0.x},{k0.y}) and ({k1.x},{k1.y}): "
                f"walk_time={mid_x} → score={mid_y}"
            ),
            "inputs": {
                "walk_time_min": mid_x,
            },
            "expected": {
                "piecewise_score": mid_y,
                "quality_ceiling": None,
                "final_score_min": None,
                "final_score_max": None,
                "final_score_exact": mid_y,
            },
        })
    return cases


def _generate_monotonicity_tests(knots, rng):
    """Generate ordered pairs to verify score(t1) >= score(t2) when t1 < t2."""
    cases = []

    # Systematic: test each adjacent pair of knots
    knot_xs = [k.x for k in knots]
    all_points = sorted(set(knot_xs))

    # Add midpoints
    for i in range(1, len(knots)):
        mid = (knots[i - 1].x + knots[i].x) / 2.0
        all_points.append(mid)

    # Add some random samples within the curve range
    x_min, x_max = knots[0].x, knots[-1].x
    for _ in range(8):
        all_points.append(rng.uniform(x_min, x_max))

    all_points = sorted(set(all_points))

    # Generate pairs (every consecutive pair in sorted order)
    idx = 0
    for i in range(len(all_points) - 1):
        t1, t2 = all_points[i], all_points[i + 1]
        s1 = apply_piecewise(knots, t1)
        s2 = apply_piecewise(knots, t2)
        idx += 1
        cases.append({
            "id": f"gt-coffee-mono-{idx:02d}",
            "test_type": "monotonicity",
            "description": (
                f"walk_time={t1:.2f} (score={s1:.2f}) <= "
                f"walk_time={t2:.2f} (score={s2:.2f})"
            ),
            "inputs": {
                "walk_time_a": round(t1, 4),
                "walk_time_b": round(t2, 4),
            },
            "expected": {
                "score_a_gte_score_b": True,
                "score_a": round(s1, 4),
                "score_b": round(s2, 4),
            },
        })
    return cases


def _generate_clamping_tests(knots):
    """Test values outside the knot range are clamped."""
    cases = []
    first, last = knots[0], knots[-1]

    cases.append({
        "id": "gt-coffee-clamp-01",
        "test_type": "clamping",
        "description": f"walk_time={first.x - 10} (before first knot) → clamped to {first.y}",
        "inputs": {"walk_time_min": first.x - 10},
        "expected": {
            "piecewise_score": first.y,
            "quality_ceiling": None,
            "final_score_min": None,
            "final_score_max": None,
            "final_score_exact": first.y,
        },
    })

    cases.append({
        "id": "gt-coffee-clamp-02",
        "test_type": "clamping",
        "description": f"walk_time={last.x + 60} (after last knot) → clamped to {last.y}",
        "inputs": {"walk_time_min": last.x + 60},
        "expected": {
            "piecewise_score": last.y,
            "quality_ceiling": None,
            "final_score_min": None,
            "final_score_max": None,
            "final_score_exact": last.y,
        },
    })

    return cases


def _generate_floor_tests(floor):
    """Test that floor is applied for extreme walk times."""
    cases = []
    for i, wt in enumerate([60, 90, 120], start=1):
        raw_score = apply_piecewise(SCORING_MODEL.coffee.knots, wt)
        cases.append({
            "id": f"gt-coffee-floor-{i:02d}",
            "test_type": "floor",
            "description": (
                f"walk_time={wt} → raw_score={raw_score}, "
                f"floor={floor} → final >= {floor}"
            ),
            "inputs": {"walk_time_min": wt},
            "expected": {
                "piecewise_score": raw_score,
                "floor": floor,
                "final_score_min": floor,
                "final_score_max": None,
                "final_score_exact": None,
            },
        })
    return cases


def _generate_ceiling_max_test(ceiling_config):
    """Verify that maximal diversity can achieve ceiling = 10."""
    places = [
        _make_place("cafe", 250),
        _make_place("bakery", 300),
        _make_place("coffee_shop", 200),
    ]

    if EVALUATOR_AVAILABLE:
        ceiling = _compute_quality_ceiling(places, ceiling_config, social_bucket_count=4)
    else:
        # Manually compute: base(4) + div(2, 3 types) + social(3, 4 buckets) + depth(1.5, median 250) = 10.5 → 10
        ceiling = 10

    return [{
        "id": "gt-coffee-ceilmax-01",
        "test_type": "ceiling_max",
        "description": (
            "Maximal diversity (3 sub-types, 4 social buckets, 250+ median reviews) "
            f"→ ceiling={ceiling}, walk_time=0 → score=10"
        ),
        "inputs": {
            "walk_time_min": 0,
            "eligible_places": places,
            "social_bucket_count": 4,
        },
        "expected": {
            "piecewise_score": 10.0,
            "quality_ceiling": ceiling,
            "final_score_min": None,
            "final_score_max": None,
            "final_score_exact": 10.0,
        },
    }]


def _generate_quality_ceiling_tests(ceiling_config):
    """Test _compute_quality_ceiling() with controlled diversity/depth combos."""
    cases = []

    # Each scenario: (id_suffix, description, places, social_bucket_count, expected_ceiling)
    scenarios = [
        (
            "empty",
            "No eligible places → base ceiling",
            [],
            0,
            round(ceiling_config.base_ceiling),
        ),
        (
            "1type-0bucket-low",
            "1 sub-type, 0 social buckets, low reviews (20) → base only",
            [_make_place("cafe", 20), _make_place("cafe", 30)],
            0,
            4,  # base(4) + div(0) + bucket(0) + depth(0) = 4
        ),
        (
            "2type-0bucket-low",
            "2 sub-types, 0 social buckets, low reviews → base + diversity(1)",
            [_make_place("cafe", 20), _make_place("bakery", 30)],
            0,
            5,  # base(4) + div(1) + bucket(0) + depth(0) = 5
        ),
        (
            "3type-0bucket-low",
            "3 sub-types, 0 social buckets, low reviews → base + diversity(2)",
            [
                _make_place("cafe", 20),
                _make_place("bakery", 30),
                _make_place("coffee_shop", 25),
            ],
            0,
            6,  # base(4) + div(2) + bucket(0) + depth(0) = 6
        ),
        (
            "1type-2bucket-low",
            "1 sub-type, 2 social buckets, low reviews → base + bucket(1)",
            [_make_place("cafe", 20), _make_place("cafe", 30)],
            2,
            5,  # base(4) + div(0) + bucket(1) + depth(0) = 5
        ),
        (
            "1type-3bucket-low",
            "1 sub-type, 3 social buckets, low reviews → base + bucket(2)",
            [_make_place("cafe", 20), _make_place("cafe", 30)],
            3,
            6,  # base(4) + div(0) + bucket(2) + depth(0) = 6
        ),
        (
            "1type-4bucket-low",
            "1 sub-type, 4+ social buckets, low reviews → base + bucket(3)",
            [_make_place("cafe", 20), _make_place("cafe", 30)],
            4,
            7,  # base(4) + div(0) + bucket(3) + depth(0) = 7
        ),
        (
            "1type-0bucket-med50",
            "1 sub-type, 0 buckets, median reviews ~60 → base + depth(0.5) → 4",
            [_make_place("cafe", 60), _make_place("cafe", 70)],
            0,
            4,  # base(4) + div(0) + bucket(0) + depth(0.5) = 4.5 → round(4.5) = 4
        ),
        (
            "1type-0bucket-med100",
            "1 sub-type, 0 buckets, median reviews ~120 → base + depth(1.0) → 5",
            [_make_place("cafe", 120), _make_place("cafe", 130)],
            0,
            5,  # base(4) + div(0) + bucket(0) + depth(1.0) = 5.0 → 5
        ),
        (
            "1type-0bucket-med200",
            "1 sub-type, 0 buckets, median reviews ~250 → base + depth(1.5) → 6",
            [_make_place("cafe", 250), _make_place("cafe", 300)],
            0,
            6,  # base(4) + div(0) + bucket(0) + depth(1.5) = 5.5 → round(5.5) = 6
        ),
        (
            "2type-2bucket-med100",
            "2 sub-types, 2 social buckets, median 100+ → full mid-range",
            [_make_place("cafe", 120), _make_place("bakery", 110)],
            2,
            7,  # base(4) + div(1) + bucket(1) + depth(1.0) = 7
        ),
        (
            "3type-4bucket-med200",
            "Full diversity: 3 sub-types, 4 buckets, 200+ reviews → 10",
            [
                _make_place("cafe", 250),
                _make_place("bakery", 300),
                _make_place("coffee_shop", 200),
            ],
            4,
            10,  # base(4) + div(2) + bucket(3) + depth(1.5) = 10.5 → cap at 10
        ),
    ]

    # If evaluator is available, compute expected from the actual function
    # to catch any discrepancy between our manual calc and the code
    for i, (id_suffix, desc, places, bucket_count, expected) in enumerate(scenarios, start=1):
        if EVALUATOR_AVAILABLE:
            actual_expected = _compute_quality_ceiling(
                places, ceiling_config, social_bucket_count=bucket_count
            )
            if actual_expected != expected:
                print(
                    f"WARNING: Manual expected ceiling ({expected}) differs from "
                    f"computed ({actual_expected}) for scenario '{id_suffix}'. "
                    f"Using computed value."
                )
                expected = actual_expected

        cases.append({
            "id": f"gt-coffee-ceil-{i:02d}-{id_suffix}",
            "test_type": "quality_ceiling",
            "description": desc,
            "inputs": {
                "eligible_places": places,
                "social_bucket_count": bucket_count,
            },
            "expected": {
                "quality_ceiling": expected,
            },
        })

    return cases


def _generate_ceiling_caps_tests(knots, ceiling_config):
    """Test that ceiling < proximity → final score capped at ceiling."""
    cases = []

    # Scenario 1: walk_time=0 (proximity=10), minimal diversity → ceiling=4
    places_minimal = [_make_place("cafe", 20), _make_place("cafe", 30)]
    if EVALUATOR_AVAILABLE:
        ceil_1 = _compute_quality_ceiling(places_minimal, ceiling_config, social_bucket_count=0)
    else:
        ceil_1 = 4

    cases.append({
        "id": "gt-coffee-ceilcap-01",
        "test_type": "ceiling_caps",
        "description": (
            f"walk_time=0 (proximity=10), minimal diversity → "
            f"ceiling={ceil_1}, final capped at {ceil_1}"
        ),
        "inputs": {
            "walk_time_min": 0,
            "eligible_places": places_minimal,
            "social_bucket_count": 0,
        },
        "expected": {
            "piecewise_score": 10.0,
            "quality_ceiling": ceil_1,
            "final_score_min": None,
            "final_score_max": None,
            "final_score_exact": float(ceil_1),
        },
    })

    # Scenario 2: walk_time=10 (proximity=10), 2 types + 2 buckets → ceiling=6
    places_mid = [_make_place("cafe", 20), _make_place("bakery", 30)]
    if EVALUATOR_AVAILABLE:
        ceil_2 = _compute_quality_ceiling(places_mid, ceiling_config, social_bucket_count=2)
    else:
        ceil_2 = 6

    cases.append({
        "id": "gt-coffee-ceilcap-02",
        "test_type": "ceiling_caps",
        "description": (
            f"walk_time=10 (proximity=10), 2 types + 2 buckets → "
            f"ceiling={ceil_2}, final capped at {ceil_2}"
        ),
        "inputs": {
            "walk_time_min": 10,
            "eligible_places": places_mid,
            "social_bucket_count": 2,
        },
        "expected": {
            "piecewise_score": 10.0,
            "quality_ceiling": ceil_2,
            "final_score_min": None,
            "final_score_max": None,
            "final_score_exact": float(ceil_2),
        },
    })

    # Scenario 3: walk_time=15 (proximity=8), 1 type + 0 buckets → ceiling=4
    if EVALUATOR_AVAILABLE:
        ceil_3 = _compute_quality_ceiling(places_minimal, ceiling_config, social_bucket_count=0)
    else:
        ceil_3 = 4

    cases.append({
        "id": "gt-coffee-ceilcap-03",
        "test_type": "ceiling_caps",
        "description": (
            f"walk_time=15 (proximity=8), minimal diversity → "
            f"ceiling={ceil_3}, final capped at {ceil_3}"
        ),
        "inputs": {
            "walk_time_min": 15,
            "eligible_places": places_minimal,
            "social_bucket_count": 0,
        },
        "expected": {
            "piecewise_score": 8.0,
            "quality_ceiling": ceil_3,
            "final_score_min": None,
            "final_score_max": None,
            "final_score_exact": float(ceil_3),
        },
    })

    return cases


def _generate_pipeline_composition_tests(knots, floor, ceiling_config):
    """Test the full scoring pipeline in the same order as score_third_place_access().

    Pipeline: piecewise(walk_time) → min(score, ceiling) → max(floor, score) → round

    This catches double-ceiling bugs (NES-222): if a second ceiling mechanism
    is accidentally introduced, the final rounded score will differ from the
    expected single-ceiling result.  The ceiling_caps tests verify sub-function
    outputs; these tests verify the *composition* produces the right final int.
    """
    cases = []

    if not EVALUATOR_AVAILABLE:
        return cases

    # Import confidence cap to match the real pipeline
    from property_evaluator import _apply_confidence_cap

    # Scenario matrix: (walk_time, places, buckets, confidence, description)
    scenarios = [
        # 1. High proximity, low diversity, verified confidence
        #    → ceiling should cap once, not twice
        (
            0, [_make_place("cafe", 20)], 0, "verified",
            "proximity=10 capped once by low-diversity ceiling (4)",
        ),
        # 2. High proximity, full diversity, verified confidence
        #    → ceiling=10, no cap, final=10
        (
            5,
            [_make_place("cafe", 250), _make_place("bakery", 300),
             _make_place("coffee_shop", 200)],
            4, "verified",
            "proximity=10, full diversity ceiling=10 → no cap → 10",
        ),
        # 3. Moderate proximity, moderate diversity, estimated confidence
        #    → ceiling and confidence cap interact (ceiling applied once,
        #      then confidence cap, then floor)
        (
            20,
            [_make_place("cafe", 120), _make_place("bakery", 110)],
            2, "estimated",
            "proximity=6, ceiling=7, confidence cap=8 → ceiling doesn't bind, final=6",
        ),
        # 4. Very long walk, minimal diversity, verified confidence
        #    → floor rescues from both low proximity and low ceiling
        (
            90, [_make_place("cafe", 20)], 0, "verified",
            "proximity=2 (clamped), ceiling=4 → ceiling doesn't bind, floor=2 → 2",
        ),
        # 5. Moderate proximity, low diversity → ceiling < proximity, ceiling binds
        #    If double-ceiling existed, this would produce a *lower* score
        (
            10,
            [_make_place("cafe", 20), _make_place("cafe", 30)],
            0, "verified",
            "proximity=10, ceiling=4 → single cap → 4 (double-cap regression would show lower)",
        ),
        # 6. Walk time just past flat region, mid diversity
        #    Tests that ceiling applied at the right stage (before floor/round)
        (
            15,
            [_make_place("cafe", 120), _make_place("bakery", 110)],
            2, "verified",
            "proximity=8, ceiling=7 → ceiling binds → 7",
        ),
    ]

    for i, (walk_time, places, buckets, confidence, desc) in enumerate(scenarios, start=1):
        # Replicate the pipeline from score_third_place_access()
        proximity_score = apply_piecewise(knots, walk_time)
        ceiling = _compute_quality_ceiling(
            places, ceiling_config, social_bucket_count=buckets
        )
        after_ceiling = min(proximity_score, ceiling)
        after_confidence = _apply_confidence_cap(after_ceiling, confidence)
        after_floor = max(floor, after_confidence)
        final_points = int(after_floor + 0.5)

        cases.append({
            "id": f"gt-coffee-pipeline-{i:02d}",
            "test_type": "pipeline_composition",
            "description": desc,
            "inputs": {
                "walk_time_min": walk_time,
                "eligible_places": places,
                "social_bucket_count": buckets,
                "confidence": confidence,
            },
            "expected": {
                "piecewise_score": proximity_score,
                "quality_ceiling": ceiling,
                "after_ceiling": after_ceiling,
                "after_confidence": after_confidence,
                "after_floor": after_floor,
                "final_points": final_points,
            },
        })

    return cases


def main():
    parser = argparse.ArgumentParser(
        description="Generate ground-truth test cases for coffee/third-place scoring"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--output", type=str, default="data/ground_truth/coffee.json",
        help="Output JSON path (default: data/ground_truth/coffee.json)",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)

    cfg = SCORING_MODEL.coffee
    knots = cfg.knots
    floor = cfg.floor
    ceiling_config = cfg.quality_ceiling

    print(f"Scoring model version: {SCORING_MODEL.version}")
    print(f"Coffee knots: {[(k.x, k.y) for k in knots]}")
    print(f"Coffee floor: {floor}")
    print(f"Quality ceiling config: {'yes' if ceiling_config else 'no'}")
    if EVALUATOR_AVAILABLE:
        print("Evaluator: imported successfully (computing ceilings from code)")
    else:
        print("Evaluator: not available (using manual ceiling calculations)")
    print()

    # Generate all test cases
    all_cases = []

    knot_cases = _generate_knot_boundary_tests(knots, floor)
    all_cases.extend(knot_cases)
    print(f"Generated {len(knot_cases)} knot boundary tests")

    interp_cases = _generate_interpolation_tests(knots)
    all_cases.extend(interp_cases)
    print(f"Generated {len(interp_cases)} interpolation tests")

    mono_cases = _generate_monotonicity_tests(knots, rng)
    all_cases.extend(mono_cases)
    print(f"Generated {len(mono_cases)} monotonicity tests")

    clamp_cases = _generate_clamping_tests(knots)
    all_cases.extend(clamp_cases)
    print(f"Generated {len(clamp_cases)} clamping tests")

    floor_cases = _generate_floor_tests(floor)
    all_cases.extend(floor_cases)
    print(f"Generated {len(floor_cases)} floor tests")

    if ceiling_config:
        ceilmax_cases = _generate_ceiling_max_test(ceiling_config)
        all_cases.extend(ceilmax_cases)
        print(f"Generated {len(ceilmax_cases)} ceiling max test")

        ceil_cases = _generate_quality_ceiling_tests(ceiling_config)
        all_cases.extend(ceil_cases)
        print(f"Generated {len(ceil_cases)} quality ceiling tests")

        ceilcap_cases = _generate_ceiling_caps_tests(knots, ceiling_config)
        all_cases.extend(ceilcap_cases)
        print(f"Generated {len(ceilcap_cases)} ceiling-caps-score tests")

        pipeline_cases = _generate_pipeline_composition_tests(knots, floor, ceiling_config)
        all_cases.extend(pipeline_cases)
        print(f"Generated {len(pipeline_cases)} pipeline composition tests")

    print(f"\nTotal: {len(all_cases)} test cases")

    # Build output
    output = {
        "_schema_version": "0.2.0",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_generator": "generate_ground_truth_coffee.py",
        "_scoring_model_version": SCORING_MODEL.version,
        "_test_count": len(all_cases),
        "_seed": args.seed,
        "_curve_knots": [[k.x, k.y] for k in knots],
        "_floor": floor,
        "_quality_ceiling": ceiling_config is not None,
        "test_cases": all_cases,
    }

    # Resolve output path
    out_path = args.output
    if not os.path.isabs(out_path):
        project_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        out_path = os.path.join(project_root, out_path)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nGround truth written to: {out_path}")


if __name__ == "__main__":
    main()
