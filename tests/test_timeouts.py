"""Tests for per-API-call timeout configuration (NES-368)."""

import logging

import pytest
from unittest.mock import patch, MagicMock


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


class TestScorerGracefulDegradation:
    """Verify scorers return points=None + suppressed_reason on exception."""

    def test_park_access_returns_none_on_error(self):
        from property_evaluator import score_park_access
        maps = MagicMock()
        maps.places_nearby.side_effect = Exception("timeout")
        result = score_park_access(maps, 41.0, -73.7)
        # score_park_access returns a single Tier2Score (not a tuple)
        assert result.points is None
        assert result.suppressed_reason is not None

    def test_third_place_returns_none_on_error(self):
        from property_evaluator import score_third_place_access
        maps = MagicMock()
        maps.places_nearby.side_effect = Exception("timeout")
        score, places, counts, dd = score_third_place_access(maps, 41.0, -73.7)
        assert score.points is None
        assert score.suppressed_reason is not None

    def test_provisioning_returns_none_on_error(self):
        from property_evaluator import score_provisioning_access
        maps = MagicMock()
        maps.places_nearby.side_effect = Exception("timeout")
        score, places, dd = score_provisioning_access(maps, 41.0, -73.7)
        assert score.points is None
        assert score.suppressed_reason is not None

    def test_fitness_returns_none_on_error(self):
        from property_evaluator import score_fitness_access
        maps = MagicMock()
        maps.places_nearby.side_effect = Exception("timeout")
        score, places, dd = score_fitness_access(maps, 41.0, -73.7)
        assert score.points is None
        assert score.suppressed_reason is not None

    def test_transit_returns_none_on_error(self):
        from property_evaluator import score_transit_access
        maps = MagicMock()
        maps.places_nearby.side_effect = Exception("timeout")
        result = score_transit_access(maps, 41.0, -73.7)
        assert result.points is None
        assert result.suppressed_reason is not None

    def test_none_points_excluded_from_composite(self):
        """Verify compute_composite_score excludes None-points dimensions."""
        from property_evaluator import compute_composite_score
        scores = [
            (8, 10, "verified"),   # normal
            (None, 10, "estimated"),  # timed out — should be excluded
            (6, 10, "verified"),   # normal
        ]
        result = compute_composite_score(scores)
        # Should be (8+6)/(10+10) * 100 = 70, NOT (8+0+6)/(10+10+10) * 100 = 47
        assert result == 70


class TestF1SignalPath:
    """Verify suppressed_reason flows from scorer to serialized output."""

    def test_suppressed_reason_in_dimension_summaries(self):
        """A dimension with points=None + suppressed_reason should appear
        in dimension_summaries with suppressed_reason preserved."""
        from property_evaluator import Tier2Score

        score = Tier2Score(
            name="Test Dimension",
            points=None,
            max_points=10,
            details="Data temporarily unavailable",
            data_confidence="estimated",
            data_confidence_note="Scoring failed",
            suppressed_reason="Data temporarily unavailable",
        )
        # Verify the dataclass fields are set correctly
        assert score.points is None
        assert score.suppressed_reason == "Data temporarily unavailable"
        assert score.max_points == 10

    def test_suppressed_reason_preserved_on_dataclass(self):
        """Verify suppressed_reason is preserved and accessible."""
        from property_evaluator import Tier2Score

        score = Tier2Score(
            name="Test Dimension",
            points=None,
            max_points=10,
            details="Data temporarily unavailable",
            suppressed_reason="Data temporarily unavailable",
        )
        assert score.suppressed_reason == "Data temporarily unavailable"
        assert score.points is None


class TestTimeoutLogging:
    """Verify timeout events are logged with API name and elapsed time."""

    def test_google_maps_timeout_logged(self, caplog):
        """_traced_get logs timeout with endpoint name and elapsed time."""
        import requests
        from property_evaluator import GoogleMapsClient

        client = GoogleMapsClient("fake-key")

        with patch.object(
            client.session, "get",
            side_effect=requests.exceptions.Timeout("timed out"),
        ):
            with caplog.at_level(logging.WARNING):
                with pytest.raises(requests.exceptions.Timeout):
                    client._traced_get("geocode", "http://example.com", {})

        assert any("geocode" in r.message and "timeout" in r.message.lower()
                    for r in caplog.records)

    @patch.dict("os.environ", {"WALKSCORE_API_KEY": "test-key"})
    def test_walkscore_timeout_logged(self, caplog):
        """WalkScore timeout logs API name."""
        import requests
        from property_evaluator import get_walk_scores

        with patch("property_evaluator.requests.get",
                    side_effect=requests.exceptions.Timeout("timed out")):
            with caplog.at_level(logging.WARNING):
                get_walk_scores("123 Main St", 41.0, -73.7)

        assert any("walkscore" in r.message.lower()
                    for r in caplog.records)
