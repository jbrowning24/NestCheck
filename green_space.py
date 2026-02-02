"""
Green Escape Engine — Parks & Green Spaces for Daily Outdoor Life

Finds real parks/green spaces near an address, computes a "Daily Walk Value"
score (0–10), and returns comprehensive results including spaces that don't
meet strict criteria.

Designed for families with strollers/toddlers who need a walkable green space
for a 20–30 minute loop every day.

Data sources:
  - Google Places API (nearby search + distance matrix for walk times)
  - OpenStreetMap Overpass API (geometry/tag enrichment for trails, area, nature)

Limitations:
  - Acreage is estimated via OSM polygon area when available; otherwise we use
    review count + rating + category keywords as a weak proxy (labeled "estimate").
  - Overpass enrichment may fail for areas with sparse OSM data.
  - Walk times come from Google Distance Matrix and assume sidewalk availability.
"""

import math
import time
import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import requests


# =============================================================================
# CONFIGURATION / THRESHOLDS
# =============================================================================

# Walk-time scoring thresholds (minutes)
WALK_TIME_EXCELLENT = 10
WALK_TIME_GOOD = 20
WALK_TIME_MARGINAL = 30

# Quality proxy thresholds
QUALITY_HIGH_RATING = 4.3
QUALITY_MID_RATING = 3.8
QUALITY_HIGH_REVIEWS = 200
QUALITY_MID_REVIEWS = 50

# Size proxy thresholds (square meters from Overpass polygon area)
SIZE_LARGE_SQM = 40_000       # ~10 acres
SIZE_MEDIUM_SQM = 12_000      # ~3 acres
SIZE_SMALL_SQM = 4_000        # ~1 acre

# Trail/path network density threshold (count of footway segments within park)
PATH_NETWORK_DENSE = 5
PATH_NETWORK_MODERATE = 2

# Search radii
DEFAULT_RADIUS_M = 2000
EXPANDED_RADIUS_M = 5000
MIN_RESULTS_BEFORE_EXPAND = 3

# How many spaces to return in the nearby list
NEARBY_LIST_SIZE = 8

# Criteria pass/fail thresholds for "daily park" qualification
DAILY_PARK_MIN_WALK_SCORE = 1     # At least marginal walk time
DAILY_PARK_MIN_SIZE_SCORE = 1     # At least some size indication
DAILY_PARK_MIN_TOTAL = 5          # Overall daily value >= 5 to PASS

# Place types to search for in Google Places
SEARCH_TYPES = ["park", "national_park", "campground"]

# Keywords to search for (these get separate keyword-based searches)
SEARCH_KEYWORDS = [
    "nature preserve",
    "state park",
    "trailhead",
    "greenway",
    "riverwalk",
    "reservoir",
    "botanical garden",
]

# Types that indicate NOT a green space (hard exclusion)
EXCLUDED_TYPES = {
    "store", "shopping_mall", "restaurant", "lodging", "school",
    "church", "hospital", "doctor", "dentist", "pharmacy",
    "bank", "atm", "gas_station", "car_dealer", "car_repair",
    "car_wash", "convenience_store", "department_store",
    "electronics_store", "furniture_store", "grocery_or_supermarket",
    "hardware_store", "home_goods_store", "jewelry_store",
    "laundry", "lawyer", "library", "liquor_store", "meal_delivery",
    "meal_takeaway", "movie_theater", "night_club", "pet_store",
    "real_estate_agency", "shoe_store", "spa", "supermarket",
    "veterinary_care",
}

# Name keywords that indicate a non-green-space (garbage filter)
GARBAGE_NAME_KEYWORDS = [
    "sam's club", "walmart", "costco", "target", "home depot",
    "lowe's", "lowes", "best buy", "mcdonald", "burger king",
    "wendy's", "taco bell", "subway", "starbucks", "dunkin",
    "hotel", "motel", "inn ", "marriott", "hilton", "hyatt",
    "holiday inn", "comfort inn", "hampton inn", "la quinta",
    "auto ", "tire ", "jiffy lube", "valvoline", "autozone",
    "o'reilly", "advance auto", "pep boys",
]

# Name keywords that positively indicate a green space
GREEN_NAME_KEYWORDS = [
    "park", "trail", "preserve", "nature", "garden", "arboretum",
    "botanical", "river", "creek", "lake", "reservoir", "beach",
    "forest", "woods", "wetland", "marsh", "greenway", "walk",
    "hike", "canyon", "falls", "waterfall", "meadow", "field",
    "conservation", "sanctuary", "wilderness", "grove", "ravine",
    "pond", "brook", "spring", "bluff", "ridge", "summit",
    "overlook", "scenic", "riverwalk", "boardwalk",
]

# OSM tags that indicate nature feel
NATURE_OSM_TAGS = {
    "landuse": ["forest", "meadow", "grass", "nature_reserve", "conservation"],
    "leisure": ["nature_reserve", "park", "garden"],
    "natural": ["wood", "wetland", "water", "scrub", "heath", "grassland", "tree_row"],
    "waterway": ["river", "stream", "canal"],
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DailyWalkSubscore:
    """Individual subscore with reason text."""
    name: str
    score: float
    max_score: float
    reason: str
    is_estimate: bool = False


@dataclass
class GreenSpaceResult:
    """A single green space with scoring details."""
    place_id: Optional[str]
    name: str
    rating: Optional[float]
    user_ratings_total: int
    walk_time_min: int
    types: List[str]
    types_display: str
    lat: float
    lng: float

    # Daily Walk Value scoring (0–10)
    daily_walk_value: float = 0.0
    walk_time_score: float = 0.0
    size_loop_score: float = 0.0
    quality_score: float = 0.0
    nature_feel_score: float = 0.0

    subscores: List[DailyWalkSubscore] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    # PASS / BORDERLINE / FAIL
    criteria_status: str = "FAIL"
    criteria_reasons: List[str] = field(default_factory=list)

    # OSM enrichment metadata
    osm_enriched: bool = False
    osm_area_sqm: Optional[float] = None
    osm_path_count: int = 0
    osm_has_trail: bool = False
    osm_nature_tags: List[str] = field(default_factory=list)


@dataclass
class GreenEscapeEvaluation:
    """Full green escape evaluation result."""
    best_daily_park: Optional[GreenSpaceResult] = None
    nearby_green_spaces: List[GreenSpaceResult] = field(default_factory=list)
    green_escape_score_0_10: float = 0.0
    criteria: Dict[str, Any] = field(default_factory=dict)
    search_radius_used: int = DEFAULT_RADIUS_M
    messages: List[str] = field(default_factory=list)


# =============================================================================
# CACHING
# =============================================================================

_cache: Dict[str, Any] = {}


def _cache_key(prefix: str, *args) -> str:
    """Generate a deterministic cache key."""
    raw = f"{prefix}:" + ":".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()


def _cached_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < 600:  # 10-min TTL
        return entry["val"]
    return None


def _cached_set(key: str, val: Any):
    _cache[key] = {"val": val, "ts": time.time()}


# =============================================================================
# PLACE RETRIEVAL & FILTERING
# =============================================================================

def _is_garbage(name: str, types: List[str]) -> bool:
    """Return True if the place is clearly NOT a green space."""
    name_lower = name.lower()

    # Check excluded types
    if any(t in EXCLUDED_TYPES for t in types):
        # Exception: if also typed as "park", keep it
        if "park" not in types and "national_park" not in types:
            return True

    # Check garbage name keywords
    for kw in GARBAGE_NAME_KEYWORDS:
        if kw in name_lower:
            return True

    return False


def _is_green_space(name: str, types: List[str]) -> bool:
    """Return True if the place is plausibly a green space."""
    # Has an explicit green type
    green_types = {"park", "national_park", "campground"}
    if any(t in green_types for t in types):
        return True

    # Name contains green keywords
    name_lower = name.lower()
    if any(kw in name_lower for kw in GREEN_NAME_KEYWORDS):
        return True

    # tourist_attraction with nature name
    if "tourist_attraction" in types:
        nature_words = [
            "preserve", "trail", "riverwalk", "greenway", "botanical",
            "nature", "forest", "park", "garden", "lake", "reservoir",
        ]
        if any(w in name_lower for w in nature_words):
            return True

    return False


def _format_types(types: List[str]) -> str:
    """Format place types for display."""
    display_types = []
    skip = {"point_of_interest", "establishment", "political", "geocode"}
    for t in types:
        if t not in skip:
            display_types.append(t.replace("_", " ").title())
    return ", ".join(display_types[:3]) if display_types else "Green Space"


def find_green_spaces(
    maps_client,
    lat: float,
    lng: float,
    radius_m: int = DEFAULT_RADIUS_M,
) -> List[Dict[str, Any]]:
    """
    Find real parks and green spaces near coordinates.

    Uses Google Places nearby search with tight type/keyword filters.
    Excludes stores, hotels, and generic POIs.
    Returns de-duplicated list of place dicts with walk times.
    """
    cache_key = _cache_key("find_green", lat, lng, radius_m)
    cached = _cached_get(cache_key)
    if cached is not None:
        return cached

    places_by_id: Dict[str, Dict[str, Any]] = {}

    # Search by type
    for place_type in SEARCH_TYPES:
        try:
            results = maps_client.places_nearby(lat, lng, place_type, radius_meters=radius_m)
            for place in results:
                pid = place.get("place_id")
                if pid and pid not in places_by_id:
                    places_by_id[pid] = place
                elif pid:
                    # Merge types
                    existing_types = set(places_by_id[pid].get("types", []))
                    existing_types.update(place.get("types", []))
                    places_by_id[pid]["types"] = list(existing_types)
        except Exception:
            continue

    # Search by keyword for non-standard green spaces
    for keyword in SEARCH_KEYWORDS:
        try:
            results = maps_client.text_search(keyword, lat, lng, radius_meters=radius_m)
            for place in results:
                pid = place.get("place_id")
                if pid and pid not in places_by_id:
                    places_by_id[pid] = place
        except Exception:
            continue

    # Also search "tourist_attraction" but only keep nature-based ones
    try:
        results = maps_client.places_nearby(lat, lng, "tourist_attraction", radius_meters=radius_m)
        for place in results:
            pid = place.get("place_id")
            if pid and pid not in places_by_id:
                name = place.get("name", "")
                types = place.get("types", [])
                if _is_green_space(name, types):
                    places_by_id[pid] = place
    except Exception:
        pass

    # Filter: keep only real green spaces, remove garbage
    filtered = []
    for pid, place in places_by_id.items():
        name = place.get("name", "Unknown")
        types = place.get("types", [])

        if _is_garbage(name, types):
            continue
        if not _is_green_space(name, types):
            continue

        filtered.append(place)

    # Sort by straight-line distance and cap walk-time API calls to
    # the closest N to prevent 30+ sequential requests.
    MAX_WALK_CHECKS = 12

    def _haversine_dist(p):
        plat = p.get("geometry", {}).get("location", {}).get("lat", 0)
        plng = p.get("geometry", {}).get("location", {}).get("lng", 0)
        # Quick haversine approximation (degrees to meters)
        dlat = abs(plat - lat) * 111_000
        dlng = abs(plng - lng) * 111_000 * math.cos(math.radians(lat))
        return math.sqrt(dlat * dlat + dlng * dlng)

    filtered.sort(key=_haversine_dist)

    results = []
    for place in filtered[:MAX_WALK_CHECKS]:
        place_lat = place.get("geometry", {}).get("location", {}).get("lat")
        place_lng = place.get("geometry", {}).get("location", {}).get("lng")
        if place_lat is None or place_lng is None:
            continue

        wt_cache_key = _cache_key("walk", lat, lng, place_lat, place_lng)
        walk_time = _cached_get(wt_cache_key)
        if walk_time is None:
            try:
                walk_time = maps_client.walking_time((lat, lng), (place_lat, place_lng))
            except Exception:
                walk_time = 9999
            _cached_set(wt_cache_key, walk_time)

        if walk_time == 9999:
            continue

        place["_walk_time_min"] = walk_time
        place["_lat"] = place_lat
        place["_lng"] = place_lng
        results.append(place)

    # Sort by walk time, then rating
    results.sort(key=lambda p: (p.get("_walk_time_min", 9999), -(p.get("rating") or 0)))

    _cached_set(cache_key, results)
    return results


# =============================================================================
# OSM ENRICHMENT (Overpass API)
# =============================================================================

def _overpass_query(query: str) -> Dict:
    """Execute an Overpass query with caching."""
    cache_key = _cache_key("overpass", query)
    cached = _cached_get(cache_key)
    if cached is not None:
        return cached

    url = "https://overpass-api.de/api/interpreter"
    session = requests.Session()
    session.trust_env = False
    try:
        resp = session.post(url, data={"data": query}, timeout=25)
        data = resp.json()
    except Exception:
        data = {"elements": []}

    _cached_set(cache_key, data)
    return data


def enrich_from_osm(place_lat: float, place_lng: float, place_name: str) -> Dict[str, Any]:
    """
    Query OSM Overpass for enrichment data around a green space:
    - Polygon area (park/green boundaries)
    - Footway/path network count
    - Named trails nearby
    - Nature-related tags (forest, water, nature_reserve)
    """
    cache_key = _cache_key("osm_enrich", place_lat, place_lng)
    cached = _cached_get(cache_key)
    if cached is not None:
        return cached

    result = {
        "area_sqm": None,
        "path_count": 0,
        "has_trail": False,
        "nature_tags": [],
        "enriched": False,
    }

    # Query 1: Find park/green polygons and footways within 300m
    query = f"""
    [out:json][timeout:25];
    (
      way["leisure"="park"](around:300,{place_lat},{place_lng});
      way["landuse"~"forest|meadow|grass|recreation_ground"](around:300,{place_lat},{place_lng});
      way["leisure"="nature_reserve"](around:300,{place_lat},{place_lng});
      way["natural"~"wood|wetland|water|grassland"](around:300,{place_lat},{place_lng});
      relation["leisure"="park"](around:300,{place_lat},{place_lng});
      relation["boundary"="national_park"](around:300,{place_lat},{place_lng});
      relation["leisure"="nature_reserve"](around:300,{place_lat},{place_lng});
      way["highway"~"footway|path|cycleway|track"](around:300,{place_lat},{place_lng});
      way["waterway"~"river|stream|canal"](around:300,{place_lat},{place_lng});
    );
    out body;
    >;
    out skel qt;
    """

    data = _overpass_query(query)
    elements = data.get("elements", [])
    if not elements:
        _cached_set(cache_key, result)
        return result

    result["enriched"] = True

    # Parse elements
    max_area = 0
    path_count = 0
    nature_tags_found = set()
    has_trail = False

    for el in elements:
        if el.get("type") not in ("way", "relation"):
            continue
        tags = el.get("tags", {})

        # Check for park/green polygons with area
        if tags.get("leisure") in ("park", "nature_reserve", "garden"):
            nature_tags_found.add(f"leisure={tags['leisure']}")
        if tags.get("landuse") in ("forest", "meadow", "grass", "recreation_ground", "nature_reserve", "conservation"):
            nature_tags_found.add(f"landuse={tags['landuse']}")
        if tags.get("natural") in ("wood", "wetland", "water", "scrub", "heath", "grassland"):
            nature_tags_found.add(f"natural={tags['natural']}")
        if tags.get("waterway") in ("river", "stream", "canal"):
            nature_tags_found.add(f"waterway={tags['waterway']}")
        if tags.get("boundary") == "national_park":
            nature_tags_found.add("boundary=national_park")

        # Count footway/path segments
        highway = tags.get("highway", "")
        if highway in ("footway", "path", "cycleway", "track"):
            path_count += 1
            name = tags.get("name", "").lower()
            if any(w in name for w in ["trail", "greenway", "path", "walk", "loop"]):
                has_trail = True

        # Estimate area from way nodes (rough bounding box)
        if el.get("type") == "way" and "nodes" in el:
            # We get node coords from the skel output
            pass  # Area calculation needs node coords, handled below

    # Try to estimate area from relation/way with bounds
    # Use a simpler approach: count park-typed ways as a size proxy
    park_way_count = sum(
        1 for el in elements
        if el.get("type") == "way"
        and el.get("tags", {}).get("leisure") in ("park", "nature_reserve", "garden")
    )

    # Rough area estimation: if we found node elements, compute bounding box
    node_lats = []
    node_lngs = []
    for el in elements:
        if el.get("type") == "node" and "lat" in el and "lon" in el:
            node_lats.append(el["lat"])
            node_lngs.append(el["lon"])

    if node_lats and node_lngs:
        # Bounding box area in square meters (rough)
        lat_range = max(node_lats) - min(node_lats)
        lng_range = max(node_lngs) - min(node_lngs)
        # Degrees to meters: 1 degree lat ~ 111,000m, 1 degree lng ~ 111,000 * cos(lat)
        lat_m = lat_range * 111_000
        lng_m = lng_range * 111_000 * math.cos(math.radians(place_lat))
        bbox_area = lat_m * lng_m
        # Park is roughly 40-60% of bounding box
        estimated_area = bbox_area * 0.5
        if estimated_area > max_area:
            max_area = estimated_area

    result["area_sqm"] = max_area if max_area > 0 else None
    result["path_count"] = path_count
    result["has_trail"] = has_trail
    result["nature_tags"] = sorted(nature_tags_found)

    _cached_set(cache_key, result)
    return result


# =============================================================================
# SCORING MODEL: Daily Walk Value (0–10)
# =============================================================================

def _score_walk_time(walk_time_min: int) -> Tuple[float, str]:
    """Walk time subscore (0–3). Closer = better for daily use with stroller."""
    if walk_time_min <= WALK_TIME_EXCELLENT:
        return 3.0, f"{walk_time_min} min walk — excellent for daily stroller trips"
    elif walk_time_min <= WALK_TIME_GOOD:
        score = 3.0 - (walk_time_min - WALK_TIME_EXCELLENT) * (1.0 / (WALK_TIME_GOOD - WALK_TIME_EXCELLENT))
        return round(max(2.0, score), 1), f"{walk_time_min} min walk — good for regular visits"
    elif walk_time_min <= WALK_TIME_MARGINAL:
        score = 2.0 - (walk_time_min - WALK_TIME_GOOD) * (1.0 / (WALK_TIME_MARGINAL - WALK_TIME_GOOD))
        return round(max(1.0, score), 1), f"{walk_time_min} min walk — marginal for daily use"
    else:
        return 0.5, f"{walk_time_min} min walk — too far for daily stroller walks"


def _score_size_loop(osm_data: Dict[str, Any], rating: Optional[float], reviews: int, name: str) -> Tuple[float, str, bool]:
    """
    Size/loop potential subscore (0–3).
    Uses OSM polygon area + path network when available.
    Falls back to rating/reviews/name as weak proxy.
    """
    is_estimate = False

    # OSM-based scoring
    if osm_data.get("enriched"):
        area = osm_data.get("area_sqm")
        paths = osm_data.get("path_count", 0)
        has_trail = osm_data.get("has_trail", False)

        size_score = 0.0
        loop_score = 0.0

        # Area scoring
        if area and area >= SIZE_LARGE_SQM:
            size_score = 1.5
            size_reason = f"~{area / 4047:.0f} acres — large park"
        elif area and area >= SIZE_MEDIUM_SQM:
            size_score = 1.0
            size_reason = f"~{area / 4047:.0f} acres — medium park"
        elif area and area >= SIZE_SMALL_SQM:
            size_score = 0.5
            size_reason = f"~{area / 4047:.0f} acres — small park"
        else:
            size_score = 0.0
            size_reason = "area not determined from OSM"

        # Path/loop scoring
        if has_trail:
            loop_score = 1.5
            loop_reason = "named trail/path detected"
        elif paths >= PATH_NETWORK_DENSE:
            loop_score = 1.5
            loop_reason = f"{paths} footway segments — good loop potential"
        elif paths >= PATH_NETWORK_MODERATE:
            loop_score = 1.0
            loop_reason = f"{paths} footway segments — some paths"
        elif paths > 0:
            loop_score = 0.5
            loop_reason = f"{paths} footway segment(s) — minimal paths"
        else:
            loop_score = 0.0
            loop_reason = "no footway/path data in OSM"

        total = min(3.0, size_score + loop_score)
        reason = f"{size_reason}; {loop_reason}"
        return total, reason, False

    # Fallback: rating/reviews/name proxy
    is_estimate = True
    score = 0.0
    reasons = []

    # High reviews usually correlate with larger, well-known parks
    if reviews >= 500:
        score += 1.5
        reasons.append(f"{reviews} reviews suggests a major park")
    elif reviews >= 200:
        score += 1.0
        reasons.append(f"{reviews} reviews suggests a substantial park")
    elif reviews >= 50:
        score += 0.5
        reasons.append(f"{reviews} reviews — moderate visibility")

    # Name-based trail/greenway hints
    name_lower = name.lower()
    trail_words = ["trail", "greenway", "path", "loop", "preserve", "forest", "nature"]
    if any(w in name_lower for w in trail_words):
        score += 1.0
        reasons.append("name suggests trails or nature area")
    elif any(w in name_lower for w in ["park", "garden", "lake", "reservoir"]):
        score += 0.5
        reasons.append("name suggests green space")

    total = min(3.0, score)
    reason = "; ".join(reasons) if reasons else "limited size data"
    return total, f"{reason} (estimate)", True


def _score_quality(rating: Optional[float], reviews: int) -> Tuple[float, str]:
    """Quality proxy subscore (0–2). Based on Google rating + review count."""
    if rating is None:
        return 0.0, "no rating data"

    score = 0.0
    parts = []

    # Rating component (0–1.2)
    if rating >= QUALITY_HIGH_RATING:
        score += 1.2
        parts.append(f"{rating:.1f}★ — highly rated")
    elif rating >= QUALITY_MID_RATING:
        score += 0.8
        parts.append(f"{rating:.1f}★ — well rated")
    elif rating >= 3.5:
        score += 0.4
        parts.append(f"{rating:.1f}★ — average rating")
    else:
        parts.append(f"{rating:.1f}★ — below average")

    # Review volume component (0–0.8)
    if reviews >= QUALITY_HIGH_REVIEWS:
        score += 0.8
        parts.append(f"{reviews} reviews — well established")
    elif reviews >= QUALITY_MID_REVIEWS:
        score += 0.5
        parts.append(f"{reviews} reviews — moderate")
    elif reviews >= 10:
        score += 0.2
        parts.append(f"{reviews} reviews — limited data")
    else:
        parts.append(f"{reviews} reviews — very few reviews")

    return min(2.0, round(score, 1)), "; ".join(parts)


def _score_nature_feel(osm_data: Dict[str, Any], name: str, types: List[str]) -> Tuple[float, str]:
    """Nature feel proxy subscore (0–2). OSM nature tags + name keywords."""
    score = 0.0
    parts = []

    # OSM nature tags
    nature_tags = osm_data.get("nature_tags", [])
    if nature_tags:
        forest_water = [t for t in nature_tags if any(
            w in t for w in ["forest", "wood", "water", "river", "stream", "wetland", "nature_reserve"]
        )]
        if len(forest_water) >= 2:
            score += 1.5
            parts.append(f"strong nature indicators: {', '.join(forest_water[:3])}")
        elif forest_water:
            score += 1.0
            parts.append(f"nature indicator: {forest_water[0]}")
        else:
            score += 0.5
            parts.append(f"green tags: {', '.join(nature_tags[:2])}")

    # Name-based nature feel
    name_lower = name.lower()
    nature_name_words = [
        "forest", "woods", "nature", "preserve", "wilderness", "creek",
        "river", "lake", "pond", "wetland", "marsh", "ravine", "canyon",
        "botanical", "arboretum", "sanctuary",
    ]
    trail_name_words = ["trail", "greenway", "path", "hike"]

    if any(w in name_lower for w in nature_name_words):
        if not nature_tags:  # Don't double-count if OSM already scored
            score += 1.0
            parts.append("name suggests natural setting")
        else:
            score += 0.3
            parts.append("name reinforces nature feel")
    elif any(w in name_lower for w in trail_name_words):
        if not nature_tags:
            score += 0.5
            parts.append("name suggests trail/walking area")

    # Type-based bonus
    if "national_park" in types:
        score += 0.5
        parts.append("national park designation")
    elif "campground" in types and score < 1.5:
        score += 0.3
        parts.append("campground area")

    if not parts:
        parts.append("no nature indicators found")

    return min(2.0, round(score, 1)), "; ".join(parts)


def score_green_space(
    place: Dict[str, Any],
    lat: float,
    lng: float,
    osm_data: Optional[Dict[str, Any]] = None,
) -> GreenSpaceResult:
    """
    Score a single green space for Daily Walk Value (0–10).

    Subscores:
      - Walk time (0–3)
      - Size/loop potential (0–3)
      - Quality proxy (0–2)
      - Nature feel (0–2)
    """
    name = place.get("name", "Unknown")
    rating = place.get("rating")
    reviews = place.get("user_ratings_total", 0)
    walk_time = place.get("_walk_time_min", 9999)
    types = place.get("types", [])
    place_lat = place.get("_lat", 0)
    place_lng = place.get("_lng", 0)

    if osm_data is None:
        osm_data = {}

    # Compute subscores
    wt_score, wt_reason = _score_walk_time(walk_time)
    sz_score, sz_reason, sz_estimate = _score_size_loop(osm_data, rating, reviews, name)
    q_score, q_reason = _score_quality(rating, reviews)
    nf_score, nf_reason = _score_nature_feel(osm_data, name, types)

    total = round(wt_score + sz_score + q_score + nf_score, 1)
    total = min(10.0, total)

    # Build subscores
    subscores = [
        DailyWalkSubscore("Walk Time", wt_score, 3.0, wt_reason),
        DailyWalkSubscore("Size & Loop Potential", sz_score, 3.0, sz_reason, is_estimate=sz_estimate),
        DailyWalkSubscore("Quality", q_score, 2.0, q_reason),
        DailyWalkSubscore("Nature Feel", nf_score, 2.0, nf_reason),
    ]

    # Build reasons list
    reasons = []
    if wt_score >= 2.5:
        reasons.append(f"Very walkable ({walk_time} min)")
    elif wt_score >= 1.5:
        reasons.append(f"Walkable ({walk_time} min)")
    else:
        reasons.append(f"Far walk ({walk_time} min)")

    if sz_score >= 2.0:
        reasons.append("Good size for loops")
    elif sz_score >= 1.0:
        reasons.append("Moderate size")

    if q_score >= 1.5:
        reasons.append("Well reviewed")
    if nf_score >= 1.5:
        reasons.append("Strong nature feel")
    elif nf_score >= 0.5:
        reasons.append("Some nature elements")

    # Criteria pass/fail
    criteria_status, criteria_reasons = _evaluate_criteria(
        total, wt_score, sz_score, walk_time
    )

    return GreenSpaceResult(
        place_id=place.get("place_id"),
        name=name,
        rating=rating,
        user_ratings_total=reviews,
        walk_time_min=walk_time,
        types=types,
        types_display=_format_types(types),
        lat=place_lat,
        lng=place_lng,
        daily_walk_value=total,
        walk_time_score=wt_score,
        size_loop_score=sz_score,
        quality_score=q_score,
        nature_feel_score=nf_score,
        subscores=subscores,
        reasons=reasons,
        criteria_status=criteria_status,
        criteria_reasons=criteria_reasons,
        osm_enriched=osm_data.get("enriched", False),
        osm_area_sqm=osm_data.get("area_sqm"),
        osm_path_count=osm_data.get("path_count", 0),
        osm_has_trail=osm_data.get("has_trail", False),
        osm_nature_tags=osm_data.get("nature_tags", []),
    )


def _evaluate_criteria(total: float, wt_score: float, sz_score: float, walk_time: int) -> Tuple[str, List[str]]:
    """Determine PASS / BORDERLINE / FAIL with reasons."""
    reasons = []

    if walk_time > WALK_TIME_MARGINAL:
        reasons.append(f"Walk time ({walk_time} min) exceeds {WALK_TIME_MARGINAL} min limit")
        return "FAIL", reasons

    if total >= DAILY_PARK_MIN_TOTAL:
        if wt_score >= DAILY_PARK_MIN_WALK_SCORE and sz_score >= DAILY_PARK_MIN_SIZE_SCORE:
            reasons.append(f"Score {total:.1f}/10 meets daily park criteria")
            if walk_time <= WALK_TIME_EXCELLENT:
                reasons.append("Excellent walk distance for daily use")
            return "PASS", reasons

    # Borderline cases
    if total >= DAILY_PARK_MIN_TOTAL - 1.5:
        if wt_score < DAILY_PARK_MIN_WALK_SCORE:
            reasons.append(f"Walk time score ({wt_score}/3) is marginal")
        if sz_score < DAILY_PARK_MIN_SIZE_SCORE:
            reasons.append("Insufficient size/loop evidence")
        reasons.append(f"Score {total:.1f}/10 is borderline")
        return "BORDERLINE", reasons

    # Fail
    if wt_score < DAILY_PARK_MIN_WALK_SCORE:
        reasons.append(f"Walk time ({walk_time} min) is too far for daily stroller walks")
    if sz_score < DAILY_PARK_MIN_SIZE_SCORE:
        reasons.append("No evidence of adequate size or loop paths")
    if total < DAILY_PARK_MIN_TOTAL:
        reasons.append(f"Score {total:.1f}/10 below {DAILY_PARK_MIN_TOTAL} threshold")

    return "FAIL", reasons


# =============================================================================
# MAIN ENGINE
# =============================================================================

def evaluate_green_escape(
    maps_client,
    lat: float,
    lng: float,
    enable_osm: bool = True,
) -> GreenEscapeEvaluation:
    """
    Full green escape evaluation.

    1. Find green spaces within walking distance.
    2. Optionally expand radius if too few results.
    3. Enrich with OSM data.
    4. Score each space for Daily Walk Value.
    5. Return best daily park + comprehensive nearby list.
    """
    evaluation = GreenEscapeEvaluation()
    evaluation.criteria = {
        "walk_time_max_min": WALK_TIME_MARGINAL,
        "walk_time_ideal_min": WALK_TIME_EXCELLENT,
        "daily_value_pass_threshold": DAILY_PARK_MIN_TOTAL,
        "scoring_model": "walk_time(0-3) + size_loop(0-3) + quality(0-2) + nature_feel(0-2)",
    }

    # Step 1: Find green spaces
    radius = DEFAULT_RADIUS_M
    places = find_green_spaces(maps_client, lat, lng, radius_m=radius)

    if len(places) < MIN_RESULTS_BEFORE_EXPAND:
        # Expand search
        radius = EXPANDED_RADIUS_M
        places = find_green_spaces(maps_client, lat, lng, radius_m=radius)
        evaluation.messages.append(
            f"Expanded search to {radius}m — only {len(places)} results in default radius."
        )

    evaluation.search_radius_used = radius

    if not places:
        evaluation.messages.append("No green spaces found within search radius.")
        return evaluation

    # Step 2: Enrich with OSM and score each place.
    # Cap OSM enrichment to the closest N spaces to limit Overpass calls.
    MAX_OSM_ENRICHMENTS = 8
    scored: List[GreenSpaceResult] = []
    for idx, place in enumerate(places):
        place_lat = place.get("_lat", 0)
        place_lng = place.get("_lng", 0)

        osm_data = {}
        if enable_osm and place_lat and place_lng and idx < MAX_OSM_ENRICHMENTS:
            try:
                osm_data = enrich_from_osm(place_lat, place_lng, place.get("name", ""))
            except Exception:
                osm_data = {}

        result = score_green_space(place, lat, lng, osm_data)
        scored.append(result)

    # Step 3: Sort by daily walk value (descending)
    scored.sort(key=lambda r: (-r.daily_walk_value, r.walk_time_min))

    # Step 4: Select best daily park
    passing = [s for s in scored if s.criteria_status == "PASS"]
    if passing:
        evaluation.best_daily_park = passing[0]
    elif scored:
        # If no PASS, pick the best BORDERLINE, or best overall
        borderline = [s for s in scored if s.criteria_status == "BORDERLINE"]
        if borderline:
            evaluation.best_daily_park = borderline[0]
            evaluation.messages.append(
                "No park fully meets daily walk criteria. Best borderline option shown."
            )
        else:
            evaluation.best_daily_park = scored[0]
            evaluation.messages.append(
                "No park meets daily walk criteria. Closest option shown."
            )

    # Step 5: Build nearby list (top N, excluding best if present)
    best_id = evaluation.best_daily_park.place_id if evaluation.best_daily_park else None
    nearby = [s for s in scored if s.place_id != best_id][:NEARBY_LIST_SIZE]
    evaluation.nearby_green_spaces = nearby

    # Step 6: Overall green escape score
    if evaluation.best_daily_park:
        evaluation.green_escape_score_0_10 = evaluation.best_daily_park.daily_walk_value
    else:
        evaluation.green_escape_score_0_10 = 0.0

    return evaluation


# =============================================================================
# INTEGRATION HELPERS
# =============================================================================

def green_escape_to_dict(evaluation: GreenEscapeEvaluation) -> Dict[str, Any]:
    """Convert GreenEscapeEvaluation to a JSON-serializable dict."""
    def _space_dict(s: GreenSpaceResult) -> Dict[str, Any]:
        return {
            "place_id": s.place_id,
            "name": s.name,
            "rating": s.rating,
            "user_ratings_total": s.user_ratings_total,
            "walk_time_min": s.walk_time_min,
            "types": s.types,
            "types_display": s.types_display,
            "daily_walk_value": s.daily_walk_value,
            "walk_time_score": s.walk_time_score,
            "size_loop_score": s.size_loop_score,
            "quality_score": s.quality_score,
            "nature_feel_score": s.nature_feel_score,
            "subscores": [
                {
                    "name": ss.name,
                    "score": ss.score,
                    "max_score": ss.max_score,
                    "reason": ss.reason,
                    "is_estimate": ss.is_estimate,
                }
                for ss in s.subscores
            ],
            "reasons": s.reasons,
            "criteria_status": s.criteria_status,
            "criteria_reasons": s.criteria_reasons,
            "osm_enriched": s.osm_enriched,
            "osm_area_sqm": s.osm_area_sqm,
            "osm_path_count": s.osm_path_count,
            "osm_has_trail": s.osm_has_trail,
            "osm_nature_tags": s.osm_nature_tags,
        }

    return {
        "best_daily_park": _space_dict(evaluation.best_daily_park) if evaluation.best_daily_park else None,
        "nearby_green_spaces": [_space_dict(s) for s in evaluation.nearby_green_spaces],
        "green_escape_score_0_10": evaluation.green_escape_score_0_10,
        "criteria": evaluation.criteria,
        "search_radius_used": evaluation.search_radius_used,
        "messages": evaluation.messages,
    }


def green_escape_to_legacy_format(evaluation: GreenEscapeEvaluation) -> Dict[str, Any]:
    """
    Convert to the legacy GreenSpaceEvaluation-compatible format so existing
    property_evaluator.py code continues to work during transition.
    """
    best = evaluation.best_daily_park
    return {
        "green_escape": {
            "name": best.name,
            "rating": best.rating,
            "user_ratings_total": best.user_ratings_total,
            "walk_time_min": best.walk_time_min,
            "types": best.types,
            "types_display": best.types_display,
        } if best else None,
        "green_escape_message": (
            evaluation.messages[0] if evaluation.messages and not best else
            (None if best else "No green spaces found within walking distance.")
        ),
        "green_spaces": [],
        "other_green_spaces": [
            {
                "name": s.name,
                "rating": s.rating,
                "user_ratings_total": s.user_ratings_total,
                "walk_time_min": s.walk_time_min,
                "types": s.types,
                "types_display": s.types_display,
            }
            for s in evaluation.nearby_green_spaces
        ],
        "green_spaces_message": (
            "Other parks and green spaces within walking distance."
            if evaluation.nearby_green_spaces
            else "No other green spaces found within walking distance."
        ),
    }
