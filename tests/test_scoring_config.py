"""Tests for scoring_config.py — drive-time piecewise knots (NES-280)."""

import pytest

from scoring_config import (
    PiecewiseKnot,
    apply_piecewise,
    _COFFEE_DRIVE_KNOTS,
    _GROCERY_DRIVE_KNOTS,
    _FITNESS_DRIVE_KNOTS,
)


# Coffee and grocery share identical breakpoints (ceiling 6, matching fitness — NES-322).
_WALK_ONLY_DRIVE_KNOTS = [
    ("_COFFEE_DRIVE_KNOTS", _COFFEE_DRIVE_KNOTS),
    ("_GROCERY_DRIVE_KNOTS", _GROCERY_DRIVE_KNOTS),
]


@pytest.mark.parametrize("name,knots", _WALK_ONLY_DRIVE_KNOTS)
class TestCoffeeGroceryDriveKnots:
    """Verify apply_piecewise for coffee/grocery drive knots (ceiling 6, NES-322)."""

    def test_at_0_min(self, name, knots):
        assert apply_piecewise(knots, 0) == 6

    def test_at_5_min(self, name, knots):
        assert apply_piecewise(knots, 5) == 6

    def test_at_10_min(self, name, knots):
        assert apply_piecewise(knots, 10) == 5

    def test_at_15_min(self, name, knots):
        assert apply_piecewise(knots, 15) == 3

    def test_at_20_min(self, name, knots):
        assert apply_piecewise(knots, 20) == 1

    def test_at_25_min(self, name, knots):
        assert apply_piecewise(knots, 25) == 0

    def test_at_30_min(self, name, knots):
        assert apply_piecewise(knots, 30) == 0

    def test_midpoint_interpolation(self, name, knots):
        # 12.5 min is halfway between (10, 5) and (15, 3) → expect 4.0
        result = apply_piecewise(knots, 12.5)
        assert result == pytest.approx(4.0)

    def test_clamp_below_range(self, name, knots):
        # Negative time clamps to first knot's y value
        assert apply_piecewise(knots, -5) == 6

    def test_clamp_above_range(self, name, knots):
        # Beyond 30 min clamps to last knot's y value
        assert apply_piecewise(knots, 45) == 0


class TestFitnessDriveKnots:
    """Verify apply_piecewise for fitness drive knots (ceiling 6, NES-315)."""

    def test_at_0_min(self):
        assert apply_piecewise(_FITNESS_DRIVE_KNOTS, 0) == 6

    def test_at_5_min(self):
        assert apply_piecewise(_FITNESS_DRIVE_KNOTS, 5) == 6

    def test_at_10_min(self):
        assert apply_piecewise(_FITNESS_DRIVE_KNOTS, 10) == 5

    def test_at_15_min(self):
        assert apply_piecewise(_FITNESS_DRIVE_KNOTS, 15) == 3

    def test_at_20_min(self):
        assert apply_piecewise(_FITNESS_DRIVE_KNOTS, 20) == 1

    def test_at_25_min(self):
        assert apply_piecewise(_FITNESS_DRIVE_KNOTS, 25) == 0

    def test_at_30_min(self):
        assert apply_piecewise(_FITNESS_DRIVE_KNOTS, 30) == 0

    def test_midpoint_interpolation(self):
        # 7.5 min is halfway between (5, 6) and (10, 5) → expect 5.5
        result = apply_piecewise(_FITNESS_DRIVE_KNOTS, 7.5)
        assert result == pytest.approx(5.5)

    def test_clamp_below_range(self):
        # Negative time clamps to first knot's y value
        assert apply_piecewise(_FITNESS_DRIVE_KNOTS, -5) == 6

    def test_clamp_above_range(self):
        # Beyond 30 min clamps to last knot's y value
        assert apply_piecewise(_FITNESS_DRIVE_KNOTS, 45) == 0
