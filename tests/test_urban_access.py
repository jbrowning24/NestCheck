"""Tests for urban_access.py — verdict thresholds, hub loading, and engine.

Covers the UrbanAccessEngine which calculates commute times to
major hubs (NYC, airports, hospitals).
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from urban_access import (
    HubReachability,
    PrimaryHubCommute,
    UrbanAccessEngine,
    UrbanAccessResult,
    _load_airport_hubs,
    _verdict,
    hub_reachability_to_dict,
    primary_hub_commute_to_dict,
    urban_access_result_to_dict,
)


# ============================================================================
# Verdict thresholds
# ============================================================================

class TestVerdict:
    """_verdict(minutes, category) returns Great / OK / Painful."""

    def test_primary_hub_great(self):
        assert _verdict(30, "primary_hub") == "Great"

    def test_primary_hub_boundary_great(self):
        assert _verdict(45, "primary_hub") == "Great"

    def test_primary_hub_ok(self):
        assert _verdict(60, "primary_hub") == "OK"

    def test_primary_hub_boundary_ok(self):
        assert _verdict(75, "primary_hub") == "OK"

    def test_primary_hub_painful(self):
        assert _verdict(76, "primary_hub") == "Painful"

    def test_airport_great(self):
        assert _verdict(50, "airport") == "Great"

    def test_airport_ok(self):
        assert _verdict(70, "airport") == "OK"

    def test_airport_painful(self):
        assert _verdict(100, "airport") == "Painful"

    def test_downtown_great(self):
        assert _verdict(30, "downtown") == "Great"

    def test_hospital_great(self):
        assert _verdict(20, "hospital") == "Great"

    def test_hospital_ok(self):
        assert _verdict(45, "hospital") == "OK"

    def test_hospital_painful(self):
        assert _verdict(65, "hospital") == "Painful"

    def test_unknown_category_uses_defaults(self):
        # Default thresholds: (45, 75) from VERDICT_THRESHOLDS.get fallback
        assert _verdict(44, "nonexistent") == "Great"
        assert _verdict(46, "nonexistent") == "OK"
        assert _verdict(76, "nonexistent") == "Painful"


# ============================================================================
# Airport hub loading
# ============================================================================

class TestLoadAirportHubs:
    def test_default_hubs(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AIRPORT_HUBS", None)
            hubs = _load_airport_hubs()
        assert len(hubs) == 3
        names = [h["name"] for h in hubs]
        assert "JFK International Airport" in names
        assert "LaGuardia Airport" in names

    def test_custom_hubs_from_env(self):
        custom = [{"name": "Test Airport", "address": "123 Test, NY"}]
        with patch.dict(os.environ, {"AIRPORT_HUBS": json.dumps(custom)}):
            hubs = _load_airport_hubs()
        assert len(hubs) == 1
        assert hubs[0]["name"] == "Test Airport"

    def test_malformed_json_falls_back(self):
        with patch.dict(os.environ, {"AIRPORT_HUBS": "not-json{"}):
            hubs = _load_airport_hubs()
        assert len(hubs) == 3  # defaults


# ============================================================================
# UrbanAccessEngine
# ============================================================================

class TestUrbanAccessEngineBestTravel:
    def setup_method(self):
        self.maps = MagicMock()
        self.engine = UrbanAccessEngine(self.maps, 40.9, -73.8)
        UrbanAccessEngine.clear_cache()

    def test_transit_preferred_when_faster(self):
        self.maps.transit_time.return_value = 30
        self.maps.driving_time.return_value = 45
        time_min, mode, fallback = self.engine._best_travel((40.75, -73.98))
        assert time_min == 30
        assert mode == "transit"
        assert fallback is False

    def test_driving_preferred_when_faster(self):
        self.maps.transit_time.return_value = 60
        self.maps.driving_time.return_value = 35
        time_min, mode, fallback = self.engine._best_travel((40.75, -73.98))
        assert time_min == 35
        assert mode == "driving"
        assert fallback is False

    def test_transit_only_no_fallback(self):
        self.maps.transit_time.return_value = 40
        self.maps.driving_time.return_value = 9999  # unreachable
        time_min, mode, fallback = self.engine._best_travel((40.75, -73.98))
        assert time_min == 40
        assert mode == "transit"
        assert fallback is False

    def test_driving_fallback_when_transit_unreachable(self):
        self.maps.transit_time.return_value = 9999
        self.maps.driving_time.return_value = 25
        time_min, mode, fallback = self.engine._best_travel((40.75, -73.98))
        assert time_min == 25
        assert mode == "driving"
        assert fallback is True

    def test_both_unreachable(self):
        self.maps.transit_time.return_value = 9999
        self.maps.driving_time.return_value = 9999
        time_min, mode, fallback = self.engine._best_travel((40.75, -73.98))
        assert time_min is None
        assert fallback is True


class TestUrbanAccessEnginePrimaryHubCommute:
    def setup_method(self):
        self.maps = MagicMock()
        self.engine = UrbanAccessEngine(self.maps, 40.9, -73.8)
        UrbanAccessEngine.clear_cache()

    def test_successful_commute(self):
        self.maps.geocode.return_value = (40.7527, -73.9772)
        self.maps.transit_time.return_value = 40
        self.maps.driving_time.return_value = 50
        result = self.engine.get_primary_hub_commute()
        assert result is not None
        assert result.time_min == 40
        assert result.mode == "transit"
        assert result.verdict == "Great"

    def test_geocode_failure_returns_none(self):
        self.maps.geocode.side_effect = ValueError("Geocoding failed")
        result = self.engine.get_primary_hub_commute()
        assert result is None


class TestUrbanAccessEngineNearestAirport:
    def setup_method(self):
        self.maps = MagicMock()
        self.engine = UrbanAccessEngine(self.maps, 40.9, -73.8)
        UrbanAccessEngine.clear_cache()

    def test_picks_nearest(self):
        geocode_results = {
            "JFK Airport, Queens, NY": (40.6413, -73.7781),
            "LaGuardia Airport, Queens, NY": (40.7769, -73.8740),
            "Newark Liberty International Airport, Newark, NJ": (40.6895, -74.1745),
        }
        self.maps.geocode.side_effect = lambda addr: geocode_results[addr]
        # Make LGA the fastest
        transit_times = {}
        driving_times = {}
        def mock_transit(orig, dest):
            if dest == (40.7769, -73.8740):
                return 25  # LGA
            if dest == (40.6413, -73.7781):
                return 55  # JFK
            return 60  # EWR

        def mock_driving(orig, dest):
            return 9999  # Always unreachable

        self.maps.transit_time.side_effect = mock_transit
        self.maps.driving_time.side_effect = mock_driving

        result = self.engine._nearest_airport()
        assert result is not None
        assert result.hub_name == "LaGuardia Airport"
        assert result.total_time_min == 25

    def test_all_unreachable_returns_none(self):
        self.maps.geocode.return_value = (40.0, -74.0)
        self.maps.transit_time.return_value = 9999
        self.maps.driving_time.return_value = 9999
        result = self.engine._nearest_airport()
        assert result is None


# ============================================================================
# Serialization helpers
# ============================================================================

class TestSerialization:
    def test_hub_reachability_to_dict(self):
        hub = HubReachability(
            hub_name="JFK",
            category="airport",
            best_mode="transit",
            total_time_min=55,
            verdict="Great",
            fallback=False,
        )
        d = hub_reachability_to_dict(hub)
        assert d["hub_name"] == "JFK"
        assert d["total_time_min"] == 55
        assert d["fallback"] is False

    def test_primary_hub_commute_to_dict(self):
        commute = PrimaryHubCommute(
            hub_name="Grand Central Terminal",
            hub_address="Grand Central Terminal, New York, NY",
            mode="transit",
            time_min=40,
            verdict="Great",
        )
        d = primary_hub_commute_to_dict(commute)
        assert d["hub_name"] == "Grand Central Terminal"
        assert d["mode"] == "transit"

    def test_urban_access_result_to_dict_empty(self):
        result = UrbanAccessResult()
        d = urban_access_result_to_dict(result)
        assert d["primary_hub_commute"] is None
        assert d["reachability_hubs"] == []
