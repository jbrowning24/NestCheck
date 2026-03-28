#!/usr/bin/env python3
"""Generate ground truth test cases for canopy nature-feel scoring."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_config import CANOPY_NATURE_FEEL_KNOTS, apply_piecewise

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "ground_truth", "canopy.json",
)


def generate():
    cases = []

    # Knot boundary tests
    for knot in CANOPY_NATURE_FEEL_KNOTS:
        cases.append({
            "type": "knot_boundary",
            "canopy_pct": knot.x,
            "expected_score": knot.y,
        })

    # Interpolation midpoints
    for i in range(len(CANOPY_NATURE_FEEL_KNOTS) - 1):
        k1 = CANOPY_NATURE_FEEL_KNOTS[i]
        k2 = CANOPY_NATURE_FEEL_KNOTS[i + 1]
        mid_x = (k1.x + k2.x) / 2
        mid_y = (k1.y + k2.y) / 2
        cases.append({
            "type": "interpolation",
            "canopy_pct": mid_x,
            "expected_score": round(mid_y, 4),
        })

    # Clamping tests
    cases.append({"type": "clamping_low", "canopy_pct": 0, "expected_score": 0.0})
    cases.append({"type": "clamping_high", "canopy_pct": 100, "expected_score": 2.0})

    # Monotonicity: every 5%
    for pct in range(0, 101, 5):
        score = apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, pct)
        cases.append({
            "type": "monotonicity",
            "canopy_pct": pct,
            "expected_score": round(score, 4),
        })

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump({"dimension": "canopy", "cases": cases}, f, indent=2)
    print(f"Generated {len(cases)} test cases -> {OUTPUT_PATH}")


if __name__ == "__main__":
    generate()
