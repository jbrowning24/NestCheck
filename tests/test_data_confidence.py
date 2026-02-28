"""
Unit tests for NES-189 data confidence classifiers and integration.

Tests cover:
  - _classify_places_confidence: boundary and edge cases
  - _classify_transit_confidence: with/without transit data
  - _classify_park_confidence: OSM-enriched vs estimated
  - _classify_cost_confidence: provided vs missing cost
  - Tier2Score / DimensionResult confidence fields
  - Serialization in result_to_dict() and aggregate confidence
"""

from unittest.mock import patch, MagicMock

import pytest

from property_evaluator import (
    Tier2Score,
    _classify_places_confidence,
    _classify_transit_confidence,
    _classify_park_confidence,
    _classify_cost_confidence,
    _PLACES_HIGH_COUNT,
    _PLACES_HIGH_REVIEWS,
    _PLACES_MED_REVIEWS,
    score_cost,
)
from scoring_config import DimensionResult


# =============================================================================
# Tier2Score / DimensionResult confidence fields
# =============================================================================

class TestTier2ScoreConfidenceFields:
    """Verify optional confidence fields on Tier2Score."""

    def test_defaults_to_none(self):
        s = Tier2Score("X", 5, 10, "ok")
        assert s.data_confidence is None
        assert s.data_confidence_note is None

    def test_accepts_confidence(self):
        s = Tier2Score("X", 5, 10, "ok",
                       data_confidence="HIGH",
                       data_confidence_note="5 places found")
        assert s.data_confidence == "HIGH"
        assert s.data_confidence_note == "5 places found"

    def test_backward_compat_positional(self):
        """Old code that uses positional args (name, pts, max, details) still works."""
        s = Tier2Score("X", 5, 10, "details")
        assert s.name == "X"
        assert s.points == 5
        assert s.data_confidence is None


class TestDimensionResultConfidenceFields:
    """Verify optional confidence fields on DimensionResult."""

    def test_defaults_to_none(self):
        d = DimensionResult(score=5, max_score=10, name="X",
                            details="ok", scoring_inputs={})
        assert d.data_confidence is None
        assert d.data_confidence_note is None

    def test_accepts_confidence(self):
        d = DimensionResult(score=5, max_score=10, name="X",
                            details="ok", scoring_inputs={},
                            data_confidence="MEDIUM",
                            data_confidence_note="partial data")
        assert d.data_confidence == "MEDIUM"


# =============================================================================
# _classify_places_confidence
# =============================================================================

class TestClassifyPlacesConfidence:
    """Test Google Places confidence classifier (coffee, grocery, fitness)."""

    def test_high_many_places_many_reviews(self):
        level, note = _classify_places_confidence(5, 200)
        assert level == "HIGH"
        assert "5 places" in note
        assert "200 reviews" in note

    def test_high_boundary(self):
        """Exactly at HIGH thresholds."""
        level, _ = _classify_places_confidence(
            _PLACES_HIGH_COUNT, _PLACES_HIGH_REVIEWS,
        )
        assert level == "HIGH"

    def test_medium_few_places_decent_reviews(self):
        level, _ = _classify_places_confidence(1, 50)
        assert level == "MEDIUM"

    def test_medium_boundary(self):
        """Exactly at MEDIUM review threshold."""
        level, _ = _classify_places_confidence(1, _PLACES_MED_REVIEWS)
        assert level == "MEDIUM"

    def test_low_no_places(self):
        level, note = _classify_places_confidence(0, 0)
        assert level == "LOW"
        assert "No eligible" in note

    def test_low_few_reviews(self):
        level, _ = _classify_places_confidence(2, 10)
        assert level == "LOW"

    def test_low_one_place_few_reviews(self):
        level, note = _classify_places_confidence(1, 5)
        assert level == "LOW"
        assert "1 place" in note  # singular

    def test_high_requires_both_conditions(self):
        """Many places but few reviews should NOT be HIGH."""
        level, _ = _classify_places_confidence(5, 20)
        assert level == "LOW"

    def test_high_requires_enough_places(self):
        """Many reviews but not enough places should be MEDIUM."""
        level, _ = _classify_places_confidence(2, 200)
        assert level == "MEDIUM"


# =============================================================================
# _classify_transit_confidence
# =============================================================================

class TestClassifyTransitConfidence:
    """Test transit/getting-around confidence classifier."""

    def test_no_data(self):
        level, note = _classify_transit_confidence(None, None)
        assert level == "LOW"
        assert "No transit data" in note

    def test_high_walk_time_and_nodes(self):
        transit = MagicMock()
        transit.nearby_node_count = 15
        transit.walk_minutes = 12

        urban = MagicMock()
        urban.primary_transit = MagicMock()
        urban.primary_transit.walk_time_min = 12

        level, note = _classify_transit_confidence(transit, urban)
        assert level == "HIGH"
        assert "15 transit nodes" in note

    def test_medium_walk_time_no_nodes(self):
        transit = MagicMock()
        transit.nearby_node_count = 3
        transit.walk_minutes = 12

        urban = MagicMock()
        urban.primary_transit = MagicMock()
        urban.primary_transit.walk_time_min = 12

        level, _ = _classify_transit_confidence(transit, urban)
        assert level == "MEDIUM"

    def test_low_no_walk_time(self):
        transit = MagicMock()
        transit.nearby_node_count = 0
        transit.walk_minutes = None

        urban = MagicMock()
        urban.primary_transit = None

        level, _ = _classify_transit_confidence(transit, urban)
        assert level == "LOW"


# =============================================================================
# _classify_park_confidence
# =============================================================================

class TestClassifyParkConfidence:
    """Test parks/green-space confidence classifier."""

    def test_no_evaluation(self):
        level, note = _classify_park_confidence(None)
        assert level == "LOW"
        assert "No green spaces" in note

    def test_no_best_park(self):
        eval_ = MagicMock()
        eval_.best_daily_park = None
        level, _ = _classify_park_confidence(eval_)
        assert level == "LOW"

    def test_high_osm_enriched_many_reviews(self):
        park = MagicMock()
        park.user_ratings_total = 250
        park.osm_enriched = True
        park.subscores = []  # no estimates

        eval_ = MagicMock()
        eval_.best_daily_park = park

        level, note = _classify_park_confidence(eval_)
        assert level == "HIGH"
        assert "OSM-verified" in note

    def test_medium_osm_enriched_few_reviews(self):
        park = MagicMock()
        park.user_ratings_total = 40
        park.osm_enriched = True
        park.subscores = []

        eval_ = MagicMock()
        eval_.best_daily_park = park

        level, _ = _classify_park_confidence(eval_)
        assert level == "MEDIUM"

    def test_medium_many_reviews_no_osm(self):
        park = MagicMock()
        park.user_ratings_total = 300
        park.osm_enriched = False
        park.subscores = []

        eval_ = MagicMock()
        eval_.best_daily_park = park

        level, _ = _classify_park_confidence(eval_)
        assert level == "MEDIUM"

    def test_low_few_reviews_no_osm(self):
        park = MagicMock()
        park.user_ratings_total = 5
        park.osm_enriched = False
        park.subscores = []

        eval_ = MagicMock()
        eval_.best_daily_park = park

        level, note = _classify_park_confidence(eval_)
        assert level == "LOW"
        assert "5 reviews" in note

    def test_medium_when_estimates_present(self):
        """OSM-enriched + many reviews BUT some estimated subscores → MEDIUM, not HIGH."""
        subscore = MagicMock()
        subscore.is_estimate = True

        park = MagicMock()
        park.user_ratings_total = 250
        park.osm_enriched = True
        park.subscores = [subscore]

        eval_ = MagicMock()
        eval_.best_daily_park = park

        level, _ = _classify_park_confidence(eval_)
        assert level == "MEDIUM"


# =============================================================================
# _classify_cost_confidence
# =============================================================================

class TestClassifyCostConfidence:
    """Test cost confidence classifier."""

    def test_cost_provided(self):
        level, note = _classify_cost_confidence(2500)
        assert level == "HIGH"
        assert "provided" in note

    def test_cost_zero_is_still_provided(self):
        level, _ = _classify_cost_confidence(0)
        assert level == "HIGH"

    def test_cost_missing(self):
        level, note = _classify_cost_confidence(None)
        assert level == "LOW"
        assert "not specified" in note


# =============================================================================
# score_cost integration (NES-189 confidence wired through)
# =============================================================================

class TestScoreCostConfidence:
    """Verify score_cost returns confidence fields."""

    def test_cost_provided_has_high_confidence(self):
        score = score_cost(2000)
        assert score.data_confidence == "HIGH"
        assert score.data_confidence_note is not None

    def test_cost_none_has_low_confidence(self):
        score = score_cost(None)
        assert score.data_confidence == "LOW"
        assert "not specified" in score.data_confidence_note


# =============================================================================
# result_to_dict serialization (NES-189)
# =============================================================================

class TestResultToDictConfidence:
    """Verify confidence fields survive serialization."""

    def test_tier2_scores_include_confidence(self):
        """Mock a minimal EvaluationResult and check serialized output."""
        from unittest.mock import MagicMock, PropertyMock
        from app import result_to_dict

        # Build a minimal mock EvaluationResult
        result = MagicMock()
        result.listing.address = "123 Test St"
        result.lat = 41.0
        result.lng = -73.0
        result.walk_scores = None
        result.child_schooling_snapshot = None
        result.urban_access = None
        result.transit_access = None
        result.green_escape_evaluation = None
        result.transit_score = None
        result.passed_tier1 = True
        result.neighborhood_places = None
        result.ejscreen_profile = None
        result.persona = None

        s1 = Tier2Score("Test Dim", 7, 10, "test detail",
                        data_confidence="HIGH",
                        data_confidence_note="good data")
        s2 = Tier2Score("Other Dim", 3, 10, "other detail",
                        data_confidence="LOW",
                        data_confidence_note="sparse data")
        result.tier2_scores = [s1, s2]
        result.tier2_total = 10
        result.tier2_max = 20
        result.tier2_normalized = 50
        result.tier3_bonuses = []
        result.tier3_total = 0
        result.tier3_bonus_reasons = []
        result.final_score = 50
        result.percentile_top = 50
        result.percentile_label = "Top 50%"
        result.tier1_checks = []

        output = result_to_dict(result)

        # Check tier2_scores carry confidence
        assert len(output["tier2_scores"]) == 2
        assert output["tier2_scores"][0]["data_confidence"] == "HIGH"
        assert output["tier2_scores"][1]["data_confidence"] == "LOW"

        # Check dimension_summaries carry confidence
        assert len(output["dimension_summaries"]) == 2
        assert output["dimension_summaries"][0]["data_confidence"] == "HIGH"
        assert output["dimension_summaries"][1]["data_confidence"] == "LOW"

        # Check aggregate confidence (weakest-link = LOW)
        assert output["data_confidence_summary"]["level"] == "LOW"
        assert "Other Dim" in output["data_confidence_summary"]["limited_dimensions"]

    def test_old_snapshot_without_confidence(self):
        """Old snapshots missing confidence fields render without errors."""
        from app import result_to_dict

        result = MagicMock()
        result.listing.address = "456 Old St"
        result.lat = 41.0
        result.lng = -73.0
        result.walk_scores = None
        result.child_schooling_snapshot = None
        result.urban_access = None
        result.transit_access = None
        result.green_escape_evaluation = None
        result.transit_score = None
        result.passed_tier1 = False
        result.neighborhood_places = None
        result.ejscreen_profile = None
        result.persona = None
        result.tier2_scores = []
        result.tier2_total = 0
        result.tier2_max = 0
        result.tier2_normalized = 0
        result.tier3_bonuses = []
        result.tier3_total = 0
        result.tier3_bonus_reasons = []
        result.final_score = 0
        result.percentile_top = 100
        result.percentile_label = "Top 100%"
        result.tier1_checks = []

        output = result_to_dict(result)

        # No tier2 scores → no confidence summary
        assert "data_confidence_summary" not in output
        assert output["dimension_summaries"] == []

    def test_all_high_confidence_summary(self):
        """When all dimensions are HIGH, aggregate level is HIGH."""
        from app import result_to_dict

        result = MagicMock()
        result.listing.address = "789 New St"
        result.lat = 41.0
        result.lng = -73.0
        result.walk_scores = None
        result.child_schooling_snapshot = None
        result.urban_access = None
        result.transit_access = None
        result.green_escape_evaluation = None
        result.transit_score = None
        result.passed_tier1 = True
        result.neighborhood_places = None
        result.ejscreen_profile = None
        result.persona = None

        result.tier2_scores = [
            Tier2Score("A", 8, 10, "a", data_confidence="HIGH", data_confidence_note="x"),
            Tier2Score("B", 7, 10, "b", data_confidence="HIGH", data_confidence_note="y"),
        ]
        result.tier2_total = 15
        result.tier2_max = 20
        result.tier2_normalized = 75
        result.tier3_bonuses = []
        result.tier3_total = 0
        result.tier3_bonus_reasons = []
        result.final_score = 75
        result.percentile_top = 25
        result.percentile_label = "Top 25%"
        result.tier1_checks = []

        output = result_to_dict(result)
        assert output["data_confidence_summary"]["level"] == "HIGH"
        assert output["data_confidence_summary"]["limited_dimensions"] == []
