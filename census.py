"""
Community Profile — Census ACS 5-year demographic data for property context.

Fetches city/place-level demographic data from the US Census Bureau ACS
5-Year API for five tables: B01003 (population), B11001 (households),
B19013 (median household income), B01002 (median age), B25003 (tenure).

Place-level geography (city, town, village, CDP) is resolved via the
Census Geocoder, which returns Incorporated Places and Census Designated
Places from coordinates.

Data source:
  - US Census Bureau ACS 5-Year Estimates (api.census.gov)
  - Census Geocoder (geocoding.geo.census.gov) for place lookup

Limitations:
  - ACS 5-year estimates are rolling averages, not point-in-time snapshots.
    The most recent data lags ~2 years behind the current date.
  - Addresses in unincorporated areas may not fall within any Census Place;
    in that case get_demographics() returns None and the section is hidden.
  - Very small places may lack ACS 5-year estimates.

Fair Housing guardrail:
  - This data is purely informational and NEVER used in scoring.
  - Narrative uses context-not-judgment framing: counts and dollar values
    only, no characterizations of desirability.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any

import requests
from models import get_census_cache, set_census_cache
from nc_trace import get_trace

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# API endpoints
_CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
# Pinned to 2022 vintage — the most recent ACS 5-year estimates available.
# Bump when Census releases the next vintage (typically late in the following
# year), then verify all _ACS_PLACE_VARS still exist in the new schema.
_ACS_BASE = "https://api.census.gov/data/2022/acs/acs5"

# Timeouts (seconds)
_CENSUS_GEO_TIMEOUT = 10
_ACS_TIMEOUT = 15

# Census missing-data sentinel
_CENSUS_MISSING = "-666666666"

# ACS variables for place-level queries (NES-257)
_ACS_PLACE_VARS = [
    # B01003 — total population
    "B01003_001E",
    # B11001 — households
    "B11001_001E",  # total households
    # B19013 — median household income
    "B19013_001E",
    # B01002 — median age
    "B01002_001E",
    # B25003 — tenure (owner vs. renter)
    "B25003_001E",  # total occupied units
    "B25003_002E",  # owner-occupied
    "B25003_003E",  # renter-occupied
]

# Suffix patterns stripped from Census place/subdivision names for display
_PLACE_NAME_SUFFIXES = re.compile(
    r"\s+(city|town|charter township|township|village|borough|CDP|"
    r"municipality|plantation|comunidad|zona urbana)$",
    re.IGNORECASE,
)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CityProfile:
    """City/place-level demographic profile from Census ACS 5-Year.

    All percentages are 0-100 floats.  Dollar values are integers.
    """
    state_fips: str = ""
    place_fips: str = ""
    place_name: str = ""  # cleaned display name (e.g., "Novi")

    # B01003 — population
    population: int = 0

    # B11001 — households
    total_households: int = 0

    # B19013 — median household income
    median_household_income: Optional[int] = None

    # B01002 — median age
    median_age: Optional[float] = None

    # B25003 — tenure
    total_occupied: int = 0
    owner_occupied: int = 0
    renter_occupied: int = 0
    owner_pct: float = 0.0
    renter_pct: float = 0.0


# =============================================================================
# CACHE KEY GENERATION
# =============================================================================

def _place_cache_key(state: str, place: str,
                     geo_type: str = "place",
                     county: Optional[str] = None) -> str:
    """Cache key for place or county-subdivision level data.

    COUSUB FIPS codes are unique within a county but not within a state,
    so county must be part of the key for county_subdivision entries.
    """
    if geo_type == "county_subdivision" and county:
        return f"{geo_type}:{state}{county}{place}"
    return f"{geo_type}:{state}{place}"


# =============================================================================
# HELPERS
# =============================================================================

def _safe_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    """Convert Census API value to int, handling missing-data sentinel."""
    if val is None or str(val) == _CENSUS_MISSING or val == "":
        return default
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """Convert Census API value to float, handling missing-data sentinel."""
    if val is None or str(val) == _CENSUS_MISSING or val == "":
        return default
    try:
        return round(float(val), 1)
    except (TypeError, ValueError):
        return default


def _safe_pct(numerator: Optional[int], denominator: Optional[int]) -> float:
    """Compute percentage, returning 0.0 if denominator is zero or None."""
    if denominator is None or denominator == 0:
        return 0.0
    if numerator is None:
        return 0.0
    return round((numerator / denominator) * 100, 1)


def _clean_place_name(raw_name: str) -> str:
    """Strip Census place-type suffixes for display.

    Census returns names like "Novi city", "Greenwich town",
    "Hoboken city".  Strip the trailing type word.
    """
    cleaned = _PLACE_NAME_SUFFIXES.sub("", raw_name.strip())
    return cleaned or raw_name.strip()


def _record_api(service: str, endpoint: str, t0: float,
                status_code: int, ok: bool, note: str = "") -> None:
    """Record an API call to trace and health monitor."""
    elapsed_ms = (time.time() - t0) * 1000
    trace = get_trace()
    if trace:
        trace.record_api_call(
            service=service,
            endpoint=endpoint,
            elapsed_ms=elapsed_ms,
            status_code=status_code,
            provider_status="OK" if ok else (note or "ERROR"),
        )
    try:
        from health_monitor import record_call
        record_call(service, ok, int(elapsed_ms), note or None)
    except Exception:
        pass


# =============================================================================
# GEOCODE → CENSUS PLACE LOOKUP
# =============================================================================

def _lookup_place(lat: float, lng: float) -> Optional[Dict[str, str]]:
    """Resolve lat/lng to a Census geography via Census Geocoder.

    Tries three geography layers in order of specificity:
      1. Incorporated Places (cities)
      2. Census Designated Places (CDPs — named unincorporated communities)
      3. County Subdivisions (townships, towns — common in MI, NJ, NY, CT)

    Returns a dict with keys:
      - state: state FIPS code
      - place: place or COUSUB FIPS code
      - name: display name from Census
      - geo_type: "place" or "county_subdivision" (determines ACS query)
      - county: county FIPS (only for county_subdivision)
    or None if no matching geography is found.
    """
    t0 = time.time()
    params = {
        "x": lng,
        "y": lat,
        "benchmark": "Public_AR_Current",
        "vintage": "Census2020_Current",
        "format": "json",
    }
    try:
        resp = requests.get(
            _CENSUS_GEOCODER, params=params, timeout=_CENSUS_GEO_TIMEOUT,
        )
        _record_api("census_geocoder", "geographies/coordinates", t0,
                     resp.status_code, resp.ok)

        if not resp.ok:
            logger.warning("Census Geocoder returned %d", resp.status_code)
            return None

        data = resp.json()
        geographies = data.get("result", {}).get("geographies", {})

        # Try Incorporated Places first, then Census Designated Places
        for geo_key in ("Incorporated Places", "Census Designated Places"):
            places = geographies.get(geo_key, [])
            if places:
                p = places[0]
                state = p.get("STATE", "")
                place = p.get("PLACE", "")
                name = p.get("NAME", "")
                if state and place:
                    return {
                        "state": state,
                        "place": place,
                        "name": name,
                        "geo_type": "place",
                    }

        # Fallback: County Subdivisions (townships in MI, NJ, NY, CT, etc.)
        cousubs = geographies.get("County Subdivisions", [])
        if cousubs:
            cs = cousubs[0]
            state = cs.get("STATE", "")
            cousub = cs.get("COUSUB", "")
            county = cs.get("COUNTY", "")
            name = cs.get("NAME", cs.get("BASENAME", ""))
            if state and cousub and county:
                return {
                    "state": state,
                    "place": cousub,
                    "name": name,
                    "geo_type": "county_subdivision",
                    "county": county,
                }

        logger.info("No Census Place or subdivision found for (%.4f, %.4f)",
                     lat, lng)
        return None

    except requests.Timeout:
        _record_api("census_geocoder", "geographies/coordinates", t0,
                     0, False, "timeout")
        logger.warning("Census Geocoder timed out for (%.4f, %.4f)", lat, lng)
        return None
    except Exception:
        _record_api("census_geocoder", "geographies/coordinates", t0,
                     0, False, "exception")
        logger.warning("Census Geocoder failed for (%.4f, %.4f)", lat, lng,
                        exc_info=True)
        return None


# =============================================================================
# ACS DATA FETCH
# =============================================================================

def _fetch_acs_place(state: str, place: str, api_key: str,
                     geo_type: str = "place",
                     county: Optional[str] = None) -> Optional[dict]:
    """Fetch ACS 5-year estimates for a Census Place or County Subdivision.

    Args:
        geo_type: "place" for incorporated places/CDPs, or
                  "county_subdivision" for townships/towns.
        county: Required when geo_type is "county_subdivision".

    Returns a dict mapping variable names to values, or None on failure.
    """
    variables = ",".join(_ACS_PLACE_VARS)
    params: Dict[str, str] = {"get": f"NAME,{variables}"}

    if geo_type == "county_subdivision":
        if not county:
            logger.warning("county_subdivision geo_type requires county; "
                           "got %r for place %s", county, place)
            return None
        params["for"] = f"county subdivision:{place}"
        params["in"] = f"state:{state} county:{county}"
        label = f"cousub {state}{county}{place}"
        endpoint = "acs5/cousub"
    else:
        params["for"] = f"place:{place}"
        params["in"] = f"state:{state}"
        label = f"place {state}{place}"
        endpoint = "acs5/place"

    if api_key:
        params["key"] = api_key

    t0 = time.time()
    try:
        resp = requests.get(_ACS_BASE, params=params, timeout=_ACS_TIMEOUT)
        _record_api("census_acs", endpoint, t0, resp.status_code, resp.ok)

        if not resp.ok:
            logger.warning("Census ACS API returned %d for %s",
                           resp.status_code, label)
            return None

        data = resp.json()
        if not data or len(data) < 2:
            return None

        headers = data[0]
        return dict(zip(headers, data[1]))

    except requests.Timeout:
        _record_api("census_acs", endpoint, t0, 0, False, "timeout")
        logger.warning("Census ACS API timed out for %s", label)
        return None
    except Exception:
        _record_api("census_acs", endpoint, t0, 0, False, "exception")
        logger.warning("Census ACS API failed for %s", label, exc_info=True)
        return None


# =============================================================================
# PARSING — raw ACS row → CityProfile
# =============================================================================

def _parse_place_row(row: dict) -> dict:
    """Parse raw ACS place-level row into structured fields."""
    population = _safe_int(row.get("B01003_001E"), 0)
    total_hh = _safe_int(row.get("B11001_001E"), 0)
    median_income = _safe_int(row.get("B19013_001E"))
    median_age = _safe_float(row.get("B01002_001E"))

    total_occ = _safe_int(row.get("B25003_001E"), 0)
    owner = _safe_int(row.get("B25003_002E"), 0)
    renter = _safe_int(row.get("B25003_003E"), 0)

    return {
        "population": population,
        "total_households": total_hh,
        "median_household_income": median_income,
        "median_age": median_age,
        "total_occupied": total_occ,
        "owner_occupied": owner,
        "renter_occupied": renter,
        "owner_pct": _safe_pct(owner, total_occ),
        "renter_pct": _safe_pct(renter, total_occ),
    }


# =============================================================================
# PUBLIC API
# =============================================================================

def get_demographics(lat: float, lng: float) -> Optional[CityProfile]:
    """Fetch Census ACS demographic profile for a location.

    Resolves the address to the most specific Census geography available:
    Incorporated Place → Census Designated Place → County Subdivision
    (township/town).  This covers cities, CDPs, and unincorporated
    townships (common in MI, NJ, NY, CT).

    Returns None on any failure — demographics is optional context.
    """
    api_key = os.environ.get("CENSUS_API_KEY", "")
    if not api_key and not getattr(get_demographics, "_warned_no_key", False):
        logger.info("CENSUS_API_KEY not set; ACS requests limited to 500/day")
        get_demographics._warned_no_key = True  # type: ignore[attr-defined]

    # Step 1: Resolve to Census Place or County Subdivision
    place_info = _lookup_place(lat, lng)
    if not place_info:
        logger.info("Could not resolve (%.4f, %.4f) to a Census geography",
                     lat, lng)
        return None

    state = place_info["state"]
    place = place_info["place"]
    raw_name = place_info["name"]
    geo_type = place_info.get("geo_type", "place")
    county = place_info.get("county")

    # Step 2: Check cache
    cache_key = _place_cache_key(state, place, geo_type, county)
    cached = get_census_cache(cache_key)
    if cached is not None:
        try:
            return _deserialize_city(json.loads(cached))
        except Exception:
            logger.warning("Failed to deserialize cached city census data",
                           exc_info=True)

    # Step 3: Fetch ACS data for the resolved geography
    row = _fetch_acs_place(state, place, api_key,
                           geo_type=geo_type, county=county)
    if not row:
        return None
    parsed = _parse_place_row(row)

    # Step 4: Build CityProfile
    profile = CityProfile(
        state_fips=state,
        place_fips=place,
        place_name=_clean_place_name(raw_name),
        population=parsed["population"],
        total_households=parsed["total_households"],
        median_household_income=parsed["median_household_income"],
        median_age=parsed["median_age"],
        total_occupied=parsed["total_occupied"],
        owner_occupied=parsed["owner_occupied"],
        renter_occupied=parsed["renter_occupied"],
        owner_pct=parsed["owner_pct"],
        renter_pct=parsed["renter_pct"],
    )

    # Cache the profile
    try:
        set_census_cache(cache_key, json.dumps(_serialize_city(profile)))
    except Exception:
        logger.warning("Failed to cache city census profile", exc_info=True)

    return profile


# =============================================================================
# SERIALIZATION — for cache storage and result_to_dict
# =============================================================================

def _serialize_city(profile: CityProfile) -> dict:
    """Convert CityProfile to a plain dict for JSON storage."""
    return {
        "state_fips": profile.state_fips,
        "place_fips": profile.place_fips,
        "place_name": profile.place_name,
        "population": profile.population,
        "total_households": profile.total_households,
        "median_household_income": profile.median_household_income,
        "median_age": profile.median_age,
        "total_occupied": profile.total_occupied,
        "owner_occupied": profile.owner_occupied,
        "renter_occupied": profile.renter_occupied,
        "owner_pct": profile.owner_pct,
        "renter_pct": profile.renter_pct,
    }


def _deserialize_city(data: dict) -> CityProfile:
    """Reconstruct CityProfile from a plain dict (cache hit)."""
    return CityProfile(
        state_fips=data.get("state_fips", ""),
        place_fips=data.get("place_fips", ""),
        place_name=data.get("place_name", ""),
        population=data.get("population", 0),
        total_households=data.get("total_households", 0),
        median_household_income=data.get("median_household_income"),
        median_age=data.get("median_age"),
        total_occupied=data.get("total_occupied", 0),
        owner_occupied=data.get("owner_occupied", 0),
        renter_occupied=data.get("renter_occupied", 0),
        owner_pct=data.get("owner_pct", 0.0),
        renter_pct=data.get("renter_pct", 0.0),
    )


def serialize_for_result(profile: Optional[CityProfile]) -> Optional[dict]:
    """Serialize CityProfile for result_to_dict output.

    Public helper called from app.py.  Returns None when profile is absent
    (API failure / old snapshots), which hides the section in the template.
    """
    if not profile:
        return None
    return _serialize_city(profile)
