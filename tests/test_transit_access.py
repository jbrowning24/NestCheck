"""Tests for the smart transit frequency approximation heuristic.

Uses mocked Google Maps API responses so no network calls are needed.
"""

import unittest
from unittest.mock import MagicMock, patch

from property_evaluator import (
    evaluate_transit_access,
    _classify_mode,
    _score_from_thresholds,
    GoogleMapsClient,
    DENSITY_THRESHOLDS,
    WALK_NODE_THRESHOLDS,
    REVIEW_THRESHOLDS,
)


def _make_place(name, place_id, types, lat, lng, user_ratings_total=100):
    """Helper to create a fake Google Places result dict."""
    return {
        "name": name,
        "place_id": place_id,
        "types": types,
        "geometry": {"location": {"lat": lat, "lng": lng}},
        "user_ratings_total": user_ratings_total,
    }


class TestClassifyMode(unittest.TestCase):
    """Test mode classification from Place types and name keywords."""

    def test_subway_station_type(self):
        place = _make_place("34 St – Penn Station", "a", ["subway_station", "transit_station"], 40.75, -73.99)
        self.assertEqual(_classify_mode(place), "Subway")

    def test_subway_keyword_in_name(self):
        place = _make_place("Metro Center", "b", ["transit_station"], 38.89, -77.02)
        self.assertEqual(_classify_mode(place), "Subway")

    def test_train_station_type(self):
        place = _make_place("Grand Central Terminal", "c", ["train_station"], 40.75, -73.97)
        self.assertEqual(_classify_mode(place), "Train")

    def test_commuter_rail_keyword(self):
        place = _make_place("Metro-North Scarsdale", "d", ["train_station"], 40.99, -73.77)
        self.assertEqual(_classify_mode(place), "Commuter Rail")

    def test_bus_station_type(self):
        place = _make_place("Main St Bus Terminal", "e", ["bus_station"], 40.0, -74.0)
        self.assertEqual(_classify_mode(place), "Bus")

    def test_light_rail_type(self):
        place = _make_place("Baypointe Light Rail", "f", ["light_rail_station"], 37.4, -121.9)
        self.assertEqual(_classify_mode(place), "Light Rail")

    def test_ferry_keyword(self):
        place = _make_place("Staten Island Ferry Terminal", "g", ["transit_station"], 40.64, -74.07)
        self.assertEqual(_classify_mode(place), "Ferry")

    def test_generic_transit_defaults_to_train(self):
        place = _make_place("Union Station", "h", ["transit_station"], 34.05, -118.23)
        self.assertEqual(_classify_mode(place), "Train")


class TestScoreFromThresholds(unittest.TestCase):
    """Test the generic threshold scoring helper."""

    def test_density_thresholds(self):
        self.assertEqual(_score_from_thresholds(10, DENSITY_THRESHOLDS), 3)
        self.assertEqual(_score_from_thresholds(6, DENSITY_THRESHOLDS), 3)
        self.assertEqual(_score_from_thresholds(4, DENSITY_THRESHOLDS), 2)
        self.assertEqual(_score_from_thresholds(3, DENSITY_THRESHOLDS), 2)
        self.assertEqual(_score_from_thresholds(1, DENSITY_THRESHOLDS), 1)
        self.assertEqual(_score_from_thresholds(0, DENSITY_THRESHOLDS), 0)

    def test_review_thresholds(self):
        self.assertEqual(_score_from_thresholds(10000, REVIEW_THRESHOLDS), 2)
        self.assertEqual(_score_from_thresholds(5000, REVIEW_THRESHOLDS), 2)
        self.assertEqual(_score_from_thresholds(2000, REVIEW_THRESHOLDS), 1)
        self.assertEqual(_score_from_thresholds(500, REVIEW_THRESHOLDS), 0)


class TestEvaluateTransitAccess(unittest.TestCase):
    """Integration-style smoke tests with mocked GoogleMapsClient."""

    def _mock_client(self, nearby_results, walk_time=5):
        """Return a GoogleMapsClient mock with pre-set nearby and walk responses."""
        client = MagicMock(spec=GoogleMapsClient)
        client.places_nearby.return_value = nearby_results
        # evaluate_transit_access calls walking_time() per-node in a loop
        client.walking_time.return_value = walk_time
        return client

    def test_high_frequency_dense_subway(self):
        """Dense subway area should score High."""
        nodes = [
            _make_place("Times Sq – 42 St", "a1", ["subway_station"], 40.755, -73.987, user_ratings_total=8000),
            _make_place("42 St – Bryant Park", "a2", ["subway_station"], 40.754, -73.984, user_ratings_total=6000),
            _make_place("34 St – Herald Sq", "a3", ["subway_station"], 40.749, -73.988, user_ratings_total=7000),
            _make_place("49 St", "a4", ["subway_station"], 40.760, -73.984, user_ratings_total=3000),
            _make_place("47-50 Sts – Rockefeller", "a5", ["subway_station"], 40.759, -73.981, user_ratings_total=5000),
            _make_place("50 St", "a6", ["subway_station"], 40.762, -73.986, user_ratings_total=2000),
        ]
        client = self._mock_client(nodes, walk_time=4)
        result = evaluate_transit_access(client, 40.755, -73.987)

        self.assertEqual(result.primary_stop, "Times Sq – 42 St")
        self.assertEqual(result.mode, "Subway")
        self.assertEqual(result.frequency_bucket, "High")
        self.assertGreaterEqual(result.score_0_10, 8)
        self.assertTrue(len(result.reasons) >= 4)

    def test_low_frequency_single_bus_stop(self):
        """Single bus stop with few reviews should score Low or Very low."""
        nodes = [
            _make_place("Route 9 Bus Stop", "b1", ["bus_station"], 41.0, -73.8, user_ratings_total=50),
        ]
        client = self._mock_client(nodes, walk_time=12)
        result = evaluate_transit_access(client, 41.0, -73.8)

        self.assertEqual(result.mode, "Bus")
        self.assertIn(result.frequency_bucket, ("Low", "Very low"))
        self.assertLessEqual(result.score_0_10, 4)

    def test_no_transit_nodes_returns_zero(self):
        """When no transit nodes are found, result should be score 0."""
        client = self._mock_client([], walk_time=9999)
        result = evaluate_transit_access(client, 35.0, -110.0)

        self.assertIsNone(result.primary_stop)
        self.assertEqual(result.score_0_10, 0)
        self.assertEqual(result.frequency_bucket, "Very low")
        self.assertIn("No transit stations found", result.reasons[0])

    def test_medium_frequency_moderate_area(self):
        """A few train stations with moderate reviews should score Medium."""
        nodes = [
            _make_place("Scarsdale Metro-North Station", "c1", ["train_station"], 40.99, -73.77, user_ratings_total=1200),
            _make_place("Hartsdale Metro-North Station", "c2", ["train_station"], 41.01, -73.80, user_ratings_total=800),
            _make_place("Crestwood Metro-North Station", "c3", ["train_station"], 40.96, -73.82, user_ratings_total=600),
        ]
        client = self._mock_client(nodes, walk_time=8)
        result = evaluate_transit_access(client, 40.99, -73.77)

        self.assertEqual(result.mode, "Commuter Rail")
        self.assertIn(result.frequency_bucket, ("Medium", "High"))
        self.assertGreaterEqual(result.score_0_10, 5)

    def test_reasons_list_not_empty(self):
        """Reasons should always be populated when transit is found."""
        nodes = [
            _make_place("Test Station", "d1", ["transit_station"], 40.0, -74.0, user_ratings_total=500),
        ]
        client = self._mock_client(nodes, walk_time=10)
        result = evaluate_transit_access(client, 40.0, -74.0)

        self.assertGreater(len(result.reasons), 0)
        # Check that reasons mention the key signals
        reasons_text = " ".join(result.reasons)
        self.assertIn("Mode:", reasons_text)
        self.assertIn("Density:", reasons_text)
        self.assertIn("Walk-reachable:", reasons_text)
        self.assertIn("Foot traffic proxy:", reasons_text)


if __name__ == "__main__":
    unittest.main()
