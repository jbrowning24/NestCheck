"""Tests for NYC subway station accessibility lookup."""

import unittest

from nyc_subway_accessibility import (
    lookup_nyc_subway_accessibility,
    _approx_distance_m,
)


class TestApproxDistance(unittest.TestCase):
    """Verify the fast distance approximation is reasonably accurate."""

    def test_same_point_is_zero(self):
        self.assertAlmostEqual(
            _approx_distance_m(40.75, -73.98, 40.75, -73.98), 0.0
        )

    def test_known_distance(self):
        # Grand Central to Times Square ~800m
        d = _approx_distance_m(40.7527, -73.9772, 40.7580, -73.9855)
        self.assertGreater(d, 500)
        self.assertLess(d, 1200)


class TestLookupNYCSubwayAccessibility(unittest.TestCase):
    """Test the coordinate-based accessibility lookup."""

    def test_ada_station_grand_central(self):
        """Grand Central-42 St is ADA=1, fully accessible."""
        result = lookup_nyc_subway_accessibility(40.7527, -73.9772)
        self.assertIsNotNone(result)
        step_free, elevator = result
        self.assertTrue(step_free)
        self.assertTrue(elevator)

    def test_ada_station_times_square(self):
        """Times Square-42 St is ADA=1, fully accessible."""
        result = lookup_nyc_subway_accessibility(40.7580, -73.9855)
        self.assertIsNotNone(result)
        step_free, elevator = result
        self.assertTrue(step_free)
        self.assertTrue(elevator)

    def test_ada_station_atlantic_av(self):
        """Atlantic Av-Barclays Ctr is ADA=1, fully accessible."""
        result = lookup_nyc_subway_accessibility(40.6842, -73.9776)
        self.assertIsNotNone(result)
        step_free, elevator = result
        self.assertTrue(step_free)
        self.assertTrue(elevator)

    def test_non_ada_station(self):
        """Astoria-Ditmars Blvd is ADA=0, not accessible."""
        result = lookup_nyc_subway_accessibility(40.775036, -73.912034)
        self.assertIsNotNone(result)
        step_free, elevator = result
        self.assertFalse(step_free)
        self.assertFalse(elevator)

    def test_partial_ada_station(self):
        """ADA=2 stations are marked accessible (at least one direction)."""
        # 86 St (4/5/6) is ADA=2 - uptown local only
        result = lookup_nyc_subway_accessibility(40.7794, -73.9558)
        self.assertIsNotNone(result)
        step_free, elevator = result
        self.assertTrue(step_free)
        self.assertTrue(elevator)

    def test_no_match_far_from_nyc(self):
        """Location far from NYC returns None."""
        result = lookup_nyc_subway_accessibility(41.0, -73.5)
        self.assertIsNone(result)

    def test_no_match_metro_north_station(self):
        """Metro-North stations (not subway) should not match."""
        # Scarsdale Metro-North
        result = lookup_nyc_subway_accessibility(40.99, -73.77)
        self.assertIsNone(result)

    def test_slight_offset_still_matches(self):
        """A point ~100m from a station should still match within 300m radius."""
        # Slightly offset from Grand Central
        result = lookup_nyc_subway_accessibility(40.7535, -73.9780)
        self.assertIsNotNone(result)

    def test_returns_tuple_of_two_bools(self):
        """Result should be a tuple of exactly two bools."""
        result = lookup_nyc_subway_accessibility(40.7527, -73.9772)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], bool)


if __name__ == "__main__":
    unittest.main()
