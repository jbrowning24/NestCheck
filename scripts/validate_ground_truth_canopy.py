#!/usr/bin/env python3
"""Validate canopy nature-feel scoring against ground truth."""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_config import CANOPY_NATURE_FEEL_KNOTS, apply_piecewise

DEFAULT_GROUND_TRUTH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "ground_truth", "canopy.json",
)
TOLERANCE = 0.01


def validate(ground_truth_path):
    with open(ground_truth_path) as f:
        data = json.load(f)

    matches = 0
    mismatches = 0

    for case in data["cases"]:
        actual = apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, case["canopy_pct"])
        expected = case["expected_score"]
        if abs(actual - expected) <= TOLERANCE:
            matches += 1
        else:
            mismatches += 1
            print(
                f"MISMATCH [{case['type']}] canopy={case['canopy_pct']}%: "
                f"expected={expected}, actual={round(actual, 4)}"
            )

    print(f"\nMatches: {matches}")
    print(f"Mismatches: {mismatches}")
    return 0 if mismatches == 0 else 1


def main():
    parser = argparse.ArgumentParser(
        description="Validate canopy nature-feel scoring against ground truth"
    )
    parser.add_argument(
        "--input", type=str, default=DEFAULT_GROUND_TRUTH_PATH,
        help="Path to ground truth JSON file",
    )
    args = parser.parse_args()
    sys.exit(validate(args.input))


if __name__ == "__main__":
    main()
