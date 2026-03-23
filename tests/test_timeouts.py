"""Tests for per-API-call timeout configuration (NES-368)."""

import pytest


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
