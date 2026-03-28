"""Tests for canopy.py — NLCD tree canopy cover module."""

import json
import math
import pytest
from unittest.mock import patch, MagicMock

from scoring_config import CANOPY_NATURE_FEEL_KNOTS, apply_piecewise


# ---------------------------------------------------------------------------
# Piecewise scoring tests (no mocking needed)
# ---------------------------------------------------------------------------

class TestCanopyPiecewiseScoring:
    """Test apply_piecewise with CANOPY_NATURE_FEEL_KNOTS."""

    def test_below_first_knot(self):
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 0) == 0.0
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 3) == 0.0

    def test_at_knot_boundaries(self):
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 5) == 0.0
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 15) == 0.5
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 25) == 1.0
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 40) == 1.5
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 55) == 2.0

    def test_interpolation(self):
        assert abs(apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 10) - 0.25) < 0.01

    def test_above_last_knot(self):
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 80) == 2.0
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 100) == 2.0

    def test_monotonicity(self):
        prev = -1.0
        for pct in range(0, 101, 5):
            score = apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, pct)
            assert score >= prev, f"Non-monotonic at {pct}%: {score} < {prev}"
            prev = score


# ---------------------------------------------------------------------------
# Grid generation tests
# ---------------------------------------------------------------------------

class TestGridGeneration:

    def test_grid_count(self):
        from canopy import _generate_sample_grid
        points = _generate_sample_grid(40.78, -73.97, 500)
        assert 15 <= len(points) <= 30

    def test_points_within_buffer(self):
        from canopy import _generate_sample_grid
        lat, lng = 40.78, -73.97
        buffer_m = 500
        points = _generate_sample_grid(lat, lng, buffer_m)
        for plat, plng in points:
            dlat = math.radians(plat - lat)
            dlng = math.radians(plng - lng)
            a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(plat)) * math.sin(dlng / 2) ** 2
            dist_m = 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            assert dist_m <= buffer_m * 1.1, f"Point ({plat}, {plng}) is {dist_m:.0f}m from center"

    def test_latitude_correction(self):
        from canopy import _generate_sample_grid
        equator_pts = _generate_sample_grid(0.0, -73.97, 500)
        high_lat_pts = _generate_sample_grid(60.0, -73.97, 500)
        eq_lngs = [p[1] for p in equator_pts]
        hi_lngs = [p[1] for p in high_lat_pts]
        eq_range = max(eq_lngs) - min(eq_lngs)
        hi_range = max(hi_lngs) - min(hi_lngs)
        assert hi_range > eq_range * 1.5


# ---------------------------------------------------------------------------
# WMS query + caching tests (mocked)
# ---------------------------------------------------------------------------

class TestGetCanopyCover:

    def _mock_wms_response(self, canopy_pct):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"PALETTE_INDEX": canopy_pct},
            }],
        }
        return resp

    @patch("canopy.requests.get")
    @patch("canopy.get_canopy_cache", return_value=None)
    @patch("canopy.set_canopy_cache")
    def test_basic_query(self, mock_set, mock_get_cache, mock_requests_get):
        from canopy import get_canopy_cover
        mock_requests_get.return_value = self._mock_wms_response(42)

        result = get_canopy_cover(40.78, -73.97)

        assert result is not None
        assert result.canopy_pct == 42.0
        assert result.sample_count > 0
        assert result.buffer_m == 500
        assert result.source == "nlcd_2021"
        assert mock_set.called

    @patch("canopy.get_canopy_cache")
    def test_cache_hit(self, mock_get_cache):
        from canopy import get_canopy_cover
        mock_get_cache.return_value = json.dumps({
            "canopy_pct": 35.5,
            "sample_count": 25,
            "buffer_m": 500,
            "source": "nlcd_2021",
        })

        result = get_canopy_cover(40.78, -73.97)

        assert result is not None
        assert result.canopy_pct == 35.5

    @patch("canopy.requests.get", side_effect=Exception("Connection refused"))
    @patch("canopy.get_canopy_cache", return_value=None)
    def test_endpoint_failure_returns_none(self, mock_get_cache, mock_requests_get):
        from canopy import get_canopy_cover
        result = get_canopy_cover(40.78, -73.97)
        assert result is None

    @patch("canopy.requests.get")
    @patch("canopy.get_canopy_cache", return_value=None)
    @patch("canopy.set_canopy_cache")
    def test_mixed_valid_invalid_samples(self, mock_set, mock_get_cache, mock_requests_get):
        from canopy import get_canopy_cover

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {"type": "FeatureCollection", "features": []}
                return resp
            return self._mock_wms_response(30)

        mock_requests_get.side_effect = side_effect

        result = get_canopy_cover(40.78, -73.97)
        assert result is not None
        assert result.canopy_pct == 30.0
        assert result.sample_count < 25
