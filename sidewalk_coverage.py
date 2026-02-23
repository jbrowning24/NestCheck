"""
Sidewalk & Cycleway Coverage — OpenStreetMap infrastructure screening.

Estimates sidewalk and cycling infrastructure coverage around a property
by analyzing tagged road segments within a radius using the Overpass API.

Data sources:
  - OpenStreetMap Overpass API (road tags: sidewalk=*, cycleway=*, highway=*)

Limitations:
  - OSM sidewalk/cycleway tagging is highly variable across US cities.
    A 2022 study found inconsistent completeness across 50+ US cities;
    urban cores tend to be better mapped, suburbs severely underrepresented.
  - Missing tags are ambiguous: a road without a sidewalk=* tag may have
    a sidewalk that simply hasn't been surveyed in OSM yet.
  - Coverage percentages reflect OSM data completeness, not necessarily
    ground truth.  The data confidence indicator helps interpret results.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Road types to include when counting total road segments.
# Excludes motorway/trunk (pedestrians prohibited) and service roads.
ROAD_TYPES = (
    "primary", "secondary", "tertiary",
    "residential", "unclassified", "living_street",
)

# sidewalk=* tag values that indicate sidewalk presence.
SIDEWALK_PRESENT = {"both", "left", "right", "yes", "separate"}

# sidewalk=* tag values that explicitly confirm no sidewalk.
SIDEWALK_ABSENT = {"no", "none"}

# cycleway=* tag values that indicate cycling infrastructure on the road.
CYCLEWAY_PRESENT = {
    "lane", "track", "shared_lane", "shared_busway",
    "opposite_lane", "opposite_track", "opposite",
}

# Data confidence thresholds (fraction of roads with any sidewalk tag).
CONFIDENCE_HIGH_THRESHOLD = 0.60
CONFIDENCE_MEDIUM_THRESHOLD = 0.20

METHODOLOGY_NOTE = (
    "Coverage is calculated from OpenStreetMap sidewalk and cycleway tags "
    "on road segments within 500 m of the property. OSM is community-maintained "
    "and tagging completeness varies by area — the data confidence indicator "
    "reflects what fraction of nearby roads have been surveyed for sidewalk "
    "information. Low confidence means most roads lack tags, so actual sidewalk "
    "availability may be higher than reported."
)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SidewalkCoverageAssessment:
    """Result of sidewalk/cycleway coverage analysis for a property."""

    # Road network stats
    total_road_segments: int        # all road ways within radius
    roads_with_sidewalk: int        # roads with sidewalk=both|left|right|yes
    roads_without_sidewalk: int     # roads with sidewalk=no|none
    roads_untagged: int             # roads with no sidewalk tag at all

    # Cycleway stats
    roads_with_cycleway: int        # roads with cycleway=* tags on road ways
    separate_cycleways: int         # standalone highway=cycleway ways
    separate_footways: int          # standalone highway=footway + footway=sidewalk

    # Computed metrics
    sidewalk_pct: float             # 0-100
    cycleway_pct: float             # 0-100

    # Data quality
    data_confidence: str            # "HIGH" / "MEDIUM" / "LOW"
    data_confidence_note: str       # explanation of confidence level

    methodology_note: str           # static methodology text


# =============================================================================
# OVERPASS QUERY
# =============================================================================

def _build_query(lat: float, lng: float, radius_m: int = 500) -> str:
    """Build Overpass QL query for sidewalk/cycleway data."""
    highway_regex = "|".join(ROAD_TYPES)
    return f"""
    [out:json][timeout:25];
    (
      way["highway"~"{highway_regex}"](around:{radius_m},{lat},{lng});
      way["highway"="footway"]["footway"="sidewalk"](around:{radius_m},{lat},{lng});
      way["highway"="cycleway"](around:{radius_m},{lat},{lng});
    );
    out tags;
    """


def _fetch_data(lat: float, lng: float, radius_m: int = 500) -> dict:
    """Execute Overpass query and return raw JSON response.

    Uses shared Overpass HTTP layer (cache, rate limiting, retries).
    Raises on failure — caller handles graceful degradation.
    """
    from overpass_http import overpass_query

    query = _build_query(lat, lng, radius_m)
    return overpass_query(query, caller="sidewalk_coverage", timeout=25)


# =============================================================================
# PARSING
# =============================================================================

def _parse_coverage(data: dict) -> dict:
    """Parse Overpass response and compute coverage statistics.

    Returns a dict with all counts needed to build the assessment.
    """
    roads_with_sidewalk = 0
    roads_without_sidewalk = 0
    roads_untagged = 0
    roads_with_cycleway = 0
    separate_cycleways = 0
    separate_footways = 0
    total_road_segments = 0

    for element in data.get("elements", []):
        if element.get("type") != "way":
            continue

        tags = element.get("tags", {})
        highway = tags.get("highway", "")

        # Separate cycleway ways
        if highway == "cycleway":
            separate_cycleways += 1
            continue

        # Separate sidewalk ways (footway tagged as sidewalk)
        if highway == "footway" and tags.get("footway") == "sidewalk":
            separate_footways += 1
            continue

        # Regular road segments
        if highway not in ROAD_TYPES:
            continue

        total_road_segments += 1

        # Check sidewalk tags
        sidewalk_tag = tags.get("sidewalk", "").lower().strip()
        if sidewalk_tag in SIDEWALK_PRESENT:
            roads_with_sidewalk += 1
        elif sidewalk_tag in SIDEWALK_ABSENT:
            roads_without_sidewalk += 1
        else:
            roads_untagged += 1

        # Check cycleway tags on road ways
        has_cycleway = False
        for key in ("cycleway", "cycleway:left", "cycleway:right",
                     "cycleway:both"):
            val = tags.get(key, "").lower().strip()
            if val in CYCLEWAY_PRESENT:
                has_cycleway = True
                break
        if has_cycleway:
            roads_with_cycleway += 1

    return {
        "total_road_segments": total_road_segments,
        "roads_with_sidewalk": roads_with_sidewalk,
        "roads_without_sidewalk": roads_without_sidewalk,
        "roads_untagged": roads_untagged,
        "roads_with_cycleway": roads_with_cycleway,
        "separate_cycleways": separate_cycleways,
        "separate_footways": separate_footways,
    }


# =============================================================================
# CONFIDENCE CLASSIFICATION
# =============================================================================

def _classify_confidence(
    roads_with_sidewalk: int,
    roads_without_sidewalk: int,
    total_road_segments: int,
) -> tuple:
    """Determine data confidence based on tag completeness.

    Returns (confidence_level, confidence_note) tuple.
    """
    if total_road_segments == 0:
        return "LOW", "No road segments found in search area"

    tagged_fraction = (roads_with_sidewalk + roads_without_sidewalk) / total_road_segments

    if tagged_fraction >= CONFIDENCE_HIGH_THRESHOLD:
        return (
            "HIGH",
            f"{tagged_fraction:.0%} of roads have sidewalk tags in OSM"
        )
    elif tagged_fraction >= CONFIDENCE_MEDIUM_THRESHOLD:
        return (
            "MEDIUM",
            f"Only {tagged_fraction:.0%} of roads have sidewalk tags — "
            f"actual coverage may differ"
        )
    else:
        return (
            "LOW",
            f"Only {tagged_fraction:.0%} of roads have sidewalk tags — "
            f"most roads unsurveyed in OSM"
        )


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def assess_sidewalk_coverage(
    lat: float, lng: float
) -> Optional[SidewalkCoverageAssessment]:
    """Assess sidewalk and cycleway coverage around a property.

    Fetches road segments within 500 m, analyzes sidewalk/cycleway tags,
    and computes coverage percentages with a data confidence indicator.

    Returns None if the query fails or no roads are found (graceful
    degradation).
    """
    try:
        data = _fetch_data(lat, lng, radius_m=500)
    except Exception:
        logger.warning(
            "Overpass sidewalk coverage query failed",
            exc_info=True,
        )
        return None

    stats = _parse_coverage(data)

    total = stats["total_road_segments"]
    if total == 0:
        return None

    sidewalk_pct = round(stats["roads_with_sidewalk"] / total * 100, 1)
    cycleway_pct = round(stats["roads_with_cycleway"] / total * 100, 1)

    confidence, confidence_note = _classify_confidence(
        stats["roads_with_sidewalk"],
        stats["roads_without_sidewalk"],
        total,
    )

    return SidewalkCoverageAssessment(
        total_road_segments=total,
        roads_with_sidewalk=stats["roads_with_sidewalk"],
        roads_without_sidewalk=stats["roads_without_sidewalk"],
        roads_untagged=stats["roads_untagged"],
        roads_with_cycleway=stats["roads_with_cycleway"],
        separate_cycleways=stats["separate_cycleways"],
        separate_footways=stats["separate_footways"],
        sidewalk_pct=sidewalk_pct,
        cycleway_pct=cycleway_pct,
        data_confidence=confidence,
        data_confidence_note=confidence_note,
        methodology_note=METHODOLOGY_NOTE,
    )
