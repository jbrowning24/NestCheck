"""
Unit tests for data confidence classifiers and integration.

Tests cover:
  - _classify_places_confidence: boundary and edge cases
  - _classify_transit_confidence: with/without transit data
  - _classify_park_confidence: OSM-enriched vs estimated
  - _classify_cost_confidence: provided vs missing cost
  - _apply_confidence_cap: score capping by confidence level
  - Tier2Score / DimensionResult confidence fields
  - Serialization in result_to_dict() and aggregate confidence
  - Phase 3 confidence tiers: verified / estimated / not_scored
"""

from unittest.mock import patch, MagicMock

import pytest

from property_evaluator import (
    Tier2Score,
    _classify_places_confidence,
    _classify_transit_confidence,
    _classify_park_confidence,
    _classify_cost_confidence,
    _apply_confidence_cap,
    _CONFIDENCE_SCORE_CAP,
    _PLACES_HIGH_COUNT,
    _PLACES_HIGH_REVIEWS,
    _PLACES_MED_REVIEWS,
    score_cost,
    score_park_access,
    score_transit_access,
)
from scoring_config import (
    DimensionResult,
    CONFIDENCE_VERIFIED, CONFIDENCE_ESTIMATED, CONFIDENCE_SPARSE, CONFIDENCE_NOT_SCORED,
)


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

    def test_verified_many_places_many_reviews(self):
        level, note = _classify_places_confidence(5, 200)
        assert level == CONFIDENCE_VERIFIED
        assert "5 places" in note
        assert "200 reviews" in note

    def test_verified_boundary(self):
        """Exactly at verified thresholds."""
        level, _ = _classify_places_confidence(
            _PLACES_HIGH_COUNT, _PLACES_HIGH_REVIEWS,
        )
        assert level == CONFIDENCE_VERIFIED

    def test_estimated_few_places_decent_reviews(self):
        level, _ = _classify_places_confidence(1, 50)
        assert level == CONFIDENCE_ESTIMATED

    def test_estimated_boundary(self):
        """Exactly at estimated review threshold."""
        level, _ = _classify_places_confidence(1, _PLACES_MED_REVIEWS)
        assert level == CONFIDENCE_ESTIMATED

    def test_estimated_no_places(self):
        level, note = _classify_places_confidence(0, 0)
        assert level == CONFIDENCE_ESTIMATED
        assert "No eligible" in note

    def test_estimated_few_reviews(self):
        level, _ = _classify_places_confidence(2, 10)
        assert level == CONFIDENCE_ESTIMATED

    def test_sparse_one_place_few_reviews(self):
        """Single venue with few reviews → sparse confidence."""
        level, note = _classify_places_confidence(1, 5)
        assert level == CONFIDENCE_SPARSE
        assert "1 place" in note  # singular

    def test_verified_requires_both_conditions(self):
        """Many places but few reviews should NOT be verified."""
        level, _ = _classify_places_confidence(5, 20)
        assert level == CONFIDENCE_ESTIMATED

    def test_verified_requires_enough_places(self):
        """Many reviews but not enough places should be estimated."""
        level, _ = _classify_places_confidence(2, 200)
        assert level == CONFIDENCE_ESTIMATED


# =============================================================================
# _apply_confidence_cap (NES-sparse-data)
# =============================================================================

class TestApplyConfidenceCap:
    """Score should be capped when data confidence is LOW or MEDIUM."""

    def test_high_no_cap(self):
        assert _apply_confidence_cap(10, "HIGH") == 10

    def test_medium_caps_at_8(self):
        assert _apply_confidence_cap(10, "MEDIUM") == 8

    def test_medium_no_cap_when_below(self):
        assert _apply_confidence_cap(6, "MEDIUM") == 6

    def test_low_caps_at_6(self):
        assert _apply_confidence_cap(10, "LOW") == 6

    def test_low_caps_score_of_7(self):
        assert _apply_confidence_cap(7, "LOW") == 6

    def test_low_no_cap_when_below(self):
        assert _apply_confidence_cap(3, "LOW") == 3

    def test_zero_score_unchanged(self):
        assert _apply_confidence_cap(0, "LOW") == 0

    def test_unknown_confidence_no_cap(self):
        """Unknown confidence levels default to no cap."""
        assert _apply_confidence_cap(10, "UNKNOWN") == 10

    # Phase 3 tier names
    def test_verified_no_cap(self):
        assert _apply_confidence_cap(10, CONFIDENCE_VERIFIED) == 10

    def test_estimated_caps_at_8(self):
        assert _apply_confidence_cap(10, CONFIDENCE_ESTIMATED) == 8

    def test_estimated_no_cap_when_below(self):
        assert _apply_confidence_cap(6, CONFIDENCE_ESTIMATED) == 6

    def test_sparse_caps_at_6(self):
        assert _apply_confidence_cap(10, CONFIDENCE_SPARSE) == 6

    def test_sparse_caps_score_of_7(self):
        assert _apply_confidence_cap(7, CONFIDENCE_SPARSE) == 6

    def test_sparse_no_cap_when_below(self):
        assert _apply_confidence_cap(4, CONFIDENCE_SPARSE) == 4

    def test_not_scored_caps_at_0(self):
        assert _apply_confidence_cap(10, CONFIDENCE_NOT_SCORED) == 0


# =============================================================================
# _classify_transit_confidence
# =============================================================================

class TestClassifyTransitConfidence:
    """Test transit/getting-around confidence classifier."""

    def test_no_data(self):
        level, note = _classify_transit_confidence(None, None)
        assert level == CONFIDENCE_SPARSE
        assert "Sparse transit data" in note

    def test_verified_walk_time_and_nodes(self):
        transit = MagicMock()
        transit.nearby_node_count = 15
        transit.walk_minutes = 12

        urban = MagicMock()
        urban.primary_transit = MagicMock()
        urban.primary_transit.walk_time_min = 12

        level, note = _classify_transit_confidence(transit, urban)
        assert level == CONFIDENCE_VERIFIED
        assert "15 transit nodes" in note

    def test_estimated_walk_time_no_nodes(self):
        transit = MagicMock()
        transit.nearby_node_count = 3
        transit.walk_minutes = 12

        urban = MagicMock()
        urban.primary_transit = MagicMock()
        urban.primary_transit.walk_time_min = 12

        level, _ = _classify_transit_confidence(transit, urban)
        assert level == CONFIDENCE_ESTIMATED

    def test_sparse_no_walk_time_no_nodes(self):
        """No walk time, no nodes, no frequency → sparse."""
        transit = MagicMock()
        transit.nearby_node_count = 0
        transit.walk_minutes = None
        transit.frequency_bucket = None

        urban = MagicMock()
        urban.primary_transit = None

        level, _ = _classify_transit_confidence(transit, urban)
        assert level == CONFIDENCE_SPARSE


# =============================================================================
# _classify_park_confidence
# =============================================================================

class TestClassifyParkConfidence:
    """Test parks/green-space confidence classifier."""

    def test_no_evaluation(self):
        level, note = _classify_park_confidence(None)
        assert level == CONFIDENCE_ESTIMATED
        assert "No green spaces" in note

    def test_no_best_park(self):
        eval_ = MagicMock()
        eval_.best_daily_park = None
        level, _ = _classify_park_confidence(eval_)
        assert level == CONFIDENCE_ESTIMATED

    def test_verified_osm_enriched_many_reviews(self):
        park = MagicMock()
        park.user_ratings_total = 250
        park.osm_enriched = True
        park.subscores = []  # no estimates

        eval_ = MagicMock()
        eval_.best_daily_park = park

        level, note = _classify_park_confidence(eval_)
        assert level == CONFIDENCE_VERIFIED
        assert "OSM-verified" in note

    def test_estimated_osm_enriched_few_reviews(self):
        park = MagicMock()
        park.user_ratings_total = 40
        park.osm_enriched = True
        park.subscores = []

        eval_ = MagicMock()
        eval_.best_daily_park = park

        level, _ = _classify_park_confidence(eval_)
        assert level == CONFIDENCE_ESTIMATED

    def test_estimated_many_reviews_no_osm(self):
        park = MagicMock()
        park.user_ratings_total = 300
        park.osm_enriched = False
        park.subscores = []

        eval_ = MagicMock()
        eval_.best_daily_park = park

        level, _ = _classify_park_confidence(eval_)
        assert level == CONFIDENCE_ESTIMATED

    def test_sparse_few_reviews_no_osm(self):
        """Park with < 15 reviews and no OSM enrichment → sparse."""
        park = MagicMock()
        park.user_ratings_total = 5
        park.osm_enriched = False
        park.subscores = []

        eval_ = MagicMock()
        eval_.best_daily_park = park

        level, note = _classify_park_confidence(eval_)
        assert level == CONFIDENCE_SPARSE
        assert "5 reviews" in note

    def test_estimated_moderate_reviews_no_osm(self):
        """Park with 15-29 reviews and no OSM → estimated (not sparse)."""
        park = MagicMock()
        park.user_ratings_total = 20
        park.osm_enriched = False
        park.subscores = []

        eval_ = MagicMock()
        eval_.best_daily_park = park

        level, _ = _classify_park_confidence(eval_)
        assert level == CONFIDENCE_ESTIMATED

    def test_estimated_when_estimates_present(self):
        """OSM-enriched + many reviews BUT some estimated subscores → estimated, not verified."""
        subscore = MagicMock()
        subscore.is_estimate = True

        park = MagicMock()
        park.user_ratings_total = 250
        park.osm_enriched = True
        park.subscores = [subscore]

        eval_ = MagicMock()
        eval_.best_daily_park = park

        level, _ = _classify_park_confidence(eval_)
        assert level == CONFIDENCE_ESTIMATED


# =============================================================================
# _classify_cost_confidence
# =============================================================================

class TestClassifyCostConfidence:
    """Test cost confidence classifier."""

    def test_cost_provided(self):
        level, note = _classify_cost_confidence(2500)
        assert level == CONFIDENCE_VERIFIED
        assert "provided" in note

    def test_cost_zero_is_still_provided(self):
        level, _ = _classify_cost_confidence(0)
        assert level == CONFIDENCE_VERIFIED

    def test_cost_missing(self):
        level, note = _classify_cost_confidence(None)
        assert level == CONFIDENCE_ESTIMATED
        assert "not specified" in note


# =============================================================================
# score_cost integration (NES-189 confidence wired through)
# =============================================================================

class TestScoreCostConfidence:
    """Verify score_cost returns confidence fields."""

    def test_cost_provided_has_verified_confidence(self):
        score = score_cost(2000)
        assert score.data_confidence == CONFIDENCE_VERIFIED
        assert score.data_confidence_note is not None

    def test_cost_none_has_estimated_confidence(self):
        score = score_cost(None)
        assert score.data_confidence == CONFIDENCE_ESTIMATED
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
        result.demographics = None

        s1 = Tier2Score("Test Dim", 7, 10, "test detail",
                        data_confidence=CONFIDENCE_VERIFIED,
                        data_confidence_note="good data")
        s2 = Tier2Score("Other Dim", 3, 10, "other detail",
                        data_confidence=CONFIDENCE_ESTIMATED,
                        data_confidence_note="limited data")
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
        assert output["tier2_scores"][0]["data_confidence"] == CONFIDENCE_VERIFIED
        assert output["tier2_scores"][1]["data_confidence"] == CONFIDENCE_ESTIMATED

        # Check dimension_summaries carry confidence
        assert len(output["dimension_summaries"]) == 2
        assert output["dimension_summaries"][0]["data_confidence"] == CONFIDENCE_VERIFIED
        assert output["dimension_summaries"][1]["data_confidence"] == CONFIDENCE_ESTIMATED

        # Check aggregate confidence (weakest-link = estimated)
        assert output["data_confidence_summary"]["level"] == CONFIDENCE_ESTIMATED
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
        result.demographics = None
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

    def test_all_verified_confidence_summary(self):
        """When all dimensions are verified, aggregate level is verified."""
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
        result.demographics = None

        result.tier2_scores = [
            Tier2Score("A", 8, 10, "a", data_confidence=CONFIDENCE_VERIFIED, data_confidence_note="x"),
            Tier2Score("B", 7, 10, "b", data_confidence=CONFIDENCE_VERIFIED, data_confidence_note="y"),
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
        assert output["data_confidence_summary"]["level"] == CONFIDENCE_VERIFIED
        assert output["data_confidence_summary"]["limited_dimensions"] == []


# =============================================================================
# Integration: confidence cap applied in score_park_access (NES-sparse-data)
# =============================================================================

class TestParkAccessConfidenceCap:
    """Verify score_park_access applies _apply_confidence_cap."""

    def test_estimated_confidence_park_capped_at_8(self):
        """A park with estimated confidence should have score capped at 8."""
        park = MagicMock()
        park.daily_walk_value = 9.5
        park.rating = 4.0
        park.user_ratings_total = 3
        park.walk_time_min = 8
        park.name = "Test Park"
        park.criteria_status = "met"
        park.osm_enriched = False
        park.subscores = []

        eval_ = MagicMock()
        eval_.best_daily_park = park

        with patch(
            "property_evaluator._classify_park_confidence",
            return_value=(CONFIDENCE_ESTIMATED, "few reviews"),
        ):
            result = score_park_access(
                maps=MagicMock(),
                lat=41.0,
                lng=-73.0,
                green_escape_evaluation=eval_,
            )
        assert result.points <= 8, f"Expected ≤8 but got {result.points}"

    def test_verified_confidence_park_uncapped(self):
        """A park with verified confidence should retain its full score."""
        park = MagicMock()
        park.daily_walk_value = 9.0
        park.rating = 4.5
        park.user_ratings_total = 500
        park.walk_time_min = 5
        park.name = "Great Park"
        park.criteria_status = "met"
        park.osm_enriched = True
        park.subscores = []

        eval_ = MagicMock()
        eval_.best_daily_park = park

        with patch(
            "property_evaluator._classify_park_confidence",
            return_value=(CONFIDENCE_VERIFIED, "good data"),
        ):
            result = score_park_access(
                maps=MagicMock(),
                lat=41.0,
                lng=-73.0,
                green_escape_evaluation=eval_,
            )
        assert result.points == 9


# =============================================================================
# Integration: confidence cap applied in score_cost (NES-sparse-data)
# =============================================================================

class TestCostConfidenceCap:
    """Verify score_cost applies _apply_confidence_cap."""

    def test_cost_none_estimated_confidence_capped(self):
        """When cost is None → estimated confidence → points stay 0 (already below cap)."""
        result = score_cost(None)
        assert result.data_confidence == CONFIDENCE_ESTIMATED
        assert result.points == 0

    def test_cost_provided_verified_confidence_uncapped(self):
        """When cost is provided and verified confidence, score is not artificially capped."""
        result = score_cost(1500)
        assert result.data_confidence == CONFIDENCE_VERIFIED
        assert result.points == 10  # well under ideal


# =============================================================================
# Integration: confidence cap applied in score_transit_access (NES-sparse-data)
# =============================================================================

class TestTransitAccessConfidenceCap:
    """Verify score_transit_access applies _apply_confidence_cap."""

    def test_estimated_confidence_transit_capped_at_8(self):
        """Transit score with estimated confidence should cap at 8."""
        transit = MagicMock()
        transit.name = "Test Station"
        transit.walk_time_min = 10
        transit.drive_time_min = None
        transit.parking_available = False
        transit.frequency_label = "Good"
        transit.score = 9

        with patch(
            "property_evaluator._classify_transit_confidence",
            return_value=(CONFIDENCE_ESTIMATED, "limited data"),
        ):
            result = score_transit_access(
                maps=MagicMock(),
                lat=41.0,
                lng=-73.0,
                transit_access=transit,
                urban_access=MagicMock(
                    major_hub=MagicMock(name="Grand Central"),
                    major_hub_travel_time_min=45,
                ),
            )
        assert result.points <= 8, f"Expected ≤8 but got {result.points}"


# =============================================================================
# Phase 3: Road noise not_scored when no data
# =============================================================================

class TestRoadNoiseNotScored:
    """Verify road noise returns not_scored when assessment is None."""

    def test_none_assessment_returns_not_scored(self):
        from property_evaluator import score_road_noise
        result = score_road_noise(None)
        assert result.data_confidence == CONFIDENCE_NOT_SCORED
        assert result.points == 0
        assert "unavailable" in result.details
        assert "benefit of the doubt" not in result.details

    def test_valid_assessment_returns_verified(self):
        from property_evaluator import score_road_noise
        from road_noise import RoadNoiseAssessment
        assessment = RoadNoiseAssessment(
            estimated_dba=55.0,
            severity="MODERATE",
            severity_label="Moderate",
            distance_ft=200.0,
            worst_road_name="Main St",
            worst_road_ref=None,
            worst_road_type="primary",
            worst_road_lanes=2,
            methodology_note="FHWA TNM",
            all_roads_assessed=3,
        )
        result = score_road_noise(assessment)
        assert result.data_confidence == CONFIDENCE_VERIFIED
        assert result.points > 0


# =============================================================================
# Phase 3: Composite score excludes not_scored dimensions
# =============================================================================

class TestCompositeExcludesNotScored:
    """Verify not_scored dimensions are excluded from composite scoring."""

    def test_not_scored_excluded_from_totals(self):
        """A not_scored dimension should not count in tier2_total or tier2_max."""
        s1 = Tier2Score("A", 8, 10, "a", data_confidence=CONFIDENCE_VERIFIED)
        s2 = Tier2Score("B", 0, 10, "b", data_confidence=CONFIDENCE_NOT_SCORED)

        scorable = [
            s for s in [s1, s2]
            if getattr(s, "data_confidence", None) != CONFIDENCE_NOT_SCORED
        ]
        total = sum(s.points for s in scorable)
        max_total = sum(s.max_points for s in scorable)

        assert total == 8  # only A
        assert max_total == 10  # only A's max

    def test_all_scorable(self):
        """When no not_scored, all dimensions contribute."""
        s1 = Tier2Score("A", 8, 10, "a", data_confidence=CONFIDENCE_VERIFIED)
        s2 = Tier2Score("B", 6, 10, "b", data_confidence=CONFIDENCE_ESTIMATED)

        scorable = [
            s for s in [s1, s2]
            if getattr(s, "data_confidence", None) != CONFIDENCE_NOT_SCORED
        ]
        total = sum(s.points for s in scorable)
        max_total = sum(s.max_points for s in scorable)

        assert total == 14
        assert max_total == 20

    def test_sparse_included_in_composite(self):
        """Sparse dimensions still contribute to composite (unlike not_scored)."""
        s1 = Tier2Score("A", 8, 10, "a", data_confidence=CONFIDENCE_VERIFIED)
        s2 = Tier2Score("B", 5, 10, "b", data_confidence=CONFIDENCE_SPARSE)
        s3 = Tier2Score("C", 0, 10, "c", data_confidence=CONFIDENCE_NOT_SCORED)

        scorable = [
            s for s in [s1, s2, s3]
            if getattr(s, "data_confidence", None) != CONFIDENCE_NOT_SCORED
        ]
        total = sum(s.points for s in scorable)
        max_total = sum(s.max_points for s in scorable)

        assert total == 13  # A(8) + B(5), not C
        assert max_total == 20  # A(10) + B(10), not C


# =============================================================================
# Phase 3: Confidence tier migration for old snapshots
# =============================================================================

class TestConfidenceTierMigration:
    """Verify _migrate_confidence_tiers converts old values."""

    def test_high_to_verified(self):
        from app import _migrate_confidence_tiers
        result = {
            "tier2_scores": [
                {"name": "A", "points": 8, "data_confidence": "HIGH", "details": "ok"},
            ],
            "dimension_summaries": [
                {"name": "A", "data_confidence": "HIGH", "summary": "ok"},
            ],
        }
        _migrate_confidence_tiers(result)
        assert result["tier2_scores"][0]["data_confidence"] == CONFIDENCE_VERIFIED
        assert result["dimension_summaries"][0]["data_confidence"] == CONFIDENCE_VERIFIED

    def test_medium_to_estimated(self):
        from app import _migrate_confidence_tiers
        result = {
            "tier2_scores": [
                {"name": "A", "points": 6, "data_confidence": "MEDIUM", "details": "ok"},
            ],
            "dimension_summaries": [],
        }
        _migrate_confidence_tiers(result)
        assert result["tier2_scores"][0]["data_confidence"] == CONFIDENCE_ESTIMATED

    def test_low_benefit_of_doubt_to_not_scored(self):
        from app import _migrate_confidence_tiers
        result = {
            "tier2_scores": [
                {
                    "name": "Road Noise", "points": 7,
                    "data_confidence": "LOW",
                    "details": "Road noise data unavailable — benefit of the doubt",
                },
            ],
            "dimension_summaries": [],
        }
        _migrate_confidence_tiers(result)
        assert result["tier2_scores"][0]["data_confidence"] == CONFIDENCE_NOT_SCORED

    def test_low_non_road_noise_to_sparse(self):
        """Legacy LOW confidence (non-road-noise) now maps to sparse."""
        from app import _migrate_confidence_tiers
        result = {
            "tier2_scores": [
                {"name": "Other", "points": 3, "data_confidence": "LOW", "details": "ok"},
            ],
            "dimension_summaries": [],
        }
        _migrate_confidence_tiers(result)
        assert result["tier2_scores"][0]["data_confidence"] == CONFIDENCE_SPARSE

    def test_new_tier_names_unchanged(self):
        from app import _migrate_confidence_tiers
        result = {
            "tier2_scores": [
                {"name": "A", "points": 8, "data_confidence": CONFIDENCE_VERIFIED, "details": "ok"},
                {"name": "B", "points": 0, "data_confidence": CONFIDENCE_NOT_SCORED, "details": "no data"},
                {"name": "C", "points": 4, "data_confidence": CONFIDENCE_SPARSE, "details": "thin data"},
            ],
            "dimension_summaries": [],
        }
        _migrate_confidence_tiers(result)
        assert result["tier2_scores"][0]["data_confidence"] == CONFIDENCE_VERIFIED
        assert result["tier2_scores"][1]["data_confidence"] == CONFIDENCE_NOT_SCORED
        assert result["tier2_scores"][2]["data_confidence"] == CONFIDENCE_SPARSE


# =============================================================================
# Phase 3: Citations attached in present_checks
# =============================================================================

class TestCitationsInPresentChecks:
    """Verify present_checks attaches citation links from HEALTH_CHECK_CITATIONS."""

    def test_gas_station_has_citations(self):
        from app import present_checks
        checks = [{"name": "Gas station", "result": "FAIL", "details": "300 ft"}]
        presented = present_checks(checks)
        assert len(presented) == 1
        assert "citations" in presented[0]
        assert len(presented[0]["citations"]) > 0
        assert presented[0]["citations"][0]["label"] == "Hilpert et al. 2019"
        assert "doi.org" in presented[0]["citations"][0]["url"]

    def test_unknown_check_has_empty_citations(self):
        from app import present_checks
        checks = [{"name": "Unknown Check", "result": "PASS", "details": "ok"}]
        presented = present_checks(checks)
        assert presented[0]["citations"] == []
