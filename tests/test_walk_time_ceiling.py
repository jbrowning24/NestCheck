"""Tests for graduated walk-time ceiling on park Daily Value scores (NES-391)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from green_space import _apply_walk_time_ceiling, compute_park_score


class TestWalkTimeCeiling:
    """Graduated ceiling: walk > 15 -> cap 8, > 20 -> cap 6, > 25 -> cap 5, > 30 -> cap 3."""

    def test_no_ceiling_at_15_or_below(self):
        assert _apply_walk_time_ceiling(10.0, 10) == 10.0
        assert _apply_walk_time_ceiling(10.0, 15) == 10.0
        assert _apply_walk_time_ceiling(9.0, 5) == 9.0

    def test_ceiling_8_between_16_and_20(self):
        assert _apply_walk_time_ceiling(10.0, 16) == 8.0
        assert _apply_walk_time_ceiling(9.5, 18) == 8.0
        assert _apply_walk_time_ceiling(7.0, 20) == 7.0  # below ceiling, no effect

    def test_ceiling_6_between_21_and_25(self):
        assert _apply_walk_time_ceiling(10.0, 21) == 6.0
        assert _apply_walk_time_ceiling(7.4, 25) == 6.0  # Kensico-like case
        assert _apply_walk_time_ceiling(5.0, 22) == 5.0  # below ceiling, no effect

    def test_ceiling_5_between_26_and_30(self):
        assert _apply_walk_time_ceiling(7.4, 26) == 5.0  # THE Kensico case
        assert _apply_walk_time_ceiling(8.0, 30) == 5.0
        assert _apply_walk_time_ceiling(4.0, 28) == 4.0  # below ceiling, no effect

    def test_ceiling_3_above_30(self):
        assert _apply_walk_time_ceiling(7.0, 31) == 3.0
        assert _apply_walk_time_ceiling(5.0, 45) == 3.0
        assert _apply_walk_time_ceiling(2.0, 35) == 2.0  # below ceiling, no effect

    def test_exact_boundaries(self):
        assert _apply_walk_time_ceiling(10.0, 15) == 10.0  # <= 15: no ceiling
        assert _apply_walk_time_ceiling(10.0, 20) == 8.0   # <= 20: cap 8
        assert _apply_walk_time_ceiling(10.0, 25) == 6.0   # <= 25: cap 6
        assert _apply_walk_time_ceiling(10.0, 30) == 5.0   # <= 30: cap 5


class TestComputeParkScoreWithCeiling:
    def test_kensico_scenario_capped_at_5(self):
        score = compute_park_score(
            walk_time_min=26, rating=4.7, reviews=4254,
            name="Kensico Dam Plaza", park_acres=20.0,
            osm_path_count=5, osm_nature_tags=["water"],
        )
        assert score <= 5.0, f"26 min walk park should be capped at 5, got {score}"

    def test_excellent_park_at_10_min_uncapped(self):
        score = compute_park_score(
            walk_time_min=10, rating=4.7, reviews=4254,
            name="Kensico Dam Plaza", park_acres=20.0,
            osm_path_count=5, osm_nature_tags=["water"],
        )
        assert score > 5.0, f"10 min walk park should not be capped, got {score}"

    def test_moderate_park_at_22_min_capped_at_6(self):
        score = compute_park_score(
            walk_time_min=22, rating=4.5, reviews=300,
            name="Forest Park", park_acres=15.0, osm_path_count=6,
        )
        assert score <= 6.0, f"22 min walk park should be capped at 6, got {score}"


class TestNarrativeAlignment:
    def test_far_high_quality_park_below_7(self):
        score = compute_park_score(
            walk_time_min=26, rating=4.7, reviews=4254,
            name="Kensico Dam Plaza", park_acres=20.0,
            osm_path_count=5, osm_nature_tags=["water"],
        )
        assert score < 7, f"Score {score} >= 7 would contradict 'weekend destination' narrative"
        assert score >= 4, f"Score {score} < 4 would hit 'limited nearby' -- too harsh"

    def test_close_high_quality_park_above_7(self):
        score = compute_park_score(
            walk_time_min=10, rating=4.7, reviews=4254,
            name="Kensico Dam Plaza", park_acres=20.0,
            osm_path_count=5, osm_nature_tags=["water"],
        )
        assert score >= 7, f"Score {score} < 7 for close excellent park"
