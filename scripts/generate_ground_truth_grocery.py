#!/usr/bin/env python3
"""
Generate ground-truth test cases for grocery/provisioning scoring (Tier 2).

Same pattern as coffee but simpler — grocery scoring doesn't have quality
ceiling complexity.  Tests score_provisioning_access() via apply_piecewise()
with synthetic inputs.  No API calls, no spatial.db.

Test types:
  - knot_boundary:   exact knot x-values → exact y-values
  - interpolation:   midpoints between knots → linearly interpolated scores
  - monotonicity:    ordered walk-time pairs → score(t1) >= score(t2)
  - clamping:        values outside knot range → clamped to first/last y
  - floor:           walk times beyond curve → score >= floor

Usage:
    python scripts/generate_ground_truth_grocery.py
    python scripts/generate_ground_truth_grocery.py --seed 42
    python scripts/generate_ground_truth_grocery.py --output data/ground_truth/grocery.json
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


def _generate_knot_boundary_tests(knots):
    """Test cases at each knot x-value.  Expected = knot y-value."""
    cases = []
    for i, knot in enumerate(knots):
        cases.append({
            "id": f"gt-grocery-knot-{i + 1:02d}",
            "test_type": "knot_boundary",
            "description": f"Exact knot at walk_time={knot.x} → score={knot.y}",
            "inputs": {
                "walk_time_min": knot.x,
            },
            "expected": {
                "piecewise_score": knot.y,
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
            "id": f"gt-grocery-interp-{idx:02d}",
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
            "id": f"gt-grocery-mono-{idx:02d}",
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
        "id": "gt-grocery-clamp-01",
        "test_type": "clamping",
        "description": f"walk_time={first.x - 10} (before first knot) → clamped to {first.y}",
        "inputs": {"walk_time_min": first.x - 10},
        "expected": {
            "piecewise_score": first.y,
            "final_score_exact": first.y,
        },
    })

    cases.append({
        "id": "gt-grocery-clamp-02",
        "test_type": "clamping",
        "description": f"walk_time={last.x + 60} (after last knot) → clamped to {last.y}",
        "inputs": {"walk_time_min": last.x + 60},
        "expected": {
            "piecewise_score": last.y,
            "final_score_exact": last.y,
        },
    })

    return cases


def _generate_floor_tests(knots, floor):
    """Test that floor is applied for extreme walk times."""
    cases = []
    for i, wt in enumerate([60, 90, 120], start=1):
        raw_score = apply_piecewise(knots, wt)
        final = max(floor, raw_score)
        cases.append({
            "id": f"gt-grocery-floor-{i:02d}",
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
            },
        })
    return cases


def main():
    parser = argparse.ArgumentParser(
        description="Generate ground-truth test cases for grocery/provisioning scoring"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--output", type=str, default="data/ground_truth/grocery.json",
        help="Output JSON path (default: data/ground_truth/grocery.json)",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)

    cfg = SCORING_MODEL.grocery
    knots = cfg.knots
    floor = cfg.floor

    print(f"Scoring model version: {SCORING_MODEL.version}")
    print(f"Grocery knots: {[(k.x, k.y) for k in knots]}")
    print(f"Grocery floor: {floor}")
    print(f"Quality ceiling: none (grocery has no ceiling config)")
    print()

    # Generate all test cases
    all_cases = []

    knot_cases = _generate_knot_boundary_tests(knots)
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

    floor_cases = _generate_floor_tests(knots, floor)
    all_cases.extend(floor_cases)
    print(f"Generated {len(floor_cases)} floor tests")

    print(f"\nTotal: {len(all_cases)} test cases")

    # Build output
    output = {
        "_schema_version": "0.2.0",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_generator": "generate_ground_truth_grocery.py",
        "_scoring_model_version": SCORING_MODEL.version,
        "_test_count": len(all_cases),
        "_seed": args.seed,
        "_curve_knots": [[k.x, k.y] for k in knots],
        "_floor": floor,
        "_quality_ceiling": False,
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
