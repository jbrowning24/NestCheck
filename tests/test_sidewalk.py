"""Unit tests for sidewalk_coverage.py — sidewalk/cycleway coverage analysis.

Tests cover: Overpass query building, response parsing, confidence classification,
and the main assessment flow.
"""

from unittest.mock import patch

import pytest

from sidewalk_coverage import (
    _build_query,
    _parse_coverage,
    _classify_confidence,
    assess_sidewalk_coverage,
    SidewalkCoverageAssessment,
    ROAD_TYPES,
    SIDEWALK_PRESENT,
    SIDEWALK_ABSENT,
    CYCLEWAY_PRESENT,
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
    METHODOLOGY_NOTE,
)


# =========================================================================
# Query building
# =========================================================================

class TestBuildQuery:
    def test_contains_road_types(self):
        q = _build_query(41.0, -73.0, 500)
        for road_type in ROAD_TYPES:
            assert road_type in q

    def test_contains_coordinates(self):
        q = _build_query(41.05, -73.78, 500)
        assert "41.05" in q
        assert "-73.78" in q

    def test_contains_footway_and_cycleway(self):
        q = _build_query(41.0, -73.0)
        assert "footway" in q
        assert "cycleway" in q


# =========================================================================
# Parsing
# =========================================================================

class TestParseCoverage:
    def test_counts_roads_with_sidewalk(self):
        data = {
            "elements": [
                {"type": "way", "tags": {"highway": "residential", "sidewalk": "both"}},
                {"type": "way", "tags": {"highway": "residential", "sidewalk": "left"}},
                {"type": "way", "tags": {"highway": "residential", "sidewalk": "no"}},
                {"type": "way", "tags": {"highway": "residential"}},
            ]
        }
        stats = _parse_coverage(data)
        assert stats["total_road_segments"] == 4
        assert stats["roads_with_sidewalk"] == 2
        assert stats["roads_without_sidewalk"] == 1
        assert stats["roads_untagged"] == 1

    def test_counts_separate_cycleways(self):
        data = {
            "elements": [
                {"type": "way", "tags": {"highway": "cycleway"}},
                {"type": "way", "tags": {"highway": "cycleway"}},
            ]
        }
        stats = _parse_coverage(data)
        assert stats["separate_cycleways"] == 2
        assert stats["total_road_segments"] == 0

    def test_counts_separate_footways(self):
        data = {
            "elements": [
                {"type": "way", "tags": {"highway": "footway", "footway": "sidewalk"}},
            ]
        }
        stats = _parse_coverage(data)
        assert stats["separate_footways"] == 1

    def test_counts_road_cycleways(self):
        data = {
            "elements": [
                {"type": "way", "tags": {"highway": "secondary", "cycleway": "lane"}},
                {"type": "way", "tags": {"highway": "tertiary", "cycleway:right": "track"}},
                {"type": "way", "tags": {"highway": "residential"}},
            ]
        }
        stats = _parse_coverage(data)
        assert stats["roads_with_cycleway"] == 2

    def test_ignores_non_way_elements(self):
        data = {
            "elements": [
                {"type": "node", "id": 1, "lat": 41.0, "lon": -73.0},
                {"type": "way", "tags": {"highway": "residential", "sidewalk": "both"}},
            ]
        }
        stats = _parse_coverage(data)
        assert stats["total_road_segments"] == 1

    def test_ignores_non_road_highway_types(self):
        data = {
            "elements": [
                {"type": "way", "tags": {"highway": "motorway"}},
                {"type": "way", "tags": {"highway": "service"}},
                {"type": "way", "tags": {"highway": "residential"}},
            ]
        }
        stats = _parse_coverage(data)
        assert stats["total_road_segments"] == 1

    def test_empty_data(self):
        stats = _parse_coverage({"elements": []})
        assert stats["total_road_segments"] == 0
        assert stats["roads_with_sidewalk"] == 0

    def test_all_sidewalk_tag_values(self):
        """All SIDEWALK_PRESENT values should be recognized."""
        for val in SIDEWALK_PRESENT:
            data = {
                "elements": [
                    {"type": "way", "tags": {"highway": "residential", "sidewalk": val}},
                ]
            }
            stats = _parse_coverage(data)
            assert stats["roads_with_sidewalk"] == 1, f"Failed for sidewalk={val}"

    def test_all_sidewalk_absent_values(self):
        """All SIDEWALK_ABSENT values should be counted as absent."""
        for val in SIDEWALK_ABSENT:
            data = {
                "elements": [
                    {"type": "way", "tags": {"highway": "residential", "sidewalk": val}},
                ]
            }
            stats = _parse_coverage(data)
            assert stats["roads_without_sidewalk"] == 1, f"Failed for sidewalk={val}"


# =========================================================================
# Confidence classification
# =========================================================================

class TestClassifyConfidence:
    def test_high_confidence(self):
        level, note = _classify_confidence(50, 10, 80)
        assert level == "HIGH"
        assert "%" in note

    def test_medium_confidence(self):
        level, note = _classify_confidence(10, 10, 80)
        assert level == "MEDIUM"

    def test_low_confidence(self):
        level, note = _classify_confidence(2, 2, 80)
        assert level == "LOW"

    def test_zero_roads(self):
        level, note = _classify_confidence(0, 0, 0)
        assert level == "LOW"
        assert "No road segments" in note

    def test_all_tagged_is_high(self):
        level, _ = _classify_confidence(40, 40, 80)
        assert level == "HIGH"

    def test_boundary_high(self):
        # Exactly at threshold: 60 of 100 tagged
        level, _ = _classify_confidence(30, 30, 100)
        assert level == "HIGH"

    def test_boundary_medium(self):
        # Exactly at medium threshold: 20 of 100 tagged
        level, _ = _classify_confidence(10, 10, 100)
        assert level == "MEDIUM"


# =========================================================================
# Main assessment flow
# =========================================================================

class TestAssessSidewalkCoverage:
    @patch("sidewalk_coverage._fetch_data")
    def test_returns_assessment(self, mock_fetch):
        mock_fetch.return_value = {
            "elements": [
                {"type": "way", "tags": {"highway": "residential", "sidewalk": "both"}},
                {"type": "way", "tags": {"highway": "residential", "sidewalk": "no"}},
                {"type": "way", "tags": {"highway": "residential"}},
                {"type": "way", "tags": {"highway": "residential", "sidewalk": "left", "cycleway": "lane"}},
                {"type": "way", "tags": {"highway": "cycleway"}},
                {"type": "way", "tags": {"highway": "footway", "footway": "sidewalk"}},
            ]
        }

        result = assess_sidewalk_coverage(41.0, -73.0)

        assert result is not None
        assert isinstance(result, SidewalkCoverageAssessment)
        assert result.total_road_segments == 4
        assert result.roads_with_sidewalk == 2
        assert result.roads_without_sidewalk == 1
        assert result.roads_untagged == 1
        assert result.roads_with_cycleway == 1
        assert result.separate_cycleways == 1
        assert result.separate_footways == 1
        assert result.sidewalk_pct == 50.0
        assert result.cycleway_pct == 25.0
        assert result.methodology_note == METHODOLOGY_NOTE

    @patch("sidewalk_coverage._fetch_data", side_effect=Exception("network error"))
    def test_fetch_failure_returns_none(self, mock_fetch):
        assert assess_sidewalk_coverage(41.0, -73.0) is None

    @patch("sidewalk_coverage._fetch_data")
    def test_no_roads_returns_none(self, mock_fetch):
        mock_fetch.return_value = {"elements": []}
        assert assess_sidewalk_coverage(41.0, -73.0) is None

    @patch("sidewalk_coverage._fetch_data")
    def test_only_cycleways_no_roads_returns_none(self, mock_fetch):
        """If only standalone cycleways are found, total_road_segments=0 → returns None."""
        mock_fetch.return_value = {
            "elements": [
                {"type": "way", "tags": {"highway": "cycleway"}},
            ]
        }
        assert assess_sidewalk_coverage(41.0, -73.0) is None
