"""Tests for the coffee/social quality-adjusted score ceiling.

Verifies that _compute_quality_ceiling() correctly modulates the
maximum achievable score based on sub-type diversity, social bucket
diversity, and review depth — all via a single QualityCeilingConfig.
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
        assert _compute_quality_ceiling([], self.CONFIG) == 4

    def test_single_category_low_reviews_no_buckets(self):
        """1 sub-type, 0 social buckets, median reviews < 50 → base only (4)."""
        places = [_make_place("cafe", 20), _make_place("cafe", 30)]
        assert _compute_quality_ceiling(places, self.CONFIG, social_bucket_count=0) == 4

    def test_single_category_medium_reviews(self):
        """1 sub-type, 0 social buckets, median reviews 50-99 → base + depth(0.5) = 4.5 → 4."""
        places = [_make_place("cafe", 60), _make_place("cafe", 70)]
        assert _compute_quality_ceiling(places, self.CONFIG, social_bucket_count=0) == 4

    def test_single_category_high_reviews(self):
        """1 sub-type, 0 social buckets, median reviews 200+ → base + depth(1.5) = 5.5 → 6."""
        places = [_make_place("cafe", 250), _make_place("cafe", 300)]
        assert _compute_quality_ceiling(places, self.CONFIG, social_bucket_count=0) == 6

    def test_two_subtypes_two_buckets_low_reviews(self):
        """2 sub-types, 2 social buckets, low reviews → base(4) + div(1) + bucket(1) = 6."""
        places = [_make_place("cafe", 20), _make_place("bakery", 30)]
        assert _compute_quality_ceiling(places, self.CONFIG, social_bucket_count=2) == 6

    def test_two_subtypes_two_buckets_medium_reviews(self):
        """2 sub-types, 2 social buckets, median 100+ → base(4) + div(1) + bucket(1) + depth(1) = 7."""
        places = [_make_place("cafe", 120), _make_place("bakery", 110)]
        assert _compute_quality_ceiling(places, self.CONFIG, social_bucket_count=2) == 7

    def test_three_subtypes_four_buckets_high_reviews(self):
        """3 sub-types, 4 social buckets, median 200+ → base(4) + div(2) + bucket(3) + depth(1.5) = 10.5 → 10."""
        places = [
            _make_place("cafe", 250),
            _make_place("bakery", 300),
            _make_place("coffee_shop", 200),
        ]
        assert _compute_quality_ceiling(places, self.CONFIG, social_bucket_count=4) == 10

    def test_caps_at_10(self):
        """Custom config that exceeds 10 is capped."""
        config = QualityCeilingConfig(
            base_ceiling=6.0,
            diversity_thresholds=(
                (3, 3.0),
                (2, 2.0),
            ),
            social_bucket_thresholds=(
                (3, 2.0),
            ),
            depth_thresholds=(
                (200, 3.0),
                (100, 2.0),
            ),
        )
        places = [
            _make_place("cafe", 300),
            _make_place("bakery", 250),
            _make_place("coffee_shop", 280),
        ]
        # base(6) + div(3) + bucket(2) + depth(3) = 14 → capped to 10
        assert _compute_quality_ceiling(places, config, social_bucket_count=3) == 10

    def test_mixed_reviews_uses_median(self):
        """Median review count, not mean, determines depth bonus."""
        # 3 places: reviews = [10, 60, 1000] → median = 60 → depth bonus 0.5
        places = [
            _make_place("cafe", 10),
            _make_place("cafe", 60),
            _make_place("cafe", 1000),
        ]
        # 1 sub-type → diversity 0.0; 0 buckets → 0.0; median 60 → depth 0.5; total = 4.5 → 4
        assert _compute_quality_ceiling(places, self.CONFIG, social_bucket_count=0) == 4

    def test_custom_base_ceiling(self):
        """Custom base_ceiling is respected."""
        config = QualityCeilingConfig(base_ceiling=3.0)
        places = [_make_place("cafe", 20)]
        assert _compute_quality_ceiling(places, config) == 3

    def test_social_buckets_only_bonus(self):
        """Social buckets provide bonus even with single sub-type."""
        places = [_make_place("cafe", 20), _make_place("cafe", 30)]
        # 1 sub-type → div 0; 3 buckets → +2.0; low reviews → depth 0; total = 6
        assert _compute_quality_ceiling(places, self.CONFIG, social_bucket_count=3) == 6

    def test_zero_social_buckets_defaults_gracefully(self):
        """social_bucket_count=0 (default) gives no social bucket bonus."""
        places = [_make_place("cafe", 60)]
        result_default = _compute_quality_ceiling(places, self.CONFIG)
        result_explicit = _compute_quality_ceiling(places, self.CONFIG, social_bucket_count=0)
        assert result_default == result_explicit


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
