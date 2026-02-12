"""
Tests for map_generator (static neighborhood map).

Uses mocked OSM tile requests so no network calls are needed.
Run with: python -m pytest test_map_generator.py -v
         or python -m unittest test_map_generator -v
"""

import base64
import struct
import zlib
import unittest
from unittest.mock import patch

from staticmap import CircleMarker

from map_generator import (
    generate_neighborhood_map,
    _has_other_markers,
    NestCheckStaticMap,
)


def _make_tile_png():
    """Minimal 256x256 single-color PNG for mocking OSM tiles (no PIL needed)."""
    def chunk(name, data):
        return struct.pack("!I", len(data)) + name + data + struct.pack(
            "!I", zlib.crc32(name + data) & 0xFFFFFFFF
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(
        "!IIBBBBB", 256, 256, 8, 2, 0, 0, 0
    )  # 8-bit RGB
    raw = b"".join(
        b"\x00" + b"\x00" * (256 * 3) for _ in range(256)
    )  # 256 rows of RGB
    idat = chunk(b"IDAT", zlib.compress(raw))
    return sig + chunk(b"IHDR", ihdr) + idat + chunk(b"IEND", b"")


def _mock_requests_get():
    """Patch requests.get to return a valid tile PNG."""

    class FakeResponse:
        status_code = 200

        def __init__(self):
            self.content = _make_tile_png()

    def fake_get(*args, **kwargs):
        return FakeResponse()

    return patch("staticmap.staticmap.requests.get", side_effect=fake_get)


class TestHasOtherMarkers(unittest.TestCase):
    """Test _has_other_markers helper."""

    def test_transit_counts_as_other(self):
        self.assertTrue(
            _has_other_markers({}, transit_lat=40.0, transit_lng=-74.0)
        )

    def test_poi_with_coords_counts_as_other(self):
        self.assertTrue(
            _has_other_markers(
                {"grocery": [{"lat": 40.0, "lng": -74.0, "name": "Store"}]},
                None,
                None,
            )
        )

    def test_poi_without_coords_ignored(self):
        self.assertFalse(
            _has_other_markers(
                {"grocery": [{"lat": None, "lng": None, "name": "Store"}]},
                None,
                None,
            )
        )

    def test_empty_neighborhood_no_transit(self):
        self.assertFalse(_has_other_markers({}, None, None))
        self.assertFalse(_has_other_markers(None, None, None))


class TestGenerateNeighborhoodMap(unittest.TestCase):
    """Test map generation with mocked tile fetches."""

    @_mock_requests_get()
    def test_map_generates_with_property_only(self):
        """Property-only produces valid map with reasonable zoom."""
        result = generate_neighborhood_map(
            property_lat=40.99,
            property_lng=-73.78,
            neighborhood_places={},
            transit_lat=None,
            transit_lng=None,
        )
        self.assertIsNotNone(result)
        raw = base64.b64decode(result)
        self.assertGreater(len(raw), 100)
        self.assertTrue(raw.startswith(b"\x89PNG"), "Expected valid PNG")

    @_mock_requests_get()
    def test_map_generates_with_empty_neighborhood_places(self):
        """Empty neighborhood_places still works."""
        result = generate_neighborhood_map(
            property_lat=40.99,
            property_lng=-73.78,
            neighborhood_places={"grocery": [], "coffee": []},
            transit_lat=None,
            transit_lng=None,
        )
        self.assertIsNotNone(result)
        raw = base64.b64decode(result)
        self.assertGreater(len(raw), 100)
        self.assertTrue(raw.startswith(b"\x89PNG"), "Expected valid PNG")

    @_mock_requests_get()
    def test_map_generates_with_pois_and_transit(self):
        """Map generates with property + POIs + transit."""
        neighborhood_places = {
            "grocery": [
                {"lat": 40.99, "lng": -73.79, "name": "Store A"},
            ],
            "coffee": [
                {"lat": 40.98, "lng": -73.77, "name": "Cafe B"},
            ],
        }
        result = generate_neighborhood_map(
            property_lat=40.99,
            property_lng=-73.78,
            neighborhood_places=neighborhood_places,
            transit_lat=40.97,
            transit_lng=-73.76,
        )
        self.assertIsNotNone(result)
        raw = base64.b64decode(result)
        self.assertGreater(len(raw), 100)
        self.assertTrue(raw.startswith(b"\x89PNG"), "Expected valid PNG")


class TestNestCheckStaticMap(unittest.TestCase):
    """Test zoom clamping in NestCheckStaticMap."""

    def test_zoom_clamped_to_range(self):
        """_calculate_zoom returns value in [12, 16]."""
        # Add markers so extent is non-degenerate, then check zoom
        m = NestCheckStaticMap(640, 400, padding_x=24, padding_y=24)
        m.add_marker(CircleMarker((-73.78, 40.99), "#2563eb", 14))
        m.add_marker(CircleMarker((-73.77, 40.98), "#2563eb", 8))
        z = m._calculate_zoom()
        self.assertGreaterEqual(z, 12)
        self.assertLessEqual(z, 16)
