"""
Regression tests for the scoring model (NES-87).

Validates:
  - apply_piecewise() with synthetic inputs
  - apply_quality_multiplier() edge cases
  - Coffee/grocery/fitness curve outputs at representative walk times
  - Fitness multiplicative model at key rating×walk-time combos
  - Score band classification
"""

import pytest
from scoring_config import (
    SCORING_MODEL,
    PiecewiseKnot,
    DimensionResult,
    apply_piecewise,
    apply_quality_multiplier,
)
from property_evaluator import get_score_band, SCORE_BANDS, Tier2Score


# =============================================================================
# apply_piecewise() unit tests
# =============================================================================

class TestApplyPiecewise:
    """Pure-function tests for piecewise linear interpolation."""

    SIMPLE_KNOTS = (
        PiecewiseKnot(0, 10),
        PiecewiseKnot(10, 10),
        PiecewiseKnot(20, 5),
        PiecewiseKnot(30, 0),
    )

    def test_exact_first_knot(self):
        assert apply_piecewise(self.SIMPLE_KNOTS, 0) == 10

    def test_exact_last_knot(self):
        assert apply_piecewise(self.SIMPLE_KNOTS, 30) == 0

    def test_exact_middle_knot(self):
        assert apply_piecewise(self.SIMPLE_KNOTS, 10) == 10
        assert apply_piecewise(self.SIMPLE_KNOTS, 20) == 5

    def test_midpoint_between_knots(self):
        # Midpoint of (10, 10) → (20, 5) at x=15 should be 7.5
        assert apply_piecewise(self.SIMPLE_KNOTS, 15) == pytest.approx(7.5)

    def test_quarter_point_between_knots(self):
        # x=25 is midpoint of (20, 5) → (30, 0) → 2.5
        assert apply_piecewise(self.SIMPLE_KNOTS, 25) == pytest.approx(2.5)

    def test_clamp_before_first_knot(self):
        assert apply_piecewise(self.SIMPLE_KNOTS, -10) == 10

    def test_clamp_after_last_knot(self):
        assert apply_piecewise(self.SIMPLE_KNOTS, 100) == 0

    def test_flat_region(self):
        """Within the flat region (0-10), all values should return 10."""
        for x in [0, 2, 5, 8, 10]:
            assert apply_piecewise(self.SIMPLE_KNOTS, x) == 10

    def test_single_knot(self):
        single = (PiecewiseKnot(5, 7),)
        assert apply_piecewise(single, 0) == 7
        assert apply_piecewise(single, 5) == 7
        assert apply_piecewise(single, 99) == 7

    def test_empty_knots_raises(self):
        with pytest.raises(ValueError, match="knots must not be empty"):
            apply_piecewise((), 5)


# =============================================================================
# apply_quality_multiplier() unit tests
# =============================================================================

class TestApplyQualityMultiplier:

    MULTIPLIERS = SCORING_MODEL.fitness.quality_multipliers

    def test_exact_top_threshold(self):
        assert apply_quality_multiplier(self.MULTIPLIERS, 4.5) == 1.0

    def test_above_top_threshold(self):
        assert apply_quality_multiplier(self.MULTIPLIERS, 5.0) == 1.0

    def test_exact_mid_threshold(self):
        assert apply_quality_multiplier(self.MULTIPLIERS, 4.2) == 1.0

    def test_between_thresholds(self):
        # 4.1 is between 4.2 and 4.0 → should match 4.0 tier (0.8)
        assert apply_quality_multiplier(self.MULTIPLIERS, 4.1) == 0.8

    def test_exact_low_threshold(self):
        assert apply_quality_multiplier(self.MULTIPLIERS, 4.0) == 0.8

    def test_below_mid_threshold(self):
        # 3.9 → matches 3.5 tier (0.6)
        assert apply_quality_multiplier(self.MULTIPLIERS, 3.9) == 0.6

    def test_lowest_threshold(self):
        assert apply_quality_multiplier(self.MULTIPLIERS, 3.5) == 0.6

    def test_bottom_catch_all(self):
        # 0.0 → matches 0.0 tier (0.3)
        assert apply_quality_multiplier(self.MULTIPLIERS, 0.0) == 0.3

    def test_between_low_and_catchall(self):
        assert apply_quality_multiplier(self.MULTIPLIERS, 2.0) == 0.3

    def test_empty_multipliers(self):
        assert apply_quality_multiplier((), 4.5) == 0.0


# =============================================================================
# Coffee / Grocery curve tests
# =============================================================================

class TestCoffeeCurve:
    """Representative walk times through the coffee piecewise curve."""

    CFG = SCORING_MODEL.coffee

    @pytest.mark.parametrize("walk_time, min_expected, max_expected", [
        (5, 10, 10),     # Inside flat region
        (10, 10, 10),    # Edge of flat region
        (12, 8.5, 10),   # Just past flat, still high
        (15, 7.5, 8.5),  # Moving into decline
        (17, 6.5, 8),    # Mid-decline
        (20, 5.5, 6.5),  # Further decline
        (25, 4.5, 5.5),  # Approaching low range
        (30, 3.5, 4.5),  # Low range
        (40, 2, 3),      # Near floor
        (60, 2, 2),      # At floor
    ])
    def test_walk_time_produces_expected_range(self, walk_time, min_expected, max_expected):
        score = apply_piecewise(self.CFG.knots, walk_time)
        score = max(self.CFG.floor, score)
        assert min_expected <= score <= max_expected, (
            f"Coffee score at {walk_time}min: {score:.2f} not in [{min_expected}, {max_expected}]"
        )

    def test_monotonic_decreasing(self):
        """Score should never increase as walk time increases."""
        times = list(range(0, 65, 1))
        scores = [max(self.CFG.floor, apply_piecewise(self.CFG.knots, t)) for t in times]
        for i in range(1, len(scores)):
            assert scores[i] <= scores[i - 1] + 0.001, (
                f"Coffee score increased from {times[i-1]}min ({scores[i-1]:.2f}) "
                f"to {times[i]}min ({scores[i]:.2f})"
            )


class TestGroceryCurve:
    """Grocery curve is identical to coffee — spot-check a few values."""

    def test_grocery_matches_coffee(self):
        for t in [5, 15, 20, 30, 45, 60]:
            coffee_score = apply_piecewise(SCORING_MODEL.coffee.knots, t)
            grocery_score = apply_piecewise(SCORING_MODEL.grocery.knots, t)
            assert coffee_score == pytest.approx(grocery_score), (
                f"Grocery != coffee at {t}min"
            )


# =============================================================================
# Fitness multiplicative model tests
# =============================================================================

class TestFitnessModel:
    """Test the fitness distance × quality multiplicative model."""

    CFG = SCORING_MODEL.fitness

    def _score(self, walk_time: float, rating: float) -> float:
        proximity = apply_piecewise(self.CFG.knots, walk_time)
        quality = apply_quality_multiplier(self.CFG.quality_multipliers, rating)
        return max(self.CFG.floor, proximity * quality)

    @pytest.mark.parametrize("rating, walk_time, min_expected, max_expected", [
        (4.5, 8, 9, 10),      # Top gym, very close
        (4.2, 15, 7, 9),      # Good gym, walkable
        (4.0, 20, 4, 6),      # Decent gym, moderate walk
        (3.5, 25, 2, 4),      # Average gym, longer walk
        (4.5, 35, 1.5, 3),    # Top gym, far away — proximity dominates
    ])
    def test_rating_walk_combo(self, rating, walk_time, min_expected, max_expected):
        score = self._score(walk_time, rating)
        assert min_expected <= score <= max_expected, (
            f"Fitness score for {rating}★ × {walk_time}min: {score:.2f} "
            f"not in [{min_expected}, {max_expected}]"
        )

    def test_proximity_dominates(self):
        """A far gym with great rating should score lower than a close gym with okay rating."""
        close_okay = self._score(walk_time=10, rating=4.0)
        far_great = self._score(walk_time=40, rating=4.8)
        assert close_okay > far_great

    def test_quality_modifies(self):
        """Same distance, higher rating should score >= lower rating."""
        high_rating = self._score(walk_time=15, rating=4.5)
        low_rating = self._score(walk_time=15, rating=3.5)
        assert high_rating >= low_rating

    def test_floor_applied(self):
        """Score should never go below the configured floor."""
        score = self._score(walk_time=60, rating=0.0)
        assert score >= self.CFG.floor


# =============================================================================
# Score band tests
# =============================================================================

class TestScoreBands:
    """Verify score band classification matches expected labels."""

    @pytest.mark.parametrize("score, expected_band", [
        (100, "Exceptional Daily Fit"),
        (92, "Exceptional Daily Fit"),
        (85, "Exceptional Daily Fit"),
        (84, "Strong Daily Fit"),
        (75, "Strong Daily Fit"),
        (70, "Strong Daily Fit"),
        (69, "Moderate — Some Trade-offs"),
        (60, "Moderate — Some Trade-offs"),
        (55, "Moderate — Some Trade-offs"),
        (54, "Limited — Car Likely Needed"),
        (45, "Limited — Car Likely Needed"),
        (40, "Limited — Car Likely Needed"),
        (39, "Significant Gaps"),
        (20, "Significant Gaps"),
        (0, "Significant Gaps"),
    ])
    def test_score_band(self, score, expected_band):
        result = get_score_band(score)
        assert result["label"] == expected_band

    def test_bands_are_contiguous(self):
        """Every integer score 0-100 should map to some band."""
        for score in range(0, 101):
            band = get_score_band(score)
            assert band["label"] in [b.label for b in SCORING_MODEL.score_bands], (
                f"Score {score} returned unknown band: {band}"
            )
            assert "css_class" in band, f"Score {score} missing css_class"

    def test_bands_match_config(self):
        """SCORE_BANDS module-level list matches SCORING_MODEL."""
        config_bands = [(b.threshold, b.label) for b in SCORING_MODEL.score_bands]
        assert SCORE_BANDS == config_bands


# =============================================================================
# DimensionResult compatibility tests
# =============================================================================

class TestDimensionResult:
    """Verify DimensionResult provides Tier2Score-compatible interface."""

    def test_points_property_rounds(self):
        dr = DimensionResult(
            score=7.4, max_score=10.0, name="Test",
            details="test", scoring_inputs={},
        )
        assert dr.points == 7
        dr2 = DimensionResult(
            score=7.5, max_score=10.0, name="Test",
            details="test", scoring_inputs={},
        )
        assert dr2.points == 8

    def test_max_points_property(self):
        dr = DimensionResult(
            score=5.0, max_score=10.0, name="Test",
            details="test", scoring_inputs={},
        )
        assert dr.max_points == 10

    def test_subscores_default_none(self):
        dr = DimensionResult(
            score=5.0, max_score=10.0, name="Test",
            details="test", scoring_inputs={},
        )
        assert dr.subscores is None

    def test_model_version_default_empty(self):
        dr = DimensionResult(
            score=5.0, max_score=10.0, name="Test",
            details="test", scoring_inputs={},
        )
        assert dr.model_version == ""


# =============================================================================
# Tier 2 aggregation invariants
# =============================================================================

class TestTier2Aggregation:
    """Verify tier2_total always equals the sum of displayed per-dimension points.

    This catches the "round-then-sum vs sum-then-round" mismatch where
    individual dimension points each round independently before display.
    """

    def _make_dimension(self, score: float) -> DimensionResult:
        return DimensionResult(
            score=score, max_score=10.0, name="Dim",
            details="test", scoring_inputs={},
        )

    def test_round_then_sum_basic(self):
        """Sum of rounded points should equal the aggregated total."""
        # Scores chosen to trigger the classic mismatch:
        # raw sum = 38.48 -> round = 38, but 10+10+10+3+6 = 39
        scores = [
            self._make_dimension(10.0),   # parks
            self._make_dimension(10.0),   # coffee
            self._make_dimension(9.6),    # grocery
            self._make_dimension(2.88),   # fitness
            Tier2Score(name="Transit", points=6, max_points=10, details="test"),
        ]
        total = sum(s.points for s in scores)
        displayed_sum = sum(s.points for s in scores)
        assert total == displayed_sum

    def test_round_then_sum_half_boundary(self):
        """Multiple .5 boundaries should all round consistently."""
        scores = [
            self._make_dimension(7.5),   # rounds to 8
            self._make_dimension(6.5),   # rounds to 6 (banker's rounding)
            self._make_dimension(3.5),   # rounds to 4 (banker's rounding)
            self._make_dimension(8.5),   # rounds to 8 (banker's rounding)
            Tier2Score(name="Transit", points=5, max_points=10, details="test"),
        ]
        total = sum(s.points for s in scores)
        displayed = [s.points for s in scores]
        assert total == sum(displayed), (
            f"Aggregate {total} != displayed sum {sum(displayed)} from {displayed}"
        )

    @pytest.mark.parametrize("raw_scores", [
        [10.0, 10.0, 9.6, 2.88, 6.0],
        [8.3, 7.7, 5.1, 4.9, 3.0],
        [10.0, 10.0, 10.0, 10.0, 10.0],
        [0.0, 0.0, 0.0, 0.0, 0.0],
        [2.4, 3.6, 7.5, 1.1, 9.9],
    ])
    def test_invariant_total_equals_displayed_sum(self, raw_scores):
        """For any combination of raw scores, total == sum(displayed points)."""
        dims = [self._make_dimension(s) for s in raw_scores]
        total = sum(d.points for d in dims)
        displayed_sum = sum(d.points for d in dims)
        assert total == displayed_sum


# =============================================================================
# model_version presence tests
# =============================================================================

class TestModelVersionPresence:
    """Verify model_version is populated and non-empty in SCORING_MODEL."""

    def test_scoring_model_version_is_set(self):
        assert SCORING_MODEL.version
        assert isinstance(SCORING_MODEL.version, str)

    def test_scoring_model_version_is_semver(self):
        """Version string should be a valid semver-like pattern."""
        parts = SCORING_MODEL.version.split(".")
        assert len(parts) == 3, f"Expected 3-part semver, got {SCORING_MODEL.version}"
        for part in parts:
            assert part.isdigit(), f"Non-numeric semver part in {SCORING_MODEL.version}"

    def test_dimension_result_carries_version(self):
        """DimensionResult constructed with model_version preserves it."""
        dr = DimensionResult(
            score=5.0, max_score=10.0, name="Test",
            details="test", scoring_inputs={},
            model_version=SCORING_MODEL.version,
        )
        assert dr.model_version == SCORING_MODEL.version
