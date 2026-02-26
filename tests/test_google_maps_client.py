"""Tests for GoogleMapsClient, focusing on batch Distance Matrix chunking.

The _distance_matrix_batch method auto-chunks at 25 destinations per request.
An off-by-one error could silently misalign walk times with their destinations.
"""

from unittest.mock import MagicMock, patch

import pytest

from property_evaluator import GoogleMapsClient


def _ok_matrix_response(durations_seconds):
    """Build a Distance Matrix API response with given durations."""
    elements = []
    for d in durations_seconds:
        if d is None:
            elements.append({"status": "NOT_FOUND"})
        else:
            elements.append({"status": "OK", "duration": {"value": d}})
    return {
        "status": "OK",
        "rows": [{"elements": elements}],
    }


def _error_response():
    return {"status": "REQUEST_DENIED"}


class TestDistanceMatrixBatch:
    """Tests for _distance_matrix_batch chunking logic."""

    def _make_client(self):
        client = GoogleMapsClient.__new__(GoogleMapsClient)
        client.api_key = "fake-key"
        client.base_url = "https://maps.googleapis.com/maps/api"
        return client

    def test_empty_destinations(self):
        client = self._make_client()
        result = client._distance_matrix_batch((40.0, -74.0), [], "walking", "test")
        assert result == []

    def test_single_destination(self):
        client = self._make_client()
        client._traced_get = MagicMock(return_value=_ok_matrix_response([600]))
        result = client._distance_matrix_batch(
            (40.0, -74.0),
            [(40.01, -74.01)],
            "walking",
            "test",
        )
        assert result == [10]  # 600 seconds = 10 minutes
        assert client._traced_get.call_count == 1

    def test_25_destinations_single_chunk(self):
        client = self._make_client()
        durations = [i * 60 for i in range(25)]  # 0, 60, 120, ... 1440 seconds
        client._traced_get = MagicMock(return_value=_ok_matrix_response(durations))
        dests = [(40.0 + i * 0.001, -74.0) for i in range(25)]
        result = client._distance_matrix_batch((40.0, -74.0), dests, "walking", "test")
        assert len(result) == 25
        assert client._traced_get.call_count == 1
        assert result[0] == 0
        assert result[24] == 24  # 1440 // 60

    def test_26_destinations_two_chunks(self):
        client = self._make_client()
        first_chunk = [i * 60 for i in range(25)]
        second_chunk = [1500]  # 25 minutes

        call_count = [0]
        def mock_traced_get(name, url, params):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return _ok_matrix_response(first_chunk)
            return _ok_matrix_response(second_chunk)

        client._traced_get = mock_traced_get
        dests = [(40.0 + i * 0.001, -74.0) for i in range(26)]
        result = client._distance_matrix_batch((40.0, -74.0), dests, "walking", "test")
        assert len(result) == 26
        assert result[24] == 24  # Last of first chunk
        assert result[25] == 25  # First of second chunk

    def test_unreachable_destination_returns_9999(self):
        client = self._make_client()
        client._traced_get = MagicMock(
            return_value=_ok_matrix_response([600, None, 300])
        )
        dests = [(40.01, -74.01), (50.0, -80.0), (40.02, -74.02)]
        result = client._distance_matrix_batch((40.0, -74.0), dests, "walking", "test")
        assert result[0] == 10
        assert result[1] == 9999
        assert result[2] == 5

    def test_api_error_fills_9999(self):
        client = self._make_client()
        client._traced_get = MagicMock(return_value=_error_response())
        dests = [(40.01, -74.01), (40.02, -74.02)]
        result = client._distance_matrix_batch((40.0, -74.0), dests, "walking", "test")
        assert result == [9999, 9999]

    def test_50_destinations_two_chunks(self):
        client = self._make_client()
        chunk1 = [120] * 25  # 2 min each
        chunk2 = [240] * 25  # 4 min each

        call_count = [0]
        def mock_traced_get(name, url, params):
            idx = call_count[0]
            call_count[0] += 1
            if idx == 0:
                return _ok_matrix_response(chunk1)
            return _ok_matrix_response(chunk2)

        client._traced_get = mock_traced_get
        dests = [(40.0 + i * 0.001, -74.0) for i in range(50)]
        result = client._distance_matrix_batch((40.0, -74.0), dests, "walking", "test")
        assert len(result) == 50
        assert all(r == 2 for r in result[:25])
        assert all(r == 4 for r in result[25:])


class TestWalkingTimesBatch:
    def test_delegates_to_batch(self):
        client = GoogleMapsClient.__new__(GoogleMapsClient)
        client.api_key = "fake"
        client.base_url = "https://maps.googleapis.com/maps/api"
        client._traced_get = MagicMock(return_value=_ok_matrix_response([300, 600]))
        result = client.walking_times_batch(
            (40.0, -74.0),
            [(40.01, -74.01), (40.02, -74.02)],
        )
        assert result == [5, 10]


class TestDrivingTimesBatch:
    def test_delegates_to_batch(self):
        client = GoogleMapsClient.__new__(GoogleMapsClient)
        client.api_key = "fake"
        client.base_url = "https://maps.googleapis.com/maps/api"
        client._traced_get = MagicMock(return_value=_ok_matrix_response([600]))
        result = client.driving_times_batch((40.0, -74.0), [(40.01, -74.01)])
        assert result == [10]


class TestGeocode:
    def test_successful_geocode(self):
        client = GoogleMapsClient.__new__(GoogleMapsClient)
        client.api_key = "fake"
        client.base_url = "https://maps.googleapis.com/maps/api"
        client._traced_get = MagicMock(return_value={
            "status": "OK",
            "results": [{
                "geometry": {"location": {"lat": 40.7128, "lng": -74.0060}},
                "place_id": "ChIJ123",
                "formatted_address": "New York, NY",
            }],
        })
        lat, lng = client.geocode("New York, NY")
        assert lat == 40.7128
        assert lng == -74.0060

    def test_geocode_failure_raises(self):
        client = GoogleMapsClient.__new__(GoogleMapsClient)
        client.api_key = "fake"
        client.base_url = "https://maps.googleapis.com/maps/api"
        client._traced_get = MagicMock(return_value={"status": "ZERO_RESULTS"})
        with pytest.raises(ValueError, match="Geocoding failed"):
            client.geocode("xyznonexistent")


class TestPlacesNearby:
    def test_returns_results(self):
        client = GoogleMapsClient.__new__(GoogleMapsClient)
        client.api_key = "fake"
        client.base_url = "https://maps.googleapis.com/maps/api"
        places = [{"name": "Park A"}, {"name": "Park B"}]
        client._traced_get = MagicMock(return_value={"status": "OK", "results": places})
        result = client.places_nearby(40.0, -74.0, "park")
        assert len(result) == 2

    def test_zero_results_returns_empty(self):
        client = GoogleMapsClient.__new__(GoogleMapsClient)
        client.api_key = "fake"
        client.base_url = "https://maps.googleapis.com/maps/api"
        client._traced_get = MagicMock(return_value={"status": "ZERO_RESULTS"})
        result = client.places_nearby(40.0, -74.0, "park")
        assert result == []

    def test_error_status_raises(self):
        client = GoogleMapsClient.__new__(GoogleMapsClient)
        client.api_key = "fake"
        client.base_url = "https://maps.googleapis.com/maps/api"
        client._traced_get = MagicMock(return_value={"status": "REQUEST_DENIED"})
        with pytest.raises(ValueError, match="Places API failed"):
            client.places_nearby(40.0, -74.0, "park")


class TestWalkingTime:
    def test_returns_minutes(self):
        client = GoogleMapsClient.__new__(GoogleMapsClient)
        client.api_key = "fake"
        client.base_url = "https://maps.googleapis.com/maps/api"
        client._traced_get = MagicMock(return_value={
            "status": "OK",
            "rows": [{"elements": [{"status": "OK", "duration": {"value": 900}}]}],
        })
        result = client.walking_time((40.0, -74.0), (40.01, -74.01))
        assert result == 15  # 900 // 60

    def test_unreachable_returns_9999(self):
        client = GoogleMapsClient.__new__(GoogleMapsClient)
        client.api_key = "fake"
        client.base_url = "https://maps.googleapis.com/maps/api"
        client._traced_get = MagicMock(return_value={
            "status": "OK",
            "rows": [{"elements": [{"status": "NOT_FOUND"}]}],
        })
        result = client.walking_time((40.0, -74.0), (50.0, 10.0))
        assert result == 9999
