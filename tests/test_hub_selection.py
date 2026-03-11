"""Tests for determine_major_hub() fallback hub selection (NES-250).

Verifies that the fallback branch uses city-specific queries and rejects
results that are too far from the property coordinates.
"""

import unittest
from unittest.mock import MagicMock, patch

from property_evaluator import determine_major_hub, GoogleMapsClient


# Ann Arbor coordinates
ANN_ARBOR_LAT, ANN_ARBOR_LNG = 42.2808, -83.7430

# Southfield City Centre — ~35 miles from Ann Arbor (should be rejected)
SOUTHFIELD_PLACE = {
    "name": "Southfield City Centre",
    "geometry": {"location": {"lat": 42.4734, "lng": -83.2219}},
}

# Ann Arbor Downtown — ~0.5 miles (should be accepted)
ANN_ARBOR_DOWNTOWN = {
    "name": "Downtown Ann Arbor",
    "geometry": {"location": {"lat": 42.2808, "lng": -83.7485}},
}


def _mock_maps_client() -> MagicMock:
    """Build a mock GoogleMapsClient that simulates the Ann Arbor bug scenario."""
    client = MagicMock(spec=GoogleMapsClient)
    # miles_between returns >60 for all hardcoded metros so the fallback fires
    client.distance_feet.return_value = 999 * 5280  # 999 miles
    # reverse geocode returns the city name
    client.reverse_geocode_locality.return_value = "Ann Arbor"
    # transit_time for the final hub
    client.transit_time.return_value = 15
    return client


class TestHubFallbackCityPrefix(unittest.TestCase):
    """Verify that fallback queries include the city name."""

    @patch("property_evaluator.miles_between", return_value=999.0)
    def test_text_search_uses_city_name(self, _mock_miles):
        """text_search should be called with 'Ann Arbor city center', not just 'city center'."""
        client = _mock_maps_client()
        # text_search returns Ann Arbor Downtown for city-prefixed query
        client.text_search.return_value = [ANN_ARBOR_DOWNTOWN]

        result = determine_major_hub(client, ANN_ARBOR_LAT, ANN_ARBOR_LNG, "Train")

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Downtown Ann Arbor")
        # Verify the query included the city name
        first_call_query = client.text_search.call_args_list[0][0][0]
        self.assertIn("Ann Arbor", first_call_query)


class TestHubFallbackDistanceValidation(unittest.TestCase):
    """Verify that distant results are rejected even if returned by the API."""

    @patch("property_evaluator.miles_between", return_value=999.0)
    def test_rejects_distant_hub(self, _mock_miles):
        """Southfield City Centre (~35 mi from Ann Arbor) should be rejected."""
        client = _mock_maps_client()
        # text_search returns only the distant Southfield result
        client.text_search.return_value = [SOUTHFIELD_PLACE]
        # places_nearby also returns nothing useful
        client.places_nearby.return_value = []

        result = determine_major_hub(client, ANN_ARBOR_LAT, ANN_ARBOR_LNG, "Train")

        self.assertIsNone(result)

    @patch("property_evaluator.miles_between", return_value=999.0)
    def test_accepts_nearby_hub(self, _mock_miles):
        """A downtown result within 25 miles should be accepted."""
        client = _mock_maps_client()
        client.text_search.return_value = [ANN_ARBOR_DOWNTOWN]

        result = determine_major_hub(client, ANN_ARBOR_LAT, ANN_ARBOR_LNG, "Train")

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Downtown Ann Arbor")

    @patch("property_evaluator.miles_between", return_value=999.0)
    def test_skips_distant_picks_nearby(self, _mock_miles):
        """When results include both distant and nearby, pick the first nearby one."""
        client = _mock_maps_client()
        # First result is distant, second is nearby
        client.text_search.return_value = [SOUTHFIELD_PLACE, ANN_ARBOR_DOWNTOWN]

        result = determine_major_hub(client, ANN_ARBOR_LAT, ANN_ARBOR_LNG, "Train")

        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Downtown Ann Arbor")


class TestHubFallbackNoReverseGeocode(unittest.TestCase):
    """Fallback still works when reverse geocoding fails."""

    @patch("property_evaluator.miles_between", return_value=999.0)
    def test_falls_back_to_generic_queries(self, _mock_miles):
        """When reverse geocode fails, queries should be generic 'city center'."""
        client = _mock_maps_client()
        client.reverse_geocode_locality.side_effect = Exception("API error")
        client.text_search.return_value = [ANN_ARBOR_DOWNTOWN]

        result = determine_major_hub(client, ANN_ARBOR_LAT, ANN_ARBOR_LNG, "Train")

        self.assertIsNotNone(result)
        # Should have used generic query
        first_call_query = client.text_search.call_args_list[0][0][0]
        self.assertEqual(first_call_query, "city center")


if __name__ == "__main__":
    unittest.main()
