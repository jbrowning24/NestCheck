"""Unit tests for census.py — Census ACS city-level demographic data (NES-257).

Tests cover: cache key generation, safe type conversions, place-level ACS
row parsing, serialization round-trips, place lookup, and the public
get_demographics API.
"""

import json
import unittest.mock
from unittest.mock import patch, MagicMock

import pytest

from census import (
    _place_cache_key,
    _safe_int,
    _safe_float,
    _safe_pct,
    _clean_place_name,
    _parse_place_row,
    _serialize_city,
    _deserialize_city,
    serialize_for_result,
    _lookup_place,
    get_demographics,
    CityProfile,
    _CENSUS_MISSING,
)


# =========================================================================
# Cache key generation
# =========================================================================

class TestCacheKeys:
    def test_place_key_format(self):
        assert _place_cache_key("26", "59440") == "place:2659440"

    def test_cousub_key_includes_county(self):
        key = _place_cache_key("26", "17640", "county_subdivision", "125")
        assert key == "county_subdivision:2612517640"

    def test_different_counties_different_cousub_keys(self):
        k1 = _place_cache_key("26", "17640", "county_subdivision", "125")
        k2 = _place_cache_key("26", "17640", "county_subdivision", "099")
        assert k1 != k2

    def test_different_places_different_keys(self):
        k1 = _place_cache_key("26", "59440")
        k2 = _place_cache_key("36", "81677")
        assert k1 != k2


# =========================================================================
# Safe type conversions
# =========================================================================

class TestSafeInt:
    def test_normal_int(self):
        assert _safe_int("1234") == 1234

    def test_float_string(self):
        assert _safe_int("1234.0") == 1234

    def test_none_returns_default(self):
        assert _safe_int(None) is None
        assert _safe_int(None, 0) == 0

    def test_empty_string_returns_default(self):
        assert _safe_int("", 0) == 0

    def test_census_missing_sentinel(self):
        assert _safe_int(_CENSUS_MISSING) is None
        assert _safe_int("-666666666", 0) == 0

    def test_non_numeric_returns_default(self):
        assert _safe_int("N/A", 0) == 0


class TestSafeFloat:
    def test_normal_float(self):
        assert _safe_float("40.5") == 40.5

    def test_rounds_to_one_decimal(self):
        assert _safe_float("40.567") == 40.6

    def test_none_returns_default(self):
        assert _safe_float(None) is None
        assert _safe_float(None, 0.0) == 0.0

    def test_census_missing_sentinel(self):
        assert _safe_float(_CENSUS_MISSING) is None


class TestSafePct:
    def test_normal_percentage(self):
        assert _safe_pct(25, 100) == 25.0

    def test_zero_denominator(self):
        assert _safe_pct(25, 0) == 0.0

    def test_none_denominator(self):
        assert _safe_pct(25, None) == 0.0

    def test_none_numerator(self):
        assert _safe_pct(None, 100) == 0.0

    def test_rounds_to_one_decimal(self):
        assert _safe_pct(1, 3) == 33.3


# =========================================================================
# Place name cleaning
# =========================================================================

class TestCleanPlaceName:
    def test_strips_city_suffix(self):
        assert _clean_place_name("Novi city") == "Novi"

    def test_strips_town_suffix(self):
        assert _clean_place_name("Greenwich town") == "Greenwich"

    def test_strips_village_suffix(self):
        assert _clean_place_name("Tarrytown village") == "Tarrytown"

    def test_strips_cdp_suffix(self):
        assert _clean_place_name("Levittown CDP") == "Levittown"

    def test_strips_borough_suffix(self):
        assert _clean_place_name("Princeton borough") == "Princeton"

    def test_strips_charter_township_suffix(self):
        assert _clean_place_name("Commerce charter township") == "Commerce"

    def test_strips_township_suffix(self):
        assert _clean_place_name("Hempstead township") == "Hempstead"

    def test_preserves_multiword_names(self):
        assert _clean_place_name("White Plains city") == "White Plains"

    def test_preserves_multiword_with_dots(self):
        assert _clean_place_name("St. Clair Shores city") == "St. Clair Shores"

    def test_preserves_name_without_suffix(self):
        assert _clean_place_name("Manhattan") == "Manhattan"

    def test_handles_whitespace(self):
        assert _clean_place_name("  Novi city  ") == "Novi"


# =========================================================================
# ACS place-level row parsing
# =========================================================================

def _make_place_row(
    population=65870, total_hh=26516,
    median_income=110588, median_age=40.0,
    total_occ=26516, owner=18011, renter=8505,
):
    """Build a synthetic ACS place-level row matching Census API format."""
    return {
        "B01003_001E": str(population),
        "B11001_001E": str(total_hh),
        "B19013_001E": str(median_income),
        "B01002_001E": str(median_age),
        "B25003_001E": str(total_occ),
        "B25003_002E": str(owner),
        "B25003_003E": str(renter),
    }


class TestParsePlaceRow:
    def test_normal_row(self):
        row = _make_place_row()
        parsed = _parse_place_row(row)

        assert parsed["population"] == 65870
        assert parsed["total_households"] == 26516
        assert parsed["median_household_income"] == 110588
        assert parsed["median_age"] == 40.0
        assert parsed["owner_pct"] == pytest.approx(67.9, abs=0.1)
        assert parsed["renter_pct"] == pytest.approx(32.1, abs=0.1)

    def test_missing_income(self):
        row = _make_place_row()
        row["B19013_001E"] = _CENSUS_MISSING
        parsed = _parse_place_row(row)
        assert parsed["median_household_income"] is None

    def test_missing_age(self):
        row = _make_place_row()
        row["B01002_001E"] = ""
        parsed = _parse_place_row(row)
        assert parsed["median_age"] is None

    def test_zero_denominators(self):
        row = _make_place_row(total_occ=0)
        parsed = _parse_place_row(row)
        assert parsed["owner_pct"] == 0.0
        assert parsed["renter_pct"] == 0.0


# =========================================================================
# Serialization round-trips
# =========================================================================

def _make_city_profile():
    """Build a full CityProfile for serialization tests."""
    return CityProfile(
        state_fips="26",
        place_fips="59440",
        place_name="Novi",
        population=65870,
        total_households=26516,
        median_household_income=110588,
        median_age=40.0,
        total_occupied=26516,
        owner_occupied=18011,
        renter_occupied=8505,
        owner_pct=67.9,
        renter_pct=32.1,
    )


class TestSerialization:
    def test_round_trip(self):
        original = _make_city_profile()
        serialized = _serialize_city(original)
        restored = _deserialize_city(serialized)

        assert restored.place_name == "Novi"
        assert restored.population == 65870
        assert restored.median_household_income == 110588
        assert restored.median_age == 40.0
        assert restored.owner_pct == 67.9

    def test_json_round_trip(self):
        original = _make_city_profile()
        json_str = json.dumps(_serialize_city(original))
        restored = _deserialize_city(json.loads(json_str))
        assert restored.place_name == original.place_name
        assert restored.population == original.population

    def test_serialize_for_result_with_profile(self):
        p = _make_city_profile()
        result = serialize_for_result(p)
        assert result is not None
        assert result["place_name"] == "Novi"
        assert result["population"] == 65870
        assert result["median_household_income"] == 110588

    def test_serialize_for_result_none(self):
        assert serialize_for_result(None) is None

    def test_deserialize_missing_optional_fields(self):
        """Profile with missing optional fields deserializes correctly."""
        data = {
            "state_fips": "26",
            "place_fips": "59440",
            "place_name": "Novi",
            "population": 65870,
            "total_households": 26516,
            # median_household_income and median_age omitted
            "total_occupied": 26516,
            "owner_occupied": 18011,
            "renter_occupied": 8505,
            "owner_pct": 67.9,
            "renter_pct": 32.1,
        }
        restored = _deserialize_city(data)
        assert restored.median_household_income is None
        assert restored.median_age is None
        assert restored.population == 65870


# =========================================================================
# Place lookup
# =========================================================================

class TestLookupPlace:
    @patch("census.requests.get")
    def test_incorporated_place_found(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": {
                "geographies": {
                    "Incorporated Places": [
                        {"STATE": "26", "PLACE": "59440", "NAME": "Novi city"}
                    ],
                }
            }
        }
        mock_get.return_value = mock_resp

        result = _lookup_place(42.48, -83.47)
        assert result["state"] == "26"
        assert result["place"] == "59440"
        assert result["name"] == "Novi city"
        assert result["geo_type"] == "place"

    @patch("census.requests.get")
    def test_cdp_fallback(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": {
                "geographies": {
                    "Incorporated Places": [],
                    "Census Designated Places": [
                        {"STATE": "36", "PLACE": "42081", "NAME": "Levittown CDP"}
                    ],
                }
            }
        }
        mock_get.return_value = mock_resp

        result = _lookup_place(40.72, -73.51)
        assert result["state"] == "36"
        assert result["place"] == "42081"
        assert result["geo_type"] == "place"

    @patch("census.requests.get")
    def test_county_subdivision_fallback(self, mock_get):
        """Unincorporated townships fall back to County Subdivisions."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": {
                "geographies": {
                    "Incorporated Places": [],
                    "Census Designated Places": [],
                    "County Subdivisions": [
                        {
                            "STATE": "26", "COUSUB": "17640",
                            "COUNTY": "125",
                            "NAME": "Commerce charter township",
                        }
                    ],
                }
            }
        }
        mock_get.return_value = mock_resp

        result = _lookup_place(42.57, -83.49)
        assert result["state"] == "26"
        assert result["place"] == "17640"
        assert result["geo_type"] == "county_subdivision"
        assert result["county"] == "125"

    @patch("census.requests.get")
    def test_no_place_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": {
                "geographies": {
                    "Incorporated Places": [],
                    "Census Designated Places": [],
                    "County Subdivisions": [],
                }
            }
        }
        mock_get.return_value = mock_resp

        result = _lookup_place(41.0, -73.8)
        assert result is None

    @patch("census.requests.get")
    def test_api_failure_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp

        result = _lookup_place(41.0, -73.8)
        assert result is None


# =========================================================================
# Public API (get_demographics)
# =========================================================================

class TestGetDemographics:
    @patch("census.set_census_cache")
    @patch("census.get_census_cache", return_value=None)
    @patch("census._fetch_acs_place")
    @patch("census._lookup_place")
    def test_cache_miss_fetches_and_caches(self, mock_place, mock_acs,
                                            mock_get_cache, mock_set_cache):
        mock_place.return_value = {
            "state": "26", "place": "59440", "name": "Novi city",
            "geo_type": "place",
        }
        mock_acs.return_value = _make_place_row()

        result = get_demographics(42.48, -83.47)

        assert result is not None
        assert result.place_name == "Novi"
        assert result.population == 65870
        assert result.median_household_income == 110588
        assert mock_set_cache.call_count == 1
        # Verify ACS called with place geo_type
        mock_acs.assert_called_once()
        call_kwargs = mock_acs.call_args
        assert call_kwargs[1].get("geo_type", "place") == "place"

    @patch("census.set_census_cache")
    @patch("census.get_census_cache", return_value=None)
    @patch("census._fetch_acs_place")
    @patch("census._lookup_place")
    def test_county_subdivision_passes_county_to_acs(self, mock_place, mock_acs,
                                                      mock_get_cache, mock_set_cache):
        """County subdivision path passes geo_type and county to ACS fetch."""
        mock_place.return_value = {
            "state": "26", "place": "17640",
            "name": "Commerce charter township",
            "geo_type": "county_subdivision", "county": "125",
        }
        mock_acs.return_value = _make_place_row(population=43081, total_hh=16530)

        result = get_demographics(42.57, -83.49)

        assert result is not None
        assert result.place_name == "Commerce"
        assert result.population == 43081
        mock_acs.assert_called_once_with(
            "26", "17640", unittest.mock.ANY,
            geo_type="county_subdivision", county="125",
        )

    @patch("census.get_census_cache")
    @patch("census._lookup_place")
    def test_cache_hit_skips_api(self, mock_place, mock_get_cache):
        mock_place.return_value = {"state": "26", "place": "59440", "name": "Novi city"}
        cached_profile = _serialize_city(_make_city_profile())
        mock_get_cache.return_value = json.dumps(cached_profile)

        result = get_demographics(42.48, -83.47)

        assert result is not None
        assert result.place_name == "Novi"
        assert result.population == 65870

    @patch("census._lookup_place", return_value=None)
    def test_place_failure_returns_none(self, mock_place):
        result = get_demographics(41.0, -73.8)
        assert result is None

    @patch("census.get_census_cache", return_value=None)
    @patch("census._fetch_acs_place", return_value=None)
    @patch("census._lookup_place")
    def test_acs_failure_returns_none(self, mock_place, mock_acs, mock_cache):
        mock_place.return_value = {"state": "26", "place": "59440", "name": "Novi city"}

        result = get_demographics(42.48, -83.47)
        assert result is None
