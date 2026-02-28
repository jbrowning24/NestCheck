"""
Tests for the Green Escape engine (green_space.py).

Uses mocked Google Places + Distance Matrix + Overpass responses.
Run with: python -m pytest test_green_space.py -v
"""

import unittest
from unittest.mock import MagicMock, patch

from green_space import (
    find_green_spaces,
    score_green_space,
    evaluate_green_escape,
    _is_garbage,
    _is_green_space,
    _score_walk_time,
    _score_size_loop,
    _score_quality,
    _score_nature_feel,
    _evaluate_criteria,
    green_escape_to_dict,
    GreenEscapeEvaluation,
    GreenSpaceResult,
    WALK_TIME_MARGINAL,
    DRIVE_TIME_MAX,
    _cache,
    _discover_parkserve_parks,
    _merge_park_sources,
    _normalize_park_name,
    _approx_distance_m,
)


def _make_place(name, place_id, types, rating=4.0, reviews=100, lat=40.99, lng=-73.78):
    """Helper to build a mock Google Places result dict."""
    return {
        "place_id": place_id,
        "name": name,
        "types": types,
        "rating": rating,
        "user_ratings_total": reviews,
        "geometry": {"location": {"lat": lat, "lng": lng}},
    }


def _mock_maps_client(places_by_type=None, text_results=None, walk_times=None, drive_times=None):
    """Create a mock GoogleMapsClient."""
    client = MagicMock()

    places_by_type = places_by_type or {}
    text_results = text_results or {}
    walk_times = walk_times or {}

    def places_nearby(lat, lng, place_type, radius_meters=2000):
        return places_by_type.get(place_type, [])

    def text_search(query, lat, lng, radius_meters=2000):
        return text_results.get(query, [])

    def walking_time(origin, dest):
        key = (round(dest[0], 4), round(dest[1], 4))
        return walk_times.get(key, 15)

    def walking_times_batch(origin, destinations):
        return [walk_times.get((round(d[0], 4), round(d[1], 4)), 15) for d in destinations]

    drive_times = drive_times or {}

    def driving_times_batch(origin, destinations):
        return [drive_times.get((round(d[0], 4), round(d[1], 4)), 10) for d in destinations]

    client.places_nearby = MagicMock(side_effect=places_nearby)
    client.text_search = MagicMock(side_effect=text_search)
    client.walking_time = MagicMock(side_effect=walking_time)
    client.walking_times_batch = MagicMock(side_effect=walking_times_batch)
    client.driving_times_batch = MagicMock(side_effect=driving_times_batch)
    return client


class TestGarbageFilter(unittest.TestCase):
    """Test 1: Non-park POIs are excluded (e.g., Sam's Club)."""

    def test_sams_club_is_garbage(self):
        self.assertTrue(_is_garbage("Sam's Club", ["store", "point_of_interest"]))

    def test_walmart_is_garbage(self):
        self.assertTrue(_is_garbage("Walmart Supercenter", ["department_store", "point_of_interest"]))

    def test_hotel_is_garbage(self):
        self.assertTrue(_is_garbage("Holiday Inn Express", ["lodging", "point_of_interest"]))

    def test_restaurant_is_garbage(self):
        self.assertTrue(_is_garbage("Olive Garden", ["restaurant", "point_of_interest"]))

    def test_real_park_not_garbage(self):
        self.assertFalse(_is_garbage("Central Park", ["park", "point_of_interest"]))

    def test_nature_preserve_not_garbage(self):
        self.assertFalse(_is_garbage("Eagle Creek Nature Preserve", ["tourist_attraction"]))

    def test_park_with_store_type_kept(self):
        # A park that also happens to have a store type should be kept
        # because it has "park" in its types
        self.assertFalse(_is_garbage("Memorial Park Gift Shop", ["park", "store"]))

    def test_find_green_spaces_excludes_sams_club(self):
        """Integration: find_green_spaces must filter out Sam's Club."""
        _cache.clear()
        places = {
            "park": [
                _make_place("Riverside Park", "p1", ["park"], 4.5, 300),
                _make_place("Sam's Club", "p2", ["store", "point_of_interest"], 4.0, 500),
            ],
        }
        client = _mock_maps_client(places_by_type=places)
        results = find_green_spaces(client, 40.99, -73.78)
        names = [p["name"] for p in results]
        self.assertIn("Riverside Park", names)
        self.assertNotIn("Sam's Club", names)

    def test_con_ed_soccer_is_garbage_even_with_park_type(self):
        """NES-52: Sports/corporate facilities typed as 'park' are filtered by name."""
        self.assertTrue(_is_garbage("Con Ed FIAO Soccer", ["park", "point_of_interest"]))

    def test_sports_facility_is_garbage(self):
        """Sports facilities are garbage even when Google types them as park."""
        self.assertTrue(_is_garbage("Little League Baseball Field", ["park"]))
        self.assertTrue(_is_garbage("Corporate Athletic Complex", ["park"]))

    def test_field_removed_from_green_keywords(self):
        """'field' removed from GREEN_NAME_KEYWORDS — Fairfield/Springfield no longer match."""
        self.assertFalse(_is_green_space("Fairfield", ["establishment", "point_of_interest"]))

    def test_athletic_park_filtered_by_design(self):
        """Intentional: 'Athletic Park' is filtered — parent park surfaces via its own place_id."""
        self.assertTrue(_is_garbage("Athletic Park", ["park"]))

    def test_none_types_does_not_crash(self):
        """Guard: Google Places can return null types."""
        self.assertFalse(_is_garbage("Central Park", None))
        # "Central Park" still matches via name keyword — just verify no crash
        _is_green_space("Central Park", None)
        self.assertFalse(_is_green_space("Unknown Place", None))


class TestTrailKeywordInclusion(unittest.TestCase):
    """Test 2: A trail/greenway entity is included even without strict 'park' type."""

    def test_greenway_is_green_space(self):
        self.assertTrue(_is_green_space("Bronx River Greenway", ["tourist_attraction"]))

    def test_trail_is_green_space(self):
        self.assertTrue(_is_green_space("South County Trailway", ["tourist_attraction"]))

    def test_riverwalk_is_green_space(self):
        self.assertTrue(_is_green_space("Tarrytown Riverwalk", ["tourist_attraction"]))

    def test_preserve_is_green_space(self):
        self.assertTrue(_is_green_space("Mianus River Gorge Preserve", ["tourist_attraction"]))

    def test_botanical_garden_is_green_space(self):
        self.assertTrue(_is_green_space("New York Botanical Garden", ["tourist_attraction"]))

    def test_generic_attraction_not_green(self):
        self.assertFalse(_is_green_space("Dave & Buster's", ["tourist_attraction", "restaurant"]))

    def test_keyword_search_includes_trail(self):
        """Integration: trail entity found via keyword search is included."""
        _cache.clear()
        text_results = {
            "trailhead": [
                _make_place("Colonial Greenway Trailhead", "t1", ["tourist_attraction"], 4.2, 45),
            ],
        }
        client = _mock_maps_client(text_results=text_results)
        results = find_green_spaces(client, 40.99, -73.78)
        names = [p["name"] for p in results]
        self.assertIn("Colonial Greenway Trailhead", names)


class TestComprehensiveResults(unittest.TestCase):
    """Test 3: Results always include nearby list even if no items pass strict criteria."""

    def test_nearby_list_populated_even_when_all_fail(self):
        """Even when no parks meet PASS criteria, nearby list is populated."""
        _cache.clear()

        # Create parks that will likely fail (far away, low ratings)
        places = {
            "park": [
                _make_place("Tiny Pocket Park", "p1", ["park"], 3.0, 5, lat=41.01, lng=-73.80),
                _make_place("Distant Fields", "p2", ["park"], 3.5, 12, lat=41.02, lng=-73.82),
                _make_place("Small Green", "p3", ["park"], 3.2, 8, lat=41.015, lng=-73.81),
            ],
        }
        walk_times = {
            (41.01, -73.8): 25,
            (41.02, -73.82): 28,
            (41.015, -73.81): 22,
        }
        client = _mock_maps_client(places_by_type=places, walk_times=walk_times)

        evaluation = evaluate_green_escape(client, 40.99, -73.78, enable_osm=False)

        # Nearby list should always be populated
        total_spaces = len(evaluation.nearby_green_spaces)
        if evaluation.best_daily_park:
            total_spaces += 1
        self.assertGreater(total_spaces, 0, "Must have at least one space in results")

        # Even if best park doesn't fully PASS, it should be shown
        self.assertIsNotNone(
            evaluation.best_daily_park,
            "best_daily_park should be set even when nothing strictly passes"
        )

    def test_all_spaces_have_criteria_status(self):
        """Every space in results has a criteria_status field."""
        _cache.clear()
        places = {
            "park": [
                _make_place("Good Park", "p1", ["park"], 4.5, 300),
                _make_place("OK Park", "p2", ["park"], 3.8, 40),
            ],
        }
        client = _mock_maps_client(places_by_type=places)
        evaluation = evaluate_green_escape(client, 40.99, -73.78, enable_osm=False)

        if evaluation.best_daily_park:
            self.assertIn(evaluation.best_daily_park.criteria_status, ["PASS", "BORDERLINE", "FAIL"])

        for space in evaluation.nearby_green_spaces:
            self.assertIn(space.criteria_status, ["PASS", "BORDERLINE", "FAIL"])


class TestScoringModel(unittest.TestCase):
    """Additional tests for the scoring model components."""

    def test_walk_time_scoring(self):
        score, _ = _score_walk_time(5)
        self.assertEqual(score, 3.0)

        score, _ = _score_walk_time(15)
        self.assertGreaterEqual(score, 2.0)
        self.assertLessEqual(score, 3.0)

        score, _ = _score_walk_time(25)
        self.assertGreaterEqual(score, 1.0)
        self.assertLessEqual(score, 2.0)

        score, _ = _score_walk_time(35)
        self.assertEqual(score, 0.5)

    def test_quality_scoring(self):
        score, _ = _score_quality(4.5, 300)
        self.assertGreater(score, 1.5)

        score, _ = _score_quality(3.0, 5)
        self.assertLess(score, 1.0)

        score, _ = _score_quality(None, 0)
        self.assertEqual(score, 0.0)

    def test_quality_capped_for_low_reviews(self):
        """Low-review places get capped rating component (unreliable ratings)."""
        # 4.5★ with 3 reviews: rating would be 1.2 but capped to 0.6
        score_low, _ = _score_quality(4.5, 3)
        self.assertLessEqual(score_low, 0.6)

        # 4.5★ with 25 reviews: full rating component
        score_ok, _ = _score_quality(4.5, 25)
        self.assertGreater(score_ok, 1.0)
        self.assertGreater(score_ok, score_low)

    def test_size_loop_fallback_proxy(self):
        """When no OSM data, uses review count as proxy."""
        score, reason, is_estimate = _score_size_loop({}, 4.5, 500, "Big State Park")
        self.assertTrue(is_estimate)
        self.assertGreater(score, 0)
        self.assertIn("estimate", reason)

    def test_size_loop_osm_enriched(self):
        """With OSM data, uses area and path count."""
        osm_data = {
            "enriched": True,
            "area_sqm": 50_000,
            "path_count": 6,
            "has_trail": True,
        }
        score, reason, is_estimate = _score_size_loop(osm_data, 4.0, 100, "Trail Park")
        self.assertFalse(is_estimate)
        self.assertGreater(score, 2.0)

    def test_nature_feel_with_osm_tags(self):
        osm_data = {
            "nature_tags": ["landuse=forest", "natural=wood", "waterway=river"],
        }
        score, _ = _score_nature_feel(osm_data, "Forest River Park", ["park"])
        self.assertGreater(score, 1.0)

    def test_criteria_pass(self):
        status, _ = _evaluate_criteria(7.0, 2.5, 2.0, 10)
        self.assertEqual(status, "PASS")

    def test_criteria_fail_too_far(self):
        status, reasons = _evaluate_criteria(7.0, 2.5, 2.0, 35)
        self.assertEqual(status, "FAIL")
        self.assertTrue(any("exceeds" in r for r in reasons))

    def test_criteria_borderline(self):
        status, _ = _evaluate_criteria(4.0, 1.5, 0.5, 20)
        self.assertEqual(status, "BORDERLINE")


class TestGreenEscapeToDict(unittest.TestCase):
    """Test serialization to dict."""

    def test_empty_evaluation(self):
        evaluation = GreenEscapeEvaluation()
        d = green_escape_to_dict(evaluation)
        self.assertIsNone(d["best_daily_park"])
        self.assertEqual(d["nearby_green_spaces"], [])
        self.assertEqual(d["green_escape_score_0_10"], 0.0)

    def test_with_best_park(self):
        _cache.clear()
        places = {
            "park": [
                _make_place("Great Park", "p1", ["park"], 4.6, 500),
            ],
        }
        client = _mock_maps_client(
            places_by_type=places,
            walk_times={(40.99, -73.78): 8},
        )
        evaluation = evaluate_green_escape(client, 40.99, -73.78, enable_osm=False)
        d = green_escape_to_dict(evaluation)
        self.assertIsNotNone(d["best_daily_park"])
        self.assertEqual(d["best_daily_park"]["name"], "Great Park")
        self.assertGreater(d["green_escape_score_0_10"], 0)

    def test_best_park_prefers_high_reviews_when_scores_equal(self):
        """When two parks have equal daily_walk_value, higher-review wins."""
        _cache.clear()
        # Both score 5.1: 8 min walk (3.0) + size 1.0 + quality 0.6 + nature 0.5
        # Both 4.5★ with <20 reviews → rating component capped to 0.6, volume 0.0
        # Established has more reviews (8 > 5) so tiebreaker picks it
        obscure = _make_place(
            "Obscure Trail Park", "p1", ["park"], 4.5, 5,
            lat=40.99, lng=-73.78,
        )
        established = _make_place(
            "Established Trail Park", "p2", ["park"], 4.5, 8,
            lat=40.991, lng=-73.781,
        )
        places = {"park": [obscure, established]}
        walk_times = {(40.99, -73.78): 8, (40.991, -73.781): 8}
        client = _mock_maps_client(places_by_type=places, walk_times=walk_times)
        evaluation = evaluate_green_escape(client, 40.99, -73.78, enable_osm=False)
        self.assertIsNotNone(evaluation.best_daily_park)
        self.assertEqual(
            evaluation.best_daily_park.name,
            "Established Trail Park",
            "Higher-review park should win when scores are equal",
        )


class TestBatchWalkTimeBehavior(unittest.TestCase):
    """Tests for batch walk-time paths: cached failures, length guards."""

    def test_cached_9999_filtered_on_second_call(self):
        """Cached walk_time=9999 must not leak into results on a later call.

        Scenario: first call caches a 9999 value for a place.  Second call
        (different radius → function-level cache miss) should still exclude
        that place even though the per-place walk-time cache is warm.
        """
        _cache.clear()

        unreachable = _make_place(
            "Island Park", "unreachable1", ["park"], 4.0, 50,
            lat=41.05, lng=-73.85,
        )
        reachable = _make_place(
            "Riverside Park", "reachable1", ["park"], 4.5, 200,
            lat=40.995, lng=-73.785,
        )

        places = {"park": [reachable, unreachable]}
        walk_times = {
            (40.995, -73.785): 10,   # reachable
            (41.05, -73.85): 9999,   # unreachable
        }
        client = _mock_maps_client(places_by_type=places, walk_times=walk_times)

        # First call: populates per-place walk-time cache (including 9999).
        results_1 = find_green_spaces(client, 40.99, -73.78, radius_m=2000)
        names_1 = [p["name"] for p in results_1]
        self.assertIn("Riverside Park", names_1)
        self.assertNotIn("Island Park", names_1)

        # Clear only the function-level cache to simulate a second call with
        # a different radius while per-place walk-time caches remain warm.
        from green_space import _cache_key, _cache as raw_cache
        fn_key = _cache_key("find_green", 40.99, -73.78, 2000)
        raw_cache.pop(fn_key, None)

        # Second call: per-place cache hits should still filter 9999.
        results_2 = find_green_spaces(client, 40.99, -73.78, radius_m=2000)
        names_2 = [p["name"] for p in results_2]
        self.assertIn("Riverside Park", names_2)
        self.assertNotIn("Island Park", names_2,
                         "Cached walk_time=9999 must not leak into results")

    def test_batch_response_length_mismatch_treated_as_failure(self):
        """If walking_times_batch returns fewer items than requested,
        all destinations in that batch should be treated as unreachable."""
        _cache.clear()

        places = {
            "park": [
                _make_place("Park A", "pa", ["park"], 4.0, 100, lat=40.995, lng=-73.785),
                _make_place("Park B", "pb", ["park"], 4.0, 100, lat=41.00, lng=-73.79),
            ],
        }

        client = MagicMock()
        client.places_nearby = MagicMock(
            side_effect=lambda lat, lng, t, radius_meters=2000: places.get(t, [])
        )
        client.text_search = MagicMock(return_value=[])
        # Return only 1 result for 2 destinations → length mismatch.
        client.walking_times_batch = MagicMock(return_value=[10])

        results = find_green_spaces(client, 40.99, -73.78)
        # Length mismatch → all treated as 9999 → all filtered out.
        self.assertEqual(len(results), 0,
                         "Batch length mismatch should exclude all places")


class TestDriveTimeBehavior(unittest.TestCase):
    """Tests for drive-time enrichment on far parks."""

    def test_far_parks_get_drive_time(self):
        """Parks beyond WALK_TIME_MARGINAL should have drive_time_min populated."""
        _cache.clear()

        places = {
            "park": [
                _make_place("Close Park", "cp", ["park"], 4.5, 200, lat=40.995, lng=-73.785),
                _make_place("Far Park", "fp", ["park"], 4.3, 150, lat=41.05, lng=-73.85),
            ],
        }
        walk_times = {
            (40.995, -73.785): 10,   # within walking distance
            (41.05, -73.85): 45,     # beyond WALK_TIME_MARGINAL
        }
        drive_times = {
            (41.05, -73.85): 12,     # reachable by car
        }
        client = _mock_maps_client(
            places_by_type=places,
            walk_times=walk_times,
            drive_times=drive_times,
        )
        evaluation = evaluate_green_escape(client, 40.99, -73.78, enable_osm=False)

        # Far Park should appear in nearby list with drive_time_min set
        all_parks = list(evaluation.nearby_green_spaces)
        if evaluation.best_daily_park:
            all_parks.append(evaluation.best_daily_park)

        far = [p for p in all_parks if p.name == "Far Park"]
        self.assertEqual(len(far), 1, "Far Park should be in results")
        self.assertEqual(far[0].drive_time_min, 12)

        close = [p for p in all_parks if p.name == "Close Park"]
        self.assertEqual(len(close), 1)
        self.assertIsNone(close[0].drive_time_min, "Close park should have no drive_time_min")

    def test_far_parks_beyond_drive_threshold_filtered(self):
        """Parks beyond walk AND drive thresholds are removed from nearby list."""
        _cache.clear()

        places = {
            "park": [
                _make_place("Close Park", "cp", ["park"], 4.5, 200, lat=40.995, lng=-73.785),
                _make_place("Remote Park", "rp", ["park"], 4.0, 80, lat=41.08, lng=-73.90),
            ],
        }
        walk_times = {
            (40.995, -73.785): 10,
            (41.08, -73.9): 60,      # very far walk
        }
        drive_times = {
            (41.08, -73.9): 25,      # also beyond DRIVE_TIME_MAX (20)
        }
        client = _mock_maps_client(
            places_by_type=places,
            walk_times=walk_times,
            drive_times=drive_times,
        )
        evaluation = evaluate_green_escape(client, 40.99, -73.78, enable_osm=False)

        nearby_names = [s.name for s in evaluation.nearby_green_spaces]
        self.assertNotIn("Remote Park", nearby_names,
                         "Parks beyond walk + drive thresholds should be filtered out")

    def test_far_park_within_drive_threshold_kept(self):
        """A park beyond walk distance but within drive threshold stays in nearby."""
        _cache.clear()

        places = {
            "park": [
                _make_place("Close Park", "cp", ["park"], 4.5, 200, lat=40.995, lng=-73.785),
                _make_place("Driveable Park", "dp", ["park"], 4.2, 120, lat=41.04, lng=-73.84),
            ],
        }
        walk_times = {
            (40.995, -73.785): 10,
            (41.04, -73.84): 40,     # beyond walking
        }
        drive_times = {
            (41.04, -73.84): 15,     # within DRIVE_TIME_MAX
        }
        client = _mock_maps_client(
            places_by_type=places,
            walk_times=walk_times,
            drive_times=drive_times,
        )
        evaluation = evaluate_green_escape(client, 40.99, -73.78, enable_osm=False)

        nearby_names = [s.name for s in evaluation.nearby_green_spaces]
        all_names = nearby_names + ([evaluation.best_daily_park.name] if evaluation.best_daily_park else [])
        self.assertIn("Driveable Park", all_names,
                      "Park within drive threshold should remain in results")

    def test_far_parks_retained_when_drive_times_unavailable(self):
        """When driving_times_batch is missing, far parks should stay with walk times."""
        _cache.clear()

        places = {
            "park": [
                _make_place("Close Park", "cp", ["park"], 4.5, 200, lat=40.995, lng=-73.785),
                _make_place("Far Park", "fp", ["park"], 4.3, 150, lat=41.05, lng=-73.85),
            ],
        }
        walk_times = {
            (40.995, -73.785): 10,
            (41.05, -73.85): 45,     # beyond WALK_TIME_MARGINAL
        }
        client = _mock_maps_client(
            places_by_type=places,
            walk_times=walk_times,
        )
        # Remove driving_times_batch to simulate a client without the method
        del client.driving_times_batch

        evaluation = evaluate_green_escape(client, 40.99, -73.78, enable_osm=False)

        all_parks = list(evaluation.nearby_green_spaces)
        if evaluation.best_daily_park:
            all_parks.append(evaluation.best_daily_park)

        far = [p for p in all_parks if p.name == "Far Park"]
        self.assertEqual(len(far), 1,
                         "Far park should be retained when drive times unavailable")
        self.assertIsNone(far[0].drive_time_min,
                          "drive_time_min should be None when not fetched")
        self.assertEqual(far[0].walk_time_min, 45)

    def test_far_parks_retained_when_drive_times_batch_fails(self):
        """When driving_times_batch raises, far parks should stay with walk times."""
        _cache.clear()

        places = {
            "park": [
                _make_place("Close Park", "cp", ["park"], 4.5, 200, lat=40.995, lng=-73.785),
                _make_place("Far Park", "fp2", ["park"], 4.3, 150, lat=41.05, lng=-73.85),
            ],
        }
        walk_times = {
            (40.995, -73.785): 10,
            (41.05, -73.85): 45,
        }
        client = _mock_maps_client(
            places_by_type=places,
            walk_times=walk_times,
        )
        # Make driving_times_batch raise an exception
        client.driving_times_batch = MagicMock(side_effect=Exception("API error"))

        evaluation = evaluate_green_escape(client, 40.99, -73.78, enable_osm=False)

        all_parks = list(evaluation.nearby_green_spaces)
        if evaluation.best_daily_park:
            all_parks.append(evaluation.best_daily_park)

        far = [p for p in all_parks if p.name == "Far Park"]
        self.assertEqual(len(far), 1,
                         "Far park should be retained when drive time API fails")
        self.assertIsNone(far[0].drive_time_min)


class TestParkServeDiscovery(unittest.TestCase):
    """Tests for ParkServe park discovery and merge with Google Places."""

    def test_discover_parkserve_parks_graceful_fallback(self):
        """SpatialDataStore failure returns empty list, no crash."""
        with patch("green_space.SpatialDataStore") as MockStore:
            MockStore.side_effect = Exception("SpatiaLite not available")
            result = _discover_parkserve_parks(40.99, -73.78, 2000)
            self.assertEqual(result, [])

    def test_discover_parkserve_parks_shapes_output(self):
        """ParkServe records are shaped like Google Places dicts."""
        from spatial_data import FacilityRecord

        mock_records = [
            FacilityRecord(
                facility_type="parkserve",
                name="Tibbetts Brook Park",
                lat=40.99,
                lng=-73.78,
                distance_meters=500,
                distance_feet=1640,
                metadata={"park_id": "NY001", "acres": 15.2, "park_type": "Community Park"},
            ),
            FacilityRecord(
                facility_type="parkserve",
                name="",  # empty name — should be filtered
                lat=40.98,
                lng=-73.77,
                distance_meters=800,
                distance_feet=2625,
                metadata={"park_id": "NY002", "acres": 5.0, "park_type": "Pocket Park"},
            ),
        ]

        with patch("green_space.SpatialDataStore") as MockStore:
            instance = MockStore.return_value
            instance.is_available.return_value = True
            instance.find_facilities_within.return_value = mock_records

            result = _discover_parkserve_parks(40.99, -73.78, 2000)

        # Empty-name record filtered out
        self.assertEqual(len(result), 1)
        park = result[0]

        # Verify shape matches Google Places dict
        self.assertEqual(park["place_id"], "parkserve_NY001")
        self.assertEqual(park["name"], "Tibbetts Brook Park")
        self.assertEqual(park["types"], ["park"])
        self.assertIsNone(park["rating"])
        self.assertEqual(park["user_ratings_total"], 0)
        self.assertEqual(park["geometry"]["location"]["lat"], 40.99)
        self.assertEqual(park["geometry"]["location"]["lng"], -73.78)
        self.assertTrue(park["_parkserve"])
        self.assertEqual(park["_parkserve_acres"], 15.2)
        self.assertEqual(park["_parkserve_type"], "Community Park")

    def test_merge_dedup_exact_name(self):
        """Google + ParkServe parks with same name within 200m are merged."""
        google_parks = [
            {
                "place_id": "g1",
                "name": "Riverside Park",
                "types": ["park"],
                "rating": 4.5,
                "user_ratings_total": 300,
                "geometry": {"location": {"lat": 40.9, "lng": -73.8}},
            }
        ]
        parkserve_parks = [
            {
                "place_id": "parkserve_ps1",
                "name": "Riverside Park",
                "types": ["park"],
                "rating": None,
                "user_ratings_total": 0,
                "geometry": {"location": {"lat": 40.9001, "lng": -73.8001}},
                "_parkserve": True,
                "_parkserve_acres": 15,
                "_parkserve_type": "Community Park",
            }
        ]
        merged = _merge_park_sources(google_parks, parkserve_parks)
        self.assertEqual(len(merged), 1)
        # Google rating preserved
        self.assertEqual(merged[0]["rating"], 4.5)
        self.assertEqual(merged[0]["user_ratings_total"], 300)
        self.assertEqual(merged[0]["place_id"], "g1")
        # ParkServe data merged in
        self.assertTrue(merged[0]["_parkserve"])
        self.assertEqual(merged[0]["_parkserve_acres"], 15)

    def test_merge_dedup_substring(self):
        """Substring name match within 200m triggers merge."""
        google_parks = [
            {
                "place_id": "g1",
                "name": "Tibbetts Brook Park",
                "types": ["park"],
                "rating": 4.2,
                "user_ratings_total": 150,
                "geometry": {"location": {"lat": 40.9, "lng": -73.8}},
            }
        ]
        parkserve_parks = [
            {
                "place_id": "parkserve_ps1",
                "name": "Tibbetts Brook",
                "types": ["park"],
                "rating": None,
                "user_ratings_total": 0,
                "geometry": {"location": {"lat": 40.9001, "lng": -73.8001}},
                "_parkserve": True,
                "_parkserve_acres": 8,
                "_parkserve_type": "Community Park",
            }
        ]
        merged = _merge_park_sources(google_parks, parkserve_parks)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["rating"], 4.2)
        self.assertEqual(merged[0]["_parkserve_acres"], 8)

    def test_merge_no_match_adds_park(self):
        """ParkServe park far from any Google park is added as new entry."""
        google_parks = [
            {
                "place_id": "g1",
                "name": "Central Park",
                "types": ["park"],
                "rating": 4.8,
                "user_ratings_total": 5000,
                "geometry": {"location": {"lat": 40.78, "lng": -73.96}},
            }
        ]
        parkserve_parks = [
            {
                "place_id": "parkserve_ps1",
                "name": "Hidden Gem Nature Preserve",
                "types": ["park"],
                "rating": None,
                "user_ratings_total": 0,
                "geometry": {"location": {"lat": 40.79, "lng": -73.95}},
                "_parkserve": True,
                "_parkserve_acres": 25,
                "_parkserve_type": "Nature Preserve",
            }
        ]
        merged = _merge_park_sources(google_parks, parkserve_parks)
        self.assertEqual(len(merged), 2)
        names = [p["name"] for p in merged]
        self.assertIn("Central Park", names)
        self.assertIn("Hidden Gem Nature Preserve", names)

    def test_merge_short_name_no_false_positive(self):
        """Short normalized names (<4 chars) must not substring-match."""
        # "Oak Park" normalizes to "oak" (3 chars) — should NOT match
        # "Red Oak Nature Preserve" which normalizes to "red oak nature"
        google_parks = [
            {
                "place_id": "g1",
                "name": "Red Oak Nature Preserve",
                "types": ["park"],
                "rating": 4.0,
                "user_ratings_total": 50,
                "geometry": {"location": {"lat": 40.9, "lng": -73.8}},
            }
        ]
        parkserve_parks = [
            {
                "place_id": "parkserve_ps1",
                "name": "Oak Park",
                "types": ["park"],
                "rating": None,
                "user_ratings_total": 0,
                "geometry": {"location": {"lat": 40.9001, "lng": -73.8001}},
                "_parkserve": True,
                "_parkserve_acres": 3,
                "_parkserve_type": "Mini Park",
            }
        ]
        merged = _merge_park_sources(google_parks, parkserve_parks)
        # Should NOT merge — "oak" is too short for substring match
        self.assertEqual(len(merged), 2)


class TestParkServeSizeScoring(unittest.TestCase):
    """Tests for ParkServe acreage integration in size/loop scoring."""

    def test_score_size_parkserve_acreage(self):
        """ParkServe acreage produces authoritative size score."""
        # 12 acres = 48,564 sqm >= SIZE_LARGE_SQM (40,000) → size 1.5
        score, reason, is_estimate = _score_size_loop(
            {}, 4.0, 100, "Good Park", parkserve_acres=12,
        )
        self.assertFalse(is_estimate)
        self.assertEqual(score, 1.5)
        self.assertIn("ParkServe", reason)
        self.assertIn("large park", reason)

    def test_score_size_parkserve_beats_osm(self):
        """ParkServe acreage takes priority over OSM area estimate."""
        osm_data = {
            "enriched": True,
            "area_sqm": 5000,   # SMALL (5K sqm)
            "path_count": 0,
            "has_trail": False,
        }
        # Without ParkServe: would use OSM 5000 sqm → SMALL → 0.5
        score_osm, _, _ = _score_size_loop(osm_data, 4.0, 100, "Park")
        self.assertEqual(score_osm, 0.5)

        # With ParkServe: 12 acres = 48,564 sqm → LARGE → 1.5
        score_ps, reason, is_estimate = _score_size_loop(
            osm_data, 4.0, 100, "Park", parkserve_acres=12,
        )
        self.assertFalse(is_estimate)
        self.assertEqual(score_ps, 1.5)
        self.assertIn("ParkServe", reason)
        self.assertGreater(score_ps, score_osm)

    def test_score_size_parkserve_medium(self):
        """Medium park via ParkServe (3-10 acres)."""
        # 5 acres = 20,235 sqm >= SIZE_MEDIUM_SQM (12,000) → 1.0
        score, reason, _ = _score_size_loop(
            {}, None, 0, "Small Town Park", parkserve_acres=5,
        )
        self.assertEqual(score, 1.0)
        self.assertIn("medium park", reason)
        self.assertIn("ParkServe", reason)

    def test_score_size_parkserve_small(self):
        """Small park via ParkServe (1-3 acres)."""
        # 2 acres = 8,094 sqm >= SIZE_SMALL_SQM (4,000) → 0.5
        score, reason, _ = _score_size_loop(
            {}, None, 0, "Pocket Green", parkserve_acres=2,
        )
        self.assertEqual(score, 0.5)
        self.assertIn("small park", reason)
        self.assertIn("ParkServe", reason)

    def test_score_size_parkserve_with_osm_paths(self):
        """ParkServe area + OSM paths combine for best-of-both scoring."""
        osm_data = {
            "enriched": True,
            "area_sqm": 5000,  # would be SMALL, but ParkServe overrides
            "path_count": 6,   # PATH_NETWORK_DENSE → loop_score 1.5
            "has_trail": False,
        }
        # ParkServe 12 acres (LARGE → 1.5) + OSM paths (1.5) = 3.0
        score, reason, _ = _score_size_loop(
            osm_data, 4.0, 100, "Trail Park", parkserve_acres=12,
        )
        self.assertEqual(score, 3.0)
        self.assertIn("ParkServe", reason)
        self.assertIn("footway segments", reason)


class TestNormalizeParkName(unittest.TestCase):
    """Tests for park name normalization used in dedup."""

    def test_strips_park_suffix(self):
        self.assertEqual(_normalize_park_name("Riverside Park"), "riverside")

    def test_strips_preserve_suffix(self):
        self.assertEqual(_normalize_park_name("Mianus River Gorge Preserve"), "mianus river gorge")

    def test_strips_punctuation(self):
        self.assertEqual(_normalize_park_name("St. Mary's Park"), "st marys")

    def test_case_insensitive(self):
        self.assertEqual(
            _normalize_park_name("TIBBETTS BROOK PARK"),
            _normalize_park_name("tibbetts brook park"),
        )

    def test_strips_multiple_suffixes(self):
        """Names with stacked suffixes like 'Park Field' get both stripped."""
        self.assertEqual(
            _normalize_park_name("Memorial Park Field"),
            "memorial",
        )

    def test_strips_recreation_area_then_park(self):
        self.assertEqual(
            _normalize_park_name("Riverside Recreation Area"),
            "riverside",
        )


class TestApproxDistanceM(unittest.TestCase):
    """Tests for approximate distance calculation."""

    def test_same_point_is_zero(self):
        self.assertAlmostEqual(_approx_distance_m(40.9, -73.8, 40.9, -73.8), 0.0)

    def test_close_points_within_200m(self):
        # ~0.001 degrees lat ≈ 111 m
        dist = _approx_distance_m(40.9, -73.8, 40.901, -73.8)
        self.assertGreater(dist, 100)
        self.assertLess(dist, 200)

    def test_far_points_beyond_200m(self):
        # ~0.01 degrees lat ≈ 1.1 km
        dist = _approx_distance_m(40.9, -73.8, 40.91, -73.8)
        self.assertGreater(dist, 1000)


if __name__ == "__main__":
    unittest.main()
