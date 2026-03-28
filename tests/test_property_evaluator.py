"""Tests for property_evaluator.py — Tier 1 checks, helpers, and Tier 2 scoring.

Covers the most critical business logic in the codebase:
- Distance calculation helpers (pure math, no mocking)
- Voltage parsing (pure string parsing)
- Tier 1 safety checks (mocked API clients)
- Listing requirement checks (no mocking)
- Tier 2 scoring functions (score_cost is pure; others mock API)
"""

import math
from unittest.mock import MagicMock, patch

import pytest

from property_evaluator import (
    CheckResult,
    EvaluationResult,
    GreenSpace,
    GreenSpaceEvaluation,
    GoogleMapsClient,
    OverpassClient,
    PropertyListing,
    Tier1Check,
    Tier2Score,
    TransitAccessResult,
    _closest_distance_to_way_ft,
    _coerce_score,
    _distance_feet,
    _element_distance_ft,
    _parse_max_voltage,
    check_cell_towers,
    check_gas_stations,
    check_high_traffic_road,
    check_industrial_zones,
    check_listing_requirements,
    check_power_lines,
    check_substations,
    check_superfund_npl,
    check_tri_facility_proximity,
    score_cost,
    score_park_access,
    CONFIDENCE_NOT_SCORED,
    COST_IDEAL,
    TRI_FACILITY_WARNING_RADIUS_M,
    COST_MAX,
    COST_TARGET,
    GAS_STATION_FAIL_DISTANCE_FT,
    GAS_STATION_WARN_DISTANCE_FT,
    MIN_BEDROOMS,
    MIN_SQFT,
)


# ============================================================================
# Distance helpers
# ============================================================================

class TestDistanceFeet:
    """Haversine distance calculation."""

    def test_same_point_returns_zero(self):
        assert _distance_feet(40.7128, -74.0060, 40.7128, -74.0060) == 0

    def test_known_distance_roughly_correct(self):
        # Statue of Liberty to Empire State Building: ~5.1 miles ≈ 26,928 ft
        statue = (40.6892, -74.0445)
        empire = (40.7484, -73.9857)
        dist = _distance_feet(*statue, *empire)
        assert 25_000 < dist < 30_000

    def test_short_distance(self):
        # Two points ~100m apart (about 328 ft)
        lat, lng = 40.7128, -74.0060
        # ~0.001 degrees latitude ≈ 364 ft
        dist = _distance_feet(lat, lng, lat + 0.001, lng)
        assert 300 < dist < 400

    def test_returns_integer(self):
        result = _distance_feet(40.0, -74.0, 41.0, -73.0)
        assert isinstance(result, int)


class TestClosestDistanceToWay:
    """Minimum distance from property to a way's resolved nodes."""

    def test_empty_node_list(self):
        result = _closest_distance_to_way_ft(40.0, -74.0, [], {})
        assert result == float("inf")

    def test_no_matching_nodes(self):
        result = _closest_distance_to_way_ft(40.0, -74.0, [1, 2, 3], {})
        assert result == float("inf")

    def test_single_resolved_node(self):
        nodes = {10: (40.001, -74.0)}
        result = _closest_distance_to_way_ft(40.0, -74.0, [10], nodes)
        assert 300 < result < 400  # ~0.001 deg ≈ 364 ft

    def test_picks_closest_node(self):
        nodes = {
            1: (40.01, -74.0),   # ~3,640 ft away
            2: (40.001, -74.0),  # ~364 ft away (closer)
        }
        result = _closest_distance_to_way_ft(40.0, -74.0, [1, 2], nodes)
        assert 300 < result < 400

    def test_partial_resolution(self):
        # Only one of two node IDs resolves — should still work
        nodes = {2: (40.001, -74.0)}
        result = _closest_distance_to_way_ft(40.0, -74.0, [1, 2], nodes)
        assert result < float("inf")


class TestElementDistanceFt:
    """Distance from property to an Overpass element (node or way)."""

    def test_node_element(self):
        el = {"type": "node", "lat": 40.001, "lon": -74.0, "id": 1}
        dist = _element_distance_ft(40.0, -74.0, el, {})
        assert 300 < dist < 400

    def test_way_element(self):
        el = {"type": "way", "id": 1, "nodes": [10]}
        all_nodes = {10: (40.001, -74.0)}
        dist = _element_distance_ft(40.0, -74.0, el, all_nodes)
        assert 300 < dist < 400

    def test_way_with_no_resolvable_nodes(self):
        el = {"type": "way", "id": 1, "nodes": [99]}
        dist = _element_distance_ft(40.0, -74.0, el, {})
        assert dist == float("inf")

    def test_unknown_element_type(self):
        el = {"type": "relation", "id": 1}
        dist = _element_distance_ft(40.0, -74.0, el, {})
        assert dist == float("inf")

    def test_node_missing_lat(self):
        el = {"type": "node", "id": 1, "lon": -74.0}
        dist = _element_distance_ft(40.0, -74.0, el, {})
        assert dist == float("inf")


# ============================================================================
# Voltage parsing
# ============================================================================

class TestParseMaxVoltage:
    def test_single_value(self):
        assert _parse_max_voltage("115000") == 115000

    def test_semicolon_separated(self):
        assert _parse_max_voltage("115000;230000") == 230000

    def test_empty_string(self):
        assert _parse_max_voltage("") == 0

    def test_none_like_empty(self):
        assert _parse_max_voltage("") == 0

    def test_garbage_input(self):
        assert _parse_max_voltage("not_a_number") == 0

    def test_mixed_valid_and_invalid(self):
        assert _parse_max_voltage("115000;bad;230000") == 230000

    def test_whitespace_handling(self):
        assert _parse_max_voltage(" 115000 ; 230000 ") == 230000


# ============================================================================
# _coerce_score
# ============================================================================

class TestCoerceScore:
    def test_valid_int(self):
        assert _coerce_score(75) == 75

    def test_valid_string_int(self):
        assert _coerce_score("42") == 42

    def test_none_returns_none(self):
        assert _coerce_score(None) is None

    def test_garbage_returns_none(self):
        assert _coerce_score("not_a_number") is None

    def test_float_truncates(self):
        assert _coerce_score(3.9) == 3


# ============================================================================
# Tier 1: check_gas_stations
# ============================================================================

class TestCheckGasStations:
    """Tests for check_gas_stations — Places-primary, UST-enrichment.

    Google Places gas_station type is the primary source.  UST data
    enriches Places matches and provides a caution fallback when Places
    returns no results but active underground tanks exist.
    """

    def _make_maps(self, stations):
        """Create a mock GoogleMapsClient that returns *stations* from places_nearby."""
        maps = MagicMock(spec=GoogleMapsClient)
        maps.places_nearby.return_value = stations
        return maps

    def _make_unavailable_store(self):
        store = MagicMock()
        store.is_available.return_value = False
        return store

    def _make_store(self, facilities=None):
        """Create a mock spatial store returning *facilities* (default empty)."""
        store = MagicMock()
        store.is_available.return_value = True
        store.find_facilities_within.return_value = facilities or []
        return store

    @staticmethod
    def _station(lat, lng, name="Shell"):
        return {"geometry": {"location": {"lat": lat, "lng": lng}}, "name": name}

    # --- Places-primary path ---

    def test_no_stations_pass(self):
        maps = self._make_maps([])
        result = check_gas_stations(40.0, -74.0, self._make_unavailable_store(), maps)
        assert result.result == CheckResult.PASS

    def test_station_beyond_warn_threshold_pass(self):
        # Station at ~600 ft away (haversine)
        station = self._station(40.0018, -74.0, "Shell")
        maps = self._make_maps([station])
        result = check_gas_stations(40.0, -74.0, self._make_unavailable_store(), maps)
        assert result.result == CheckResult.PASS

    def test_station_within_fail_threshold_fail(self):
        """Station very close — inside CA 300 ft setback → FAIL."""
        # ~0.0007 degrees lat ≈ 255 ft
        station = self._station(40.0007, -74.0, "BP")
        maps = self._make_maps([station])
        result = check_gas_stations(40.0, -74.0, self._make_unavailable_store(), maps)
        assert result.result == CheckResult.FAIL
        assert "TOO CLOSE" in result.details

    def test_station_in_warning_band(self):
        """Station at ~350 ft — beyond CA setback, within MD 500 ft → WARNING."""
        # ~0.001 degrees lat ≈ 364 ft
        station = self._station(40.001, -74.0, "Sunoco")
        maps = self._make_maps([station])
        result = check_gas_stations(40.0, -74.0, self._make_unavailable_store(), maps)
        assert result.result == CheckResult.WARNING
        assert "NEARBY" in result.details

    def test_api_error_with_no_ust_returns_unknown(self):
        maps = MagicMock(spec=GoogleMapsClient)
        maps.places_nearby.side_effect = ValueError("API error")
        result = check_gas_stations(40.0, -74.0, self._make_unavailable_store(), maps)
        assert result.result == CheckResult.UNKNOWN

    def test_no_store_no_maps_returns_unknown(self):
        result = check_gas_stations(40.0, -74.0, None, None)
        assert result.result == CheckResult.UNKNOWN

    # --- UST enrichment of Places results ---

    def test_places_result_enriched_with_ust_tank_count(self):
        from spatial_data import FacilityRecord
        station = self._station(40.001, -74.0, "Shell")
        maps = self._make_maps([station])
        ust_match = FacilityRecord(
            facility_type="ust", name="Shell Oil",
            lat=40.001, lng=-74.0,
            distance_meters=10.0, distance_feet=33.0,
            metadata={"open_usts": 3, "closed_usts": 1},
        )
        store = self._make_store([ust_match])
        result = check_gas_stations(40.0, -74.0, store, maps)
        assert "3 active tanks" in result.details

    # --- UST-only caution (no Places match) ---

    def test_ust_active_no_places_returns_warning(self):
        """Active UST facility but no Places gas station → unverified WARNING."""
        from spatial_data import FacilityRecord
        facility = FacilityRecord(
            facility_type="ust", name="JSM SERVICE INC",
            lat=40.001, lng=-74.0,
            distance_meters=47.0, distance_feet=154.0,
            metadata={"open_usts": 2, "closed_usts": 0},
        )
        store = self._make_store([facility])
        maps = self._make_maps([])  # Places returns nothing
        result = check_gas_stations(40.0, -74.0, store, maps)
        assert result.result == CheckResult.WARNING
        assert "no operating gas station was confirmed" in result.details
        assert "JSM SERVICE INC" in result.details

    def test_ust_closed_only_no_places_returns_pass(self):
        """Closed-only UST facility, no Places gas station → PASS."""
        from spatial_data import FacilityRecord
        facility = FacilityRecord(
            facility_type="ust", name="Old Tank",
            lat=40.001, lng=-74.0,
            distance_meters=30.0, distance_feet=98.0,
            metadata={"open_usts": 0, "closed_usts": 3},
        )
        store = self._make_store([facility])
        maps = self._make_maps([])
        result = check_gas_stations(40.0, -74.0, store, maps)
        assert result.result == CheckResult.PASS

    def test_ust_no_facilities_no_places_pass(self):
        store = self._make_store([])
        maps = self._make_maps([])
        result = check_gas_stations(40.0, -74.0, store, maps)
        assert result.result == CheckResult.PASS

    # --- Fallback when Places API fails ---

    def test_places_error_ust_active_returns_warning(self):
        """Places API fails, but UST data shows active tanks → WARNING caution."""
        from spatial_data import FacilityRecord
        facility = FacilityRecord(
            facility_type="ust", name="Corner Fuel",
            lat=40.001, lng=-74.0,
            distance_meters=60.0, distance_feet=197.0,
            metadata={"open_usts": 1},
        )
        store = self._make_store([facility])
        maps = MagicMock(spec=GoogleMapsClient)
        maps.places_nearby.side_effect = ValueError("API error")
        result = check_gas_stations(40.0, -74.0, store, maps)
        assert result.result == CheckResult.WARNING
        assert "no operating gas station was confirmed" in result.details

    def test_places_error_ust_empty_returns_pass_with_note(self):
        """Places API fails, UST has no active tanks → PASS with confidence note."""
        store = self._make_store([])
        maps = MagicMock(spec=GoogleMapsClient)
        maps.places_nearby.side_effect = ValueError("API error")
        result = check_gas_stations(40.0, -74.0, store, maps)
        assert result.result == CheckResult.PASS
        assert "could not be verified" in result.details


# ============================================================================
# Tier 1: check_high_traffic_road (HPMS AADT — replaces highway + high-volume)
# Full test suite coming in Phase 4. Basic smoke tests here to ensure the
# function is importable and handles the UNKNOWN path.
# ============================================================================

class TestCheckHighTrafficRoad:
    def test_no_spatial_store_returns_unknown(self):
        result = check_high_traffic_road(40.0, -74.0, None)
        assert result.result == CheckResult.UNKNOWN
        assert result.name == "High-traffic road"

    def test_unavailable_store_returns_unknown(self):
        store = MagicMock()
        store.is_available.return_value = False
        result = check_high_traffic_road(40.0, -74.0, store)
        assert result.result == CheckResult.UNKNOWN

    def test_no_segments_returns_pass(self):
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = []
        result = check_high_traffic_road(40.0, -74.0, store)
        assert result.result == CheckResult.PASS

    def test_high_aadt_within_150m_returns_fail(self):
        from spatial_data import FacilityRecord
        segment = FacilityRecord(
            facility_type="hpms",
            name="I-95",
            lat=40.0, lng=-74.0,
            distance_meters=100.0,
            distance_feet=100.0 * 3.28084,
            metadata={"aadt": 75000, "route_id": "I-95"},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = [segment]
        result = check_high_traffic_road(40.0, -74.0, store)
        assert result.result == CheckResult.FAIL
        assert "75,000" in result.details

    def test_high_aadt_in_warning_band_returns_warning(self):
        from spatial_data import FacilityRecord
        segment = FacilityRecord(
            facility_type="hpms",
            name="I-95",
            lat=40.0, lng=-74.0,
            distance_meters=200.0,
            distance_feet=200.0 * 3.28084,
            metadata={"aadt": 60000, "route_id": "I-95"},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = [segment]
        result = check_high_traffic_road(40.0, -74.0, store)
        assert result.result == CheckResult.WARNING

    def test_null_aadt_excluded(self):
        from spatial_data import FacilityRecord
        segment = FacilityRecord(
            facility_type="hpms",
            name="Unknown Rd",
            lat=40.0, lng=-74.0,
            distance_meters=100.0,
            distance_feet=100.0 * 3.28084,
            metadata={"aadt": None, "route_id": ""},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = [segment]
        result = check_high_traffic_road(40.0, -74.0, store)
        assert result.result == CheckResult.PASS

    def test_below_threshold_aadt_returns_pass(self):
        from spatial_data import FacilityRecord
        segment = FacilityRecord(
            facility_type="hpms",
            name="Local Rd",
            lat=40.0, lng=-74.0,
            distance_meters=100.0,
            distance_feet=100.0 * 3.28084,
            metadata={"aadt": 30000, "route_id": ""},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = [segment]
        result = check_high_traffic_road(40.0, -74.0, store)
        assert result.result == CheckResult.PASS

    def test_multiple_segments_worst_wins(self):
        """FAIL zone segment beats WARNING zone segment with higher AADT."""
        from spatial_data import FacilityRecord
        segments = [
            FacilityRecord(
                facility_type="hpms", name="Local Rd",
                lat=40.0, lng=-74.0,
                distance_meters=100.0, distance_feet=100.0 * 3.28084,
                metadata={"aadt": 40000, "route_id": ""},
            ),
            FacilityRecord(
                facility_type="hpms", name="US-1",
                lat=40.0, lng=-74.0,
                distance_meters=120.0, distance_feet=120.0 * 3.28084,
                metadata={"aadt": 60000, "route_id": "US-1"},
            ),
            FacilityRecord(
                facility_type="hpms", name="I-95",
                lat=40.0, lng=-74.0,
                distance_meters=200.0, distance_feet=200.0 * 3.28084,
                metadata={"aadt": 80000, "route_id": "I-95"},
            ),
        ]
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = segments
        result = check_high_traffic_road(40.0, -74.0, store)
        assert result.result == CheckResult.FAIL
        # Detail references the 60K fail-zone segment, not the 80K warn-zone one
        assert "60,000" in result.details

    def test_fail_zone_takes_priority_over_warning(self):
        """FAIL zone hit overrides WARNING zone hit regardless of AADT."""
        from spatial_data import FacilityRecord
        segments = [
            FacilityRecord(
                facility_type="hpms", name="US-1",
                lat=40.0, lng=-74.0,
                distance_meters=140.0, distance_feet=140.0 * 3.28084,
                metadata={"aadt": 55000, "route_id": "US-1"},
            ),
            FacilityRecord(
                facility_type="hpms", name="I-95",
                lat=40.0, lng=-74.0,
                distance_meters=250.0, distance_feet=250.0 * 3.28084,
                metadata={"aadt": 70000, "route_id": "I-95"},
            ),
        ]
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = segments
        result = check_high_traffic_road(40.0, -74.0, store)
        assert result.result == CheckResult.FAIL
        assert "55,000" in result.details

    def test_warning_only_no_fail_zone_segments(self):
        """Segment above threshold in warning band (150-300m) returns WARNING."""
        from spatial_data import FacilityRecord
        segment = FacilityRecord(
            facility_type="hpms", name="I-287",
            lat=40.0, lng=-74.0,
            distance_meters=200.0, distance_feet=200.0 * 3.28084,
            metadata={"aadt": 65000, "route_id": "I-287"},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = [segment]
        result = check_high_traffic_road(40.0, -74.0, store)
        assert result.result == CheckResult.WARNING
        assert "65,000" in result.details
        assert "656" in result.details  # 200m ≈ 656 ft

    def test_detail_format_named_road(self):
        """Named road detail: '{name}: {aadt} vehicles/day, {dist} ft away'."""
        from spatial_data import FacilityRecord
        segment = FacilityRecord(
            facility_type="hpms", name="HPMS segment",
            lat=40.0, lng=-74.0,
            distance_meters=100.0, distance_feet=100.0 * 3.28084,
            metadata={"aadt": 75000, "route_id": "I-95"},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = [segment]
        result = check_high_traffic_road(40.0, -74.0, store)
        assert "I-95" in result.details
        assert "75,000" in result.details

    def test_detail_format_anonymous_road(self):
        """Anonymous road detail: 'Road with {aadt} vehicles/day found ...'."""
        from spatial_data import FacilityRecord
        segment = FacilityRecord(
            facility_type="hpms", name="",
            lat=40.0, lng=-74.0,
            distance_meters=100.0, distance_feet=100.0 * 3.28084,
            metadata={"aadt": 75000, "route_id": "", "route_name": ""},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = [segment]
        result = check_high_traffic_road(40.0, -74.0, store)
        assert "Road with" in result.details
        assert "75,000" in result.details

    def test_all_segments_below_threshold_returns_pass(self):
        """Multiple segments all with AADT < 50,000 within fail zone → PASS."""
        from spatial_data import FacilityRecord
        segments = [
            FacilityRecord(
                facility_type="hpms", name="County Rd 1",
                lat=40.0, lng=-74.0,
                distance_meters=50.0, distance_feet=50.0 * 3.28084,
                metadata={"aadt": 25000, "route_id": ""},
            ),
            FacilityRecord(
                facility_type="hpms", name="County Rd 2",
                lat=40.0, lng=-74.0,
                distance_meters=100.0, distance_feet=100.0 * 3.28084,
                metadata={"aadt": 35000, "route_id": ""},
            ),
            FacilityRecord(
                facility_type="hpms", name="County Rd 3",
                lat=40.0, lng=-74.0,
                distance_meters=140.0, distance_feet=140.0 * 3.28084,
                metadata={"aadt": 45000, "route_id": ""},
            ),
        ]
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = segments
        result = check_high_traffic_road(40.0, -74.0, store)
        assert result.result == CheckResult.PASS

    def test_high_aadt_beyond_warning_radius_returns_pass(self):
        """Segment with AADT >= 50K at 400m (beyond 300m warn radius) → PASS.

        Regression test for NES-266: warn_candidates filter was missing the
        upper distance bound (<= 300m), so segments up to 600m returned
        WARNING instead of PASS.
        """
        from spatial_data import FacilityRecord
        segment = FacilityRecord(
            facility_type="hpms", name="I-95",
            lat=40.0, lng=-74.0,
            distance_meters=400.0, distance_feet=400.0 * 3.28084,
            metadata={"aadt": 60000, "route_id": "I-95"},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = [segment]
        result = check_high_traffic_road(40.0, -74.0, store)
        assert result.result == CheckResult.PASS
        # Should report nearest high-traffic road in detail
        assert result.show_detail is True
        assert "60,000" in result.details


# ============================================================================
# Tier 1: Environmental hazard checks
# ============================================================================

class TestCheckPowerLines:
    """Tests for check_power_lines — HIFLD spatial data primary, Overpass fallback."""

    def _make_unavailable_store(self):
        store = MagicMock()
        store.is_available.return_value = False
        return store

    # --- Overpass fallback (spatial unavailable) ---

    def test_none_hazard_results_unknown(self):
        result = check_power_lines(40.0, -74.0, self._make_unavailable_store(), None)
        assert result.result == CheckResult.UNKNOWN

    def test_no_power_lines_pass(self):
        hazards = {"power_lines": [], "_all_nodes": {}}
        result = check_power_lines(40.0, -74.0, self._make_unavailable_store(), hazards)
        assert result.result == CheckResult.PASS

    def test_close_power_line_warning(self):
        # Node 100 ft away
        line = {"type": "node", "id": 1, "lat": 40.0003, "lon": -74.0}
        hazards = {"power_lines": [line], "_all_nodes": {}}
        result = check_power_lines(40.0, -74.0, self._make_unavailable_store(), hazards)
        assert result.result == CheckResult.WARNING

    def test_far_power_line_pass(self):
        # Node ~1000 ft away
        line = {"type": "node", "id": 1, "lat": 40.003, "lon": -74.0}
        hazards = {"power_lines": [line], "_all_nodes": {}}
        result = check_power_lines(40.0, -74.0, self._make_unavailable_store(), hazards)
        assert result.result == CheckResult.PASS

    def test_required_is_false(self):
        result = check_power_lines(40.0, -74.0, self._make_unavailable_store(), None)
        assert result.required is False

    # --- HIFLD spatial data path ---

    def test_spatial_no_lines_pass(self):
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = []
        result = check_power_lines(40.0, -74.0, store)
        assert result.result == CheckResult.PASS
        store.lines_within.assert_called_once_with(40.0, -74.0, 100, "hifld")

    def test_spatial_close_line_warning(self):
        from spatial_data import FacilityRecord
        line = FacilityRecord(
            facility_type="hifld", name="345 kV - ConEd",
            lat=40.0, lng=-74.0,
            distance_meters=50.0, distance_feet=164.0,
            metadata={"voltage": 345, "volt_class": "230-345"},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = [line]
        result = check_power_lines(40.0, -74.0, store)
        assert result.result == CheckResult.WARNING
        assert "345 kV" in result.details
        assert result.value == 164

    def test_spatial_far_line_pass(self):
        from spatial_data import FacilityRecord
        line = FacilityRecord(
            facility_type="hifld", name="115 kV - NYSEG",
            lat=40.0, lng=-74.0,
            distance_meters=90.0, distance_feet=295.0,
            metadata={"voltage": 115, "volt_class": "100-161"},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.lines_within.return_value = [line]
        result = check_power_lines(40.0, -74.0, store)
        assert result.result == CheckResult.PASS


class TestCheckSubstations:
    def test_none_hazard_results_unknown(self):
        result = check_substations(None, 40.0, -74.0)
        assert result.result == CheckResult.UNKNOWN

    def test_no_substations_pass(self):
        hazards = {"substations": [], "_all_nodes": {}}
        result = check_substations(hazards, 40.0, -74.0)
        assert result.result == CheckResult.PASS

    def test_close_substation_warning(self):
        sub = {"type": "node", "id": 1, "lat": 40.0003, "lon": -74.0}
        hazards = {"substations": [sub], "_all_nodes": {}}
        result = check_substations(hazards, 40.0, -74.0)
        assert result.result == CheckResult.WARNING


class TestCheckCellTowers:
    def test_none_hazard_results_unknown(self):
        result = check_cell_towers(None, 40.0, -74.0)
        assert result.result == CheckResult.UNKNOWN

    def test_no_towers_pass(self):
        hazards = {"cell_towers": [], "_all_nodes": {}}
        result = check_cell_towers(hazards, 40.0, -74.0)
        assert result.result == CheckResult.PASS

    def test_close_tower_warning(self):
        tower = {"type": "node", "id": 1, "lat": 40.001, "lon": -74.0}
        hazards = {"cell_towers": [tower], "_all_nodes": {}}
        result = check_cell_towers(hazards, 40.0, -74.0)
        assert result.result == CheckResult.WARNING


class TestCheckIndustrialZones:
    """Tests for check_industrial_zones — TRI spatial data primary, Overpass fallback."""

    def _make_unavailable_store(self):
        store = MagicMock()
        store.is_available.return_value = False
        return store

    # --- Overpass fallback (spatial unavailable) ---

    def test_none_hazard_results_unknown(self):
        result = check_industrial_zones(40.0, -74.0, self._make_unavailable_store(), None)
        assert result.result == CheckResult.UNKNOWN

    def test_no_zones_pass(self):
        hazards = {"industrial_zones": [], "_all_nodes": {}}
        result = check_industrial_zones(40.0, -74.0, self._make_unavailable_store(), hazards)
        assert result.result == CheckResult.PASS

    def test_close_zone_warning(self):
        zone = {"type": "node", "id": 1, "lat": 40.001, "lon": -74.0}
        hazards = {"industrial_zones": [zone], "_all_nodes": {}}
        result = check_industrial_zones(40.0, -74.0, self._make_unavailable_store(), hazards)
        assert result.result == CheckResult.WARNING

    # --- TRI spatial data path ---

    def test_spatial_no_facilities_pass(self):
        store = MagicMock()
        store.is_available.return_value = True
        store.find_facilities_within.return_value = []
        result = check_industrial_zones(40.0, -74.0, store)
        assert result.result == CheckResult.PASS
        store.find_facilities_within.assert_called_once_with(40.0, -74.0, 200, "tri")

    def test_spatial_close_facility_warning(self):
        from spatial_data import FacilityRecord
        facility = FacilityRecord(
            facility_type="tri", name="Chemical Corp",
            lat=40.0, lng=-74.0,
            distance_meters=100.0, distance_feet=328.0,
            metadata={"industry_sector": "Chemical Manufacturing", "total_releases_lb": 5000},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.find_facilities_within.return_value = [facility]
        result = check_industrial_zones(40.0, -74.0, store)
        assert result.result == CheckResult.WARNING
        assert "Chemical Manufacturing" in result.details
        assert result.value == 328

    def test_spatial_far_facility_pass(self):
        from spatial_data import FacilityRecord
        facility = FacilityRecord(
            facility_type="tri", name="Far Factory",
            lat=40.01, lng=-74.0,
            distance_meters=180.0, distance_feet=590.0,
            metadata={"industry_sector": "Paper Manufacturing"},
        )
        store = MagicMock()
        store.is_available.return_value = True
        store.find_facilities_within.return_value = [facility]
        result = check_industrial_zones(40.0, -74.0, store)
        assert result.result == CheckResult.PASS


# ============================================================================
# Tier 1: check_superfund_npl
# ============================================================================

class TestCheckSuperfundNpl:
    def test_unavailable_store_returns_unknown(self):
        with patch("property_evaluator.SpatialDataStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.is_available.return_value = False
            mock_store_cls.return_value = mock_store
            result = check_superfund_npl(40.0, -74.0)
        assert result.result == CheckResult.UNKNOWN
        assert result.name == "Superfund (NPL)"

    def test_empty_polygons_returns_pass(self):
        """SEMS is a national dataset — empty results means no Superfund site."""
        with patch("property_evaluator.SpatialDataStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.is_available.return_value = True
            mock_store.point_in_polygons.return_value = []
            mock_store_cls.return_value = mock_store
            result = check_superfund_npl(40.0, -74.0)
        assert result.result == CheckResult.PASS

    def test_npl_final_site_returns_fail(self):
        from spatial_data import FacilityRecord

        npl_record = FacilityRecord(
            facility_type="sems",
            name="GOWANUS CANAL",
            lat=40.67,
            lng=-73.99,
            distance_meters=0.0,
            distance_feet=0.0,
            metadata={"npl_status_code": "F", "site_name": "Gowanus Canal"},
        )
        with patch("property_evaluator.SpatialDataStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.is_available.return_value = True
            mock_store.point_in_polygons.return_value = [npl_record]
            mock_store_cls.return_value = mock_store
            result = check_superfund_npl(40.0, -74.0)
        assert result.result == CheckResult.FAIL
        assert "Gowanus Canal" in result.details
        assert result.required is True

    def test_npl_proposed_site_returns_fail(self):
        from spatial_data import FacilityRecord

        npl_record = FacilityRecord(
            facility_type="sems",
            name="Proposed Site",
            lat=40.0,
            lng=-74.0,
            distance_meters=0.0,
            distance_feet=0.0,
            metadata={"npl_status_code": "P", "site_name": "Proposed NPL Site"},
        )
        with patch("property_evaluator.SpatialDataStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.is_available.return_value = True
            mock_store.point_in_polygons.return_value = [npl_record]
            mock_store_cls.return_value = mock_store
            result = check_superfund_npl(40.0, -74.0)
        assert result.result == CheckResult.FAIL

    def test_non_npl_polygon_returns_pass(self):
        from spatial_data import FacilityRecord

        non_npl_record = FacilityRecord(
            facility_type="sems",
            name="Non-NPL Site",
            lat=40.0,
            lng=-74.0,
            distance_meters=0.0,
            distance_feet=0.0,
            metadata={"npl_status_code": "N", "site_name": "Not on NPL"},
        )
        with patch("property_evaluator.SpatialDataStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.is_available.return_value = True
            mock_store.point_in_polygons.return_value = [non_npl_record]
            mock_store_cls.return_value = mock_store
            result = check_superfund_npl(40.0, -74.0)
        assert result.result == CheckResult.PASS
        assert "Not within" in result.details


# ============================================================================
# Tier 1: check_tri_facility_proximity
# ============================================================================

class TestCheckTriFacilityProximity:
    def test_unavailable_store_returns_unknown(self):
        mock_store = MagicMock()
        mock_store.is_available.return_value = False
        result = check_tri_facility_proximity(40.0, -74.0, mock_store)
        assert result.result == CheckResult.UNKNOWN
        assert result.name == "TRI facility"

    def test_none_store_returns_unknown(self):
        result = check_tri_facility_proximity(40.0, -74.0, None)
        assert result.result == CheckResult.UNKNOWN

    def test_no_facilities_returns_pass(self):
        mock_store = MagicMock()
        mock_store.is_available.return_value = True
        mock_store.find_facilities_within.return_value = []
        mock_store.last_query_failed.return_value = False
        result = check_tri_facility_proximity(40.0, -74.0, mock_store)
        assert result.result == CheckResult.PASS
        assert "No EPA TRI facilities" in result.details
        assert result.required is False

    def test_query_failure_returns_unknown(self):
        mock_store = MagicMock()
        mock_store.is_available.return_value = True
        mock_store.find_facilities_within.return_value = []
        mock_store.last_query_failed.return_value = True
        result = check_tri_facility_proximity(40.0, -74.0, mock_store)
        assert result.result == CheckResult.UNKNOWN
        assert "check skipped" in result.details

    def test_nearby_facility_returns_warning(self):
        from spatial_data import FacilityRecord

        facility = FacilityRecord(
            facility_type="tri",
            name="ACME Chemical Plant",
            lat=40.001,
            lng=-74.0,
            distance_meters=800.0,
            distance_feet=2625.0,
            metadata={
                "industry_sector": "Chemicals",
                "total_releases_lb": 15000,
            },
        )
        mock_store = MagicMock()
        mock_store.is_available.return_value = True
        mock_store.find_facilities_within.return_value = [facility]
        result = check_tri_facility_proximity(40.0, -74.0, mock_store)
        assert result.result == CheckResult.WARNING
        assert "ACME Chemical Plant" in result.details
        assert "Chemicals" in result.details
        assert result.value == 2625
        assert result.required is False

    def test_multiple_facilities_shows_count(self):
        from spatial_data import FacilityRecord

        facilities = [
            FacilityRecord(
                facility_type="tri",
                name="Plant A",
                lat=40.001,
                lng=-74.0,
                distance_meters=500.0,
                distance_feet=1640.0,
                metadata={"industry_sector": "Chemicals"},
            ),
            FacilityRecord(
                facility_type="tri",
                name="Plant B",
                lat=40.002,
                lng=-74.0,
                distance_meters=1200.0,
                distance_feet=3937.0,
                metadata={"industry_sector": "Petroleum"},
            ),
        ]
        mock_store = MagicMock()
        mock_store.is_available.return_value = True
        mock_store.find_facilities_within.return_value = facilities
        result = check_tri_facility_proximity(40.0, -74.0, mock_store)
        assert result.result == CheckResult.WARNING
        assert "2 TRI facilities" in result.details

    def test_exception_returns_unknown(self):
        mock_store = MagicMock()
        mock_store.is_available.return_value = True
        mock_store.find_facilities_within.side_effect = RuntimeError("DB error")
        result = check_tri_facility_proximity(40.0, -74.0, mock_store)
        assert result.result == CheckResult.UNKNOWN

    def test_queries_correct_radius_and_type(self):
        mock_store = MagicMock()
        mock_store.is_available.return_value = True
        mock_store.find_facilities_within.return_value = []
        check_tri_facility_proximity(40.0, -74.0, mock_store)
        mock_store.find_facilities_within.assert_called_once_with(40.0, -74.0, TRI_FACILITY_WARNING_RADIUS_M, "tri")


# ============================================================================
# Tier 1: check_listing_requirements
# ============================================================================

class TestCheckListingRequirements:
    def _listing(self, **kwargs):
        defaults = {
            "address": "123 Test St",
            "cost": None,
            "sqft": None,
            "bedrooms": None,
            "has_washer_dryer_in_unit": None,
            "has_central_air": None,
        }
        defaults.update(kwargs)
        return PropertyListing(**defaults)

    def test_all_none_returns_unknown_for_each(self):
        checks = check_listing_requirements(self._listing())
        for check in checks:
            assert check.result == CheckResult.UNKNOWN

    def test_all_passing(self):
        listing = self._listing(
            has_washer_dryer_in_unit=True,
            has_central_air=True,
            sqft=2000,
            bedrooms=3,
            cost=5000,
        )
        checks = check_listing_requirements(listing)
        for check in checks:
            assert check.result == CheckResult.PASS

    def test_washer_dryer_false_fails(self):
        listing = self._listing(has_washer_dryer_in_unit=False)
        checks = check_listing_requirements(listing)
        wd = next(c for c in checks if c.name == "W/D in unit")
        assert wd.result == CheckResult.FAIL

    def test_central_air_false_fails(self):
        listing = self._listing(has_central_air=False)
        checks = check_listing_requirements(listing)
        ac = next(c for c in checks if c.name == "Central air")
        assert ac.result == CheckResult.FAIL

    def test_sqft_below_minimum_fails(self):
        listing = self._listing(sqft=MIN_SQFT - 1)
        checks = check_listing_requirements(listing)
        size = next(c for c in checks if c.name == "Size")
        assert size.result == CheckResult.FAIL

    def test_sqft_at_minimum_passes(self):
        listing = self._listing(sqft=MIN_SQFT)
        checks = check_listing_requirements(listing)
        size = next(c for c in checks if c.name == "Size")
        assert size.result == CheckResult.PASS

    def test_bedrooms_below_minimum_fails(self):
        listing = self._listing(bedrooms=MIN_BEDROOMS - 1)
        checks = check_listing_requirements(listing)
        br = next(c for c in checks if c.name == "Bedrooms")
        assert br.result == CheckResult.FAIL

    def test_bedrooms_at_minimum_passes(self):
        listing = self._listing(bedrooms=MIN_BEDROOMS)
        checks = check_listing_requirements(listing)
        br = next(c for c in checks if c.name == "Bedrooms")
        assert br.result == CheckResult.PASS

    def test_returns_four_checks(self):
        """Cost tier1 check was removed (users never provide cost data)."""
        checks = check_listing_requirements(self._listing())
        assert len(checks) == 4
        names = {c.name for c in checks}
        assert "Cost" not in names


# ============================================================================
# Tier 2: score_cost (pure function)
# ============================================================================

class TestScoreCost:
    def test_none_returns_zero(self):
        result = score_cost(None)
        assert result.points == 0
        assert result.max_points == 10

    def test_under_ideal_max_points(self):
        result = score_cost(COST_IDEAL - 500)
        assert result.points == 10

    def test_at_ideal_max_points(self):
        result = score_cost(COST_IDEAL)
        assert result.points == 10

    def test_between_ideal_and_target(self):
        result = score_cost(COST_IDEAL + 100)
        assert result.points == 6

    def test_at_target(self):
        result = score_cost(COST_TARGET)
        assert result.points == 6

    def test_between_target_and_max(self):
        result = score_cost(COST_TARGET + 100)
        assert result.points == 0

    def test_at_max(self):
        result = score_cost(COST_MAX)
        assert result.points == 0

    def test_over_max(self):
        result = score_cost(COST_MAX + 1)
        assert result.points == 0
        assert "OVER BUDGET" in result.details

    def test_name_is_cost(self):
        result = score_cost(5000)
        assert result.name == "Cost"


# ============================================================================
# Tier 2: score_park_access (with green escape evaluation)
# ============================================================================

class TestScoreParkAccess:
    def test_no_evaluations_calls_legacy(self):
        maps = MagicMock(spec=GoogleMapsClient)
        maps.places_nearby.return_value = []
        result = score_park_access(maps, 40.0, -74.0)
        assert result.points == 0
        assert result.max_points == 10
        assert result.data_confidence == CONFIDENCE_NOT_SCORED

    def test_legacy_with_green_escape(self):
        maps = MagicMock(spec=GoogleMapsClient)
        green_eval = GreenSpaceEvaluation(
            green_escape=GreenSpace(
                place_id="p1",
                name="Saxon Woods Park",
                rating=4.5,
                user_ratings_total=200,
                walk_time_min=15,
                types=["park"],
                types_display="Park",
            )
        )
        result = score_park_access(maps, 40.0, -74.0, green_space_evaluation=green_eval)
        assert result.points == 10  # walk_time <= 20 min ideal
        assert result.data_confidence == CONFIDENCE_NOT_SCORED

    def test_legacy_acceptable_walk_time(self):
        maps = MagicMock(spec=GoogleMapsClient)
        green_eval = GreenSpaceEvaluation(
            green_escape=GreenSpace(
                place_id="p1",
                name="Remote Park",
                rating=4.5,
                user_ratings_total=200,
                walk_time_min=25,
                types=["park"],
                types_display="Park",
            )
        )
        result = score_park_access(maps, 40.0, -74.0, green_space_evaluation=green_eval)
        assert result.points == 6  # walk_time > ideal but within acceptable
        assert result.data_confidence == CONFIDENCE_NOT_SCORED

    def test_no_green_escape_zero_points(self):
        maps = MagicMock(spec=GoogleMapsClient)
        green_eval = GreenSpaceEvaluation(green_escape=None)
        result = score_park_access(maps, 40.0, -74.0, green_space_evaluation=green_eval)
        assert result.points == 0
        assert result.data_confidence == CONFIDENCE_NOT_SCORED

    def test_legacy_not_scored_excluded_from_composite(self):
        """Legacy park score with NOT_SCORED should not contribute to composite."""
        maps = MagicMock(spec=GoogleMapsClient)
        green_eval = GreenSpaceEvaluation(
            green_escape=GreenSpace(
                place_id="p1",
                name="Saxon Woods Park",
                rating=4.5,
                user_ratings_total=200,
                walk_time_min=15,
                types=["park"],
                types_display="Park",
            )
        )
        result = score_park_access(maps, 40.0, -74.0, green_space_evaluation=green_eval)
        # Points are still computed (for display in edge cases)
        assert result.points == 10
        # But NOT_SCORED means the composite filter excludes it
        assert result.data_confidence == CONFIDENCE_NOT_SCORED
        # Verify it would be filtered by the _scorable check in evaluate_property
        assert not (
            result.points is not None
            and getattr(result, "data_confidence", None) != CONFIDENCE_NOT_SCORED
        )
