"""
Community Profile — Census ACS 5-year demographic data for property context.

Fetches tract-level demographic data from the US Census Bureau ACS 5-Year
API for four tables: B11005 (households with children), B25003 (tenure),
B08301 (commute mode), B25064 (median gross rent).  Compares tract-level
data to county-level reference to provide contextual framing.

Geocode-to-tract mapping uses the FCC Area API (primary) with Census
Geocoder as fallback.

Data source:
  - US Census Bureau ACS 5-Year Estimates (api.census.gov)
  - FCC Area API (geo.fcc.gov) for tract lookup
  - Census Geocoder (geocoding.geo.census.gov) as fallback

Limitations:
  - ACS 5-year estimates are rolling averages, not point-in-time snapshots.
    The most recent data lags ~2 years behind the current date.
  - Tract boundaries may not align perfectly with perceived neighborhoods.
  - Small tracts may have high margins of error on some estimates.
  - Median rent reflects all rental units in the tract, not units matching
    the specific listing's size or type.

Fair Housing guardrail:
  - This data is purely informational and NEVER used in scoring.
  - Narrative uses context-not-judgment framing: percentages and county
    comparisons only, no characterizations of desirability.
"""

import json
import logging
import os
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
_FCC_AREA_API = "https://geo.fcc.gov/api/census/area"
_CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
_ACS_BASE = "https://api.census.gov/data/2022/acs/acs5"

# Timeouts (seconds)
_FCC_TIMEOUT = 10
_CENSUS_GEO_TIMEOUT = 10
_ACS_TIMEOUT = 15

# Census missing-data sentinel
_CENSUS_MISSING = "-666666666"

# ACS variables to fetch — shared between tract and county queries
_ACS_VARS = [
    # B11005 — households with children under 18
    "B11005_001E",  # total households
    "B11005_002E",  # households with children under 18
    # B25003 — tenure (owner vs. renter)
    "B25003_001E",  # total occupied units
    "B25003_002E",  # owner-occupied
    "B25003_003E",  # renter-occupied
    # B08301 — commute mode
    "B08301_001E",  # total workers 16+
    "B08301_003E",  # drive alone
    "B08301_004E",  # carpool
    "B08301_010E",  # public transit
    "B08301_018E",  # bicycle
    "B08301_019E",  # walk
    "B08301_021E",  # work from home
    # B25064 — median gross rent
    "B25064_001E",  # median gross rent (dollars)
]


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CommuteBreakdown:
    """Commute mode percentages for a geography."""
    drive_alone_pct: float = 0.0
    carpool_pct: float = 0.0
    transit_pct: float = 0.0
    walk_pct: float = 0.0
    bike_pct: float = 0.0
    wfh_pct: float = 0.0


@dataclass
class CensusProfile:
    """Tract-level demographic profile with county comparison.

    All percentages are 0–100 floats.  Dollar values are integers.
    County-level fields are Optional because county fetch may fail
    independently of tract fetch.
    """
    # Tract identifiers
    state_fips: str = ""
    county_fips: str = ""
    tract_code: str = ""
    geoid: str = ""  # full 11-digit tract GEOID

    # B11005 — households with children
    total_households: int = 0
    households_with_children: int = 0
    children_pct: float = 0.0

    # B25003 — tenure
    total_occupied: int = 0
    owner_occupied: int = 0
    renter_occupied: int = 0
    owner_pct: float = 0.0
    renter_pct: float = 0.0

    # B08301 — commute mode
    total_commuters: int = 0
    commute: CommuteBreakdown = field(default_factory=CommuteBreakdown)

    # B25064 — median gross rent
    median_rent: Optional[int] = None

    # County reference (for comparison framing)
    county_name: str = ""
    county_children_pct: Optional[float] = None
    county_owner_pct: Optional[float] = None
    county_renter_pct: Optional[float] = None
    county_commute: Optional[CommuteBreakdown] = None
    county_median_rent: Optional[int] = None


# =============================================================================
# CACHE KEY GENERATION
# =============================================================================

def _tract_cache_key(state: str, county: str, tract: str) -> str:
    """Cache key from tract FIPS components.  Exact, not rounded."""
    return f"tract:{state}{county}{tract}"


def _county_cache_key(state: str, county: str) -> str:
    """Cache key for county-level reference data."""
    return f"county:{state}{county}"


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


def _safe_pct(numerator: Optional[int], denominator: Optional[int]) -> float:
    """Compute percentage, returning 0.0 if denominator is zero or None."""
    if denominator is None or denominator == 0:
        return 0.0
    if numerator is None:
        return 0.0
    return round((numerator / denominator) * 100, 1)


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
# GEOCODE → CENSUS TRACT LOOKUP
# =============================================================================

def _lookup_tract_fcc(lat: float, lng: float) -> Optional[Dict[str, str]]:
    """Primary: FCC Area API → {state, county, tract} dict or None."""
    t0 = time.time()
    params = {
        "lat": lat,
        "lon": lng,
        "censusYear": "2020",
        "format": "json",
    }
    try:
        resp = requests.get(_FCC_AREA_API, params=params, timeout=_FCC_TIMEOUT)
        _record_api("fcc_area", "census/area", t0, resp.status_code, resp.ok)

        if not resp.ok:
            logger.warning("FCC Area API returned %d", resp.status_code)
            return None

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return None

        # block_fips = SSCCCTTTTTTBBBB (15 chars)
        block_fips = results[0].get("block_fips", "")
        if len(block_fips) < 11:
            return None

        return {
            "state": block_fips[:2],
            "county": block_fips[2:5],
            "tract": block_fips[5:11],
        }

    except requests.Timeout:
        _record_api("fcc_area", "census/area", t0, 0, False, "timeout")
        logger.warning("FCC Area API timed out for (%.4f, %.4f)", lat, lng)
        return None
    except Exception:
        _record_api("fcc_area", "census/area", t0, 0, False, "exception")
        logger.warning("FCC Area API failed for (%.4f, %.4f)", lat, lng,
                        exc_info=True)
        return None


def _lookup_tract_census(lat: float, lng: float) -> Optional[Dict[str, str]]:
    """Fallback: Census Geocoder → {state, county, tract} dict or None."""
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
        tracts = geographies.get("Census Tracts", [])
        if not tracts:
            return None

        t = tracts[0]
        return {
            "state": t.get("STATE", ""),
            "county": t.get("COUNTY", ""),
            "tract": t.get("TRACT", ""),
        }

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


def _lookup_tract(lat: float, lng: float) -> Optional[Dict[str, str]]:
    """Resolve lat/lng to census tract.  FCC primary, Census Geocoder fallback."""
    result = _lookup_tract_fcc(lat, lng)
    if result and result["state"] and result["county"] and result["tract"]:
        return result
    logger.info("FCC Area API miss, trying Census Geocoder fallback")
    return _lookup_tract_census(lat, lng)


# =============================================================================
# ACS DATA FETCH
# =============================================================================

def _fetch_acs(state: str, county: str, api_key: str,
               tract: Optional[str] = None) -> Optional[dict]:
    """Fetch ACS 5-year estimates for a tract or county.

    When tract is provided, fetches tract-level data.
    When tract is None, fetches county-level data.
    Returns a dict mapping variable names to values, or None on failure.
    """
    variables = ",".join(_ACS_VARS)
    params: Dict[str, str] = {"get": f"NAME,{variables}"}

    if tract:
        params["for"] = f"tract:{tract}"
        params["in"] = f"state:{state} county:{county}"
        label = f"tract {state}{county}{tract}"
        endpoint = "acs5/tract"
    else:
        params["for"] = f"county:{county}"
        params["in"] = f"state:{state}"
        label = f"county {state}{county}"
        endpoint = "acs5/county"

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
# PARSING — raw ACS row → structured dict
# =============================================================================

def _parse_acs_row(row: dict) -> dict:
    """Parse raw ACS row into structured demographic fields.

    Returns a plain dict (not CensusProfile) to allow reuse for both
    tract and county parsing.
    """
    total_hh = _safe_int(row.get("B11005_001E"), 0)
    hh_children = _safe_int(row.get("B11005_002E"), 0)

    total_occ = _safe_int(row.get("B25003_001E"), 0)
    owner = _safe_int(row.get("B25003_002E"), 0)
    renter = _safe_int(row.get("B25003_003E"), 0)

    total_comm = _safe_int(row.get("B08301_001E"), 0)
    drive_alone = _safe_int(row.get("B08301_003E"), 0)
    carpool = _safe_int(row.get("B08301_004E"), 0)
    transit = _safe_int(row.get("B08301_010E"), 0)
    bike = _safe_int(row.get("B08301_018E"), 0)
    walk = _safe_int(row.get("B08301_019E"), 0)
    wfh = _safe_int(row.get("B08301_021E"), 0)

    median_rent = _safe_int(row.get("B25064_001E"))

    return {
        "total_households": total_hh,
        "households_with_children": hh_children,
        "children_pct": _safe_pct(hh_children, total_hh),
        "total_occupied": total_occ,
        "owner_occupied": owner,
        "renter_occupied": renter,
        "owner_pct": _safe_pct(owner, total_occ),
        "renter_pct": _safe_pct(renter, total_occ),
        "total_commuters": total_comm,
        "commute": CommuteBreakdown(
            drive_alone_pct=_safe_pct(drive_alone, total_comm),
            carpool_pct=_safe_pct(carpool, total_comm),
            transit_pct=_safe_pct(transit, total_comm),
            walk_pct=_safe_pct(walk, total_comm),
            bike_pct=_safe_pct(bike, total_comm),
            wfh_pct=_safe_pct(wfh, total_comm),
        ),
        "median_rent": median_rent,
    }


# =============================================================================
# PUBLIC API
# =============================================================================

def get_demographics(lat: float, lng: float) -> Optional[CensusProfile]:
    """Fetch Census ACS demographic profile for a location.

    Steps:
      1. Resolve lat/lng → census tract (FCC primary, Census Geocoder fallback)
      2. Check cache for tract data (90-day TTL)
      3. Fetch tract-level ACS data from Census API
      4. Fetch county-level reference data (separate cache key, also 90-day TTL)
      5. Combine into CensusProfile dataclass

    Returns None on any failure — demographics is optional context.
    """
    api_key = os.environ.get("CENSUS_API_KEY", "")
    if not api_key and not getattr(get_demographics, "_warned_no_key", False):
        logger.info("CENSUS_API_KEY not set; ACS requests limited to 500/day")
        get_demographics._warned_no_key = True  # type: ignore[attr-defined]

    # Step 1: Resolve to tract
    tract_info = _lookup_tract(lat, lng)
    if not tract_info:
        logger.info("Could not resolve (%.4f, %.4f) to a census tract", lat, lng)
        return None

    state = tract_info["state"]
    county = tract_info["county"]
    tract = tract_info["tract"]

    # Step 2: Check tract cache
    tract_key = _tract_cache_key(state, county, tract)
    cached = get_census_cache(tract_key)
    if cached is not None:
        try:
            return _deserialize(json.loads(cached))
        except Exception:
            logger.warning("Failed to deserialize cached census data",
                           exc_info=True)

    # Step 3: Fetch tract data
    tract_row = _fetch_acs(state, county, api_key, tract=tract)
    if not tract_row:
        return None
    parsed = _parse_acs_row(tract_row)

    # Step 4: Fetch county reference (may be cached separately)
    county_key = _county_cache_key(state, county)
    county_cached = get_census_cache(county_key)
    county_parsed = None
    county_name = ""

    if county_cached:
        try:
            county_data = json.loads(county_cached)
            county_parsed = county_data.get("parsed")
            county_name = county_data.get("name", "")
        except Exception:
            pass

    if county_parsed is None:
        county_row = _fetch_acs(state, county, api_key, tract=None)
        if county_row:
            county_parsed = _parse_acs_row(county_row)
            # NAME comes back as "Westchester County, New York"
            county_name = county_row.get("NAME", "").split(",")[0]
            # Serialize commute for JSON storage
            cp = county_parsed.copy()
            cp["commute"] = _serialize_commute(cp["commute"])
            try:
                set_census_cache(county_key, json.dumps({
                    "parsed": cp,
                    "name": county_name,
                }))
            except Exception:
                logger.warning("Failed to cache county census data",
                               exc_info=True)
    else:
        # Reconstruct CommuteBreakdown from cached dict
        commute_data = county_parsed.get("commute", {})
        if isinstance(commute_data, dict):
            county_parsed["commute"] = CommuteBreakdown(**commute_data)

    # Step 5: Build CensusProfile
    profile = CensusProfile(
        state_fips=state,
        county_fips=county,
        tract_code=tract,
        geoid=f"{state}{county}{tract}",
        total_households=parsed["total_households"],
        households_with_children=parsed["households_with_children"],
        children_pct=parsed["children_pct"],
        total_occupied=parsed["total_occupied"],
        owner_occupied=parsed["owner_occupied"],
        renter_occupied=parsed["renter_occupied"],
        owner_pct=parsed["owner_pct"],
        renter_pct=parsed["renter_pct"],
        total_commuters=parsed["total_commuters"],
        commute=parsed["commute"],
        median_rent=parsed["median_rent"],
        county_name=county_name,
    )

    if county_parsed:
        profile.county_children_pct = county_parsed["children_pct"]
        profile.county_owner_pct = county_parsed["owner_pct"]
        profile.county_renter_pct = county_parsed["renter_pct"]
        profile.county_median_rent = county_parsed["median_rent"]
        commute_val = county_parsed["commute"]
        if isinstance(commute_val, CommuteBreakdown):
            profile.county_commute = commute_val
        elif isinstance(commute_val, dict):
            profile.county_commute = CommuteBreakdown(**commute_val)

    # Cache the full profile
    try:
        set_census_cache(tract_key, json.dumps(_serialize(profile)))
    except Exception:
        logger.warning("Failed to cache census profile", exc_info=True)

    return profile


# =============================================================================
# SERIALIZATION — for cache storage and result_to_dict
# =============================================================================

def _serialize_commute(c: CommuteBreakdown) -> dict:
    """Convert CommuteBreakdown to a plain dict."""
    return {
        "drive_alone_pct": c.drive_alone_pct,
        "carpool_pct": c.carpool_pct,
        "transit_pct": c.transit_pct,
        "walk_pct": c.walk_pct,
        "bike_pct": c.bike_pct,
        "wfh_pct": c.wfh_pct,
    }


def _serialize(profile: CensusProfile) -> dict:
    """Convert CensusProfile to a plain dict for JSON storage."""
    return {
        "state_fips": profile.state_fips,
        "county_fips": profile.county_fips,
        "tract_code": profile.tract_code,
        "geoid": profile.geoid,
        "total_households": profile.total_households,
        "households_with_children": profile.households_with_children,
        "children_pct": profile.children_pct,
        "total_occupied": profile.total_occupied,
        "owner_occupied": profile.owner_occupied,
        "renter_occupied": profile.renter_occupied,
        "owner_pct": profile.owner_pct,
        "renter_pct": profile.renter_pct,
        "total_commuters": profile.total_commuters,
        "commute": _serialize_commute(profile.commute),
        "median_rent": profile.median_rent,
        "county_name": profile.county_name,
        "county_children_pct": profile.county_children_pct,
        "county_owner_pct": profile.county_owner_pct,
        "county_renter_pct": profile.county_renter_pct,
        "county_commute": (
            _serialize_commute(profile.county_commute)
            if profile.county_commute else None
        ),
        "county_median_rent": profile.county_median_rent,
    }


def _deserialize_commute(data: dict) -> CommuteBreakdown:
    """Reconstruct CommuteBreakdown from a plain dict."""
    return CommuteBreakdown(
        drive_alone_pct=data.get("drive_alone_pct", 0.0),
        carpool_pct=data.get("carpool_pct", 0.0),
        transit_pct=data.get("transit_pct", 0.0),
        walk_pct=data.get("walk_pct", 0.0),
        bike_pct=data.get("bike_pct", 0.0),
        wfh_pct=data.get("wfh_pct", 0.0),
    )


def _deserialize(data: dict) -> CensusProfile:
    """Reconstruct CensusProfile from a plain dict (cache hit)."""
    commute = _deserialize_commute(data.get("commute", {}))
    county_commute_data = data.get("county_commute")
    county_commute = (
        _deserialize_commute(county_commute_data)
        if county_commute_data else None
    )

    return CensusProfile(
        state_fips=data.get("state_fips", ""),
        county_fips=data.get("county_fips", ""),
        tract_code=data.get("tract_code", ""),
        geoid=data.get("geoid", ""),
        total_households=data.get("total_households", 0),
        households_with_children=data.get("households_with_children", 0),
        children_pct=data.get("children_pct", 0.0),
        total_occupied=data.get("total_occupied", 0),
        owner_occupied=data.get("owner_occupied", 0),
        renter_occupied=data.get("renter_occupied", 0),
        owner_pct=data.get("owner_pct", 0.0),
        renter_pct=data.get("renter_pct", 0.0),
        total_commuters=data.get("total_commuters", 0),
        commute=commute,
        median_rent=data.get("median_rent"),
        county_name=data.get("county_name", ""),
        county_children_pct=data.get("county_children_pct"),
        county_owner_pct=data.get("county_owner_pct"),
        county_renter_pct=data.get("county_renter_pct"),
        county_commute=county_commute,
        county_median_rent=data.get("county_median_rent"),
    )


def serialize_for_result(profile: Optional[CensusProfile]) -> Optional[dict]:
    """Serialize CensusProfile for result_to_dict output.

    Public helper called from app.py.  Returns None when profile is absent
    (API failure / old snapshots), which hides the section in the template.
    """
    if not profile:
        return None
    return _serialize(profile)
