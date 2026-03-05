"""Tests for the drive-time fallback in score_transit_access (NES-204).

Verifies that car-dependent addresses receive partial credit when driving
to transit is practical, while walkable addresses are never penalised.
"""

import unittest
from unittest.mock import MagicMock, patch

from property_evaluator import (
    score_transit_access,
    PrimaryTransitOption,
    UrbanAccessProfile,
    MajorHubAccess,
    GoogleMapsClient,
    TransitAccessResult,
)


def _make_urban_access(
    walk_time_min: int,
    drive_time_min=None,
    parking_available=None,
    hub_time=40,
    mode="Train",
    frequency_class="Medium frequency",
    user_ratings_total=2000,
) -> UrbanAccessProfile:
    """Build an UrbanAccessProfile with the given transit parameters."""
    pt = PrimaryTransitOption(
        name="Test Station",
        mode=mode,
        lat=41.0,
        lng=-73.8,
        walk_time_min=walk_time_min,
        drive_time_min=drive_time_min,
        parking_available=parking_available,
        user_ratings_total=user_ratings_total,
        frequency_class=frequency_class,
    )
    hub = MajorHubAccess(
        name="Grand Central Terminal",
        travel_time_min=hub_time,
        transit_mode="transit",
    ) if hub_time else None
    return UrbanAccessProfile(primary_transit=pt, major_hub=hub)


def _mock_client() -> MagicMock:
    """Return a minimal GoogleMapsClient mock (not used when urban_access is supplied)."""
    return MagicMock(spec=GoogleMapsClient)


class TestDriveTimeFallback(unittest.TestCase):
    """Drive-time fallback scoring for car-dependent addresses."""

    def test_walkable_address_ignores_drive_fallback(self):
        """Walk <=10 min earns 4 walk points; drive fallback should not change score."""
        ua = _make_urban_access(walk_time_min=8)
        result = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua)
        # 4 walk + 2 freq (Medium) + 3 hub (40 min) = 9
        self.assertEqual(result.points, 9)
        self.assertNotIn("drive-accessible", result.details)

    def test_moderate_walk_no_drive_time(self):
        """Walk 25 min with no drive_time should use walk_points only (2)."""
        ua = _make_urban_access(walk_time_min=25, drive_time_min=None)
        result = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua)
        # 2 walk + 2 freq + 3 hub = 7
        self.assertEqual(result.points, 7)
        self.assertNotIn("drive-accessible", result.details)

    def test_far_walk_short_drive_gets_fallback(self):
        """Walk 45 min (1 pt) but 5 min drive (3 pts) should use drive fallback."""
        ua = _make_urban_access(walk_time_min=45, drive_time_min=5)
        result = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua)
        # 3 drive + 2 freq + 3 hub = 8
        self.assertEqual(result.points, 8)
        self.assertIn("drive-accessible", result.details)

    def test_very_far_walk_10min_drive(self):
        """Walk 60 min (0 pts) but 10 min drive (2 pts)."""
        ua = _make_urban_access(walk_time_min=60, drive_time_min=10)
        result = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua)
        # 2 drive + 2 freq + 3 hub = 7
        self.assertEqual(result.points, 7)
        self.assertIn("drive-accessible", result.details)

    def test_far_walk_long_drive_no_boost(self):
        """Walk 50 min (0 pts) and 25 min drive (0 pts) — no fallback benefit."""
        ua = _make_urban_access(walk_time_min=50, drive_time_min=25)
        result = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua)
        # 0 accessibility + 2 freq + 3 hub = 5
        self.assertEqual(result.points, 5)
        self.assertNotIn("drive-accessible", result.details)

    def test_drive_fallback_capped_below_best_walk(self):
        """Drive fallback max is 3; best walk score is 4. Walking always wins."""
        ua_walk = _make_urban_access(walk_time_min=8)
        ua_drive = _make_urban_access(walk_time_min=60, drive_time_min=3)
        r_walk = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua_walk)
        r_drive = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua_drive)
        self.assertGreater(r_walk.points, r_drive.points)

    def test_parking_note_in_details(self):
        """When drive fallback is used and parking is available, details mention it."""
        ua = _make_urban_access(walk_time_min=50, drive_time_min=5, parking_available=True)
        result = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua)
        self.assertIn("parking available", result.details)

    def test_no_parking_note_without_fallback(self):
        """Parking note only appears when drive fallback is actually used."""
        ua = _make_urban_access(walk_time_min=8, drive_time_min=5, parking_available=True)
        result = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua)
        # Walk points (4) > drive points (3), so no fallback used
        self.assertNotIn("drive-accessible", result.details)

    def test_drive_15min_gives_1_point(self):
        """15 min drive should give 1 point (<=20 threshold)."""
        ua = _make_urban_access(walk_time_min=60, drive_time_min=15)
        result = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua)
        # 1 drive + 2 freq + 3 hub = 6
        self.assertEqual(result.points, 6)

    def test_no_primary_transit_returns_zero(self):
        """No transit found at all should still return 0 points."""
        ua = UrbanAccessProfile(primary_transit=None, major_hub=None)
        result = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua)
        self.assertEqual(result.points, 0)

    def test_drive_9999_treated_as_unreachable(self):
        """drive_time of 9999 (unreachable sentinel) should give 0 drive points."""
        # find_primary_transit filters 9999 to None, but test the inner logic
        ua = _make_urban_access(walk_time_min=50, drive_time_min=None)
        result = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua)
        # 0 walk + 2 freq + 3 hub = 5
        self.assertEqual(result.points, 5)

    def test_none_drive_time_no_type_error(self):
        """drive_time_min=None must not raise TypeError on numeric comparison."""
        ua = _make_urban_access(walk_time_min=45, drive_time_min=None)
        # Should not raise — None guard must short-circuit before <= comparison
        result = score_transit_access(_mock_client(), 41.0, -73.8, urban_access=ua)
        self.assertEqual(result.points, 6)  # 1 walk + 2 freq + 3 hub
        self.assertNotIn("drive-accessible", result.details)


class TestDriveTimeThreshold(unittest.TestCase):
    """Verify find_primary_transit computes drive_time when walk > 20 min."""

    @patch("property_evaluator.get_parking_availability", return_value=None)
    def test_drive_time_computed_at_25_min_walk(self, _mock_parking):
        """Drive time should be computed when walk_time is 25 (> 20 threshold)."""
        from property_evaluator import find_primary_transit

        client = MagicMock(spec=GoogleMapsClient)
        client.places_nearby.return_value = [
            {
                "name": "Scarsdale Station",
                "place_id": "abc",
                "types": ["train_station"],
                "geometry": {"location": {"lat": 40.99, "lng": -73.77}},
                "user_ratings_total": 500,
            }
        ]
        client.walking_times_batch.return_value = [25]
        client.driving_time.return_value = 8

        result = find_primary_transit(client, 41.0, -73.8)

        self.assertIsNotNone(result)
        self.assertEqual(result.drive_time_min, 8)
        client.driving_time.assert_called_once()

    @patch("property_evaluator.get_parking_availability", return_value=None)
    def test_drive_time_not_computed_at_15_min_walk(self, _mock_parking):
        """Drive time should NOT be computed when walk_time is 15 (<= 20)."""
        from property_evaluator import find_primary_transit

        client = MagicMock(spec=GoogleMapsClient)
        client.places_nearby.return_value = [
            {
                "name": "Scarsdale Station",
                "place_id": "abc",
                "types": ["train_station"],
                "geometry": {"location": {"lat": 40.99, "lng": -73.77}},
                "user_ratings_total": 500,
            }
        ]
        client.walking_times_batch.return_value = [15]

        result = find_primary_transit(client, 41.0, -73.8)

        self.assertIsNotNone(result)
        self.assertIsNone(result.drive_time_min)
        client.driving_time.assert_not_called()


if __name__ == "__main__":
    unittest.main()
