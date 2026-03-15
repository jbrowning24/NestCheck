"""Tests for scoring_config.py — drive-time piecewise knots (NES-280)."""

import pytest

from scoring_config import (
    PiecewiseKnot,
    apply_piecewise,
    _COFFEE_DRIVE_KNOTS,
    _GROCERY_DRIVE_KNOTS,
    _FITNESS_DRIVE_KNOTS,
)


# All three drive-time knot tuples share identical breakpoints.
_ALL_DRIVE_KNOTS = [
    ("_COFFEE_DRIVE_KNOTS", _COFFEE_DRIVE_KNOTS),
    ("_GROCERY_DRIVE_KNOTS", _GROCERY_DRIVE_KNOTS),
    ("_FITNESS_DRIVE_KNOTS", _FITNESS_DRIVE_KNOTS),
]


@pytest.mark.parametrize("name,knots", _ALL_DRIVE_KNOTS)
class TestDriveTimeKnots:
    """Verify apply_piecewise returns expected values at each breakpoint."""

    def test_at_0_min(self, name, knots):
        assert apply_piecewise(knots, 0) == 10

    def test_at_5_min(self, name, knots):
        assert apply_piecewise(knots, 5) == 10

    def test_at_10_min(self, name, knots):
        assert apply_piecewise(knots, 10) == 8

    def test_at_15_min(self, name, knots):
        assert apply_piecewise(knots, 15) == 6

    def test_at_20_min(self, name, knots):
        assert apply_piecewise(knots, 20) == 3

    def test_at_25_min(self, name, knots):
        assert apply_piecewise(knots, 25) == 1

    def test_at_30_min(self, name, knots):
        assert apply_piecewise(knots, 30) == 0

    def test_midpoint_interpolation(self, name, knots):
        # 12.5 min is halfway between (10, 8) and (15, 6) → expect 7.0
        result = apply_piecewise(knots, 12.5)
        assert result == pytest.approx(7.0)

    def test_clamp_below_range(self, name, knots):
        # Negative time clamps to first knot's y value
        assert apply_piecewise(knots, -5) == 10

    def test_clamp_above_range(self, name, knots):
        # Beyond 30 min clamps to last knot's y value
        assert apply_piecewise(knots, 45) == 0
