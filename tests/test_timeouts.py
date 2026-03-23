"""Tests for per-API-call timeout configuration (NES-368)."""

import pytest
from unittest.mock import patch


class TestGoogleMapsTimeouts:
    """Verify per-endpoint timeout values on GoogleMapsClient."""

    def test_endpoint_timeouts_exist(self):
        from property_evaluator import GoogleMapsClient
        assert hasattr(GoogleMapsClient, '_ENDPOINT_TIMEOUTS')

    def test_geocode_timeout_is_5s(self):
        from property_evaluator import GoogleMapsClient
        assert GoogleMapsClient._ENDPOINT_TIMEOUTS["geocode"] == 5

    def test_place_details_timeout_is_5s(self):
        from property_evaluator import GoogleMapsClient
        assert GoogleMapsClient._ENDPOINT_TIMEOUTS["place_details"] == 5

    def test_distance_matrix_timeout_is_8s(self):
        from property_evaluator import GoogleMapsClient
        assert GoogleMapsClient._ENDPOINT_TIMEOUTS["walking_time"] == 8
        assert GoogleMapsClient._ENDPOINT_TIMEOUTS["driving_time"] == 8
        assert GoogleMapsClient._ENDPOINT_TIMEOUTS["transit_time"] == 8

    def test_places_nearby_timeout_unchanged(self):
        from property_evaluator import GoogleMapsClient
        assert GoogleMapsClient._ENDPOINT_TIMEOUTS["places_nearby"] == 10

    def test_default_timeout_is_fallback(self):
        from property_evaluator import GoogleMapsClient
        assert GoogleMapsClient.DEFAULT_TIMEOUT == 10


class TestWalkScoreTimeouts:
    """Verify WalkScore API timeout values via mock assertions."""

    @patch.dict("os.environ", {"WALKSCORE_API_KEY": "test-key"})
    @patch("property_evaluator.requests.get")
    def test_bike_score_timeout_is_8s(self, mock_get):
        from property_evaluator import get_bike_score
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"status": 1}
        mock_get.return_value.raise_for_status = lambda: None
        get_bike_score("123 Main St", 41.0, -73.7)
        _, kwargs = mock_get.call_args
        assert kwargs["timeout"] == 8

    @patch.dict("os.environ", {"WALKSCORE_API_KEY": "test-key"})
    @patch("property_evaluator.requests.get")
    def test_transit_score_timeout_is_8s(self, mock_get):
        from property_evaluator import get_transit_score
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"status": 1}
        mock_get.return_value.raise_for_status = lambda: None
        get_transit_score("123 Main St", 41.0, -73.7)
        _, kwargs = mock_get.call_args
        assert kwargs["timeout"] == 8

    @patch.dict("os.environ", {"WALKSCORE_API_KEY": "test-key"})
    @patch("property_evaluator.requests.get")
    def test_walk_scores_timeout_is_8s(self, mock_get):
        from property_evaluator import get_walk_scores
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"status": 1}
        mock_get.return_value.raise_for_status = lambda: None
        get_walk_scores("123 Main St", 41.0, -73.7)
        _, kwargs = mock_get.call_args
        assert kwargs["timeout"] == 8


class TestOverpassTimeouts:
    """Verify Overpass API timeout values."""

    def test_overpass_default_timeout_is_10s(self):
        from overpass_http import OverpassHTTPClient
        assert OverpassHTTPClient.DEFAULT_TIMEOUT == 10

    def test_green_space_overpass_timeout(self):
        import inspect
        from green_space import _overpass_query
        source = inspect.getsource(_overpass_query)
        assert "timeout=10" in source

    def test_road_noise_overpass_timeout(self):
        import inspect
        from road_noise import fetch_all_roads
        source = inspect.getsource(fetch_all_roads)
        assert "timeout=10" in source
