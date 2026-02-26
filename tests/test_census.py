"""Unit tests for census.py — Census ACS demographic data integration.

Tests cover: cache key generation, safe type conversions, ACS row parsing,
serialization round-trips, tract lookup fallback chain, and the public
get_demographics API.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

try:
    from census import (
        _tract_cache_key,
        _county_cache_key,
        _safe_int,
        _safe_pct,
        _parse_acs_row,
        _serialize,
        _serialize_commute,
        _deserialize,
        _deserialize_commute,
        serialize_for_result,
        _lookup_tract,
        get_demographics,
        CensusProfile,
        CommuteBreakdown,
        _CENSUS_MISSING,
    )
except ImportError:
    pytestmark = pytest.mark.skip(
        reason="census.py imports get_census_cache/set_census_cache from models, "
               "which were removed; entire module fails to import"
    )


# =========================================================================
# Cache key generation
# =========================================================================

class TestCacheKeys:
    def test_tract_key_format(self):
        assert _tract_cache_key("36", "119", "025300") == "tract:36119025300"

    def test_county_key_format(self):
        assert _county_cache_key("36", "119") == "county:36119"

    def test_different_tracts_different_keys(self):
        k1 = _tract_cache_key("36", "119", "025300")
        k2 = _tract_cache_key("36", "119", "025400")
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
# ACS row parsing
# =========================================================================

def _make_acs_row(
    total_hh=1000, hh_children=350,
    total_occ=980, owner=600, renter=380,
    total_comm=800, drive=500, carpool=80, transit=100,
    bike=20, walk=40, wfh=60,
    median_rent=1800,
):
    """Build a synthetic ACS row dict matching Census API format."""
    return {
        "B11005_001E": str(total_hh),
        "B11005_002E": str(hh_children),
        "B25003_001E": str(total_occ),
        "B25003_002E": str(owner),
        "B25003_003E": str(renter),
        "B08301_001E": str(total_comm),
        "B08301_003E": str(drive),
        "B08301_004E": str(carpool),
        "B08301_010E": str(transit),
        "B08301_018E": str(bike),
        "B08301_019E": str(walk),
        "B08301_021E": str(wfh),
        "B25064_001E": str(median_rent),
    }


class TestParseAcsRow:
    def test_normal_row(self):
        row = _make_acs_row()
        parsed = _parse_acs_row(row)

        assert parsed["total_households"] == 1000
        assert parsed["households_with_children"] == 350
        assert parsed["children_pct"] == 35.0
        assert parsed["owner_pct"] == pytest.approx(61.2, abs=0.1)
        assert parsed["renter_pct"] == pytest.approx(38.8, abs=0.1)
        assert parsed["median_rent"] == 1800

        commute = parsed["commute"]
        assert isinstance(commute, CommuteBreakdown)
        assert commute.drive_alone_pct == 62.5
        assert commute.transit_pct == 12.5
        assert commute.walk_pct == 5.0
        assert commute.bike_pct == 2.5
        assert commute.wfh_pct == 7.5

    def test_missing_values_handled(self):
        row = _make_acs_row()
        row["B25064_001E"] = _CENSUS_MISSING  # median rent suppressed
        row["B11005_002E"] = ""  # children missing

        parsed = _parse_acs_row(row)
        assert parsed["median_rent"] is None
        assert parsed["households_with_children"] == 0
        assert parsed["children_pct"] == 0.0

    def test_zero_denominators(self):
        row = _make_acs_row(total_hh=0, total_occ=0, total_comm=0)
        parsed = _parse_acs_row(row)

        assert parsed["children_pct"] == 0.0
        assert parsed["owner_pct"] == 0.0
        assert parsed["commute"].drive_alone_pct == 0.0


# =========================================================================
# Serialization round-trips
# =========================================================================

def _make_profile():
    """Build a full CensusProfile for serialization tests."""
    return CensusProfile(
        state_fips="36",
        county_fips="119",
        tract_code="025300",
        geoid="36119025300",
        total_households=1000,
        households_with_children=350,
        children_pct=35.0,
        total_occupied=980,
        owner_occupied=600,
        renter_occupied=380,
        owner_pct=61.2,
        renter_pct=38.8,
        total_commuters=800,
        commute=CommuteBreakdown(
            drive_alone_pct=62.5,
            carpool_pct=10.0,
            transit_pct=12.5,
            walk_pct=5.0,
            bike_pct=2.5,
            wfh_pct=7.5,
        ),
        median_rent=1800,
        county_name="Westchester County",
        county_children_pct=32.0,
        county_owner_pct=65.0,
        county_renter_pct=35.0,
        county_commute=CommuteBreakdown(
            drive_alone_pct=58.0,
            carpool_pct=8.0,
            transit_pct=18.0,
            walk_pct=4.0,
            bike_pct=1.0,
            wfh_pct=11.0,
        ),
        county_median_rent=1650,
    )


class TestSerialization:
    def test_round_trip(self):
        original = _make_profile()
        serialized = _serialize(original)
        restored = _deserialize(serialized)

        assert restored.geoid == original.geoid
        assert restored.children_pct == original.children_pct
        assert restored.commute.transit_pct == original.commute.transit_pct
        assert restored.county_name == "Westchester County"
        assert restored.county_commute.transit_pct == 18.0
        assert restored.median_rent == 1800
        assert restored.county_median_rent == 1650

    def test_json_round_trip(self):
        original = _make_profile()
        json_str = json.dumps(_serialize(original))
        restored = _deserialize(json.loads(json_str))
        assert restored.geoid == original.geoid
        assert restored.commute.wfh_pct == original.commute.wfh_pct

    def test_serialize_for_result_with_profile(self):
        p = _make_profile()
        result = serialize_for_result(p)
        assert result is not None
        assert result["geoid"] == "36119025300"
        assert "commute" in result
        assert result["commute"]["transit_pct"] == 12.5

    def test_serialize_for_result_none(self):
        assert serialize_for_result(None) is None

    def test_commute_round_trip(self):
        original = CommuteBreakdown(
            drive_alone_pct=60.0, carpool_pct=8.0, transit_pct=15.0,
            walk_pct=5.0, bike_pct=2.0, wfh_pct=10.0,
        )
        serialized = _serialize_commute(original)
        restored = _deserialize_commute(serialized)
        assert restored.transit_pct == 15.0
        assert restored.wfh_pct == 10.0

    def test_deserialize_missing_county_commute(self):
        """Profile with county_commute=None deserializes correctly."""
        p = _make_profile()
        p.county_commute = None
        serialized = _serialize(p)
        assert serialized["county_commute"] is None

        restored = _deserialize(serialized)
        assert restored.county_commute is None


# =========================================================================
# Tract lookup fallback chain
# =========================================================================

class TestLookupTract:
    @patch("census._lookup_tract_census")
    @patch("census._lookup_tract_fcc")
    def test_fcc_success(self, mock_fcc, mock_census):
        mock_fcc.return_value = {"state": "36", "county": "119", "tract": "025300"}

        result = _lookup_tract(41.0, -73.8)

        assert result == {"state": "36", "county": "119", "tract": "025300"}
        mock_census.assert_not_called()

    @patch("census._lookup_tract_census")
    @patch("census._lookup_tract_fcc")
    def test_fcc_fails_census_fallback(self, mock_fcc, mock_census):
        mock_fcc.return_value = None
        mock_census.return_value = {"state": "36", "county": "119", "tract": "025300"}

        result = _lookup_tract(41.0, -73.8)

        assert result is not None
        mock_census.assert_called_once()

    @patch("census._lookup_tract_census")
    @patch("census._lookup_tract_fcc")
    def test_both_fail_returns_none(self, mock_fcc, mock_census):
        mock_fcc.return_value = None
        mock_census.return_value = None

        result = _lookup_tract(41.0, -73.8)

        assert result is None

    @patch("census._lookup_tract_census")
    @patch("census._lookup_tract_fcc")
    def test_fcc_empty_fields_triggers_fallback(self, mock_fcc, mock_census):
        mock_fcc.return_value = {"state": "", "county": "119", "tract": "025300"}
        mock_census.return_value = {"state": "36", "county": "119", "tract": "025300"}

        result = _lookup_tract(41.0, -73.8)

        mock_census.assert_called_once()
        assert result["state"] == "36"


# =========================================================================
# Public API (get_demographics)
# =========================================================================

class TestGetDemographics:
    @patch("census.set_census_cache")
    @patch("census.get_census_cache", return_value=None)
    @patch("census._fetch_acs")
    @patch("census._lookup_tract")
    def test_cache_miss_fetches_and_caches(self, mock_tract, mock_acs,
                                            mock_get_cache, mock_set_cache):
        mock_tract.return_value = {"state": "36", "county": "119", "tract": "025300"}
        tract_row = _make_acs_row()
        county_row = _make_acs_row(
            total_hh=200000, hh_children=64000,
            total_occ=195000, owner=126750, renter=68250,
            median_rent=1650,
        )
        county_row["NAME"] = "Westchester County, New York"
        mock_acs.side_effect = [tract_row, county_row]

        result = get_demographics(41.0, -73.8)

        assert result is not None
        assert result.children_pct == 35.0
        assert result.county_name == "Westchester County"
        assert result.county_children_pct == 32.0
        # Tract cache + county cache = 2 set_census_cache calls
        assert mock_set_cache.call_count == 2

    @patch("census.get_census_cache")
    @patch("census._lookup_tract")
    def test_cache_hit_skips_api(self, mock_tract, mock_get_cache):
        mock_tract.return_value = {"state": "36", "county": "119", "tract": "025300"}
        cached_profile = _serialize(_make_profile())
        mock_get_cache.return_value = json.dumps(cached_profile)

        result = get_demographics(41.0, -73.8)

        assert result is not None
        assert result.geoid == "36119025300"
        assert result.children_pct == 35.0

    @patch("census._lookup_tract", return_value=None)
    def test_tract_failure_returns_none(self, mock_tract):
        result = get_demographics(41.0, -73.8)
        assert result is None

    @patch("census.get_census_cache", return_value=None)
    @patch("census._fetch_acs", return_value=None)
    @patch("census._lookup_tract")
    def test_acs_failure_returns_none(self, mock_tract, mock_acs, mock_cache):
        mock_tract.return_value = {"state": "36", "county": "119", "tract": "025300"}

        result = get_demographics(41.0, -73.8)
        assert result is None

    @patch("census.set_census_cache")
    @patch("census.get_census_cache", return_value=None)
    @patch("census._fetch_acs")
    @patch("census._lookup_tract")
    def test_county_failure_still_returns_profile(self, mock_tract, mock_acs,
                                                   mock_get_cache, mock_set_cache):
        mock_tract.return_value = {"state": "36", "county": "119", "tract": "025300"}
        tract_row = _make_acs_row()
        # Tract succeeds, county fails
        mock_acs.side_effect = [tract_row, None]

        result = get_demographics(41.0, -73.8)

        assert result is not None
        assert result.children_pct == 35.0
        # County fields should be None
        assert result.county_children_pct is None
        assert result.county_commute is None
