"""Unit tests for overpass_http.py — coordinated Overpass API HTTP layer.

Tests cover: cache integration, rate limiting, retry logic, error classification,
response parsing, and trace recording.
"""

import json
import time
from unittest.mock import patch, MagicMock

import pytest
import requests

from overpass_http import (
    OverpassHTTPClient,
    OverpassRateLimitError,
    OverpassQueryError,
    overpass_query,
)


# =========================================================================
# Helpers
# =========================================================================

def _mock_response(status_code=200, json_data=None, text=""):
    """Create a mock requests.Response object."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# =========================================================================
# Cache integration
# =========================================================================

class TestCacheIntegration:
    @patch("overpass_http.get_overpass_cache")
    def test_cache_hit_returns_cached_data(self, mock_cache):
        mock_cache.return_value = '{"elements": [{"id": 1}]}'

        client = OverpassHTTPClient()
        result = client.query("[out:json];node(1);out;", caller="test")

        assert result == {"elements": [{"id": 1}]}
        mock_cache.assert_called_once()

    @patch("overpass_http.set_overpass_cache")
    @patch("overpass_http.get_overpass_cache", return_value=None)
    def test_cache_miss_fetches_and_caches(self, mock_get, mock_set):
        client = OverpassHTTPClient()

        mock_resp = _mock_response(200, {"elements": []})
        with patch.object(requests.Session, "post", return_value=mock_resp):
            result = client.query("[out:json];node(1);out;", caller="test")

        assert result == {"elements": []}
        mock_set.assert_called_once()

    @patch("overpass_http.get_overpass_cache")
    def test_corrupted_cache_falls_through(self, mock_cache):
        mock_cache.return_value = "not valid json{{"

        client = OverpassHTTPClient()
        mock_resp = _mock_response(200, {"elements": []})
        with patch.object(requests.Session, "post", return_value=mock_resp):
            result = client.query("[out:json];node(1);out;", caller="test")

        assert result == {"elements": []}


# =========================================================================
# HTTP error handling
# =========================================================================

class TestHTTPErrors:
    @patch("overpass_http.get_overpass_cache_stale", return_value=None)
    @patch("overpass_http.get_overpass_cache", return_value=None)
    def test_429_raises_rate_limit_error(self, mock_cache, mock_stale):
        client = OverpassHTTPClient()
        client.MAX_RETRIES = 0  # no retries for this test

        mock_resp = _mock_response(429)
        with patch.object(requests.Session, "post", return_value=mock_resp):
            with pytest.raises(OverpassRateLimitError):
                client.query("test query", caller="test")

    @patch("overpass_http.get_overpass_cache_stale", return_value=None)
    @patch("overpass_http.get_overpass_cache", return_value=None)
    def test_504_raises_query_error(self, mock_cache, mock_stale):
        client = OverpassHTTPClient()
        client.MAX_RETRIES = 0

        mock_resp = _mock_response(504)
        with patch.object(requests.Session, "post", return_value=mock_resp):
            with pytest.raises(OverpassQueryError, match="504"):
                client.query("test query", caller="test")

    @patch("overpass_http.get_overpass_cache_stale", return_value=None)
    @patch("overpass_http.get_overpass_cache", return_value=None)
    def test_400_raises_query_error(self, mock_cache, mock_stale):
        client = OverpassHTTPClient()
        client.MAX_RETRIES = 0

        mock_resp = _mock_response(400)
        with patch.object(requests.Session, "post", return_value=mock_resp):
            with pytest.raises(OverpassQueryError, match="400"):
                client.query("test query", caller="test")

    @patch("overpass_http.get_overpass_cache_stale", return_value=None)
    @patch("overpass_http.get_overpass_cache", return_value=None)
    def test_non_json_response_raises(self, mock_cache, mock_stale):
        client = OverpassHTTPClient()
        client.MAX_RETRIES = 0

        mock_resp = _mock_response(200, json_data=None, text="<html>error</html>")
        with patch.object(requests.Session, "post", return_value=mock_resp):
            with pytest.raises(OverpassQueryError, match="non-JSON"):
                client.query("test query", caller="test")

    @patch("overpass_http.get_overpass_cache_stale", return_value=None)
    @patch("overpass_http.get_overpass_cache", return_value=None)
    def test_timeout_raises_query_error(self, mock_cache, mock_stale):
        client = OverpassHTTPClient()
        client.MAX_RETRIES = 0

        with patch.object(
            requests.Session, "post", side_effect=requests.exceptions.Timeout("timed out")
        ):
            with pytest.raises(OverpassQueryError, match="timeout"):
                client.query("test query", caller="test")


# =========================================================================
# Response body error detection
# =========================================================================

class TestResponseBodyErrors:
    @patch("overpass_http.get_overpass_cache_stale", return_value=None)
    @patch("overpass_http.get_overpass_cache", return_value=None)
    def test_rate_limit_in_body(self, mock_cache, mock_stale):
        client = OverpassHTTPClient()
        client.MAX_RETRIES = 0

        body = {"osm3s": {"remark": "Too many requests"}, "elements": []}
        mock_resp = _mock_response(200, body)
        with patch.object(requests.Session, "post", return_value=mock_resp):
            with pytest.raises(OverpassRateLimitError):
                client.query("test query", caller="test")

    @patch("overpass_http.get_overpass_cache_stale", return_value=None)
    @patch("overpass_http.get_overpass_cache", return_value=None)
    def test_runtime_error_in_body(self, mock_cache, mock_stale):
        client = OverpassHTTPClient()
        client.MAX_RETRIES = 0

        body = {"remark": "runtime error: Query timed out", "elements": []}
        mock_resp = _mock_response(200, body)
        with patch.object(requests.Session, "post", return_value=mock_resp):
            with pytest.raises(OverpassQueryError, match="server error"):
                client.query("test query", caller="test")


# =========================================================================
# Retry logic
# =========================================================================

class TestRetryLogic:
    @patch("overpass_http.get_overpass_cache", return_value=None)
    @patch("overpass_http.time.sleep")
    def test_retries_on_rate_limit(self, mock_sleep, mock_cache):
        client = OverpassHTTPClient()
        client.MAX_RETRIES = 2

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return _mock_response(429)
            return _mock_response(200, {"elements": []})

        with patch.object(requests.Session, "post", side_effect=side_effect):
            result = client.query("test query", caller="test")

        assert result == {"elements": []}
        assert call_count == 3
        assert mock_sleep.call_count >= 2  # rate limiter + retry backoff sleeps

    @patch("overpass_http.get_overpass_cache_stale", return_value=None)
    @patch("overpass_http.get_overpass_cache", return_value=None)
    @patch("overpass_http.time.sleep")
    def test_exhausts_retries_and_raises(self, mock_sleep, mock_cache, mock_stale):
        client = OverpassHTTPClient()
        client.MAX_RETRIES = 1

        mock_resp = _mock_response(429)
        with patch.object(requests.Session, "post", return_value=mock_resp):
            with pytest.raises(OverpassRateLimitError):
                client.query("test query", caller="test")

    @patch("overpass_http.get_overpass_cache_stale")
    @patch("overpass_http.get_overpass_cache", return_value=None)
    @patch("overpass_http.time.sleep")
    def test_stale_cache_fallback_when_http_fails(self, mock_sleep, mock_cache, mock_stale):
        """When HTTP fails and no fresh cache, serve stale cache if available."""
        stale_json = '{"elements": [{"id": 1, "type": "way"}], "version": 0.6}'
        mock_stale.return_value = (stale_json, "2024-01-15T12:00:00+00:00")

        client = OverpassHTTPClient()
        client.MAX_RETRIES = 0

        mock_resp = _mock_response(504)
        with patch.object(requests.Session, "post", return_value=mock_resp):
            result = client.query("test query", caller="test")

        assert result["elements"] == [{"id": 1, "type": "way"}]
        assert result["_stale"] is True
        assert result["_stale_created_at"] == "2024-01-15T12:00:00+00:00"

    @patch("overpass_http.get_overpass_cache_stale")
    @patch("overpass_http.get_overpass_cache", return_value=None)
    @patch("overpass_http.time.sleep")
    def test_400_does_not_fall_back_to_stale_cache(self, mock_sleep, mock_cache, mock_stale):
        """Non-retryable client errors (400) must propagate, not serve stale data."""
        mock_stale.return_value = ('{"elements": []}', "2024-01-15T12:00:00+00:00")

        client = OverpassHTTPClient()
        client.MAX_RETRIES = 0

        mock_resp = _mock_response(400)
        with patch.object(requests.Session, "post", return_value=mock_resp):
            with pytest.raises(OverpassQueryError, match="400"):
                client.query("test query", caller="test")

        mock_stale.assert_not_called()

    @patch("overpass_http.get_overpass_cache_stale")
    @patch("overpass_http.get_overpass_cache", return_value=None)
    @patch("overpass_http.time.sleep")
    def test_corrupted_stale_cache_reraises_original(self, mock_sleep, mock_cache, mock_stale):
        """Corrupted stale cache entry should re-raise the original HTTP error."""
        mock_stale.return_value = ("not valid json{{", "2024-01-01T00:00:00+00:00")

        client = OverpassHTTPClient()
        client.MAX_RETRIES = 0

        mock_resp = _mock_response(504)
        with patch.object(requests.Session, "post", return_value=mock_resp):
            with pytest.raises(OverpassQueryError, match="504"):
                client.query("test query", caller="test")


# =========================================================================
# Retryable error classification
# =========================================================================

class TestIsRetryableError:
    def test_timeout_is_retryable(self):
        e = OverpassQueryError("Overpass request timeout after 30s")
        assert OverpassHTTPClient._is_retryable_error(e) is True

    def test_server_error_is_retryable(self):
        e = OverpassQueryError("Overpass server error in response body: something")
        assert OverpassHTTPClient._is_retryable_error(e) is True

    def test_504_is_retryable(self):
        e = OverpassQueryError("Overpass HTTP 504 [caller=test]")
        assert OverpassHTTPClient._is_retryable_error(e) is True

    def test_400_is_not_retryable(self):
        e = OverpassQueryError("Overpass HTTP 400 [caller=test]")
        assert OverpassHTTPClient._is_retryable_error(e) is False

    def test_parse_error_is_not_retryable(self):
        e = OverpassQueryError("non-JSON response")
        assert OverpassHTTPClient._is_retryable_error(e) is False


# =========================================================================
# Module-level convenience function
# =========================================================================

class TestModuleLevelFunction:
    @patch("overpass_http._client")
    def test_delegates_to_client(self, mock_client):
        mock_client.query.return_value = {"elements": []}
        result = overpass_query("[out:json];", caller="test", timeout=10)

        assert result == {"elements": []}
        mock_client.query.assert_called_once_with(
            "[out:json];", caller="test", timeout=10, ttl_days=None
        )
