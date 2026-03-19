"""
Coverage manifest for NestCheck.

Declares per-state, per-source data availability so the /coverage page,
report-level badges, and internal diagnostics can report honestly about
what backs each evaluation.

Statuses are grounded in the actual spatial.db contents as of 2026-03-18.
Update this file whenever a new state is onboarded or a dataset is ingested.
"""

import logging
import os
import re
import sqlite3
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nestcheck.coverage_config")


# =============================================================================
# Enums
# =============================================================================

class CoverageTier(str, Enum):
    """Rollup of source-level statuses into a dimension-level tier."""
    FULL = "full"           # All sources for this dimension are active
    PARTIAL = "partial"     # >50% of sources active
    MINIMAL = "minimal"     # Any source active but <=50%
    NONE = "none"           # No sources active


# Tier severity ordering for weakest-link comparisons (higher = worse).
_TIER_ORDER = {
    CoverageTier.FULL: 0,
    CoverageTier.PARTIAL: 1,
    CoverageTier.MINIMAL: 2,
    CoverageTier.NONE: 3,
}


class SourceStatus(str, Enum):
    """Status of a single data source for a given state."""
    ACTIVE = "active"           # Table exists, has rows for this state
    INTENDED = "intended"       # Table exists but 0 rows for this state
    PLANNED = "planned"         # State on roadmap, no ingestion attempted
    NOT_AVAILABLE = "not_available"  # Source doesn't apply to this state


# =============================================================================
# Dimension definitions
# =============================================================================

# Maps each source to its scoring/display dimension.
# "health" = Tier 1 safety checks, "education" = school context,
# "context" = informational area data (never scored).
DIMENSION_LABELS = {
    "health": "Health & Safety",
    "green_space": "Parks & Green Space",
    "transit": "Getting Around",
    "education": "Education",
    "context": "Area Context",
}


# =============================================================================
# Source display list (ordered for the /coverage page table)
# =============================================================================

# Ordered: Health first (grouped), then Education, then Context.
# Matches the report's visual hierarchy.
# INVARIANT: entries must be sorted by dimension group. The /coverage
# template generates colspan headers by detecting dimension transitions,
# which breaks silently if sources are interleaved across dimensions.
SOURCE_DISPLAY_LIST = [
    {"key": "SEMS", "name": "Superfund Sites", "dimension": "Health", "source_org": "EPA"},
    {"key": "EJSCREEN", "name": "Environmental Justice", "dimension": "Health", "source_org": "EPA"},
    {"key": "TRI", "name": "Toxic Releases", "dimension": "Health", "source_org": "EPA"},
    {"key": "UST", "name": "Storage Tanks", "dimension": "Health", "source_org": "EPA"},
    {"key": "HPMS", "name": "Traffic Counts", "dimension": "Health", "source_org": "FHWA"},
    {"key": "HIFLD", "name": "Power Lines", "dimension": "Health", "source_org": "DHS"},
    {"key": "FRA", "name": "Rail Lines", "dimension": "Health", "source_org": "FRA"},
    {"key": "FEMA_NFHL", "name": "Flood Zones", "dimension": "Health", "source_org": "FEMA"},
    {"key": "GOOGLE_PLACES_PARKS", "name": "Park & Green Space Venues", "dimension": "Parks", "source_org": "Google"},
    {"key": "GOOGLE_TRANSIT", "name": "Transit Stations & Routes", "dimension": "Transit", "source_org": "Google"},
    {"key": "OVERPASS_SIDEWALKS", "name": "Sidewalk & Pedestrian Data", "dimension": "Transit", "source_org": "OSM"},
    {"key": "SCHOOL_DISTRICTS", "name": "School Districts", "dimension": "Education", "source_org": "Census"},
    {"key": "STATE_EDUCATION", "name": "School Performance", "dimension": "Education", "source_org": "State DOE"},
    {"key": "NCES_SCHOOLS", "name": "School Locations", "dimension": "Education", "source_org": "NCES"},
    {"key": "CENSUS_ACS", "name": "Demographics", "dimension": "Context", "source_org": "Census"},
]


# =============================================================================
# Source metadata (shared across all states)
# =============================================================================

_SOURCE_METADATA = {
    "SEMS": {
        "description": "EPA Superfund Sites (SEMS)",
        "table": "facilities_sems",
        "dimension": "health",
        "source_url": "https://www.epa.gov/superfund/search-superfund-sites-where-you-live",
        "state_filter": "json_extract(metadata_json, '$.state_code')",
        "state_key_format": "abbr",  # 2-letter code
        "notes": "Nationwide dataset — no state filter applied at ingest.",
    },
    "EJSCREEN": {
        "description": "EPA Environmental Justice Screening",
        "table": "facilities_ejscreen",
        "dimension": "health",
        "source_url": "https://www.epa.gov/ejscreen",
        "state_filter": "json_extract(metadata_json, '$.state')",
        "state_key_format": "abbr",
        "notes": "PEDP community mirror V2.32 (EPA endpoint removed Feb 2025).",
    },
    "TRI": {
        "description": "EPA Toxics Release Inventory",
        "table": "facilities_tri",
        "dimension": "health",
        "source_url": "https://www.epa.gov/toxics-release-inventory-tri-program",
        "state_filter": "json_extract(metadata_json, '$.state')",
        "state_key_format": "abbr",
        "notes": None,
    },
    "UST": {
        "description": "EPA Underground Storage Tanks",
        "table": "facilities_ust",
        "dimension": "health",
        "source_url": "https://www.epa.gov/ust",
        "state_filter": "json_extract(metadata_json, '$.state')",
        "state_key_format": "full_name",  # "New York"
        "notes": "UST state field uses full state names (e.g. 'New York'). Normalized at ingest time from ArcGIS no-space format.",
    },
    "HPMS": {
        "description": "Highway Performance Monitoring System (Traffic Counts)",
        "table": "facilities_hpms",
        "dimension": "health",
        "source_url": "https://www.fhwa.dot.gov/policyinformation/hpms.cfm",
        "state_filter": "json_extract(metadata_json, '$.state')",
        "state_key_format": "abbr",
        "notes": None,
    },
    "HIFLD": {
        "description": "Power Transmission Lines",
        "table": "facilities_hifld",
        "dimension": "health",
        "source_url": "https://hifld-geoplatform.opendata.arcgis.com/",
        "state_filter": None,  # bbox-filtered, no state column
        "spatial_filter_required": True,
        "notes": "Bbox-filtered to tri-state area (-75.6, 38.9, -71.8, 42.1).",
    },
    "FRA": {
        "description": "Freight Rail Network Lines",
        "table": "facilities_fra",
        "dimension": "health",
        "source_url": "https://geodata.bts.gov/datasets/north-american-rail-network-lines",
        "state_filter": None,
        "spatial_filter_required": True,
        "notes": "Bbox-filtered to tri-state area (-75.6, 38.9, -71.8, 42.1).",
    },
    "FEMA_NFHL": {
        "description": "FEMA Flood Zones (NFHL)",
        "table": "facilities_fema_nfhl",
        "dimension": "health",
        "source_url": "https://www.fema.gov/flood-maps/national-flood-hazard-layer",
        "state_filter": None,
        "spatial_filter_required": True,
        "notes": "Bbox-filtered to tri-state area, chunked 0.5° tiles.",
    },
    "SCHOOL_DISTRICTS": {
        "description": "Census TIGER School District Boundaries",
        "table": "facilities_school_districts",
        "dimension": "education",
        "source_url": "https://tigerweb.geo.census.gov/",
        "state_filter": "SUBSTR(json_extract(metadata_json, '$.geoid'), 1, 2)",
        "state_key_format": "fips",
        "notes": None,
    },
    "STATE_EDUCATION": {
        "description": "State Education Performance Data",
        "table": "state_education_performance",
        "dimension": "education",
        "source_url": None,  # varies by state
        "state_filter": "state",  # direct column
        "state_key_format": "abbr",
        "notes": "Per-state curated CSVs. Sources vary: NYSED, NJDOE, EdSight/CTData, CEPI.",
        "per_state_urls": {
            "NY": "https://data.nysed.gov/",
            "NJ": "https://www.nj.gov/education/spr/download/",
            "CT": "https://edsight.ct.gov/",
            "MI": "https://www.mischooldata.org/",
            "CA": "https://www.cde.ca.gov/ds/ad/fileslsafl.asp",
            "TX": "https://tea.texas.gov/reports-and-data",
            "FL": "https://edudata.fldoe.org",
            "IL": "https://www.isbe.net/ilreportcarddata",
        },
    },
    "NCES_SCHOOLS": {
        "description": "NCES Public School Locations (2022-23)",
        "table": "facilities_nces_schools",
        "dimension": "education",
        "source_url": "https://nces.ed.gov/ccd/schoolsearch/",
        "state_filter": "SUBSTR(json_extract(metadata_json, '$.leaid'), 1, 2)",
        "state_key_format": "fips",
        "notes": "2022-23 school year from EDGE open data.",
    },
    "GOOGLE_PLACES_PARKS": {
        "description": "Park & Green Space Venues (Google Places)",
        "table": None,  # fetched live via Google Places API
        "dimension": "green_space",
        "source_url": "https://developers.google.com/maps/documentation/places",
        "state_filter": None,
        "notes": "Fetched live per-evaluation via Google Places API. No spatial.db table.",
    },
    "GOOGLE_TRANSIT": {
        "description": "Transit Stations & Routes (Google Maps)",
        "table": None,  # fetched live via Google Maps API
        "dimension": "transit",
        "source_url": "https://developers.google.com/maps/documentation/directions",
        "state_filter": None,
        "notes": "Fetched live per-evaluation via Google Maps API. No spatial.db table.",
    },
    "OVERPASS_SIDEWALKS": {
        "description": "Sidewalk & Pedestrian Infrastructure (OpenStreetMap)",
        "table": None,  # fetched live via Overpass API
        "dimension": "transit",
        "source_url": "https://wiki.openstreetmap.org/wiki/Overpass_API",
        "state_filter": None,
        "notes": "Fetched live per-evaluation via Overpass API. No spatial.db table.",
    },
    "CENSUS_ACS": {
        "description": "Census American Community Survey (5-Year)",
        "table": None,  # fetched live via API, not in spatial.db
        "dimension": "context",
        "source_url": "https://www.census.gov/programs-surveys/acs",
        "state_filter": None,
        "notes": "Fetched live per-evaluation via Census API. No spatial.db table.",
    },
}

# Full state name mapping for UST (normalized at ingest time)
_STATE_FULL_NAME = {
    "NY": "New York",
    "NJ": "New Jersey",
    "CT": "Connecticut",
    "MI": "Michigan",
    "CA": "California",
    "TX": "Texas",
    "FL": "Florida",
    "IL": "Illinois",
}

# FIPS codes for states (for tables keyed by FIPS prefix)
_STATE_FIPS = {
    "NY": "36",
    "NJ": "34",
    "CT": "09",
    "MI": "26",
    "CA": "06",
    "TX": "48",
    "FL": "12",
    "IL": "17",
}


# =============================================================================
# Per-state manifest
# =============================================================================

# Status reflects actual spatial.db contents as of 2026-03-18.
# "active" = verified rows exist for this state
# "intended" = table exists, ingestion targets this state, but 0 rows currently
# "planned" = state on roadmap, no ingestion attempted yet

COVERAGE_MANIFEST: Dict[str, Dict[str, str]] = {
    # --- Supported states (have at least some active data) ---
    "NY": {
        "name": "New York",
        "SEMS": "active",           # 126 rows (nationwide, not state-filtered)
        "EJSCREEN": "active",       # 16,070 rows
        "TRI": "active",            # 581 rows
        "UST": "active",            # 200 rows
        "HPMS": "active",           # 277,751 rows
        "HIFLD": "active",          # bbox covers NY (2,126 total)
        "FRA": "active",            # bbox covers NY (9,832 total)
        "FEMA_NFHL": "active",      # bbox covers NY (17,907 total)
        "GOOGLE_PLACES_PARKS": "active",   # live API
        "GOOGLE_TRANSIT": "active",        # live API
        "OVERPASS_SIDEWALKS": "active",    # live API
        "SCHOOL_DISTRICTS": "active",  # 665 rows
        "STATE_EDUCATION": "active",   # 691 rows (NYSED)
        "NCES_SCHOOLS": "active",      # 4,835 rows
        "CENSUS_ACS": "active",        # live API
    },
    "NJ": {
        "name": "New Jersey",
        "SEMS": "active",           # 155 rows
        "EJSCREEN": "active",       # 6,599 rows
        "TRI": "active",            # 325 rows
        "UST": "intended",          # 0 rows — ingest targets NJ but no data loaded
        "HPMS": "active",           # 103,361 rows
        "HIFLD": "active",          # bbox covers NJ
        "FRA": "active",            # bbox covers NJ
        "FEMA_NFHL": "active",      # bbox covers NJ
        "GOOGLE_PLACES_PARKS": "active",   # live API
        "GOOGLE_TRANSIT": "active",        # live API
        "OVERPASS_SIDEWALKS": "active",    # live API
        "SCHOOL_DISTRICTS": "active",  # 342 rows
        "STATE_EDUCATION": "active",   # 25 rows (NJDOE)
        "NCES_SCHOOLS": "active",      # 2,566 rows
        "CENSUS_ACS": "active",
    },
    "CT": {
        "name": "Connecticut",
        "SEMS": "active",           # 17 rows
        "EJSCREEN": "active",       # 2,717 rows
        "TRI": "active",            # 257 rows
        "UST": "intended",          # 0 rows
        "HPMS": "active",           # 42,590 rows
        "HIFLD": "active",          # bbox covers CT
        "FRA": "active",            # bbox covers CT
        "FEMA_NFHL": "active",      # bbox covers CT
        "GOOGLE_PLACES_PARKS": "active",   # live API
        "GOOGLE_TRANSIT": "active",        # live API
        "OVERPASS_SIDEWALKS": "active",    # live API
        "SCHOOL_DISTRICTS": "active",  # 114 rows
        "STATE_EDUCATION": "active",   # 34 rows (EdSight/CTData)
        "NCES_SCHOOLS": "active",      # 1,022 rows
        "CENSUS_ACS": "active",
    },
    "MI": {
        "name": "Michigan",
        "SEMS": "active",           # 90 rows (nationwide dataset)
        "EJSCREEN": "intended",     # targeted but 0 rows
        "TRI": "intended",          # targeted but 0 rows
        "UST": "intended",          # targeted but 0 rows
        "HPMS": "intended",         # targeted but 0 rows
        "HIFLD": "planned",         # bbox doesn't cover MI
        "FRA": "planned",           # bbox doesn't cover MI
        "FEMA_NFHL": "active",      # Detroit metro bbox (NES-286)
        "GOOGLE_PLACES_PARKS": "active",   # live API
        "GOOGLE_TRANSIT": "active",        # live API
        "OVERPASS_SIDEWALKS": "active",    # live API
        "SCHOOL_DISTRICTS": "intended",  # targeted but 0 rows
        "STATE_EDUCATION": "active",     # 514 rows (CEPI)
        "NCES_SCHOOLS": "intended",      # targeted but 0 rows
        "CENSUS_ACS": "active",          # live API, works anywhere
    },
    # --- Expansion states (federal data + education onboarding) ---
    "CA": {
        "name": "California",
        "SEMS": "active",
        "EJSCREEN": "intended",
        "TRI": "intended",
        "UST": "intended",
        "HPMS": "intended",
        "HIFLD": "planned",
        "FRA": "planned",
        "FEMA_NFHL": "planned",
        "GOOGLE_PLACES_PARKS": "active",
        "GOOGLE_TRANSIT": "active",
        "OVERPASS_SIDEWALKS": "active",
        "SCHOOL_DISTRICTS": "intended",
        "STATE_EDUCATION": "intended",
        "NCES_SCHOOLS": "intended",
        "CENSUS_ACS": "active",
    },
    "TX": {
        "name": "Texas",
        "SEMS": "active",
        "EJSCREEN": "intended",
        "TRI": "intended",
        "UST": "intended",
        "HPMS": "intended",
        "HIFLD": "planned",
        "FRA": "planned",
        "FEMA_NFHL": "planned",
        "GOOGLE_PLACES_PARKS": "active",
        "GOOGLE_TRANSIT": "active",
        "OVERPASS_SIDEWALKS": "active",
        "SCHOOL_DISTRICTS": "intended",
        "STATE_EDUCATION": "intended",
        "NCES_SCHOOLS": "intended",
        "CENSUS_ACS": "active",
    },
    "FL": {
        "name": "Florida",
        "SEMS": "active",
        "EJSCREEN": "intended",
        "TRI": "intended",
        "UST": "intended",
        "HPMS": "intended",
        "HIFLD": "planned",
        "FRA": "planned",
        "FEMA_NFHL": "planned",
        "GOOGLE_PLACES_PARKS": "active",
        "GOOGLE_TRANSIT": "active",
        "OVERPASS_SIDEWALKS": "active",
        "SCHOOL_DISTRICTS": "intended",
        "STATE_EDUCATION": "intended",
        "NCES_SCHOOLS": "intended",
        "CENSUS_ACS": "active",
    },
    "IL": {
        "name": "Illinois",
        "SEMS": "active",
        "EJSCREEN": "intended",
        "TRI": "intended",
        "UST": "intended",
        "HPMS": "intended",
        "HIFLD": "planned",
        "FRA": "planned",
        "FEMA_NFHL": "planned",
        "GOOGLE_PLACES_PARKS": "active",
        "GOOGLE_TRANSIT": "active",
        "OVERPASS_SIDEWALKS": "active",
        "SCHOOL_DISTRICTS": "intended",
        "STATE_EDUCATION": "intended",
        "NCES_SCHOOLS": "intended",
        "CENSUS_ACS": "active",
    },
}

# Sources that every state gets an entry for (used to fill "planned" for
# coming-soon states that only have a name).
_ALL_SOURCES = [k for k in _SOURCE_METADATA]


# =============================================================================
# Helper functions
# =============================================================================

def get_source_metadata(source_key: str) -> Optional[dict]:
    """Return metadata dict for a source, or None if unknown."""
    return _SOURCE_METADATA.get(source_key)


def get_source_coverage(state_code: str) -> Dict[str, dict]:
    """Return per-source coverage detail for a state.

    Each entry includes status, description, source_url, and notes.
    Returns empty dict for unknown states.
    """
    state = COVERAGE_MANIFEST.get(state_code.upper())
    if not state:
        return {}

    result = {}
    for source_key, meta in _SOURCE_METADATA.items():
        status_str = state.get(source_key, "planned")
        result[source_key] = {
            "status": status_str,
            "description": meta["description"],
            "source_url": meta.get("source_url"),
            "dimension": meta["dimension"],
            "notes": meta.get("notes"),
            "table": meta.get("table"),
        }
        # Per-state source URL override (e.g. education)
        per_state_urls = meta.get("per_state_urls")
        if per_state_urls and state_code.upper() in per_state_urls:
            result[source_key]["source_url"] = per_state_urls[state_code.upper()]

    return result


def get_dimension_coverage(state_code: str) -> Dict[str, CoverageTier]:
    """Return {dimension_name: CoverageTier} for a given state.

    Rollup logic: count active vs total sources per dimension.
    All active → FULL, >50% → PARTIAL, any active → MINIMAL, none → NONE.
    """
    sources = get_source_coverage(state_code)
    if not sources:
        return {}

    # Group sources by dimension
    dim_counts: Dict[str, Tuple[int, int]] = {}  # {dim: (active, total)}
    for source_key, info in sources.items():
        dim = info["dimension"]
        active_count, total_count = dim_counts.get(dim, (0, 0))
        total_count += 1
        if info["status"] == SourceStatus.ACTIVE:
            active_count += 1
        dim_counts[dim] = (active_count, total_count)

    result = {}
    for dim, (active, total) in dim_counts.items():
        if active == total:
            result[dim] = CoverageTier.FULL
        elif active > total / 2:
            result[dim] = CoverageTier.PARTIAL
        elif active > 0:
            result[dim] = CoverageTier.MINIMAL
        else:
            result[dim] = CoverageTier.NONE

    return result


def get_all_states() -> List[dict]:
    """Return list of {code, name, status} for all states in manifest.

    status is 'supported' (any active sources) or 'coming_soon'.
    """
    states = []
    for code, state_data in COVERAGE_MANIFEST.items():
        name = state_data.get("name", code)
        # Check if any source is active
        has_active = any(
            state_data.get(src) == SourceStatus.ACTIVE
            for src in _ALL_SOURCES
        )
        states.append({
            "code": code,
            "name": name,
            "status": "supported" if has_active else "coming_soon",
        })
    return states


def get_dataset_registry() -> Dict[str, dict]:
    """Read the dataset_registry table from spatial.db for last-refreshed dates.

    Returns {facility_type: {source_url, ingested_at, record_count, notes}}.
    Returns empty dict if spatial.db is unavailable.
    """
    try:
        from spatial_data import _spatial_db_path
        db_path = _spatial_db_path()
        if not os.path.exists(db_path):
            return {}
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM dataset_registry").fetchall()
        conn.close()
        return {
            row["facility_type"]: {
                "source_url": row["source_url"],
                "ingested_at": row["ingested_at"],
                "record_count": row["record_count"],
                "notes": row["notes"],
            }
            for row in rows
        }
    except Exception:
        logger.warning("Could not read dataset_registry", exc_info=True)
        return {}


# Map from manifest source keys to dataset_registry facility_type keys
_SOURCE_TO_REGISTRY_KEY = {
    "SEMS": "sems",
    "EJSCREEN": "ejscreen",
    "TRI": "tri",
    "UST": "ust",
    "HPMS": "hpms",
    "HIFLD": "hifld",
    "FRA": "fra",
    "FEMA_NFHL": "fema_nfhl",
    "SCHOOL_DISTRICTS": "school_districts",
    "STATE_EDUCATION": "state_education_performance",
    "NCES_SCHOOLS": "nces_schools",
    "GOOGLE_PLACES_PARKS": None,  # live API, not in registry
    "GOOGLE_TRANSIT": None,  # live API, not in registry
    "OVERPASS_SIDEWALKS": None,  # live API, not in registry
    "CENSUS_ACS": None,  # live API, not in registry
}


def get_source_last_refreshed(source_key: str) -> Optional[str]:
    """Return the ingested_at timestamp for a source, or None."""
    registry_key = _SOURCE_TO_REGISTRY_KEY.get(source_key)
    if not registry_key:
        return None
    registry = get_dataset_registry()
    entry = registry.get(registry_key)
    return entry["ingested_at"] if entry else None


# =============================================================================
# Section-to-dimension mapping (report sections → manifest dimensions)
# =============================================================================

# Maps report section identifiers to the manifest dimensions they depend on.
# Sections fed entirely by live APIs (Google Places, Walk Score) always show
# FULL — the coverage badge only matters for sections backed by spatial.db
# bulk data.
SECTION_DIMENSION_MAP = {
    "health": ["health"],           # Health & Environment section
    "parks": ["green_space"],       # Park scoring uses Google Places (live).
                                    # Own dimension so badge reflects parks data,
                                    # not health bucket. Add ParkServe source here
                                    # when ingested.
    "road_noise": ["health"],       # Road noise uses HPMS data (health dimension)
    "getting_around": ["transit"],  # Transit from Google (live), sidewalks from
                                    # Overpass (live). Own dimension so badge
                                    # reflects transit data independently.
    "school_district": ["education"],  # School district + NCES schools
    "ejscreen": ["health"],         # EPA Environmental Profile section
}

# Sections NOT in the map are fed by live APIs and always FULL:
#   - coffee_social (Google Places)
#   - provisioning (Google Places)
#   - fitness (Google Places)
#   - community_profile (Census ACS live API)
#   - local_services (Google Places)


# US state abbreviation → full name for display in badge tooltips
_STATE_NAMES = {
    code: data["name"]
    for code, data in COVERAGE_MANIFEST.items()
    if "name" in data
}


# Regex to extract 2-letter US state code from a formatted address.
# Google Geocoding returns addresses like "123 Main St, White Plains, NY 10601, USA"
_STATE_CODE_RE = re.compile(r',\s*([A-Z]{2})\s+\d{5}')


def extract_state_from_address(address: str) -> Optional[str]:
    """Extract 2-letter state code from a formatted US address.

    Looks for the pattern ", XX NNNNN" (state + zip) common in Google
    Geocoding API formatted_address output.
    Returns None if no state code found or state not in manifest.
    """
    match = _STATE_CODE_RE.search(address)
    if match:
        code = match.group(1)
        if code in COVERAGE_MANIFEST:
            return code
    return None


def get_state_name(state_code: str) -> str:
    """Return human-readable state name, or the code itself as fallback."""
    return _STATE_NAMES.get(state_code.upper(), state_code) if state_code else ""


def get_section_coverage(state_code: str) -> Dict[str, str]:
    """Return {section_name: coverage_tier_value} for report sections.

    Sections not in SECTION_DIMENSION_MAP are omitted (always FULL).
    Returns string values (not enum) for easy template consumption.
    Returns empty dict for unknown states or on any error.
    """
    if not state_code:
        return {}
    try:
        dim_coverage = get_dimension_coverage(state_code)
        if not dim_coverage:
            return {}

        result = {}
        for section, dimensions in SECTION_DIMENSION_MAP.items():
            # Take the weakest tier across all dimensions the section depends on
            tiers = [dim_coverage.get(d, CoverageTier.NONE) for d in dimensions]
            weakest = max(tiers, key=lambda t: _TIER_ORDER.get(t, 3))
            # Only include in result if NOT full (full = no badge)
            if weakest != CoverageTier.FULL:
                result[section] = weakest.value
        return result
    except Exception:
        logger.warning("get_section_coverage failed for %s", state_code, exc_info=True)
        return {}


# =============================================================================
# Verification (diagnostic, not called during evaluations)
# =============================================================================

def verify_coverage(state_code: str) -> Dict[str, dict]:
    """Compare manifest statuses against actual spatial.db row counts.

    Returns {source_name: {manifest_status, actual_rows, mismatch, note}}.
    Skips sources with spatial_filter_required=True (need spatial join).
    Skips sources with no table (e.g. CENSUS_ACS).
    """
    state_code = state_code.upper()
    state_data = COVERAGE_MANIFEST.get(state_code)
    if not state_data:
        return {}

    try:
        from spatial_data import _spatial_db_path
        db_path = _spatial_db_path()
        if not os.path.exists(db_path):
            return {src: {"manifest_status": state_data.get(src, "planned"),
                          "actual_rows": None,
                          "mismatch": False,
                          "note": "spatial.db not found"}
                    for src in _ALL_SOURCES}
        conn = sqlite3.connect(db_path)
    except Exception as e:
        logger.warning("verify_coverage: cannot connect to spatial.db: %s", e)
        return {}

    results = {}
    for source_key, meta in _SOURCE_METADATA.items():
        manifest_status = state_data.get(source_key, "planned")
        table = meta.get("table")

        # Skip sources with no DB table
        if not table:
            results[source_key] = {
                "manifest_status": manifest_status,
                "actual_rows": None,
                "mismatch": False,
                "note": "No spatial.db table (live API).",
            }
            continue

        # Skip bbox-filtered tables (need spatial join to determine state)
        if meta.get("spatial_filter_required"):
            results[source_key] = {
                "manifest_status": manifest_status,
                "actual_rows": None,
                "mismatch": False,
                "note": "Spatial filter required — skipped.",
            }
            continue

        # Check if table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if not cursor.fetchone():
            actual_rows = 0
            note = f"Table '{table}' does not exist."
        else:
            # Build state-specific count query
            state_filter_col = meta.get("state_filter")
            key_format = meta.get("state_key_format", "abbr")

            if key_format == "fips":
                state_value = _STATE_FIPS.get(state_code, state_code)
            elif key_format == "full_name":
                state_value = _STATE_FULL_NAME.get(state_code, state_code)
            else:
                state_value = state_code

            if state_filter_col:
                # table and state_filter_col are from _SOURCE_METADATA (hardcoded),
                # not user input — safe for f-string interpolation.
                query = f"SELECT count(*) FROM {table} WHERE {state_filter_col} = ?"
                actual_rows = conn.execute(query, (state_value,)).fetchone()[0]
                note = None
            else:
                # No state filter available — count all rows
                actual_rows = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                note = "No state filter — total row count."

        # Determine mismatch
        mismatch = False
        if manifest_status == SourceStatus.ACTIVE and actual_rows == 0:
            mismatch = True
            note = (note or "") + " Manifest says active but 0 rows found."
        elif manifest_status in (SourceStatus.INTENDED, SourceStatus.PLANNED) and actual_rows and actual_rows > 0:
            mismatch = True
            note = (note or "") + f" Manifest says {manifest_status} but {actual_rows} rows found."

        results[source_key] = {
            "manifest_status": manifest_status,
            "actual_rows": actual_rows,
            "mismatch": mismatch,
            "note": note,
        }

    conn.close()
    return results
