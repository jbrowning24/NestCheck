"""Unit tests for road_noise.py — FHWA TNM-based noise estimation.

Tests cover: haversine distance, nearest-point geometry, noise estimation,
severity classification, Overpass data parsing, and the main assessment flow.
"""

import math
from unittest.mock import patch

import pytest

from road_noise import (
    _haversine_ft,
    _nearest_point_on_segment,
    _nearest_distance_to_road_ft,
    _estimate_noise_dba,
    _classify_severity,
    _parse_roads_with_geometry,
    assess_road_noise,
    RoadSegment,
    RoadNoiseAssessment,
    NoiseSeverity,
    FHWA_REFERENCE_DBA,
    REFERENCE_DISTANCE_FT,
    DECAY_RATE,
    SEVERITY_LABELS,
)


# =========================================================================
# Haversine distance
# =========================================================================

class TestHaversineFt:
    def test_same_point_is_zero(self):
        assert _haversine_ft(41.0, -73.0, 41.0, -73.0) == 0.0

    def test_known_distance(self):
        # NYC to Newark is roughly 9 miles (47,500 ft)
        dist = _haversine_ft(40.7128, -74.0060, 40.7357, -74.1724)
        assert 40_000 < dist < 60_000

    def test_short_distance(self):
        # Two points ~100m apart
        dist = _haversine_ft(41.0, -73.0, 41.001, -73.0)
        assert 300 < dist < 400  # ~365 ft

    def test_symmetry(self):
        d1 = _haversine_ft(41.0, -73.0, 41.01, -73.01)
        d2 = _haversine_ft(41.01, -73.01, 41.0, -73.0)
        assert abs(d1 - d2) < 0.01


# =========================================================================
# Nearest point on segment
# =========================================================================

class TestNearestPointOnSegment:
    def test_projection_on_segment(self):
        # Point directly above midpoint of horizontal segment
        px, py = 1.0, 1.0
        ax, ay = 0.0, 0.0
        bx, by = 2.0, 0.0

        nx, ny = _nearest_point_on_segment(px, py, ax, ay, bx, by)
        assert abs(nx - 1.0) < 0.001
        assert abs(ny - 0.0) < 0.001

    def test_clamp_to_start(self):
        # Point behind segment start
        px, py = -1.0, 0.0
        ax, ay = 0.0, 0.0
        bx, by = 2.0, 0.0

        nx, ny = _nearest_point_on_segment(px, py, ax, ay, bx, by)
        assert abs(nx - 0.0) < 0.001
        assert abs(ny - 0.0) < 0.001

    def test_clamp_to_end(self):
        # Point beyond segment end
        px, py = 3.0, 0.0
        ax, ay = 0.0, 0.0
        bx, by = 2.0, 0.0

        nx, ny = _nearest_point_on_segment(px, py, ax, ay, bx, by)
        assert abs(nx - 2.0) < 0.001
        assert abs(ny - 0.0) < 0.001

    def test_degenerate_segment(self):
        # A == B (zero-length segment)
        px, py = 1.0, 1.0
        ax, ay = 0.0, 0.0

        nx, ny = _nearest_point_on_segment(px, py, ax, ay, ax, ay)
        assert abs(nx - 0.0) < 0.001
        assert abs(ny - 0.0) < 0.001


# =========================================================================
# Road distance calculation
# =========================================================================

class TestNearestDistanceToRoadFt:
    def test_distance_to_simple_road(self):
        road = RoadSegment(
            name="Test Rd",
            ref="",
            highway_type="residential",
            lanes=2,
            nodes=[(41.0, -73.0), (41.001, -73.0)],
        )
        dist = _nearest_distance_to_road_ft(41.0005, -73.001, road)
        assert dist > 0
        assert dist < 1000  # Should be close (within ~300ft)


# =========================================================================
# Noise estimation
# =========================================================================

class TestEstimateNoiseDba:
    def test_at_reference_distance(self):
        road = RoadSegment("", "", "primary", 2, [])
        dba = _estimate_noise_dba(road, REFERENCE_DISTANCE_FT)
        assert dba == FHWA_REFERENCE_DBA["primary"]

    def test_closer_than_reference(self):
        road = RoadSegment("", "", "primary", 2, [])
        dba = _estimate_noise_dba(road, 25.0)
        # At 25ft (closer than 50ft reference), noise should be at reference level
        assert dba == FHWA_REFERENCE_DBA["primary"]

    def test_farther_reduces_noise(self):
        road = RoadSegment("", "", "primary", 2, [])
        dba_near = _estimate_noise_dba(road, 50)
        dba_far = _estimate_noise_dba(road, 200)
        assert dba_far < dba_near

    def test_lane_bonus(self):
        road_2 = RoadSegment("", "", "primary", 2, [])
        road_4 = RoadSegment("", "", "primary", 4, [])

        dba_2 = _estimate_noise_dba(road_2, 100)
        dba_4 = _estimate_noise_dba(road_4, 100)
        assert dba_4 > dba_2

    def test_floor_at_30(self):
        road = RoadSegment("", "", "living_street", 2, [])
        dba = _estimate_noise_dba(road, 100_000)  # very far away
        assert dba == 30.0

    def test_all_road_types_have_reference(self):
        for road_type in FHWA_REFERENCE_DBA:
            road = RoadSegment("", "", road_type, 2, [])
            dba = _estimate_noise_dba(road, 50)
            assert dba > 0

    def test_motorway_louder_than_residential(self):
        motorway = RoadSegment("", "", "motorway", 2, [])
        residential = RoadSegment("", "", "residential", 2, [])
        assert _estimate_noise_dba(motorway, 100) > _estimate_noise_dba(residential, 100)


# =========================================================================
# Severity classification
# =========================================================================

class TestClassifySeverity:
    def test_very_loud(self):
        severity, label = _classify_severity(80)
        assert severity == NoiseSeverity.VERY_LOUD

    def test_loud(self):
        severity, label = _classify_severity(70)
        assert severity == NoiseSeverity.LOUD

    def test_moderate(self):
        severity, label = _classify_severity(60)
        assert severity == NoiseSeverity.MODERATE

    def test_quiet(self):
        severity, label = _classify_severity(45)
        assert severity == NoiseSeverity.QUIET

    def test_boundary_75(self):
        severity, _ = _classify_severity(75)
        assert severity == NoiseSeverity.VERY_LOUD

    def test_boundary_65(self):
        severity, _ = _classify_severity(65)
        assert severity == NoiseSeverity.LOUD

    def test_boundary_55(self):
        severity, _ = _classify_severity(55)
        assert severity == NoiseSeverity.MODERATE

    def test_all_severities_have_labels(self):
        for sev in NoiseSeverity:
            assert sev in SEVERITY_LABELS


# =========================================================================
# Overpass parsing
# =========================================================================

class TestParseRoadsWithGeometry:
    def test_parses_roads(self):
        data = {
            "elements": [
                {"type": "node", "id": 1, "lat": 41.0, "lon": -73.0},
                {"type": "node", "id": 2, "lat": 41.001, "lon": -73.0},
                {
                    "type": "way",
                    "id": 100,
                    "tags": {"highway": "primary", "name": "Main St", "ref": "US 9", "lanes": "4"},
                    "nodes": [1, 2],
                },
            ]
        }
        roads = _parse_roads_with_geometry(data)
        assert len(roads) == 1
        assert roads[0].name == "Main St"
        assert roads[0].ref == "US 9"
        assert roads[0].highway_type == "primary"
        assert roads[0].lanes == 4
        assert len(roads[0].nodes) == 2

    def test_skips_unknown_highway_types(self):
        data = {
            "elements": [
                {"type": "node", "id": 1, "lat": 41.0, "lon": -73.0},
                {"type": "node", "id": 2, "lat": 41.001, "lon": -73.0},
                {
                    "type": "way",
                    "id": 100,
                    "tags": {"highway": "footway"},
                    "nodes": [1, 2],
                },
            ]
        }
        roads = _parse_roads_with_geometry(data)
        assert len(roads) == 0

    def test_defaults_to_2_lanes(self):
        data = {
            "elements": [
                {"type": "node", "id": 1, "lat": 41.0, "lon": -73.0},
                {"type": "node", "id": 2, "lat": 41.001, "lon": -73.0},
                {
                    "type": "way",
                    "id": 100,
                    "tags": {"highway": "residential", "name": "Elm St"},
                    "nodes": [1, 2],
                },
            ]
        }
        roads = _parse_roads_with_geometry(data)
        assert roads[0].lanes == 2

    def test_skips_ways_with_insufficient_nodes(self):
        data = {
            "elements": [
                {"type": "node", "id": 1, "lat": 41.0, "lon": -73.0},
                {
                    "type": "way",
                    "id": 100,
                    "tags": {"highway": "residential"},
                    "nodes": [1],
                },
            ]
        }
        roads = _parse_roads_with_geometry(data)
        assert len(roads) == 0

    def test_empty_elements(self):
        roads = _parse_roads_with_geometry({"elements": []})
        assert roads == []

    def test_missing_elements_key(self):
        roads = _parse_roads_with_geometry({})
        assert roads == []


# =========================================================================
# Main assessment flow
# =========================================================================

class TestAssessRoadNoise:
    @patch("road_noise.fetch_all_roads")
    def test_returns_assessment(self, mock_fetch):
        mock_fetch.return_value = [
            RoadSegment(
                name="Main St",
                ref="US 9",
                highway_type="primary",
                lanes=4,
                nodes=[(41.0, -73.0), (41.001, -73.0)],
            ),
            RoadSegment(
                name="Elm St",
                ref="",
                highway_type="residential",
                lanes=2,
                nodes=[(41.0005, -73.001), (41.0005, -73.002)],
            ),
        ]

        result = assess_road_noise(41.0003, -73.0005)

        assert result is not None
        assert isinstance(result, RoadNoiseAssessment)
        assert result.all_roads_assessed == 2
        assert result.estimated_dba > 0
        assert result.distance_ft > 0
        assert result.severity in NoiseSeverity
        assert result.methodology_note != ""

    @patch("road_noise.fetch_all_roads", return_value=[])
    def test_no_roads_returns_none(self, mock_fetch):
        assert assess_road_noise(41.0, -73.0) is None
