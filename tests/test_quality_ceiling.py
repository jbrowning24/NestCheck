"""Tests for the coffee/social quality-adjusted score ceiling.

Verifies that _compute_quality_ceiling() correctly modulates the
maximum achievable score based on category diversity and review depth.
"""

import pytest
from scoring_config import QualityCeilingConfig
from property_evaluator import _compute_quality_ceiling


def _make_place(sub_type: str, reviews: int = 50) -> dict:
    """Create a minimal place dict for ceiling tests."""
    type_map = {
        "bakery": ["bakery", "food"],
        "cafe": ["cafe", "food"],
        "coffee_shop": ["food"],  # no bakery/cafe → falls through to coffee_shop
    }
    return {
        "types": type_map.get(sub_type, ["food"]),
        "user_ratings_total": reviews,
    }


class TestComputeQualityCeiling:
    """Unit tests for _compute_quality_ceiling."""

    CONFIG = QualityCeilingConfig()  # default thresholds

    def test_empty_places_returns_base_ceiling(self):
        assert _compute_quality_ceiling([], self.CONFIG) == 5

    def test_single_category_low_reviews_returns_base(self):
        """1 category, median reviews < 50 → base only (5)."""
        places = [_make_place("cafe", 20), _make_place("cafe", 30)]
        assert _compute_quality_ceiling(places, self.CONFIG) == 5

    def test_single_category_medium_reviews(self):
        """1 category, median reviews 50-99 → base + depth(1.0) = 6."""
        places = [_make_place("cafe", 60), _make_place("cafe", 70)]
        assert _compute_quality_ceiling(places, self.CONFIG) == 6

    def test_single_category_high_reviews(self):
        """1 category, median reviews 200+ → base + depth(2.0) = 7."""
        places = [_make_place("cafe", 250), _make_place("cafe", 300)]
        assert _compute_quality_ceiling(places, self.CONFIG) == 7

    def test_two_categories_low_reviews(self):
        """2 categories, low reviews → base + diversity(1.0) = 6."""
        places = [_make_place("cafe", 20), _make_place("bakery", 30)]
        assert _compute_quality_ceiling(places, self.CONFIG) == 6

    def test_two_categories_medium_reviews(self):
        """2 categories, median 100+ → base + diversity(1.0) + depth(1.5) = 7."""
        places = [_make_place("cafe", 120), _make_place("bakery", 110)]
        assert _compute_quality_ceiling(places, self.CONFIG) == 7

    def test_three_categories_high_reviews(self):
        """3 categories, median 200+ → base + diversity(2.0) + depth(2.0) = 9."""
        places = [
            _make_place("cafe", 250),
            _make_place("bakery", 300),
            _make_place("coffee_shop", 200),
        ]
        assert _compute_quality_ceiling(places, self.CONFIG) == 9

    def test_four_plus_categories_high_reviews_caps_at_10(self):
        """4+ categories, high reviews → base(5) + div(3) + depth(2) = 10."""
        # _classify_coffee_sub_type only returns 3 distinct types (bakery/cafe/coffee_shop),
        # so 4+ distinct types isn't reachable with the current classifier.
        # This test uses a custom config to verify the cap-at-10 behavior.
        config = QualityCeilingConfig(
            base_ceiling=5.0,
            diversity_thresholds=(
                (3, 3.0),  # 3 categories → +3.0
                (2, 2.0),
            ),
            depth_thresholds=(
                (200, 3.0),  # boosted to exceed 10
                (100, 2.0),
            ),
        )
        places = [
            _make_place("cafe", 300),
            _make_place("bakery", 250),
            _make_place("coffee_shop", 280),
        ]
        # base(5) + div(3) + depth(3) = 11 → capped to 10
        assert _compute_quality_ceiling(places, config) == 10

    def test_mixed_reviews_uses_median(self):
        """Median review count, not mean, determines depth bonus."""
        # 3 places: reviews = [10, 60, 1000] → median = 60 → depth bonus 1.0
        places = [
            _make_place("cafe", 10),
            _make_place("cafe", 60),
            _make_place("cafe", 1000),
        ]
        # 1 category → diversity 0.0; median 60 → depth 1.0; total = 6
        assert _compute_quality_ceiling(places, self.CONFIG) == 6

    def test_custom_base_ceiling(self):
        """Custom base_ceiling is respected."""
        config = QualityCeilingConfig(base_ceiling=3.0)
        places = [_make_place("cafe", 20)]
        assert _compute_quality_ceiling(places, config) == 3


class TestQualityCeilingIntegration:
    """Verify the ceiling composes with confidence cap correctly."""

    def test_ceiling_below_confidence_cap_wins(self):
        """Quality ceiling of 6 beats HIGH confidence cap of 10."""
        from property_evaluator import _apply_confidence_cap

        proximity_score = 10
        quality_ceiling = 6
        ceiled = min(proximity_score, quality_ceiling)
        final = _apply_confidence_cap(ceiled, "HIGH")
        assert final == 6

    def test_confidence_cap_below_ceiling_wins(self):
        """LOW confidence cap of 6 beats quality ceiling of 9."""
        from property_evaluator import _apply_confidence_cap

        proximity_score = 10
        quality_ceiling = 9
        ceiled = min(proximity_score, quality_ceiling)
        final = _apply_confidence_cap(ceiled, "LOW")
        assert final == 6
