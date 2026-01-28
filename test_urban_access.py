"""
Tests for the Urban Access Engine.

Covers:
1. Fallback behaviour when transit directions are unavailable.
2. Stable verdict classification (Great / OK / Painful) for known inputs.
"""

import unittest
from unittest.mock import MagicMock, patch
from urban_access import (
    UrbanAccessEngine,
    HubReachability,
    PrimaryHubCommute,
    _verdict,
    VERDICT_THRESHOLDS,
)


class _FakeMaps:
    """Minimal mock of GoogleMapsClient used by the engine."""

    def __init__(self, transit_returns=None, driving_returns=None, geocode_returns=None):
        """
        Parameters
        ----------
        transit_returns : dict
            Mapping of "(olat,olng)|(dlat,dlng)" -> minutes (int) or None.
        driving_returns : dict
            Same format for driving mode.
        geocode_returns : dict
            Mapping of address -> (lat, lng).
        """
        self._transit = transit_returns or {}
        self._driving = driving_returns or {}
        self._geocode = geocode_returns or {}

    def geocode(self, address):
        if address in self._geocode:
            return self._geocode[address]
        raise ValueError(f"Geocode not mocked for: {address}")

    def transit_time(self, origin, dest):
        key = self._key(origin, dest)
        val = self._transit.get(key)
        if val is None:
            return 9999  # simulate unreachable
        return val

    def driving_time(self, origin, dest):
        key = self._key(origin, dest)
        val = self._driving.get(key)
        if val is None:
            return 9999
        return val

    @staticmethod
    def _key(origin, dest):
        return f"{origin[0]:.6f},{origin[1]:.6f}|{dest[0]:.6f},{dest[1]:.6f}"


# ── Coordinates for tests ────────────────────────────────────────────────

PROPERTY = (40.9500, -73.8000)          # somewhere in Westchester
GCT = (40.7527, -73.9772)              # Grand Central Terminal
JFK = (40.6413, -73.7781)              # JFK Airport
LGA = (40.7769, -73.8740)              # LaGuardia Airport
EWR = (40.6895, -74.1745)              # Newark Airport
DOWNTOWN = (40.7128, -74.0060)         # Downtown Manhattan
HOSPITAL = (40.7644, -73.9535)         # NY-Presbyterian


class TestVerdictClassification(unittest.TestCase):
    """Verify that _verdict returns stable buckets for known minute values."""

    def test_primary_hub_great(self):
        self.assertEqual(_verdict(30, "primary_hub"), "Great")
        self.assertEqual(_verdict(45, "primary_hub"), "Great")

    def test_primary_hub_ok(self):
        self.assertEqual(_verdict(46, "primary_hub"), "OK")
        self.assertEqual(_verdict(75, "primary_hub"), "OK")

    def test_primary_hub_painful(self):
        self.assertEqual(_verdict(76, "primary_hub"), "Painful")
        self.assertEqual(_verdict(120, "primary_hub"), "Painful")

    def test_airport_great(self):
        self.assertEqual(_verdict(50, "airport"), "Great")
        self.assertEqual(_verdict(60, "airport"), "Great")

    def test_airport_ok(self):
        self.assertEqual(_verdict(61, "airport"), "OK")
        self.assertEqual(_verdict(90, "airport"), "OK")

    def test_airport_painful(self):
        self.assertEqual(_verdict(91, "airport"), "Painful")

    def test_downtown_boundaries(self):
        self.assertEqual(_verdict(40, "downtown"), "Great")
        self.assertEqual(_verdict(41, "downtown"), "OK")
        self.assertEqual(_verdict(70, "downtown"), "OK")
        self.assertEqual(_verdict(71, "downtown"), "Painful")

    def test_hospital_boundaries(self):
        self.assertEqual(_verdict(30, "hospital"), "Great")
        self.assertEqual(_verdict(31, "hospital"), "OK")
        self.assertEqual(_verdict(60, "hospital"), "OK")
        self.assertEqual(_verdict(61, "hospital"), "Painful")

    def test_unknown_category_uses_default(self):
        # Unknown categories fall back to (45, 75) default
        self.assertEqual(_verdict(44, "nonexistent"), "Great")
        self.assertEqual(_verdict(46, "nonexistent"), "OK")
        self.assertEqual(_verdict(76, "nonexistent"), "Painful")


class TestFallbackWhenTransitUnavailable(unittest.TestCase):
    """When transit directions return 9999 (unreachable), the engine must
    fall back to driving and label it explicitly."""

    def setUp(self):
        UrbanAccessEngine.clear_cache()

    def tearDown(self):
        UrbanAccessEngine.clear_cache()

    def test_primary_hub_falls_back_to_driving(self):
        """If transit is unavailable for primary hub, use driving and flag fallback."""
        maps = _FakeMaps(
            geocode_returns={
                "Grand Central Terminal, New York, NY": GCT,
            },
            transit_returns={},   # no transit at all
            driving_returns={
                _FakeMaps._key(PROPERTY, GCT): 55,
            },
        )

        engine = UrbanAccessEngine(maps, *PROPERTY)
        commute = engine.get_primary_hub_commute()

        self.assertIsNotNone(commute)
        self.assertEqual(commute.mode, "driving")
        self.assertTrue(commute.fallback)
        self.assertEqual(commute.time_min, 55)
        self.assertEqual(commute.verdict, "OK")  # 55 min -> OK for primary_hub

    def test_reachability_hub_falls_back_to_driving(self):
        """If transit unavailable for an airport, driving should be used."""
        maps = _FakeMaps(
            geocode_returns={
                "Grand Central Terminal, New York, NY": GCT,
                "JFK Airport, Queens, NY": JFK,
                "LaGuardia Airport, Queens, NY": LGA,
                "Newark Liberty International Airport, Newark, NJ": EWR,
                "Downtown Manhattan, New York, NY": DOWNTOWN,
                "NewYork-Presbyterian Hospital, New York, NY": HOSPITAL,
            },
            transit_returns={},  # no transit routes at all
            driving_returns={
                _FakeMaps._key(PROPERTY, GCT): 50,
                _FakeMaps._key(PROPERTY, JFK): 70,
                _FakeMaps._key(PROPERTY, LGA): 40,
                _FakeMaps._key(PROPERTY, EWR): 80,
                _FakeMaps._key(PROPERTY, DOWNTOWN): 45,
                _FakeMaps._key(PROPERTY, HOSPITAL): 35,
            },
        )

        engine = UrbanAccessEngine(maps, *PROPERTY)
        hubs = engine.get_reachability_hubs()

        self.assertEqual(len(hubs), 3)

        airport = next(h for h in hubs if h.category == "airport")
        self.assertEqual(airport.hub_name, "LaGuardia Airport")
        self.assertEqual(airport.total_time_min, 40)
        self.assertEqual(airport.best_mode, "driving")
        self.assertTrue(airport.fallback)
        self.assertEqual(airport.verdict, "Great")  # 40 <= 60

        downtown = next(h for h in hubs if h.category == "downtown")
        self.assertTrue(downtown.fallback)
        self.assertEqual(downtown.best_mode, "driving")

        hospital = next(h for h in hubs if h.category == "hospital")
        self.assertTrue(hospital.fallback)
        self.assertEqual(hospital.best_mode, "driving")

    def test_transit_preferred_over_driving_when_faster(self):
        """When both modes available, pick the faster one."""
        maps = _FakeMaps(
            geocode_returns={
                "Grand Central Terminal, New York, NY": GCT,
            },
            transit_returns={
                _FakeMaps._key(PROPERTY, GCT): 35,
            },
            driving_returns={
                _FakeMaps._key(PROPERTY, GCT): 50,
            },
        )

        engine = UrbanAccessEngine(maps, *PROPERTY)
        commute = engine.get_primary_hub_commute()

        self.assertIsNotNone(commute)
        self.assertEqual(commute.mode, "transit")
        self.assertFalse(commute.fallback)
        self.assertEqual(commute.time_min, 35)
        self.assertEqual(commute.verdict, "Great")  # 35 <= 45

    def test_driving_preferred_when_faster_than_transit(self):
        """When driving is faster, it should be selected (not a fallback)."""
        maps = _FakeMaps(
            geocode_returns={
                "Grand Central Terminal, New York, NY": GCT,
            },
            transit_returns={
                _FakeMaps._key(PROPERTY, GCT): 80,
            },
            driving_returns={
                _FakeMaps._key(PROPERTY, GCT): 40,
            },
        )

        engine = UrbanAccessEngine(maps, *PROPERTY)
        commute = engine.get_primary_hub_commute()

        self.assertIsNotNone(commute)
        self.assertEqual(commute.mode, "driving")
        self.assertFalse(commute.fallback)  # not a fallback, just faster
        self.assertEqual(commute.time_min, 40)

    def test_full_evaluation_structure(self):
        """Full evaluate() should return all expected fields."""
        maps = _FakeMaps(
            geocode_returns={
                "Grand Central Terminal, New York, NY": GCT,
                "JFK Airport, Queens, NY": JFK,
                "LaGuardia Airport, Queens, NY": LGA,
                "Newark Liberty International Airport, Newark, NJ": EWR,
                "Downtown Manhattan, New York, NY": DOWNTOWN,
                "NewYork-Presbyterian Hospital, New York, NY": HOSPITAL,
            },
            transit_returns={
                _FakeMaps._key(PROPERTY, GCT): 45,
                _FakeMaps._key(PROPERTY, LGA): 55,
                _FakeMaps._key(PROPERTY, DOWNTOWN): 38,
                _FakeMaps._key(PROPERTY, HOSPITAL): 25,
            },
            driving_returns={
                _FakeMaps._key(PROPERTY, GCT): 50,
                _FakeMaps._key(PROPERTY, JFK): 65,
                _FakeMaps._key(PROPERTY, LGA): 60,
                _FakeMaps._key(PROPERTY, EWR): 75,
                _FakeMaps._key(PROPERTY, DOWNTOWN): 50,
                _FakeMaps._key(PROPERTY, HOSPITAL): 30,
            },
        )

        engine = UrbanAccessEngine(maps, *PROPERTY)
        result = engine.evaluate(primary_transit_data={"name": "Test Station"})

        # Primary transit passed through
        self.assertEqual(result.primary_transit, {"name": "Test Station"})

        # Primary hub commute
        self.assertIsNotNone(result.primary_hub_commute)
        self.assertEqual(result.primary_hub_commute.hub_name, "Grand Central Terminal")
        self.assertEqual(result.primary_hub_commute.time_min, 45)
        self.assertEqual(result.primary_hub_commute.mode, "transit")
        self.assertEqual(result.primary_hub_commute.verdict, "Great")

        # Reachability hubs
        self.assertEqual(len(result.reachability_hubs), 3)
        categories = {h.category for h in result.reachability_hubs}
        self.assertEqual(categories, {"airport", "downtown", "hospital"})

    def test_cache_avoids_duplicate_calls(self):
        """Verify that repeated calls to the same destination use the cache."""
        maps = _FakeMaps(
            geocode_returns={
                "Grand Central Terminal, New York, NY": GCT,
            },
            transit_returns={
                _FakeMaps._key(PROPERTY, GCT): 40,
            },
            driving_returns={
                _FakeMaps._key(PROPERTY, GCT): 50,
            },
        )

        engine = UrbanAccessEngine(maps, *PROPERTY)

        # First call populates cache
        commute1 = engine.get_primary_hub_commute()
        # Second call should use cache
        commute2 = engine.get_primary_hub_commute()

        self.assertEqual(commute1.time_min, commute2.time_min)
        self.assertEqual(commute1.mode, commute2.mode)


if __name__ == "__main__":
    unittest.main()
