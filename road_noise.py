"""
Road Noise Estimator — FHWA TNM-based environmental noise screening.

Estimates environmental noise exposure at a property based on the nearest
road, using FHWA Traffic Noise Model (TNM) reference levels and road
geometry from OpenStreetMap.

Data sources:
  - OpenStreetMap Overpass API (road classification, lane count, geometry)
  - FHWA Traffic Noise Model Activity Category defaults (reference dBA)

Limitations:
  - Reference dBA values are midpoints for typical traffic mixes; actual
    levels vary with vehicle counts, speed, truck percentage, and time of day.
  - Distance decay uses a single rate (soft ground suburban); terrain,
    barriers (walls, berms), and building shielding are not modeled.
  - OSM lane counts may be missing or inaccurate; defaults to 2 lanes.
  - Estimates represent typical daytime conditions, not peak or nighttime.
"""

import logging
import math
import time
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Tuple

import requests
from models import overpass_cache_key, get_overpass_cache, set_overpass_cache
from nc_trace import get_trace

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS — FHWA reference noise levels
# =============================================================================

# Reference dBA at 50 feet from roadway centerline, based on FHWA Traffic
# Noise Model Activity Category defaults.  These are defensible midpoints
# for a screening-level estimate; actual TNM values vary by traffic mix.
FHWA_REFERENCE_DBA = {
    "motorway": 77,
    "trunk": 74,
    "primary": 70,
    "secondary": 67,
    "tertiary": 62,
    "residential": 55,
    "unclassified": 55,
    "living_street": 50,
}

# +1.5 dBA per additional lane beyond 2.  Simplified proxy for increased
# traffic volume — FHWA models show roughly +3 dB per doubling of volume;
# adding 2 lanes roughly doubles capacity.
LANE_ADJUSTMENT_DBA = 1.5

# Distance at which FHWA_REFERENCE_DBA values are measured (feet).
REFERENCE_DISTANCE_FT = 50.0

# dBA reduction per doubling of distance.  FHWA TNM uses 3 dB (hard ground)
# to 4.5 dB (soft ground) per doubling for point sources, but road segments
# are line sources with higher decay.  7.5 accounts for typical suburban
# soft ground propagation with some barrier attenuation.  Conservative
# (optimistic for the resident).
DECAY_RATE = 7.5


# =============================================================================
# CONSTANTS — Severity bands
# =============================================================================

class NoiseSeverity(str, Enum):
    QUIET = "QUIET"           # < 55 dBA — residential ambient
    MODERATE = "MODERATE"     # 55-65 dBA — noticeable, conversation outdoors easy
    LOUD = "LOUD"             # 65-75 dBA — impacts outdoor enjoyment
    VERY_LOUD = "VERY_LOUD"   # > 75 dBA — health concern per WHO/EPA

SEVERITY_THRESHOLDS = [
    (75, NoiseSeverity.VERY_LOUD),
    (65, NoiseSeverity.LOUD),
    (55, NoiseSeverity.MODERATE),
]
# Below 55 → QUIET

SEVERITY_LABELS = {
    NoiseSeverity.VERY_LOUD: (
        "Very Loud \u2014 potential health impact, equivalent to "
        "standing near a busy highway"
    ),
    NoiseSeverity.LOUD: (
        "Loud \u2014 outdoor conversation difficult, similar to "
        "a busy urban street"
    ),
    NoiseSeverity.MODERATE: (
        "Moderate \u2014 noticeable outdoors, similar to background "
        "noise in a restaurant"
    ),
    NoiseSeverity.QUIET: "Quiet \u2014 typical residential ambient noise",
}

METHODOLOGY_NOTE = (
    "Noise estimates based on FHWA Traffic Noise Model (TNM) reference "
    "levels with logarithmic distance decay. Actual levels vary with "
    "traffic volume, vehicle mix, terrain, and barriers. Estimates "
    "represent typical daytime conditions."
)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class RoadSegment:
    """Internal representation of a road with geometry for distance calculation."""
    name: str
    ref: str
    highway_type: str
    lanes: int
    nodes: List[Tuple[float, float]]  # list of (lat, lng) pairs


@dataclass
class RoadNoiseAssessment:
    """Result of a road noise screening assessment for a property."""
    worst_road_name: str          # e.g. "Route 9" or "Unnamed"
    worst_road_ref: str           # e.g. "US 9" or ""
    worst_road_type: str          # OSM highway value, e.g. "primary"
    worst_road_lanes: int         # parsed lane count, default 2
    distance_ft: float            # nearest-point distance to worst road
    estimated_dba: float          # estimated noise at property
    severity: NoiseSeverity
    severity_label: str           # human-readable
    methodology_note: str         # static FHWA citation string
    all_roads_assessed: int       # total roads found in radius


# =============================================================================
# GEOMETRY HELPERS
# =============================================================================

def _haversine_ft(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance between two points, returned in feet."""
    R_MILES = 3958.8
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))

    return R_MILES * c * 5280


def _nearest_point_on_segment(
    px: float, py: float,
    ax: float, ay: float,
    bx: float, by: float,
) -> Tuple[float, float]:
    """Return the closest point on segment A→B to point P.

    Uses vector projection.  Works on lat/lng directly — at the scale
    we operate (< 500 m), the planar approximation is sufficient.
    """
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay

    ab_dot_ab = abx * abx + aby * aby
    if ab_dot_ab == 0:
        # Degenerate segment (A == B)
        return (ax, ay)

    t = (apx * abx + apy * aby) / ab_dot_ab
    t = max(0.0, min(1.0, t))

    return (ax + t * abx, ay + t * aby)


def _nearest_distance_to_road_ft(
    prop_lat: float, prop_lng: float, road: RoadSegment
) -> float:
    """Minimum distance from property to any segment of the road polyline."""
    min_dist = float("inf")
    nodes = road.nodes

    for i in range(len(nodes) - 1):
        a_lat, a_lng = nodes[i]
        b_lat, b_lng = nodes[i + 1]

        nearest_lat, nearest_lng = _nearest_point_on_segment(
            prop_lat, prop_lng, a_lat, a_lng, b_lat, b_lng,
        )
        dist = _haversine_ft(prop_lat, prop_lng, nearest_lat, nearest_lng)

        if dist < min_dist:
            min_dist = dist

    return min_dist


# =============================================================================
# NOISE ESTIMATION
# =============================================================================

def _estimate_noise_dba(road: RoadSegment, distance_ft: float) -> float:
    """Estimate noise level at the property from a single road.

    Uses FHWA reference dBA at 50 ft with lane adjustment and
    logarithmic distance decay.
    """
    base_dba = FHWA_REFERENCE_DBA[road.highway_type]
    lane_bonus = max(0, (road.lanes - 2)) * LANE_ADJUSTMENT_DBA
    reference_dba = base_dba + lane_bonus

    if distance_ft <= REFERENCE_DISTANCE_FT:
        return reference_dba

    dba = reference_dba - DECAY_RATE * math.log2(distance_ft / REFERENCE_DISTANCE_FT)
    return max(dba, 30.0)  # floor at 30 dBA (ambient quiet)


def _classify_severity(dba: float) -> Tuple[NoiseSeverity, str]:
    """Map estimated dBA to a severity level and human-readable label."""
    for threshold, severity in SEVERITY_THRESHOLDS:
        if dba >= threshold:
            return severity, SEVERITY_LABELS[severity]
    return NoiseSeverity.QUIET, SEVERITY_LABELS[NoiseSeverity.QUIET]


# =============================================================================
# OVERPASS DATA FETCHING
# =============================================================================

def _parse_roads_with_geometry(data: dict) -> List[RoadSegment]:
    """Parse an Overpass JSON response into RoadSegment objects with geometry.

    First pass: build node_id → (lat, lon) lookup.
    Second pass: extract ways with highway tags in FHWA_REFERENCE_DBA,
    resolve node coordinates, and build RoadSegment objects.
    """
    # Pass 1: build node coordinate lookup
    node_coords: dict = {}
    for element in data.get("elements", []):
        if element.get("type") == "node" and "lat" in element and "lon" in element:
            node_coords[element["id"]] = (element["lat"], element["lon"])

    # Pass 2: extract road ways with geometry
    roads: List[RoadSegment] = []
    for element in data.get("elements", []):
        if element.get("type") != "way" or "tags" not in element:
            continue

        highway_type = element["tags"].get("highway", "")
        if highway_type not in FHWA_REFERENCE_DBA:
            continue

        # Parse lane count
        lanes_str = element["tags"].get("lanes", "")
        try:
            lanes = int(lanes_str)
        except (ValueError, TypeError):
            lanes = 2

        # Resolve node coordinates
        nodes: List[Tuple[float, float]] = []
        for node_id in element.get("nodes", []):
            coord = node_coords.get(node_id)
            if coord is not None:
                nodes.append(coord)

        # Need at least 2 nodes to form a segment
        if len(nodes) < 2:
            continue

        roads.append(RoadSegment(
            name=element["tags"].get("name", "Unnamed"),
            ref=element["tags"].get("ref", ""),
            highway_type=highway_type,
            lanes=lanes,
            nodes=nodes,
        ))

    return roads


def fetch_all_roads(
    lat: float, lng: float, radius_m: int = 500
) -> List[RoadSegment]:
    """Fetch all roads within radius using Overpass, with caching.

    Queries for all road types in FHWA_REFERENCE_DBA.  Uses the same
    two-level cache pattern as OverpassClient.get_nearby_roads().

    Returns an empty list on any failure (graceful degradation).
    """
    query = f"""
    [out:json][timeout:25];
    (
      way["highway"~"motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street"](around:{radius_m},{lat},{lng});
    );
    out body;
    >;
    out skel qt;
    """

    # Check SQLite persistent cache
    db_cache_key = overpass_cache_key(query)
    try:
        cached_json = get_overpass_cache(db_cache_key)
        if cached_json is not None:
            data = json.loads(cached_json)
            return _parse_roads_with_geometry(data)
    except Exception:
        logger.warning(
            "Overpass cache read failed in fetch_all_roads, falling through to HTTP",
            exc_info=True,
        )

    # HTTP fetch
    url = "https://overpass-api.de/api/interpreter"
    session = requests.Session()
    session.trust_env = False
    try:
        t0 = time.time()
        resp = session.post(url, data={"data": query}, timeout=25)
        elapsed_ms = int((time.time() - t0) * 1000)
        resp.raise_for_status()
        data = resp.json()

        # Record in trace
        trace = get_trace()
        if trace:
            trace.record_api_call(
                service="overpass",
                endpoint="road_noise_overpass",
                elapsed_ms=elapsed_ms,
                status_code=resp.status_code,
            )
    except Exception:
        logger.warning("Overpass fetch failed in fetch_all_roads", exc_info=True)
        return []

    # Cache successful response
    try:
        set_overpass_cache(db_cache_key, json.dumps(data))
    except Exception:
        logger.warning(
            "Overpass cache write failed in fetch_all_roads", exc_info=True,
        )

    return _parse_roads_with_geometry(data)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def assess_road_noise(
    lat: float, lng: float
) -> Optional[RoadNoiseAssessment]:
    """Estimate environmental noise exposure at a property.

    Fetches all roads within 500 m, computes distance and estimated noise
    for each, and returns an assessment based on the worst (loudest) road.

    Returns None if no roads are found within the search radius.
    """
    roads = fetch_all_roads(lat, lng, radius_m=500)
    if not roads:
        return None

    worst_road: Optional[RoadSegment] = None
    worst_dba = -1.0
    worst_distance = 0.0

    for road in roads:
        distance = _nearest_distance_to_road_ft(lat, lng, road)
        dba = _estimate_noise_dba(road, distance)

        if dba > worst_dba:
            worst_dba = dba
            worst_road = road
            worst_distance = distance

    if worst_road is None:
        return None

    severity, severity_label = _classify_severity(worst_dba)

    return RoadNoiseAssessment(
        worst_road_name=worst_road.name,
        worst_road_ref=worst_road.ref,
        worst_road_type=worst_road.highway_type,
        worst_road_lanes=worst_road.lanes,
        distance_ft=round(worst_distance, 1),
        estimated_dba=round(worst_dba, 1),
        severity=severity,
        severity_label=severity_label,
        methodology_note=METHODOLOGY_NOTE,
        all_roads_assessed=len(roads),
    )
