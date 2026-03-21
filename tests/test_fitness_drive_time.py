"""Tests for drive-time scoring in score_fitness_access (NES-259).

Verifies that suburban gyms reachable by car get scored on drive time
when walk time exceeds the WALK_DRIVE_BOTH_THRESHOLD, and that walkable
addresses never trigger a drive-time API call.
"""

import unittest
from unittest.mock import MagicMock

from property_evaluator import score_fitness_access, GoogleMapsClient
from scoring_config import WALK_DRIVE_BOTH_THRESHOLD


def _make_gym(name="Planet Fitness", rating=4.5, reviews=500, place_id="pf1",
              lat=42.48, lng=-83.49):
    """Build a minimal Google Places result dict for a gym."""
    return {
        "name": name,
        "rating": rating,
        "user_ratings_total": reviews,
        "place_id": place_id,
        "types": ["gym", "health", "point_of_interest"],
        "geometry": {"location": {"lat": lat, "lng": lng}},
    }


def _mock_maps(gyms, walk_times, drive_time=None):
    """Build a GoogleMapsClient mock with canned responses.

    Args:
        gyms: list of place dicts returned by places_nearby (first call only;
              subsequent calls return []).
        walk_times: list of ints returned by walking_times_batch.
        drive_time: int returned by driving_time(), or None to not set it.
    """
    maps = MagicMock(spec=GoogleMapsClient)
    # First places_nearby returns gyms; subsequent calls (yoga, keyword,
    # text_search) return [] to avoid duplicates.
    maps.places_nearby.side_effect = [gyms, [], []]
    maps.text_search.return_value = []
    maps.walking_times_batch.return_value = walk_times
    if drive_time is not None:
        maps.driving_time.return_value = drive_time
    return maps


class TestFitnessDriveTimeScoring(unittest.TestCase):
    """Drive-time scoring for suburban fitness facilities."""

    def test_drive_score_wins_over_walk_for_far_gym(self):
        """Walk 25 min (score ~4.5) but 8 min drive (score ~5.4).
        Final score should use drive score, details should say 'drive'."""
        gym = _make_gym()
        maps = _mock_maps([gym], walk_times=[25], drive_time=8)

        score, places, _dd = score_fitness_access(maps, 42.5, -83.5)

        # Drive score should dominate — 8 min drive on FITNESS_DRIVE_KNOTS
        # (NES-315 ceiling 6): base ~5.4, × 1.0 quality = 5.4, rounded to 5.
        # Walk score: base ~4.5 × 1.0 = ~4.5. Drive wins.
        self.assertGreaterEqual(score.points, 5)
        self.assertIn("drive", score.details)
        self.assertNotIn("walk", score.details)

        # driving_time was called exactly once (for the best facility)
        maps.driving_time.assert_called_once()

        # drive_time_min populated in neighborhood places
        best_place = next(
            p for p in places if p["place_id"] == "pf1"
        )
        self.assertEqual(best_place["drive_time_min"], 8)

    def test_walkable_gym_skips_drive_lookup(self):
        """Walk ≤ 20 min should never call driving_time()."""
        gym = _make_gym()
        maps = _mock_maps([gym], walk_times=[15])

        score, places, _dd = score_fitness_access(maps, 42.5, -83.5)

        # Walk 15 min → base 8.0 × 1.0 quality = 8.0, rounded to 8
        self.assertGreaterEqual(score.points, 7)
        self.assertIn("walk", score.details)
        maps.driving_time.assert_not_called()

        # drive_time_min should be None in neighborhood places
        best_place = next(
            p for p in places if p["place_id"] == "pf1"
        )
        self.assertIsNone(best_place["drive_time_min"])

    def test_walk_at_threshold_skips_drive(self):
        """Walk == WALK_DRIVE_BOTH_THRESHOLD (20 min) should NOT trigger drive."""
        gym = _make_gym()
        maps = _mock_maps([gym], walk_times=[WALK_DRIVE_BOTH_THRESHOLD])

        score, places, _dd = score_fitness_access(maps, 42.5, -83.5)

        maps.driving_time.assert_not_called()
        self.assertIn("walk", score.details)

    def test_walk_just_above_threshold_triggers_drive(self):
        """Walk == 21 min should trigger drive lookup."""
        gym = _make_gym()
        maps = _mock_maps([gym], walk_times=[21], drive_time=6)

        score, places, _dd = score_fitness_access(maps, 42.5, -83.5)

        maps.driving_time.assert_called_once()

    def test_drive_unreachable_falls_back_to_walk(self):
        """driving_time returns 9999 → treated as unreachable, walk score used."""
        gym = _make_gym()
        maps = _mock_maps([gym], walk_times=[25], drive_time=9999)

        score, places, _dd = score_fitness_access(maps, 42.5, -83.5)

        # Walk score should be used (25 min walk → ~4.5)
        self.assertIn("walk", score.details)
        best_place = next(
            p for p in places if p["place_id"] == "pf1"
        )
        self.assertIsNone(best_place["drive_time_min"])

    def test_drive_api_error_falls_back_to_walk(self):
        """driving_time raises → gracefully falls back to walk score."""
        gym = _make_gym()
        maps = _mock_maps([gym], walk_times=[25])
        maps.driving_time.side_effect = ValueError("Distance Matrix API failed")

        score, places, _dd = score_fitness_access(maps, 42.5, -83.5)

        self.assertIn("walk", score.details)
        self.assertIsNotNone(score.points)

    def test_walk_score_wins_when_better(self):
        """Walk 21 min with 25 min drive — walk score should still win."""
        gym = _make_gym()
        maps = _mock_maps([gym], walk_times=[21], drive_time=25)

        score, places, _dd = score_fitness_access(maps, 42.5, -83.5)

        # Walk 21 min → ~5.7, drive 25 min → ~1.0. Walk wins.
        self.assertIn("walk", score.details)

    def test_old_snapshot_compat_drive_time_field_always_present(self):
        """neighborhood_places always has drive_time_min key (None if not fetched)."""
        gym = _make_gym()
        maps = _mock_maps([gym], walk_times=[10])

        _, places, _dd = score_fitness_access(maps, 42.5, -83.5)

        for p in places:
            self.assertIn("drive_time_min", p)


if __name__ == "__main__":
    unittest.main()
