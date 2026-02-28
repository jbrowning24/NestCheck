#!/usr/bin/env python3
"""
Property Livability Evaluator

Evaluates any U.S. address for daily life quality, health, and livability.
Works for rentals, purchases, or general location research.

Requirements:
- Google Maps API key (for Places, Distance Matrix, and Geocoding)
- OpenStreetMap data via Overpass API (for road classification)

Usage:
    python property_evaluator.py "123 Main St, Scarsdale, NY"
    python property_evaluator.py --url "https://www.zillow.com/homedetails/..."
"""

import os
import sys
import json
import math
import time
import logging
import argparse
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, List, Tuple, Dict, Any
from enum import Enum
import requests

logger = logging.getLogger(__name__)
from nc_trace import get_trace
from urllib.parse import quote
from dotenv import load_dotenv
from green_space import (
    GreenEscapeEvaluation,
    evaluate_green_escape,
)
from scoring_config import (
    PERSONA_PRESETS, DEFAULT_PERSONA, PersonaPreset, SCORING_MODEL,
    TIER2_NAME_TO_DIMENSION,
)
from spatial_data import SpatialDataStore

load_dotenv()

# Module-level score bands derived from SCORING_MODEL (consumed by tests)
SCORE_BANDS = [(b.threshold, b.label) for b in SCORING_MODEL.score_bands]


def get_score_band(score: int) -> dict:
    """Return the score band dict for a given 0-100 score."""
    for band in SCORING_MODEL.score_bands:
        if score >= band.threshold:
            return {"label": band.label, "css_class": band.css_class}
    last = SCORING_MODEL.score_bands[-1]
    return {"label": last.label, "css_class": last.css_class}

# =============================================================================
# CONFIGURATION
# =============================================================================

# Health & Safety Thresholds (in feet)
GAS_STATION_MIN_DISTANCE_FT = 500
HIGHWAY_MIN_DISTANCE_FT = 500
HIGH_VOLUME_ROAD_MIN_DISTANCE_FT = 500

# Environmental Health Warning Thresholds (in feet)
POWER_LINE_WARNING_DISTANCE_FT = 200
SUBSTATION_WARNING_DISTANCE_FT = 300
CELL_TOWER_WARNING_DISTANCE_FT = 500
INDUSTRIAL_ZONE_WARNING_DISTANCE_FT = 500
TRI_FACILITY_WARNING_DISTANCE_FT = 5280  # 1 mile — EPA TRI toxic release facilities
TRI_FACILITY_WARNING_RADIUS_M = round(TRI_FACILITY_WARNING_DISTANCE_FT / 3.28084)  # ≈ 1609m

# Walking time thresholds (in minutes)
PARK_WALK_IDEAL_MIN = 20
PARK_WALK_ACCEPTABLE_MIN = 30
THIRD_PLACE_WALK_IDEAL_MIN = 20
THIRD_PLACE_WALK_ACCEPTABLE_MIN = 30
METRO_NORTH_WALK_IDEAL_MIN = 20
METRO_NORTH_WALK_ACCEPTABLE_MIN = 30
PROVISIONING_WALK_IDEAL_MIN = 15
PROVISIONING_WALK_ACCEPTABLE_MIN = 30
FITNESS_WALK_IDEAL_MIN = 15
FITNESS_WALK_ACCEPTABLE_MIN = 30
SCHOOL_WALK_MAX_MIN = 30

# Schools evaluation is disabled by default due to high API call volume (~200+ calls).
# Set ENABLE_SCHOOLS=true in environment to activate.
ENABLE_SCHOOLS = os.environ.get("ENABLE_SCHOOLS", "").lower() == "true"

# Cost thresholds (monthly cost - rent or estimated mortgage + expenses)
COST_MAX = 7000
COST_TARGET = 6500
COST_IDEAL = 6000

# Size thresholds
MIN_SQFT = 1700
MIN_BEDROOMS = 2

# Park quality thresholds
MIN_PARK_ACRES = 5
MIN_PARK_RATING = 4.0
MIN_PARK_REVIEWS = 50
GREEN_SPACE_WALK_MAX_MIN = 30
GREEN_ESCAPE_MIN_REVIEWS = 100

GREEN_SPACE_TYPES = [
    "park",
    "playground",
    "campground",
    "natural_feature",
    "trail",
    "rv_park",
    "tourist_attraction",
]

PRIMARY_GREEN_ESCAPE_KEYWORDS = [
    "nature preserve",
    "state park",
    "trail",
    "riverwalk",
    "forest",
    "greenway",
]

EXCLUDED_PRIMARY_KEYWORDS = [
    "dog park",
    "playground",
    "sports complex",
    "skating rink",
    "ice rink",
    "roller rink",
    "pocket park",
    "mini park",
    "tot lot",
]

EXCLUDED_PRIMARY_TYPES = {
    "dog_park",
    "sports_complex",
    "stadium",
    "ice_skating_rink",
}

SUPPORTING_GREEN_SPACE_TYPES = {"park", "playground"}

# High-volume road detection is done via OSM tags (highway type, lane count)
# No hardcoded road names needed - works anywhere in the US



# =============================================================================
# EXCEPTIONS
# =============================================================================

class OverpassUnavailableError(Exception):
    """Raised when the Overpass API is temporarily unreachable or returns errors."""


# =============================================================================
# DATA CLASSES
# =============================================================================

class CheckResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    UNKNOWN = "UNKNOWN"


@dataclass
class Tier1Check:
    name: str
    result: CheckResult
    details: str
    value: Optional[Any] = None
    required: bool = True


@dataclass
class Tier2Score:
    name: str
    points: int
    max_points: int
    details: str


@dataclass
class Tier3Bonus:
    name: str
    points: int
    details: str


@dataclass
class GreenSpace:
    place_id: Optional[str]
    name: str
    rating: Optional[float]
    user_ratings_total: int
    walk_time_min: int
    types: List[str]
    types_display: str


@dataclass
class GreenSpaceEvaluation:
    green_spaces: List[GreenSpace] = field(default_factory=list)
    green_escape: Optional[GreenSpace] = None
    other_green_spaces: List[GreenSpace] = field(default_factory=list)
    green_escape_message: Optional[str] = None
    green_spaces_message: Optional[str] = None


@dataclass
class NeighborhoodPlace:
    """Single nearby amenity for context"""
    category: str  # "Provisioning", "Third Place", "Park", "School"
    name: str
    rating: Optional[float]
    walk_time_min: int
    place_type: str  # "supermarket", "cafe", etc.


@dataclass
class NeighborhoodSnapshot:
    """Collection of nearest key amenities"""
    places: List[NeighborhoodPlace] = field(default_factory=list)


@dataclass
class ChildcarePlace:
    name: str
    rating: Optional[float]
    user_ratings_total: Optional[int]
    walk_time_min: int
    website: Optional[str]


@dataclass
class SchoolPlace:
    name: str
    rating: Optional[float]
    user_ratings_total: Optional[int]
    walk_time_min: int
    website: Optional[str]
    level: str


@dataclass
class ChildSchoolingSnapshot:
    childcare: List[ChildcarePlace] = field(default_factory=list)
    schools_by_level: Dict[str, Optional[SchoolPlace]] = field(default_factory=dict)


@dataclass
class PrimaryTransitOption:
    name: str
    mode: str
    lat: float
    lng: float
    walk_time_min: int
    drive_time_min: Optional[int] = None
    parking_available: Optional[bool] = None
    user_ratings_total: Optional[int] = None
    frequency_class: Optional[str] = None


@dataclass
class MajorHubAccess:
    name: str
    travel_time_min: int
    transit_mode: str
    route_summary: Optional[str] = None


@dataclass
class UrbanAccessProfile:
    primary_transit: Optional[PrimaryTransitOption] = None
    major_hub: Optional[MajorHubAccess] = None


@dataclass
class TransitAccessResult:
    """Result of the smart transit frequency approximation."""
    primary_stop: Optional[str] = None
    walk_minutes: Optional[int] = None
    mode: Optional[str] = None
    frequency_bucket: str = "Very low"
    score_0_10: int = 0
    reasons: List[str] = field(default_factory=list)
    nearby_node_count: int = 0
    density_node_count: int = 0


@dataclass
class PropertyListing:
    """Property listing data - can be populated from manual input or scraped"""
    address: str
    cost: Optional[int] = None  # Monthly cost (rent or estimated mortgage + expenses)
    sqft: Optional[int] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    has_washer_dryer_in_unit: Optional[bool] = None
    has_central_air: Optional[bool] = None
    has_parking: Optional[bool] = None
    has_outdoor_space: Optional[bool] = None
    url: Optional[str] = None


@dataclass
class EvaluationResult:
    listing: PropertyListing
    lat: float
    lng: float
    neighborhood_snapshot: Optional[NeighborhoodSnapshot] = None
    child_schooling_snapshot: Optional[ChildSchoolingSnapshot] = None
    urban_access: Optional[UrbanAccessProfile] = None
    transit_access: Optional[TransitAccessResult] = None
    green_space_evaluation: Optional[GreenSpaceEvaluation] = None
    green_escape_evaluation: Optional[GreenEscapeEvaluation] = None
    transit_score: Optional[Dict[str, Any]] = None
    walk_scores: Dict[str, Optional[Any]] = field(default_factory=dict)
    bike_score: Optional[int] = None
    bike_rating: Optional[str] = None
    bike_metadata: Optional[Dict[str, Any]] = None

    tier1_checks: List[Tier1Check] = field(default_factory=list)
    tier2_scores: List[Tier2Score] = field(default_factory=list)
    tier3_bonuses: List[Tier3Bonus] = field(default_factory=list)

    passed_tier1: bool = False
    tier2_total: int = 0
    tier2_max: int = 0
    tier2_normalized: int = 0
    tier3_total: int = 0

    # Keep this from your branch
    tier3_bonus_reasons: List[str] = field(default_factory=list)

    # Neighborhood places surfaced from scoring (Phase 3)
    neighborhood_places: Optional[Dict[str, list]] = None

    # Scoring lens / persona applied during aggregation (NES-133)
    persona: Optional[PersonaPreset] = None

    # Keep these from main
    final_score: int = 0
    percentile_top: int = 0
    percentile_label: str = ""
    notes: List[str] = field(default_factory=list)

    # EJScreen block group environmental indicators (NES-EJScreen)
    ejscreen_profile: Optional[Dict[str, Any]] = None


# =============================================================================
# DEDUPLICATION HELPERS
# =============================================================================

def _dedupe_by_place_id(places: List[Dict]) -> List[Dict]:
    """Remove duplicate places by Google place_id, keeping the first occurrence."""
    seen: set = set()
    unique: List[Dict] = []
    for place in places:
        pid = place.get("place_id")
        if pid and pid in seen:
            continue
        if pid:
            seen.add(pid)
        unique.append(place)
    return unique


# =============================================================================
# DISTANCE HELPERS
# =============================================================================

def _distance_feet(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """Haversine straight-line distance between two points, in feet."""
    R = 20902231  # Earth's radius in feet
    rlat1, rlon1 = math.radians(lat1), math.radians(lng1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lng2)
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return int(R * c)


def _closest_distance_to_way_ft(
    prop_lat: float, prop_lng: float, way_node_ids: List[int], all_nodes: Dict[int, Tuple[float, float]]
) -> float:
    """Minimum distance in feet from property to any resolved node of a way.

    *way_node_ids* is the ``nodes`` list from the Overpass way element.
    *all_nodes* maps node-ID → (lat, lon) for every ``type=node`` element in
    the Overpass response.  Returns ``float('inf')`` when no nodes can be
    resolved (prevents false-positive warnings).
    """
    min_dist = float("inf")
    for nid in way_node_ids:
        coords = all_nodes.get(nid)
        if coords is None:
            continue
        d = _distance_feet(prop_lat, prop_lng, coords[0], coords[1])
        if d < min_dist:
            min_dist = d
    return min_dist


# =============================================================================
# API CLIENTS
# =============================================================================

class GoogleMapsClient:
    """Client for Google Maps APIs"""

    # Per-call timeout in seconds.  Keeps any single request from hanging
    # the whole evaluation.  10 s is generous for Google Maps — p99 is < 2 s.
    DEFAULT_TIMEOUT = 10

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://maps.googleapis.com/maps/api"
        self.session = requests.Session()
        self.session.trust_env = False
        # Per-evaluation cache for places_nearby — avoids duplicate searches
        # within the same evaluation run.  Keyed by (lat, lng, type, radius, keyword).
        self._places_cache: Dict[tuple, List[Dict]] = {}

    def _traced_get(self, endpoint_name: str, url: str, params: dict) -> dict:
        """GET request with automatic trace recording."""
        t0 = time.time()
        response = self.session.get(url, params=params, timeout=self.DEFAULT_TIMEOUT)
        elapsed_ms = int((time.time() - t0) * 1000)
        data = response.json()
        provider_status = data.get("status", "") if isinstance(data, dict) else ""
        trace = get_trace()
        if trace:
            trace.record_api_call(
                service="google_maps",
                endpoint=endpoint_name,
                elapsed_ms=elapsed_ms,
                status_code=response.status_code,
                provider_status=provider_status,
            )
        return data

    def geocode(self, address: str) -> Tuple[float, float]:
        """Convert address to lat/lng coordinates"""
        details = self.geocode_details(address)
        return details["lat"], details["lng"]

    def geocode_details(self, address: str) -> Dict[str, Any]:
        """Geocode address and return canonical details used for dedupe."""
        url = f"{self.base_url}/geocode/json"
        params = {
            "address": address,
            "key": self.api_key
        }
        data = self._traced_get("geocode", url, params)

        if data["status"] != "OK":
            raise ValueError(f"Geocoding failed: {data['status']}")

        first = data["results"][0]
        location = first["geometry"]["location"]
        return {
            "lat": location["lat"],
            "lng": location["lng"],
            "place_id": first.get("place_id"),
            "formatted_address": first.get("formatted_address", address),
        }
    
    def places_nearby(
        self,
        lat: float,
        lng: float,
        place_type: str,
        radius_meters: int = 2000,
        keyword: Optional[str] = None
    ) -> List[Dict]:
        """Search for places near a location.

        Results are cached per-evaluation so repeated identical searches
        (same coordinates, type, radius, keyword) return instantly without
        an API call.
        """
        cache_key = (round(lat, 6), round(lng, 6), place_type, radius_meters, keyword)
        if not hasattr(self, "_places_cache"):
            self._places_cache = {}
        cached = self._places_cache.get(cache_key)
        if cached is not None:
            return cached

        url = f"{self.base_url}/place/nearbysearch/json"
        params = {
            "location": f"{lat},{lng}",
            "radius": radius_meters,
            "type": place_type,
            "key": self.api_key
        }
        if keyword:
            params["keyword"] = keyword

        data = self._traced_get("places_nearby", url, params)

        if data["status"] not in ["OK", "ZERO_RESULTS"]:
            raise ValueError(f"Places API failed: {data['status']}")

        results = data.get("results", [])
        self._places_cache[cache_key] = results
        return results
    
    def place_details(self, place_id: str, fields: Optional[List[str]] = None) -> Dict:
        """Get detailed information about a place"""
        url = f"{self.base_url}/place/details/json"
        default_fields = [
            "name",
            "rating",
            "user_ratings_total",
            "types",
            "formatted_address",
            "website",
        ]
        params = {
            "place_id": place_id,
            "fields": ",".join(fields or default_fields),
            "key": self.api_key
        }
        data = self._traced_get("place_details", url, params)

        if data["status"] != "OK":
            raise ValueError(f"Place Details API failed: {data['status']}")

        return data.get("result", {})

    def walking_time(self, origin: Tuple[float, float], dest: Tuple[float, float]) -> int:
        """Get walking time in minutes between two points"""
        url = f"{self.base_url}/distancematrix/json"
        params = {
            "origins": f"{origin[0]},{origin[1]}",
            "destinations": f"{dest[0]},{dest[1]}",
            "mode": "walking",
            "key": self.api_key
        }
        data = self._traced_get("walking_time", url, params)

        if data["status"] != "OK":
            raise ValueError(f"Distance Matrix API failed: {data['status']}")

        element = data["rows"][0]["elements"][0]
        if element["status"] != "OK":
            return 9999  # Unreachable

        return element["duration"]["value"] // 60  # Convert seconds to minutes

    def driving_time(self, origin: Tuple[float, float], dest: Tuple[float, float]) -> int:
        """Get driving time in minutes between two points"""
        url = f"{self.base_url}/distancematrix/json"
        params = {
            "origins": f"{origin[0]},{origin[1]}",
            "destinations": f"{dest[0]},{dest[1]}",
            "mode": "driving",
            "key": self.api_key
        }
        data = self._traced_get("driving_time", url, params)

        if data["status"] != "OK":
            raise ValueError(f"Distance Matrix API failed: {data['status']}")

        element = data["rows"][0]["elements"][0]
        if element["status"] != "OK":
            return 9999  # Unreachable

        return element["duration"]["value"] // 60  # Convert seconds to minutes

    def transit_time(self, origin: Tuple[float, float], dest: Tuple[float, float]) -> int:
        """Get transit time in minutes between two points"""
        url = f"{self.base_url}/distancematrix/json"
        params = {
            "origins": f"{origin[0]},{origin[1]}",
            "destinations": f"{dest[0]},{dest[1]}",
            "mode": "transit",
            "key": self.api_key
        }
        data = self._traced_get("transit_time", url, params)

        if data["status"] != "OK":
            raise ValueError(f"Distance Matrix API failed: {data['status']}")

        element = data["rows"][0]["elements"][0]
        if element["status"] != "OK":
            return 9999  # Unreachable

        return element["duration"]["value"] // 60  # Convert seconds to minutes

    def text_search(
        self,
        query: str,
        lat: float,
        lng: float,
        radius_meters: int = 50000
    ) -> List[Dict]:
        """Search for places using a text query near a location"""
        url = f"{self.base_url}/place/textsearch/json"
        params = {
            "query": query,
            "location": f"{lat},{lng}",
            "radius": radius_meters,
            "key": self.api_key
        }
        data = self._traced_get("text_search", url, params)

        if data["status"] not in ["OK", "ZERO_RESULTS"]:
            raise ValueError(f"Text Search API failed: {data['status']}")

        return data.get("results", [])

    def _distance_matrix_batch(
        self,
        origin: Tuple[float, float],
        destinations: List[Tuple[float, float]],
        mode: str,
        endpoint_name: str,
    ) -> List[int]:
        """Batch Distance Matrix request — shared implementation for walk/drive.

        Accepts up to len(destinations) points.  Chunks into groups of 25
        (the Google Distance Matrix per-request limit) so callers don't need
        to worry about the cap.

        Returns a list of travel times in **minutes** (int), one per
        destination in the same order.  Unreachable destinations get 9999.

        Each chunk is a single traced API call, so 50 destinations = 2 calls
        instead of 50.
        """
        if not destinations:
            return []

        CHUNK_SIZE = 25
        all_times: List[int] = []
        origin_str = f"{origin[0]},{origin[1]}"
        url = f"{self.base_url}/distancematrix/json"

        for i in range(0, len(destinations), CHUNK_SIZE):
            chunk = destinations[i : i + CHUNK_SIZE]
            dest_str = "|".join(f"{d[0]},{d[1]}" for d in chunk)
            params = {
                "origins": origin_str,
                "destinations": dest_str,
                "mode": mode,
                "key": self.api_key,
            }
            data = self._traced_get(endpoint_name, url, params)

            if data.get("status") != "OK":
                all_times.extend([9999] * len(chunk))
                continue

            elements = data.get("rows", [{}])[0].get("elements", [])
            for j, dest_coord in enumerate(chunk):
                if j < len(elements) and elements[j].get("status") == "OK":
                    all_times.append(elements[j]["duration"]["value"] // 60)
                else:
                    all_times.append(9999)

        return all_times

    def walking_times_batch(
        self,
        origin: Tuple[float, float],
        destinations: List[Tuple[float, float]],
    ) -> List[int]:
        """Batch walking times — 1 API call per 25 destinations instead of 1 each.

        Example: 10 destinations = 1 API call instead of 10.
        For >25 destinations, automatically chunks into multiple requests of 25.

        Returns list of walk times in minutes (int), 9999 for unreachable.
        Order matches the input destinations list.
        """
        return self._distance_matrix_batch(origin, destinations, "walking", "walking_batch")

    def driving_times_batch(
        self,
        origin: Tuple[float, float],
        destinations: List[Tuple[float, float]],
    ) -> List[int]:
        """Batch driving times — 1 API call per 25 destinations instead of 1 each.

        Example: 10 destinations = 1 API call instead of 10.
        For >25 destinations, automatically chunks into multiple requests of 25.

        Returns list of drive times in minutes (int), 9999 for unreachable.
        Order matches the input destinations list.
        """
        return self._distance_matrix_batch(origin, destinations, "driving", "driving_batch")

    def distance_feet(self, origin: Tuple[float, float], dest: Tuple[float, float]) -> int:
        """Calculate straight-line distance in feet"""
        return _distance_feet(origin[0], origin[1], dest[0], dest[1])


class OverpassClient:
    """Client for OpenStreetMap Overpass API - for road data."""

    def __init__(self):
        pass

    def get_nearby_roads(self, lat: float, lng: float, radius_meters: int = 200) -> List[Dict]:
        # DEPRECATED: No longer called by evaluate_property() as of HPMS migration.
        # Retained temporarily for backward compatibility. Remove in future cleanup.
        """Get roads within radius of a point"""
        query = f"""
        [out:json][timeout:25];
        (
          way["highway"~"motorway|trunk|primary|secondary"](around:{radius_meters},{lat},{lng});
        );
        out body;
        >;
        out skel qt;
        """
        try:
            from overpass_http import (
                OverpassQueryError as _HTTPQueryError,
                OverpassRateLimitError as _HTTPRateLimitError,
                overpass_query,
            )
            data = overpass_query(query, caller="get_nearby_roads", timeout=25, ttl_days=30)
        except (_HTTPRateLimitError, _HTTPQueryError) as e:
            raise OverpassUnavailableError(
                "Road-data service temporarily unavailable"
            ) from e
        
        roads = []
        for element in data.get("elements", []):
            if element["type"] == "way" and "tags" in element:
                roads.append({
                    "name": element["tags"].get("name", "Unnamed"),
                    "ref": element["tags"].get("ref", ""),
                    "highway_type": element["tags"].get("highway", ""),
                    "lanes": element["tags"].get("lanes", ""),
                })

        return roads


def get_bike_score(address: str, lat: float, lon: float) -> Dict[str, Optional[Any]]:
    """Fetch bike score details from Walk Score API."""
    api_key = os.environ.get("WALKSCORE_API_KEY")
    if not api_key:
        return {"bike_score": None, "bike_rating": None, "bike_metadata": None}

    url = "https://api.walkscore.com/score"
    params = {
        "format": "json",
        "address": address,
        "lat": lat,
        "lon": lon,
        "bike": 1,
        "wsapikey": api_key,
    }

    try:
        _t0 = time.time()
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        _elapsed = int((time.time() - _t0) * 1000)
        _trace = get_trace()
        if _trace:
            _trace.record_api_call(
                service="walkscore", endpoint="get_bike_score",
                elapsed_ms=_elapsed, status_code=response.status_code,
                provider_status=str(data.get("status", "")),
            )
    except (requests.RequestException, ValueError):
        return {"bike_score": None, "bike_rating": None, "bike_metadata": None}

    bike_data = data.get("bike") if isinstance(data, dict) else None
    if not bike_data:
        return {"bike_score": None, "bike_rating": None, "bike_metadata": None}

    bike_score = bike_data.get("score")
    bike_rating = bike_data.get("description")
    metadata = {key: value for key, value in bike_data.items() if key not in {"score", "description"}}

    return {
        "bike_score": int(bike_score) if bike_score is not None else None,
        "bike_rating": bike_rating,
        "bike_metadata": metadata or None,
    }


# =============================================================================
# EVALUATION FUNCTIONS
# =============================================================================

def get_transit_score(address: str, lat: float, lon: float) -> Dict[str, Any]:
    api_key = os.environ.get("WALKSCORE_API_KEY")
    default_response = {
        "transit_score": None,
        "transit_rating": None,
        "transit_summary": None,
        "nearby_transit_lines": None,
    }

    if not api_key:
        return default_response

    url = "https://api.walkscore.com/score"
    params = {
        "format": "json",
        "address": address,
        "lat": lat,
        "lon": lon,
        "transit": 1,
        "bike": 1,
        "wsapikey": api_key,
    }

    try:
        _t0 = time.time()
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        _elapsed = int((time.time() - _t0) * 1000)
        _trace = get_trace()
        if _trace:
            _trace.record_api_call(
                service="walkscore", endpoint="get_transit_score",
                elapsed_ms=_elapsed, status_code=response.status_code,
                provider_status=str(data.get("status", "")),
            )
    except (requests.RequestException, ValueError):
        return default_response

    if data.get("status") != 1:
        return default_response

    transit_data = data.get("transit") or {}
    transit_score = transit_data.get("score")
    transit_description = transit_data.get("description")
    transit_summary = transit_data.get("summary")
    nearby_routes = transit_data.get("nearbyRoutes") or []

    nearby_transit_lines = []
    for route in nearby_routes:
        if not isinstance(route, dict):
            continue
        name = route.get("route_name")
        route_type = route.get("route_type")
        distance = route.get("distance")
        if not name and not route_type and distance is None:
            continue
        route_type_label = None
        if route_type:
            route_type_label = str(route_type).replace("_", " ").title()
        nearby_transit_lines.append(
            {
                "name": name,
                "type": route_type_label,
                "distance_miles": distance,
            }
        )

    return {
        "transit_score": int(transit_score) if transit_score is not None else None,
        "transit_rating": transit_description,
        "transit_summary": transit_summary,
        "nearby_transit_lines": nearby_transit_lines or None,
    }


def _coerce_score(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_walk_scores(address: str, lat: float, lon: float) -> Dict[str, Optional[Any]]:
    api_key = os.environ.get("WALKSCORE_API_KEY")
    default_scores = {
        "walk_score": None,
        "walk_description": None,
        "transit_score": None,
        "transit_description": None,
        "bike_score": None,
        "bike_description": None,
    }
    if not api_key:
        return default_scores

    url = "https://api.walkscore.com/score"
    params = {
        "format": "json",
        "address": address,
        "lat": lat,
        "lon": lon,
        "transit": 1,
        "bike": 1,
        "wsapikey": api_key,
    }

    try:
        _t0 = time.time()
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        _elapsed = int((time.time() - _t0) * 1000)
        _trace = get_trace()
        if _trace:
            _trace.record_api_call(
                service="walkscore", endpoint="get_walk_scores",
                elapsed_ms=_elapsed, status_code=response.status_code,
                provider_status=str(data.get("status", "")),
            )
    except (requests.RequestException, ValueError):
        return default_scores

    if data.get("status") != 1:
        return default_scores

    transit = data.get("transit") or {}
    bike = data.get("bike") or {}

    return {
        "walk_score": _coerce_score(data.get("walkscore")),
        "walk_description": data.get("description"),
        "transit_score": _coerce_score(transit.get("score")),
        "transit_description": transit.get("description"),
        "bike_score": _coerce_score(bike.get("score")),
        "bike_description": bike.get("description"),
    }

def check_gas_stations(
    maps: GoogleMapsClient, 
    lat: float, 
    lng: float
) -> Tier1Check:
    """Check distance to nearest gas station"""
    try:
        stations = maps.places_nearby(lat, lng, "gas_station", radius_meters=500)
        
        if not stations:
            return Tier1Check(
                name="Gas station",
                result=CheckResult.PASS,
                details="No gas stations within 500 feet",
                value=None
            )
        
        # Find closest
        min_distance = float('inf')
        closest_name = ""
        for station in stations:
            station_lat = station["geometry"]["location"]["lat"]
            station_lng = station["geometry"]["location"]["lng"]
            dist = maps.distance_feet((lat, lng), (station_lat, station_lng))
            if dist < min_distance:
                min_distance = dist
                closest_name = station.get("name", "Unknown")
        
        if min_distance >= GAS_STATION_MIN_DISTANCE_FT:
            return Tier1Check(
                name="Gas station",
                result=CheckResult.PASS,
                details=f"Nearest: {closest_name} ({min_distance:,} ft)",
                value=min_distance
            )
        else:
            return Tier1Check(
                name="Gas station",
                result=CheckResult.FAIL,
                details=f"TOO CLOSE: {closest_name} ({min_distance:,} ft < {GAS_STATION_MIN_DISTANCE_FT} ft)",
                value=min_distance
            )
    except Exception as e:
        logger.warning("Gas station check failed: %s", e)
        return Tier1Check(
            name="Gas station",
            result=CheckResult.UNKNOWN,
            details="Could not reach mapping service to verify this check"
        )


# ---------------------------------------------------------------------------
# High-traffic road check (HPMS AADT data) — replaces check_highways() and
# check_high_volume_roads() which used Overpass/OSM road classification as a
# proxy. This check uses actual measured traffic volume from FHWA HPMS data.
#
# Evidence basis: CDC/HEI finding that traffic-related air pollution causes
# health effects within 150m of roads carrying AADT >= 50,000, diminishing
# to background levels at 150-300m.
# ---------------------------------------------------------------------------

HIGH_TRAFFIC_AADT_THRESHOLD = 50_000   # vehicles/day
HIGH_TRAFFIC_FAIL_RADIUS_M = 150       # meters — elevated-risk zone
HIGH_TRAFFIC_WARN_RADIUS_M = 300       # meters — diminishing-risk zone


def check_high_traffic_road(lat: float, lng: float, spatial_store) -> Tier1Check:
    """Check for high-traffic roads using HPMS AADT data.

    Queries the local SpatiaLite database for HPMS road segments within 300m.
    Uses measured Annual Average Daily Traffic (AADT) counts rather than
    OSM road classification.

    Thresholds (per CDC/HEI research):
      FAIL:    AADT >= 50,000 within 150m
      WARNING: AADT >= 50,000 within 150-300m
      PASS:    No qualifying segments within 300m
      UNKNOWN: SpatialDataStore unavailable or no data
    """
    if spatial_store is None or not spatial_store.is_available():
        return Tier1Check(
            name="High-traffic road",
            result=CheckResult.UNKNOWN,
            details="Traffic volume data not available for this area",
            value=None,
        )

    try:
        segments = spatial_store.lines_within(
            lat, lng, HIGH_TRAFFIC_WARN_RADIUS_M, "hpms"
        )

        # Filter out segments with no AADT data
        with_aadt = [
            s for s in segments
            if s.metadata.get("aadt") is not None
        ]

        # Find highest-AADT segment within the fail radius (150m)
        fail_candidates = [
            s for s in with_aadt
            if s.distance_meters <= HIGH_TRAFFIC_FAIL_RADIUS_M
            and s.metadata["aadt"] >= HIGH_TRAFFIC_AADT_THRESHOLD
        ]

        if fail_candidates:
            worst = max(fail_candidates, key=lambda s: s.metadata["aadt"])
            return _high_traffic_result(CheckResult.FAIL, worst)

        # Check warning band (150-300m)
        warn_candidates = [
            s for s in with_aadt
            if s.distance_meters > HIGH_TRAFFIC_FAIL_RADIUS_M
            and s.metadata["aadt"] >= HIGH_TRAFFIC_AADT_THRESHOLD
        ]

        if warn_candidates:
            worst = max(warn_candidates, key=lambda s: s.metadata["aadt"])
            return _high_traffic_result(CheckResult.WARNING, worst)

        # No high-traffic roads nearby
        return Tier1Check(
            name="High-traffic road",
            result=CheckResult.PASS,
            details="No high-traffic roads within 1,000 ft",
            value=None,
        )

    except Exception as e:
        logger.warning("High-traffic road check failed: %s", e)
        return Tier1Check(
            name="High-traffic road",
            result=CheckResult.UNKNOWN,
            details="Could not query traffic volume data",
            value=None,
        )


def _high_traffic_result(result: CheckResult, segment) -> Tier1Check:
    """Build a Tier1Check for a high-traffic road FAIL or WARNING."""
    aadt = segment.metadata.get("aadt", 0)
    dist_ft = round(segment.distance_feet)

    # Use route_id as fallback when the name is missing or generic
    road_name = segment.name
    if not road_name or road_name == "Unknown" or road_name == "HPMS segment":
        road_name = segment.metadata.get("route_id", "")
    road_name = road_name.strip() if road_name else ""

    if road_name:
        details = f"{road_name}: {aadt:,} vehicles/day, {dist_ft:,} ft away"
    else:
        details = f"Road with {aadt:,} vehicles/day found {dist_ft:,} ft away"

    return Tier1Check(
        name="High-traffic road",
        result=result,
        details=details,
        value={
            "aadt": aadt,
            "distance_ft": dist_ft,
            "road_name": road_name or None,
            "radius_m": round(segment.distance_meters, 1),
        },
    )


# =============================================================================
# ENVIRONMENTAL HEALTH PROXIMITY CHECKS (NES-57)
# =============================================================================

def _parse_max_voltage(voltage_str: str) -> int:
    """Parse an OSM voltage tag, returning the maximum value in volts.

    The tag may be a single number (``"115000"``), semicolon-separated for
    multi-circuit lines (``"115000;230000"``), or absent/empty.
    Returns 0 on any parse failure so the element is excluded rather than
    producing a false positive.
    """
    if not voltage_str:
        return 0
    max_v = 0
    for part in voltage_str.split(";"):
        part = part.strip()
        try:
            v = int(part)
            if v > max_v:
                max_v = v
        except (ValueError, TypeError):
            continue
    return max_v


# =============================================================================
# EJSCREEN BLOCK GROUP DATA (local SpatiaLite — no API cost)
# =============================================================================

# 12 of 13 EPA EJScreen environmental indicators stored during ingestion.
# Extreme Heat and Drinking Water require a future ingestion update.
EJSCREEN_INDICATOR_FIELDS = {
    "PM25":   "PM2.5 Particulate Matter",
    "OZONE":  "Ozone",
    "DSLPM":  "Diesel Particulate Matter",
    "CANCER": "Air Toxics Cancer Risk",
    "RESP":   "Air Toxics Respiratory HI",
    "PTRAF":  "Traffic Proximity",
    "PNPL":   "Superfund Proximity",
    "PRMP":   "RMP Facility Proximity",
    "PTSDF":  "Hazardous Waste Proximity",
    "UST":    "Underground Storage Tanks",
    "PWDIS":  "Wastewater Discharge",
    "LEAD":   "Lead Paint (Pre-1960 Housing)",
}

# 6 indicators that drive Tier 1 checks: field → (check_name, threshold, label)
_EJSCREEN_CHECK_INDICATORS = {
    "PM25":  ("EJScreen PM2.5",           80, "PM2.5 particulate matter"),
    "CANCER":("EJScreen cancer risk",     80, "air toxics cancer risk"),
    "DSLPM": ("EJScreen diesel PM",       80, "diesel particulate matter"),
    "LEAD":  ("EJScreen lead paint",      80, "lead paint indicator (pre-1960 housing)"),
    "PNPL":  ("EJScreen Superfund",       80, "Superfund site proximity"),
    "PTSDF": ("EJScreen hazardous waste", 80, "hazardous waste facility proximity"),
}


def _query_ejscreen_block_group(
    lat: float, lng: float, spatial_store: SpatialDataStore,
) -> Optional[Dict[str, Any]]:
    """Query nearest EJScreen block group centroid for environmental indicators.

    Returns dict of indicator percentile values for the nearest census block
    group within 2 km, or None if no data available. Excludes all demographic
    fields (DEMOGIDX, PEOPCOLORPCT, LOWINCPCT).

    Zero API calls — pure local SpatiaLite query.
    """
    if not spatial_store.is_available():
        return None

    results = spatial_store.find_facilities_within(lat, lng, 2000, "ejscreen")
    if not results:
        return None

    # find_facilities_within() returns results sorted by distance ascending
    nearest = results[0]

    # Extract only environmental indicator fields
    indicators = {}
    for field_name in EJSCREEN_INDICATOR_FIELDS:
        value = nearest.metadata.get(field_name)
        if value is not None:
            try:
                indicators[field_name] = float(value)
            except (ValueError, TypeError):
                pass

    if not indicators:
        return None

    indicators["_distance_m"] = nearest.distance_meters
    indicators["_block_group_id"] = nearest.metadata.get("block_group_id", "")
    return indicators


def _check_ejscreen_indicators(
    ejscreen_data: Optional[Dict[str, Any]],
    sems_result: Optional[Tier1Check],
) -> List[Tier1Check]:
    """Generate Tier 1 checks from EJScreen block group percentile data.

    Each of the 6 check-driving indicators produces a WARNING when the block
    group percentile >= 80th, PASS otherwise. The Superfund indicator is
    suppressed when the SEMS containment check already FAILed (dedup).
    """
    if ejscreen_data is None:
        return []

    checks = []
    for field_name, (check_name, threshold, label) in _EJSCREEN_CHECK_INDICATORS.items():
        value = ejscreen_data.get(field_name)
        if value is None:
            continue

        # Superfund dedup: skip if SEMS already flagged NPL containment
        if field_name == "PNPL" and sems_result and sems_result.result == CheckResult.FAIL:
            continue

        if value >= threshold:
            checks.append(Tier1Check(
                name=check_name,
                result=CheckResult.WARNING,
                details=(
                    f"Block group ranks in the {value:.0f}th percentile nationally "
                    f"for {label}. Elevated levels may affect long-term health."
                ),
                value=value,
                required=False,
            ))
        else:
            checks.append(Tier1Check(
                name=check_name,
                result=CheckResult.PASS,
                details=f"Block group ranks in the {value:.0f}th percentile for {label}",
                value=value,
                required=False,
            ))

    return checks


def _query_environmental_hazards(lat: float, lng: float) -> Optional[Dict[str, List[Dict]]]:
    """Query Overpass for environmental health hazards near a property.

    Makes a single Overpass API call through the shared rate-limited HTTP
    layer (overpass_http) and categorises the results into four buckets:
    power_lines, substations, cell_towers, industrial_zones.

    Returns None on any failure so check functions can fall back to UNKNOWN.
    """
    query = f"""
    [out:json][timeout:25];
    (
      way["power"="line"](around:200,{lat},{lng});
      node["power"="substation"](around:200,{lat},{lng});
      way["power"="substation"](around:200,{lat},{lng});
      node["man_made"="mast"]["communication:mobile_phone"="yes"](around:200,{lat},{lng});
      node["man_made"="tower"]["tower:type"="communication"](around:200,{lat},{lng});
      node["man_made"="communications_tower"](around:200,{lat},{lng});
      way["landuse"="industrial"](around:200,{lat},{lng});
    );
    out body;
    >;
    out skel qt;
    """

    try:
        from overpass_http import (
            OverpassQueryError as _HTTPQueryError,
            OverpassRateLimitError as _HTTPRateLimitError,
            overpass_query as _overpass_http_query,
        )
        data = _overpass_http_query(query, caller="environmental_hazards", timeout=25, ttl_days=14)
    except (ImportError, _HTTPQueryError, _HTTPRateLimitError) as e:
        logger.warning("Environmental hazard Overpass query failed: %s", e, exc_info=True)
        return None

    elements = data.get("elements", [])

    # Build a node-ID → (lat, lon) lookup for resolving way child nodes
    all_nodes: Dict[int, Tuple[float, float]] = {}
    for el in elements:
        if el.get("type") == "node" and "lat" in el and "lon" in el:
            all_nodes[el["id"]] = (el["lat"], el["lon"])

    result: Dict[str, List[Dict]] = {
        "power_lines": [],
        "substations": [],
        "cell_towers": [],
        "industrial_zones": [],
    }

    for el in elements:
        tags = el.get("tags")
        if not tags:
            continue

        # Power lines — high-voltage only (≥69kV)
        if tags.get("power") == "line":
            voltage = _parse_max_voltage(tags.get("voltage", ""))
            if voltage >= 69000:
                result["power_lines"].append(el)
            continue

        # Electrical substations
        if tags.get("power") == "substation":
            result["substations"].append(el)
            continue

        # Cell towers / communication masts
        man_made = tags.get("man_made", "")
        if man_made == "mast" and tags.get("communication:mobile_phone") == "yes":
            result["cell_towers"].append(el)
            continue
        if man_made == "tower" and tags.get("tower:type") == "communication":
            result["cell_towers"].append(el)
            continue
        if man_made == "communications_tower":
            result["cell_towers"].append(el)
            continue

        # Industrial zones
        if tags.get("landuse") == "industrial":
            result["industrial_zones"].append(el)
            continue

    # Attach the node lookup so check functions can resolve way geometry
    result["_all_nodes"] = all_nodes  # type: ignore[assignment]

    return result


def _element_distance_ft(
    prop_lat: float, prop_lng: float, el: Dict, all_nodes: Dict[int, Tuple[float, float]]
) -> float:
    """Distance in feet from property to an Overpass element (node or way)."""
    if el.get("type") == "node" and "lat" in el and "lon" in el:
        return float(_distance_feet(prop_lat, prop_lng, el["lat"], el["lon"]))
    if el.get("type") == "way" and "nodes" in el:
        return _closest_distance_to_way_ft(prop_lat, prop_lng, el["nodes"], all_nodes)
    return float("inf")


def check_power_lines(
    hazard_results: Optional[Dict], prop_lat: float, prop_lng: float
) -> Tier1Check:
    """Check proximity to high-voltage transmission lines (≥69kV)."""
    if hazard_results is None:
        return Tier1Check(
            name="Power lines",
            result=CheckResult.UNKNOWN,
            details="Unable to query environmental data",
            required=False,
        )

    all_nodes = hazard_results.get("_all_nodes", {})
    min_dist = float("inf")
    for el in hazard_results.get("power_lines", []):
        d = _element_distance_ft(prop_lat, prop_lng, el, all_nodes)
        if d < min_dist:
            min_dist = d

    if min_dist <= POWER_LINE_WARNING_DISTANCE_FT:
        return Tier1Check(
            name="Power lines",
            result=CheckResult.WARNING,
            details=(
                f"High-voltage transmission line (\u226569kV) detected within {round(min_dist):,} ft. "
                "Research associates proximity to high-voltage lines with elevated EMF exposure, "
                "though evidence is classified as moderate-contested (IARC Group 2B)."
            ),
            value=round(min_dist),
            required=False,
        )

    return Tier1Check(
        name="Power lines",
        result=CheckResult.PASS,
        details="No high-voltage transmission lines detected within 200 ft",
        required=False,
    )


def check_substations(
    hazard_results: Optional[Dict], prop_lat: float, prop_lng: float
) -> Tier1Check:
    """Check proximity to electrical substations."""
    if hazard_results is None:
        return Tier1Check(
            name="Electrical substation",
            result=CheckResult.UNKNOWN,
            details="Unable to query environmental data",
            required=False,
        )

    all_nodes = hazard_results.get("_all_nodes", {})
    min_dist = float("inf")
    for el in hazard_results.get("substations", []):
        d = _element_distance_ft(prop_lat, prop_lng, el, all_nodes)
        if d < min_dist:
            min_dist = d

    if min_dist <= SUBSTATION_WARNING_DISTANCE_FT:
        return Tier1Check(
            name="Electrical substation",
            result=CheckResult.WARNING,
            details=(
                f"Electrical substation detected within {round(min_dist):,} ft. "
                "Substations concentrate electromagnetic fields from the surrounding transmission network."
            ),
            value=round(min_dist),
            required=False,
        )

    return Tier1Check(
        name="Electrical substation",
        result=CheckResult.PASS,
        details="No electrical substations detected within 300 ft",
        required=False,
    )


def check_cell_towers(
    hazard_results: Optional[Dict], prop_lat: float, prop_lng: float
) -> Tier1Check:
    """Check proximity to cell/communication towers."""
    if hazard_results is None:
        return Tier1Check(
            name="Cell tower",
            result=CheckResult.UNKNOWN,
            details="Unable to query environmental data",
            required=False,
        )

    all_nodes = hazard_results.get("_all_nodes", {})
    min_dist = float("inf")
    for el in hazard_results.get("cell_towers", []):
        d = _element_distance_ft(prop_lat, prop_lng, el, all_nodes)
        if d < min_dist:
            min_dist = d

    if min_dist <= CELL_TOWER_WARNING_DISTANCE_FT:
        return Tier1Check(
            name="Cell tower",
            result=CheckResult.WARNING,
            details=(
                f"Cell tower detected within {round(min_dist):,} ft. "
                "RF exposure from cell towers is typically well below regulatory limits; "
                "IARC classifies RF fields as Group 2B (possibly carcinogenic) based on limited evidence."
            ),
            value=round(min_dist),
            required=False,
        )

    return Tier1Check(
        name="Cell tower",
        result=CheckResult.PASS,
        details="No cell towers detected within 500 ft",
        required=False,
    )


def check_industrial_zones(
    hazard_results: Optional[Dict], prop_lat: float, prop_lng: float
) -> Tier1Check:
    """Check proximity to industrial-zoned land."""
    if hazard_results is None:
        return Tier1Check(
            name="Industrial zone",
            result=CheckResult.UNKNOWN,
            details="Unable to query environmental data",
            required=False,
        )

    all_nodes = hazard_results.get("_all_nodes", {})
    min_dist = float("inf")
    for el in hazard_results.get("industrial_zones", []):
        d = _element_distance_ft(prop_lat, prop_lng, el, all_nodes)
        if d < min_dist:
            min_dist = d

    if min_dist <= INDUSTRIAL_ZONE_WARNING_DISTANCE_FT:
        return Tier1Check(
            name="Industrial zone",
            result=CheckResult.WARNING,
            details=(
                f"Industrial-zoned land detected within {round(min_dist):,} ft. "
                "Verify the nature of nearby facilities \u2014 industrial zones may include "
                "manufacturing, warehousing, or chemical processing."
            ),
            value=round(min_dist),
            required=False,
        )

    return Tier1Check(
        name="Industrial zone",
        result=CheckResult.PASS,
        details="No industrial-zoned land detected within 500 ft",
        required=False,
    )


def check_flood_zones(lat: float, lng: float) -> Tier1Check:
    """Check whether the property falls within a FEMA flood zone.

    Queries the local SpatiaLite database (fema_nfhl layer) — no external
    API calls.  Severity precedence across all overlapping polygons:
      1. Zone A* / V*  → FAIL  (Special Flood Hazard Area)
      2. Zone X shaded → WARNING (moderate risk)
      3. Everything else → PASS
    Empty results (no data coverage) → UNKNOWN.
    """
    _unknown = Tier1Check(
        name="Flood zone",
        result=CheckResult.UNKNOWN,
        details="Flood zone data not available for this area",
        value=None,
        required=True,
    )
    try:
        store = SpatialDataStore()
        polygons = store.point_in_polygons(lat, lng, "fema_nfhl")

        if not polygons:
            return _unknown

        # Scan all overlapping polygons — highest severity wins.
        has_high_risk = False
        high_risk_zone = ""
        has_moderate_risk = False

        for record in polygons:
            fld_zone = record.metadata.get("fld_zone", "")
            zone_subtype = record.metadata.get("zone_subtype", "")

            if fld_zone.startswith("A") or fld_zone.startswith("V"):
                has_high_risk = True
                high_risk_zone = fld_zone
            elif (
                fld_zone.startswith("X")
                and zone_subtype
                and "SHADED" in zone_subtype.upper()
            ):
                has_moderate_risk = True

        if has_high_risk:
            return Tier1Check(
                name="Flood zone",
                result=CheckResult.FAIL,
                details=(
                    f"Property is in a FEMA Special Flood Hazard Area "
                    f"(Zone {high_risk_zone})"
                ),
                value=high_risk_zone,
                required=True,
            )

        if has_moderate_risk:
            return Tier1Check(
                name="Flood zone",
                result=CheckResult.WARNING,
                details="Property is in a moderate flood risk area (Zone X, shaded)",
                value="X-shaded",
                required=True,
            )

        # No high or moderate risk — property is outside SFHA.
        display_zone = polygons[0].metadata.get("fld_zone", "X")
        return Tier1Check(
            name="Flood zone",
            result=CheckResult.PASS,
            details=(
                f"Not in a FEMA Special Flood Hazard Area "
                f"(Zone {display_zone})"
            ),
            value=display_zone,
            required=True,
        )

    except Exception:
        logger.warning("Flood zone check failed", exc_info=True)
        return _unknown


def check_superfund_npl(lat: float, lng: float) -> Tier1Check:
    """Check whether the property falls within an EPA Superfund NPL site boundary.

    Queries the local SpatiaLite database (sems layer) via point-in-polygon.
    Filters to NPL sites only: npl_status_code in ("F", "P") — Final and
    Proposed National Priorities List. Non-NPL sites are excluded to avoid
    false positives (EPA-evaluated sites with no further action).

    PRD: Hard fail if within EPA-defined remediation boundary.
    Empty results (no data) → UNKNOWN.

    Known limitation: NES-173 — multipart polygons with disjoint exterior rings
    may produce false negatives (missed containment). Most NPL sites have
    single contiguous boundaries.
    """
    _unknown = Tier1Check(
        name="Superfund (NPL)",
        result=CheckResult.UNKNOWN,
        details="Superfund site data not available for this area",
        value=None,
        required=True,
    )
    try:
        store = SpatialDataStore()
        if not store.is_available():
            return _unknown

        polygons = store.point_in_polygons(lat, lng, "sems")
        if not polygons:
            return _unknown

        # Filter to NPL sites only (Final F, Proposed P)
        npl_sites = [
            r for r in polygons
            if r.metadata.get("npl_status_code", "").upper() in ("F", "P")
        ]

        if npl_sites:
            site_name = npl_sites[0].metadata.get("site_name", npl_sites[0].name)
            return Tier1Check(
                name="Superfund (NPL)",
                result=CheckResult.FAIL,
                details=(
                    f"Property is within EPA Superfund NPL site: {site_name}. "
                    "Contaminants may pose health risks (cancer, neurological effects)."
                ),
                value=site_name,
                required=True,
            )

        # Property is inside a Superfund polygon but not NPL-listed (npl_status_code
        # not F/P, or missing) — treat as pass; only NPL sites cause hard fail.
        return Tier1Check(
            name="Superfund (NPL)",
            result=CheckResult.PASS,
            details="Not within an EPA Superfund National Priorities List site",
            value=None,
            required=True,
        )

    except Exception:
        logger.warning("Superfund NPL check failed", exc_info=True)
        return _unknown


def check_tri_facility_proximity(lat: float, lng: float, spatial_store) -> Tier1Check:
    """Check proximity to EPA Toxic Release Inventory (TRI) facilities.

    Queries the local SpatiaLite database (facilities_tri layer) for TRI
    reporting facilities within 1 mile of the property.  TRI facilities
    manufacture, process, or use significant quantities of listed toxic
    chemicals and are required to report annual releases to the EPA.

    Tier 0 WARNING — nearby TRI facilities indicate potential exposure to
    toxic air emissions, water discharges, or soil contamination.  This is
    a proximity warning, not a containment check (unlike Superfund NPL).

    Returns WARNING when the nearest TRI facility is within 1 mile,
    PASS when none are found within 1 mile, UNKNOWN when data is
    unavailable.
    """
    _unknown = Tier1Check(
        name="TRI facility",
        result=CheckResult.UNKNOWN,
        details="TRI facility data not available for this area",
        value=None,
        required=False,
    )

    if spatial_store is None or not spatial_store.is_available():
        return _unknown

    try:
        facilities = spatial_store.find_facilities_within(
            lat, lng, TRI_FACILITY_WARNING_RADIUS_M, "tri"
        )

        if not facilities:
            return Tier1Check(
                name="TRI facility",
                result=CheckResult.PASS,
                details="No EPA TRI facilities within 1 mile",
                value=None,
                required=False,
            )

        nearest = facilities[0]
        dist_ft = round(nearest.distance_feet)
        facility_name = nearest.name or "Unknown facility"
        industry = nearest.metadata.get("industry_sector", "")

        detail_parts = [
            f"EPA Toxic Release Inventory facility within {dist_ft:,} ft: "
            f"{facility_name}."
        ]
        if industry:
            detail_parts.append(f"Industry: {industry}.")
        detail_parts.append(
            "TRI facilities report annual releases of toxic chemicals to "
            "air, water, and land."
        )

        count = len(facilities)
        if count > 1:
            detail_parts.append(
                f"{count} TRI facilities found within 1 mile."
            )

        return Tier1Check(
            name="TRI facility",
            result=CheckResult.WARNING,
            details=" ".join(detail_parts),
            value=dist_ft,
            required=False,
        )

    except Exception:
        logger.warning("TRI facility proximity check failed", exc_info=True)
        return _unknown


def check_listing_requirements(listing: PropertyListing) -> List[Tier1Check]:
    """Check listing-based requirements (W/D, AC, size, etc.)"""
    checks = []
    is_required = False
    
    # Washer/dryer
    if listing.has_washer_dryer_in_unit is None:
        checks.append(Tier1Check(
            name="W/D in unit",
            result=CheckResult.UNKNOWN,
            details="Not specified - verify manually",
            required=is_required
        ))
    elif listing.has_washer_dryer_in_unit:
        checks.append(Tier1Check(
            name="W/D in unit",
            result=CheckResult.PASS,
            details="Washer/dryer in unit confirmed",
            required=is_required
        ))
    else:
        checks.append(Tier1Check(
            name="W/D in unit",
            result=CheckResult.FAIL,
            details="No washer/dryer in unit",
            required=is_required
        ))
    
    # Central air
    if listing.has_central_air is None:
        checks.append(Tier1Check(
            name="Central air",
            result=CheckResult.UNKNOWN,
            details="Not specified - verify manually",
            required=is_required
        ))
    elif listing.has_central_air:
        checks.append(Tier1Check(
            name="Central air",
            result=CheckResult.PASS,
            details="Central air confirmed",
            required=is_required
        ))
    else:
        checks.append(Tier1Check(
            name="Central air",
            result=CheckResult.FAIL,
            details="No central air",
            required=is_required
        ))
    
    # Size
    if listing.sqft is None:
        checks.append(Tier1Check(
            name="Size",
            result=CheckResult.UNKNOWN,
            details="Square footage not specified",
            required=is_required
        ))
    elif listing.sqft >= MIN_SQFT:
        checks.append(Tier1Check(
            name="Size",
            result=CheckResult.PASS,
            details=f"{listing.sqft:,} sq ft",
            value=listing.sqft,
            required=is_required
        ))
    else:
        checks.append(Tier1Check(
            name="Size",
            result=CheckResult.FAIL,
            details=f"{listing.sqft:,} sq ft < {MIN_SQFT:,} sq ft minimum",
            value=listing.sqft,
            required=is_required
        ))
    
    # Bedrooms
    if listing.bedrooms is None:
        checks.append(Tier1Check(
            name="Bedrooms",
            result=CheckResult.UNKNOWN,
            details="Bedroom count not specified",
            required=is_required
        ))
    elif listing.bedrooms >= MIN_BEDROOMS:
        checks.append(Tier1Check(
            name="Bedrooms",
            result=CheckResult.PASS,
            details=f"{listing.bedrooms} BR",
            value=listing.bedrooms,
            required=is_required
        ))
    else:
        checks.append(Tier1Check(
            name="Bedrooms",
            result=CheckResult.FAIL,
            details=f"{listing.bedrooms} BR < {MIN_BEDROOMS} BR minimum",
            value=listing.bedrooms,
            required=is_required
        ))
    
    # Cost (monthly - rent or estimated)
    if listing.cost is None:
        checks.append(Tier1Check(
            name="Cost",
            result=CheckResult.UNKNOWN,
            details="Monthly cost not specified",
            required=is_required
        ))
    elif listing.cost <= COST_MAX:
        checks.append(Tier1Check(
            name="Cost",
            result=CheckResult.PASS,
            details=f"${listing.cost:,}/month",
            value=listing.cost,
            required=is_required
        ))
    else:
        checks.append(Tier1Check(
            name="Cost",
            result=CheckResult.FAIL,
            details=f"${listing.cost:,}/month > ${COST_MAX:,} max",
            value=listing.cost,
            required=is_required
        ))
    
    return checks


def get_neighborhood_snapshot(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> NeighborhoodSnapshot:
    """Collect nearest key amenities for neighborhood context"""
    snapshot = NeighborhoodSnapshot()

    # Find nearest of each category
    categories = [
        ("Provisioning", "grocery_store", "supermarket"),
        ("Third Place", "cafe", "bakery"),
        ("Park", "park", None),
        ("School", "school", "primary_school")
    ]

    for category, primary_type, secondary_type in categories:
        try:
            places = maps.places_nearby(lat, lng, primary_type, radius_meters=3000)
            if secondary_type:
                places.extend(maps.places_nearby(lat, lng, secondary_type, radius_meters=3000))
            places = _dedupe_by_place_id(places)

            # Special handling for Provisioning - apply household provisioning filter
            if category == "Provisioning":
                eligible_places = []
                included_types = ["supermarket", "grocery_store", "warehouse_store", "superstore"]
                excluded_types = ["convenience_store", "gas_station", "pharmacy", "liquor_store", "meal_takeaway", "fast_food"]

                for place in places:
                    types = place.get("types", [])

                    # Must have provisioning type
                    has_provisioning = any(t in types for t in included_types)
                    if not has_provisioning:
                        continue

                    # Must NOT have excluded type
                    has_excluded = any(t in types for t in excluded_types)
                    if has_excluded:
                        continue

                    # Must meet quality threshold
                    rating = place.get("rating", 0)
                    reviews = place.get("user_ratings_total", 0)
                    if rating >= 4.0 and reviews >= 50:
                        eligible_places.append(place)

                places = eligible_places

                if not places:
                    # Add placeholder entry
                    snapshot.places.append(NeighborhoodPlace(
                        category=category,
                        name="No full-service provisioning options nearby",
                        rating=None,
                        walk_time_min=0,
                        place_type="none"
                    ))
                    continue

            # Special handling for Third Place - apply third-place quality filter
            if category == "Third Place":
                eligible_places = []
                excluded_types = ["convenience_store", "gas_station", "meal_takeaway", "fast_food", "supermarket"]

                for place in places:
                    types = place.get("types", [])

                    # Must have acceptable type
                    has_acceptable = any(t in types for t in ["cafe", "coffee_shop", "bakery"])
                    if not has_acceptable:
                        continue

                    # Must NOT have excluded type
                    has_excluded = any(t in types for t in excluded_types)
                    if has_excluded:
                        continue

                    # Must meet quality threshold
                    rating = place.get("rating", 0)
                    reviews = place.get("user_ratings_total", 0)
                    if rating >= 4.0 and reviews >= 30:
                        eligible_places.append(place)

                places = eligible_places

                if not places:
                    # Add placeholder entry
                    snapshot.places.append(NeighborhoodPlace(
                        category=category,
                        name="No good third-place spots nearby",
                        rating=None,
                        walk_time_min=0,
                        place_type="none"
                    ))
                    continue

            if places:
                # Find closest using batch walking times (1 API call per 25 places)
                destinations = [
                    (p["geometry"]["location"]["lat"], p["geometry"]["location"]["lng"])
                    for p in places
                ]
                walk_times = maps.walking_times_batch((lat, lng), destinations)
                best = None
                best_time = 9999
                for place, walk_time in zip(places, walk_times):
                    if walk_time < best_time:
                        best_time = walk_time
                        best = place

                if best:
                    place_types = best.get("types", [])
                    snapshot.places.append(NeighborhoodPlace(
                        category=category,
                        name=best.get("name", "Unknown"),
                        rating=best.get("rating"),
                        walk_time_min=best_time,
                        place_type=place_types[0] if place_types else "unknown"
                    ))
        except Exception as e:
            # Skip this category if there's an error
            continue

    return snapshot


def get_child_and_schooling_snapshot(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> ChildSchoolingSnapshot:
    """Collect nearby childcare and schooling options for situational awareness."""
    snapshot = ChildSchoolingSnapshot()

    childcare_keywords = {
        "daycare",
        "pre-k",
        "pre k",
        "preschool",
        "nursery",
        "early childhood",
        "early learning",
        "child care",
    }
    childcare_types = {"preschool", "kindergarten", "child_care", "school"}
    childcare_religious_keywords = {
        "church",
        "temple",
        "mosque",
        "religious",
        "sunday school",
        "faith",
    }
    childcare_excluded_keywords = {
        "tutoring",
        "tutor",
        "music",
        "dance",
        "gym",
        "martial arts",
        "karate",
        "taekwondo",
        "lesson",
    }

    school_excluded_keywords = {
        "music",
        "tutoring",
        "tutor",
        "lesson",
        "dance",
        "martial arts",
        "karate",
        "taekwondo",
        "dojo",
        "church",
        "temple",
        "mosque",
        "religious",
        "bible",
        "catholic",
        "christian",
        "lutheran",
        "jewish",
        "islamic",
        "montessori",
        "montessori school",
        "private school",
    }

    def normalize_text(text: str) -> str:
        return re.sub(r"\\s+", " ", text or "").strip().lower()

    def fetch_website_text(website: Optional[str]) -> str:
        if not website:
            return ""
        try:
            _t0 = time.time()
            response = requests.get(website, timeout=6)
            _elapsed = int((time.time() - _t0) * 1000)
            _trace = get_trace()
            if _trace:
                _trace.record_api_call(
                    service="website", endpoint="fetch_website_text",
                    elapsed_ms=_elapsed, status_code=response.status_code,
                )
            if response.status_code >= 400:
                return ""
            text = re.sub(r"<[^>]+>", " ", response.text)
            return normalize_text(text)
        except Exception:
            return ""

    def build_text_blob(place: Dict, website_text: str = "") -> str:
        name = normalize_text(place.get("name", ""))
        types_text = " ".join(place.get("types", []))
        return normalize_text(" ".join([name, types_text, website_text]))

    def is_childcare(place: Dict, website_text: str) -> bool:
        text_blob = build_text_blob(place, website_text)
        has_keyword = any(keyword in text_blob for keyword in childcare_keywords)
        has_type = any(t in childcare_types for t in place.get("types", []))
        has_excluded = any(keyword in text_blob for keyword in childcare_excluded_keywords)
        has_religious = any(keyword in text_blob for keyword in childcare_religious_keywords)
        has_preschool = "preschool" in place.get("types", []) or "preschool" in text_blob
        return (has_keyword or has_preschool) and has_type and not has_excluded and (not has_religious or has_preschool)

    def is_public_school(place: Dict, website_text: str) -> bool:
        text_blob = build_text_blob(place, website_text)
        if not website_text and any(
            t in place.get("types", []) for t in ["primary_school", "secondary_school", "school"]
        ):
            return True
        if any(keyword in text_blob for keyword in school_excluded_keywords):
            return False
        public_signals = [
            "public school",
            "school district",
            "public schools",
            ".k12.",
            "k12",
            "isd",
            "usd",
            "ps ",
            "public",
        ]
        return any(signal in text_blob for signal in public_signals)

    def infer_school_level(place: Dict, website_text: str) -> str:
        text_blob = build_text_blob(place, website_text)
        if "elementary" in text_blob or "primary school" in text_blob:
            return "Elementary"
        if "middle" in text_blob or "junior high" in text_blob or "intermediate" in text_blob:
            return "Middle"
        if "high school" in text_blob or "secondary school" in text_blob or "senior high" in text_blob:
            return "High"
        if "k-12" in text_blob or "k12" in text_blob:
            return "K-12"
        if "primary_school" in place.get("types", []):
            return "Elementary"
        if "secondary_school" in place.get("types", []):
            return "High"
        return ""

    def fetch_place_details(place: Dict) -> Dict:
        place_id = place.get("place_id")
        if not place_id:
            return {}
        try:
            return maps.place_details(place_id)
        except Exception:
            return {}

    def build_childcare_places(places: List[Dict], max_results: int) -> List[ChildcarePlace]:
        scored_places = []
        for place in places:
            p_lat = place["geometry"]["location"]["lat"]
            p_lng = place["geometry"]["location"]["lng"]
            walk_time = maps.walking_time((lat, lng), (p_lat, p_lng))
            if walk_time > SCHOOL_WALK_MAX_MIN:
                continue
            scored_places.append((walk_time, place))

        scored_places.sort(key=lambda item: item[0])
        selected = scored_places[:max_results]
        results = []

        for walk_time, place in selected:
            details = fetch_place_details(place)
            website = details.get("website")
            results.append(ChildcarePlace(
                name=place.get("name", "Unknown"),
                rating=place.get("rating"),
                user_ratings_total=place.get("user_ratings_total"),
                walk_time_min=walk_time,
                website=website
            ))
        return results

    childcare_searches = [
        ("daycare", "child_care"),
        ("preschool", "preschool"),
        ("nursery", "school"),
        ("early childhood education", "school"),
    ]
    childcare_places: Dict[str, Dict] = {}
    for keyword, place_type in childcare_searches:
        try:
            places = maps.places_nearby(lat, lng, place_type, radius_meters=3000, keyword=keyword)
        except Exception:
            continue
        for place in places:
            place_id = place.get("place_id")
            if place_id and place_id not in childcare_places:
                childcare_places[place_id] = place

    childcare_candidates = []
    for place in childcare_places.values():
        details = fetch_place_details(place)
        website_text = fetch_website_text(details.get("website"))
        if is_childcare(place, website_text):
            childcare_candidates.append(place)

    snapshot.childcare = build_childcare_places(childcare_candidates, 5)

    school_search_queries = [
        "public elementary school",
        "public middle school",
        "public high school",
    ]
    school_candidates: Dict[str, Dict] = {}
    for query in school_search_queries:
        try:
            places = maps.text_search(query, lat, lng, radius_meters=50000)
        except Exception:
            continue
        for place in places:
            place_id = place.get("place_id")
            if place_id and place_id not in school_candidates:
                school_candidates[place_id] = place

    schools_by_level: Dict[str, Optional[SchoolPlace]] = {
        "Elementary": None,
        "Middle": None,
        "High": None,
    }

    def maybe_set_school(level: str, place: Dict, walk_time: int, website: Optional[str]) -> None:
        existing = schools_by_level.get(level)
        if existing is None or walk_time < existing.walk_time_min:
            schools_by_level[level] = SchoolPlace(
                name=place.get("name", "Unknown"),
                rating=place.get("rating"),
                user_ratings_total=place.get("user_ratings_total"),
                walk_time_min=walk_time,
                website=website,
                level=level,
            )

    for place in school_candidates.values():
        details = fetch_place_details(place)
        website = details.get("website")
        website_text = fetch_website_text(website)
        if not is_public_school(place, website_text):
            continue
        level = infer_school_level(place, website_text)
        if not level:
            continue
        p_lat = place["geometry"]["location"]["lat"]
        p_lng = place["geometry"]["location"]["lng"]
        walk_time = maps.walking_time((lat, lng), (p_lat, p_lng))
        if walk_time > SCHOOL_WALK_MAX_MIN:
            continue
        if level == "K-12":
            for level_name in schools_by_level.keys():
                maybe_set_school(level_name, place, walk_time, website)
        else:
            maybe_set_school(level, place, walk_time, website)

    snapshot.schools_by_level = schools_by_level
    return snapshot


def get_parking_availability(maps: GoogleMapsClient, place_id: Optional[str]) -> Optional[bool]:
    if not place_id:
        return None
    try:
        details = maps.place_details(
            place_id,
            fields=[
                "name",
                "types",
                "parking_options",
                "wheelchair_accessible_parking",
            ]
        )
    except Exception:
        return None

    parking_options = details.get("parking_options", {})
    if isinstance(parking_options, dict):
        for value in parking_options.values():
            if value is True:
                return True
        if parking_options:
            return False

    wheelchair_parking = details.get("wheelchair_accessible_parking")
    if wheelchair_parking is True:
        return True
    if wheelchair_parking is False:
        return False

    return None


def transit_frequency_class(review_count: int) -> str:
    if review_count >= 5000:
        return "High frequency"
    if review_count >= 1000:
        return "Medium frequency"
    if review_count >= 200:
        return "Low frequency"
    return "Very low frequency"


def find_primary_transit(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> Optional[PrimaryTransitOption]:
    """Find the best nearby transit option with preference for rail."""
    search_types = [
        ("train_station", "Train", 1),
        ("subway_station", "Subway", 1),
        ("light_rail_station", "Light Rail", 1),
    ]

    raw_candidates: List[Tuple[int, Dict, str]] = []
    for place_type, mode, priority in search_types:
        try:
            places = maps.places_nearby(lat, lng, place_type, radius_meters=5000)
        except Exception:
            continue
        for place in places:
            raw_candidates.append((priority, place, mode))

    if not raw_candidates:
        return None

    # Batch walking times — 1 API call per 25 candidates instead of 1 each
    destinations = [
        (p["geometry"]["location"]["lat"], p["geometry"]["location"]["lng"])
        for _, p, _ in raw_candidates
    ]
    walk_times = maps.walking_times_batch((lat, lng), destinations)

    candidates: List[Tuple[int, int, Dict, str]] = [
        (priority, wt, place, mode)
        for (priority, place, mode), wt in zip(raw_candidates, walk_times)
    ]
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, walk_time, place, mode = candidates[0]
    place_lat = place["geometry"]["location"]["lat"]
    place_lng = place["geometry"]["location"]["lng"]

    drive_time = None
    if walk_time > 30:
        drive_time = maps.driving_time(
            (lat, lng),
            (place_lat, place_lng)
        )

    parking_available = get_parking_availability(maps, place.get("place_id"))
    user_ratings_total = place.get("user_ratings_total")

    return PrimaryTransitOption(
        name=place.get("name", "Unknown"),
        mode=mode,
        lat=place_lat,
        lng=place_lng,
        walk_time_min=walk_time,
        drive_time_min=drive_time if drive_time and drive_time != 9999 else None,
        parking_available=parking_available,
        user_ratings_total=user_ratings_total,
        frequency_class=(
            transit_frequency_class(user_ratings_total)
            if isinstance(user_ratings_total, int)
            else None
        ),
    )


def miles_between(maps: GoogleMapsClient, origin: Tuple[float, float], dest: Tuple[float, float]) -> float:
    return maps.distance_feet(origin, dest) / 5280


def determine_major_hub(
    maps: GoogleMapsClient,
    lat: float,
    lng: float,
    primary_mode: Optional[str],
    transit_origin: Optional[Tuple[float, float]] = None
) -> Optional[MajorHubAccess]:
    metros = [
        {
            "name": "NYC Metro",
            "center": (40.7128, -74.0060),
            "radius_miles": 60,
            "hub_name": "Grand Central Terminal",
            "hub_coords": (40.7527, -73.9772),
            "bus_hub_name": "Port Authority Bus Terminal",
            "bus_hub_coords": (40.7570, -73.9903),
        },
        {
            "name": "SF Bay",
            "center": (37.7749, -122.4194),
            "radius_miles": 50,
            "hub_name": "Powell Street Station",
            "hub_coords": (37.7844, -122.4078),
        },
        {
            "name": "Seattle",
            "center": (47.6062, -122.3321),
            "radius_miles": 40,
            "hub_name": "Westlake Station",
            "hub_coords": (47.6114, -122.3381),
        },
        {
            "name": "Chicago",
            "center": (41.8781, -87.6298),
            "radius_miles": 50,
            "hub_name": "Union Station",
            "hub_coords": (41.8786, -87.6404),
        },
        {
            "name": "Boston",
            "center": (42.3601, -71.0589),
            "radius_miles": 40,
            "hub_name": "South Station",
            "hub_coords": (42.3522, -71.0552),
        },
    ]

    hub_name = None
    hub_coords = None

    for metro in metros:
        distance_miles = miles_between(maps, (lat, lng), metro["center"])
        if distance_miles <= metro["radius_miles"]:
            if metro["name"] == "NYC Metro" and primary_mode == "Bus":
                hub_name = metro.get("bus_hub_name")
                hub_coords = metro.get("bus_hub_coords")
            else:
                hub_name = metro["hub_name"]
                hub_coords = metro["hub_coords"]
            break

    if not hub_name or not hub_coords:
        search_queries = ["city center", "downtown"]
        hub_place = None
        for query in search_queries:
            try:
                results = maps.text_search(query, lat, lng, radius_meters=50000)
            except Exception:
                continue
            if results:
                hub_place = results[0]
                break

        if not hub_place:
            try:
                results = maps.places_nearby(lat, lng, "locality", radius_meters=50000)
            except Exception:
                results = []
            if results:
                hub_place = results[0]

        if not hub_place:
            return None

        hub_name = hub_place.get("name", "City Center")
        hub_coords = (
            hub_place["geometry"]["location"]["lat"],
            hub_place["geometry"]["location"]["lng"],
        )

    travel_origin = transit_origin or (lat, lng)
    travel_time = maps.transit_time(travel_origin, hub_coords)
    transit_mode = "transit"
    if primary_mode in {"Train", "Subway", "Light Rail"}:
        transit_mode = "train"
    elif primary_mode == "Bus":
        transit_mode = "bus"

    return MajorHubAccess(
        name=hub_name,
        travel_time_min=travel_time if travel_time != 9999 else 0,
        transit_mode=transit_mode
    )


def urban_access_route_summary(
    primary_transit: Optional[PrimaryTransitOption],
    major_hub: Optional[MajorHubAccess]
) -> Optional[str]:
    if not primary_transit or not major_hub or not major_hub.travel_time_min:
        return None

    mode_label = "Train"
    if primary_transit.mode not in {"Train", "Subway", "Light Rail"}:
        mode_label = primary_transit.mode

    if primary_transit.walk_time_min > 30:
        return f"Bus \u2192 {mode_label} \u2192 {major_hub.name} \u2014 {major_hub.travel_time_min} min"

    return f"{mode_label} to {major_hub.name} \u2014 {major_hub.travel_time_min} min"


def get_urban_access_profile(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> UrbanAccessProfile:
    primary_transit = find_primary_transit(maps, lat, lng)
    transit_origin = (primary_transit.lat, primary_transit.lng) if primary_transit else None
    major_hub = determine_major_hub(
        maps,
        lat,
        lng,
        primary_transit.mode if primary_transit else None,
        transit_origin=transit_origin
    )
    if major_hub:
        major_hub.route_summary = urban_access_route_summary(primary_transit, major_hub)

    return UrbanAccessProfile(
        primary_transit=primary_transit,
        major_hub=major_hub,
    )


# =============================================================================
# SMART TRANSIT FREQUENCY APPROXIMATION
# =============================================================================
#
# How the heuristic works:
#
#   We cannot access GTFS feeds or real-time schedules, so we approximate
#   transit service frequency using four signals available from Google Places:
#
#   1. MODE WEIGHT (0-3 pts) — Rail/subway modes correlate with higher
#      frequency service than bus-only corridors.  subway/rail=3, light_rail=2,
#      tram=2, bus=1, ferry=1.
#
#   2. NODE DENSITY (0-3 pts) — Count distinct transit places (transit_station,
#      bus_station, subway_station) within a 1.2 km radius.  More stops in a
#      small area imply overlapping routes and higher aggregate frequency.
#      >=6 nodes=3, >=3=2, >=1=1, 0=0.
#
#   3. WALK-REACHABLE NODES (0-2 pts) — Count of distinct transit nodes within
#      a 15-min walk (≈1.2 km radius, but using walking API for accuracy).
#      Uses the nearby search results already fetched for density.
#      >=4 nodes=2, >=2=1, else 0.
#
#   4. REVIEW-COUNT PROXY (0-2 pts) — Google user_ratings_total on the primary
#      stop is a rough proxy for foot traffic volume, which correlates with
#      service frequency.  >=5000=2, >=1000=1, else 0.
#
#   Total raw score 0-10 maps directly to Urban Access Score.
#   Frequency bucket thresholds:  >=8 High, >=5 Medium, >=3 Low, else Very low.
#
# How to tune:
#   - Adjust MODE_WEIGHTS dict to change mode importance.
#   - Adjust DENSITY_THRESHOLDS / WALK_NODE_THRESHOLDS for different urban contexts.
#   - Adjust FREQUENCY_BUCKET_THRESHOLDS to shift bucket boundaries.
#   - The radius_meters for density search (1200) assumes flat walking terrain;
#     increase in hilly or spread-out areas.
#

MODE_WEIGHTS = {
    "Subway": 3,
    "Train": 3,
    "Light Rail": 2,
    "Tram": 2,
    "Commuter Rail": 3,
    "Bus": 1,
    "Ferry": 1,
}

TRANSIT_SEARCH_TYPES = [
    "transit_station",
    "bus_station",
    "subway_station",
]

# (threshold, points)
DENSITY_THRESHOLDS = [(6, 3), (3, 2), (1, 1)]
WALK_NODE_THRESHOLDS = [(4, 2), (2, 1)]
REVIEW_THRESHOLDS = [(5000, 2), (1000, 1)]
FREQUENCY_BUCKET_THRESHOLDS = [(8, "High"), (5, "Medium"), (3, "Low")]


def _classify_mode(place: Dict) -> str:
    """Classify transit mode from Place types and name keywords."""
    types = set(place.get("types", []))
    name = (place.get("name") or "").lower()

    # Check commuter rail keywords first (before generic subway/metro match)
    commuter_kw = ("commuter", "metra", "caltrain", "lirr", "metro-north", "nj transit")
    if "train_station" in types and any(kw in name for kw in commuter_kw):
        return "Commuter Rail"
    if "subway_station" in types or "subway" in name:
        return "Subway"
    if "train_station" in types:
        if "metro" in name:
            return "Subway"
        return "Train"
    if "light_rail_station" in types or "light rail" in name or "tram" in name or "streetcar" in name:
        return "Light Rail"
    if any(kw in name for kw in ("ferry", "water taxi")):
        return "Ferry"
    if "bus_station" in types or "bus" in name:
        return "Bus"
    if "transit_station" in types:
        if "metro" in name:
            return "Subway"
        return "Train"  # default for generic transit_station
    return "Bus"


def _score_from_thresholds(value: int, thresholds: List[Tuple[int, int]]) -> int:
    """Return points for value given descending (threshold, points) pairs."""
    for threshold, points in thresholds:
        if value >= threshold:
            return points
    return 0


def evaluate_transit_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float,
) -> TransitAccessResult:
    """Approximate transit service frequency using Google Places signals.

    Returns a TransitAccessResult with primary_stop, walk_minutes, mode,
    frequency_bucket (Very low / Low / Medium / High), score_0_10, and
    human-readable reasons list.
    """
    reasons: List[str] = []

    # ------------------------------------------------------------------
    # 1. Gather all nearby transit nodes within density radius (1200 m)
    # ------------------------------------------------------------------
    seen_ids: set = set()
    all_nodes: List[Dict] = []
    for place_type in TRANSIT_SEARCH_TYPES:
        try:
            places = maps.places_nearby(lat, lng, place_type, radius_meters=1200)
        except Exception:
            continue
        for p in places:
            pid = p.get("place_id")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_nodes.append(p)

    density_count = len(all_nodes)

    if density_count == 0:
        return TransitAccessResult(
            frequency_bucket="Very low",
            score_0_10=0,
            reasons=["No transit stations found within 1.2 km"],
        )

    # ------------------------------------------------------------------
    # 2. Find primary node (closest walkable transit stop)
    # ------------------------------------------------------------------
    # Batch walking times — 1 API call per 25 nodes instead of 1 each
    destinations = [
        (node["geometry"]["location"]["lat"], node["geometry"]["location"]["lng"])
        for node in all_nodes
    ]
    try:
        walk_time_results = maps.walking_times_batch((lat, lng), destinations)
    except Exception:
        walk_time_results = [9999] * len(all_nodes)

    node_walk_times: List[Tuple[int, Dict]] = [
        (wt, node) for wt, node in zip(walk_time_results, all_nodes)
    ]

    node_walk_times.sort(key=lambda x: x[0])
    walk_min, primary = node_walk_times[0]

    primary_name = primary.get("name", "Unknown stop")
    primary_mode = _classify_mode(primary)
    user_ratings = primary.get("user_ratings_total") or 0

    # ------------------------------------------------------------------
    # 3. Count walk-reachable nodes (within 15 min walk)
    # ------------------------------------------------------------------
    walk_reachable = sum(1 for wt, _ in node_walk_times if wt <= 15)

    # ------------------------------------------------------------------
    # 4. Score each signal
    # ------------------------------------------------------------------
    mode_pts = MODE_WEIGHTS.get(primary_mode, 1)
    density_pts = _score_from_thresholds(density_count, DENSITY_THRESHOLDS)
    walk_node_pts = _score_from_thresholds(walk_reachable, WALK_NODE_THRESHOLDS)
    review_pts = _score_from_thresholds(user_ratings, REVIEW_THRESHOLDS)

    raw_score = mode_pts + density_pts + walk_node_pts + review_pts
    score = min(10, raw_score)

    # ------------------------------------------------------------------
    # 5. Determine frequency bucket
    # ------------------------------------------------------------------
    bucket = "Very low"
    for threshold, label in FREQUENCY_BUCKET_THRESHOLDS:
        if score >= threshold:
            bucket = label
            break

    # ------------------------------------------------------------------
    # 6. Build explanation reasons
    # ------------------------------------------------------------------
    reasons.append(
        f"Mode: {primary_mode} (+{mode_pts} pts) — "
        f"{'rail/subway modes score higher' if mode_pts >= 2 else 'bus/ferry modes score lower'}"
    )
    reasons.append(
        f"Density: {density_count} transit node(s) within 1.2 km (+{density_pts} pts)"
    )
    reasons.append(
        f"Walk-reachable: {walk_reachable} node(s) within 15 min walk (+{walk_node_pts} pts)"
    )
    reasons.append(
        f"Foot traffic proxy: {user_ratings:,} reviews on primary stop (+{review_pts} pts)"
    )
    reasons.append(f"Total raw: {raw_score} -> Score {score}/10 -> Bucket: {bucket}")

    return TransitAccessResult(
        primary_stop=primary_name,
        walk_minutes=walk_min if walk_min != 9999 else None,
        mode=primary_mode,
        frequency_bucket=bucket,
        score_0_10=score,
        reasons=reasons,
        nearby_node_count=walk_reachable,
        density_node_count=density_count,
    )


def is_nature_based_attraction(place: Dict) -> bool:
    """Return True if a tourist attraction is clearly nature-based."""
    types = place.get("types", [])
    if "tourist_attraction" not in types:
        return True

    nature_types = {"park", "natural_feature", "campground", "trail", "rv_park"}
    if any(t in types for t in nature_types):
        return True

    name = place.get("name", "").lower()
    nature_keywords = [
        "park",
        "trail",
        "preserve",
        "nature",
        "garden",
        "arboretum",
        "botanical",
        "river",
        "creek",
        "lake",
        "reservoir",
        "beach",
        "forest",
        "woods",
        "wetland",
        "marsh",
        "greenway",
        "walk",
        "hike",
        "canyon",
        "falls",
        "waterfall",
    ]
    return any(keyword in name for keyword in nature_keywords)


def format_place_types(types: List[str]) -> str:
    if not types:
        return "Unspecified"
    return ", ".join([t.replace("_", " ").title() for t in types])


def is_excluded_primary_green_space(name: str, types: List[str]) -> bool:
    name_lower = name.lower()
    has_park_type = "park" in types
    if any(keyword in name_lower for keyword in EXCLUDED_PRIMARY_KEYWORDS):
        if "playground" in name_lower and has_park_type:
            return False
        return True
    if any(space_type in EXCLUDED_PRIMARY_TYPES for space_type in types):
        return True
    if "playground" in types and not has_park_type:
        return True
    return False


def is_primary_green_escape(space: GreenSpace) -> bool:
    if is_excluded_primary_green_space(space.name, space.types):
        return False

    name_lower = space.name.lower()
    if any(keyword in name_lower for keyword in PRIMARY_GREEN_ESCAPE_KEYWORDS):
        return True

    reviews = space.user_ratings_total or 0
    if "park" in space.types and reviews >= GREEN_ESCAPE_MIN_REVIEWS:
        return True

    return False


def is_supporting_green_space(space: GreenSpace) -> bool:
    return any(space_type in SUPPORTING_GREEN_SPACE_TYPES for space_type in space.types)


def evaluate_green_spaces(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> GreenSpaceEvaluation:
    """Collect all nearby green spaces and determine the best primary green escape."""
    evaluation = GreenSpaceEvaluation()
    places_by_id: Dict[str, Dict[str, Any]] = {}

    for place_type in GREEN_SPACE_TYPES:
        places = maps.places_nearby(lat, lng, place_type, radius_meters=2500)
        for place in places:
            if place_type == "tourist_attraction" and not is_nature_based_attraction(place):
                continue

            place_id = place.get("place_id")
            if not place_id:
                continue

            entry = places_by_id.get(place_id)
            if entry:
                entry["types"].update(place.get("types", []))
                continue

            places_by_id[place_id] = {
                "place": place,
                "types": set(place.get("types", [])),
            }

    # Batch walking times — 1 API call per 25 places instead of 1 each
    entries_list = list(places_by_id.values())
    destinations = [
        (e["place"]["geometry"]["location"]["lat"], e["place"]["geometry"]["location"]["lng"])
        for e in entries_list
    ]
    walk_times = maps.walking_times_batch((lat, lng), destinations)

    green_spaces: List[GreenSpace] = []
    for entry, walk_time in zip(entries_list, walk_times):
        if walk_time > GREEN_SPACE_WALK_MAX_MIN or walk_time == 9999:
            continue

        place = entry["place"]
        place_id = place.get("place_id")
        types = sorted(entry["types"])
        green_spaces.append(GreenSpace(
            place_id=place_id,
            name=place.get("name", "Unknown"),
            rating=place.get("rating"),
            user_ratings_total=place.get("user_ratings_total", 0),
            walk_time_min=walk_time,
            types=types,
            types_display=format_place_types(types),
        ))

    green_spaces.sort(
        key=lambda space: (space.walk_time_min, -(space.rating or 0), -(space.user_ratings_total or 0))
    )

    evaluation.green_spaces = green_spaces

    primary_green_escape_candidates = [
        space for space in green_spaces if is_primary_green_escape(space)
    ]

    if primary_green_escape_candidates:
        evaluation.green_escape = max(
            primary_green_escape_candidates,
            key=lambda space: (
                (space.rating or 0) * math.log(space.user_ratings_total or 1),
                -space.walk_time_min,
            ),
        )
        evaluation.green_escape_message = None
    else:
        evaluation.green_escape_message = (
            "No primary green escape within a 30-minute walk — nearby parks and playgrounds listed below."
        )

    supporting_green_spaces = [
        space for space in green_spaces if is_supporting_green_space(space)
    ]
    if evaluation.green_escape:
        evaluation.other_green_spaces = [
            space for space in supporting_green_spaces
            if space.place_id != evaluation.green_escape.place_id
        ]
    else:
        evaluation.other_green_spaces = supporting_green_spaces.copy()

    if not evaluation.other_green_spaces:
        evaluation.green_spaces_message = "No other parks or playgrounds within a 30-minute walk."
    else:
        evaluation.green_spaces_message = "Other parks and playgrounds within a 30-minute walk."

    return evaluation


def is_quality_park(place: Dict, maps: GoogleMapsClient) -> Tuple[bool, str]:
    """Determine if a park meets quality criteria"""
    name = place.get("name", "Unknown")
    rating = place.get("rating", 0)
    reviews = place.get("user_ratings_total", 0)
    
    # Get more details if needed
    place_id = place.get("place_id")
    
    # Check if it's likely a small playground vs. real park
    types = place.get("types", [])
    if "playground" in types and "park" not in types:
        return False, f"{name} appears to be just a playground"
    
    # Use rating as a proxy for quality
    if rating >= MIN_PARK_RATING and reviews >= MIN_PARK_REVIEWS:
        return True, f"{name} ({rating}★, {reviews} reviews)"
    
    # Lower-rated but still a park
    if rating >= 3.5 and reviews >= 20:
        return True, f"{name} ({rating}★, {reviews} reviews) - verify quality"
    
    return False, f"{name} - insufficient data ({rating}★, {reviews} reviews)"


def score_park_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float,
    green_space_evaluation: Optional[GreenSpaceEvaluation] = None,
    green_escape_evaluation: Optional[GreenEscapeEvaluation] = None,
) -> Tier2Score:
    """Score primary green escape access (0-10 points).

    Uses the new green_space.py engine when a GreenEscapeEvaluation is provided,
    falling back to the legacy GreenSpaceEvaluation otherwise.
    """
    try:
        # New engine path
        if green_escape_evaluation is not None:
            best = green_escape_evaluation.best_daily_park
            if not best:
                return Tier2Score(
                    name="Primary Green Escape",
                    points=0,
                    max_points=10,
                    details="No green spaces found within walking distance",
                )

            # Use the daily walk value score directly (already 0–10)
            points = round(best.daily_walk_value)
            rating_str = f"{best.rating:.1f}★" if best.rating else "unrated"
            details = (
                f"{best.name} ({rating_str}, {best.user_ratings_total} reviews) "
                f"— {best.walk_time_min} min walk — Daily Value {best.daily_walk_value:.1f}/10 "
                f"[{best.criteria_status}]"
            )
            return Tier2Score(
                name="Primary Green Escape",
                points=points,
                max_points=10,
                details=details,
            )

        # Legacy path
        evaluation = green_space_evaluation or evaluate_green_spaces(maps, lat, lng)
        green_escape = evaluation.green_escape

        if not green_escape:
            return Tier2Score(
                name="Primary Green Escape",
                points=0,
                max_points=10,
                details="No primary green escape within a 30-minute walk"
            )

        if green_escape.walk_time_min <= PARK_WALK_IDEAL_MIN:
            points = 10
        else:
            points = 6

        details = (
            f"{green_escape.name} ({green_escape.rating}★, "
            f"{green_escape.user_ratings_total} reviews) — {green_escape.walk_time_min} min walk"
        )

        return Tier2Score(
            name="Primary Green Escape",
            points=points,
            max_points=10,
            details=details
        )

    except Exception as e:
        return Tier2Score(
            name="Primary Green Escape",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        )


def score_third_place_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> Tuple[Tier2Score, list]:
    """Score third-place access based on third-place quality (0-10 points).

    Returns (Tier2Score, places_list) where places_list contains up to 5
    nearby places for the neighborhood display.
    """
    try:
        # Search for cafes, coffee shops, and bakeries
        # Use 3000m radius to share cached results with neighborhood snapshot
        all_places = []
        all_places.extend(maps.places_nearby(lat, lng, "cafe", radius_meters=3000))
        all_places.extend(maps.places_nearby(lat, lng, "bakery", radius_meters=3000))
        all_places = _dedupe_by_place_id(all_places)

        if not all_places:
            return (Tier2Score(
                name="Third Place",
                points=0,
                max_points=10,
                details="No high-quality third places within walking distance"
            ), [])

        # Filter for third-place quality
        eligible_places = []
        excluded_types = ["convenience_store", "gas_station", "meal_takeaway", "fast_food", "supermarket"]

        for place in all_places:
            # Get place types
            types = place.get("types", [])

            # Must have at least one acceptable type
            has_acceptable_type = any(t in types for t in ["cafe", "coffee_shop", "bakery"])
            if not has_acceptable_type:
                continue

            # Must NOT have any excluded type
            has_excluded_type = any(t in types for t in excluded_types)
            if has_excluded_type:
                continue

            # Must meet quality threshold
            rating = place.get("rating", 0)
            reviews = place.get("user_ratings_total", 0)

            if rating >= 4.0 and reviews >= 30:
                eligible_places.append(place)

        if not eligible_places:
            return (Tier2Score(
                name="Third Place",
                points=0,
                max_points=10,
                details="No high-quality third places within walking distance"
            ), [])

        # Batch walking times — 1 API call per 25 places instead of 1 each
        destinations = [
            (p["geometry"]["location"]["lat"], p["geometry"]["location"]["lng"])
            for p in eligible_places
        ]
        walk_times = maps.walking_times_batch((lat, lng), destinations)

        # Find best scoring place and collect all scored places
        best_score = 0
        best_place = None
        best_walk_time = 9999
        scored_places = []

        for place, walk_time in zip(eligible_places, walk_times):
            # Score based on walk time
            score = 0
            if walk_time <= 15:
                score = 10
            elif walk_time <= 20:
                score = 7
            elif walk_time <= 30:
                score = 4
            else:
                score = 2

            if score > best_score or (score == best_score and walk_time < best_walk_time):
                best_score = score
                best_place = place
                best_walk_time = walk_time

            scored_places.append((score, walk_time, place))

        # Sort by score desc, then walk time asc; take top 5
        scored_places.sort(key=lambda x: (-x[0], x[1]))
        neighborhood_places = [
            {
                "name": p.get("name", "Coffee shop"),
                "rating": p.get("rating"),
                "review_count": p.get("user_ratings_total", 0),
                "walk_time_min": wt,
                "lat": p["geometry"]["location"]["lat"],
                "lng": p["geometry"]["location"]["lng"],
                "place_id": p.get("place_id"),
            }
            for _sc, wt, p in scored_places[:5]
        ]
        neighborhood_places.sort(key=lambda p: p.get("walk_time_min") or 9999)

        # Format details
        name = best_place.get("name", "Third place")
        rating = best_place.get("rating", 0)
        reviews = best_place.get("user_ratings_total", 0)
        details = f"{name} ({rating}★, {reviews} reviews) — {best_walk_time} min walk"

        return (Tier2Score(
            name="Third Place",
            points=best_score,
            max_points=10,
            details=details
        ), neighborhood_places)

    except Exception as e:
        return (Tier2Score(
            name="Third Place",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        ), [])


def score_cost(cost: Optional[int]) -> Tier2Score:
    """Score based on monthly cost (0-10 points)"""
    if cost is None:
        return Tier2Score(
            name="Cost",
            points=0,
            max_points=10,
            details="Monthly cost not specified"
        )

    if cost <= COST_IDEAL:
        points = 10
        details = f"${cost:,} — ${COST_IDEAL - cost:,} under ideal target"
    elif cost <= COST_TARGET:
        points = 6
        details = f"${cost:,} — within target range"
    elif cost <= COST_MAX:
        points = 0
        details = f"${cost:,} — at cost ceiling"
    else:
        points = 0
        details = f"${cost:,} — OVER BUDGET"

    return Tier2Score(
        name="Cost",
        points=points,
        max_points=10,
        details=details
    )


def score_transit_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float,
    transit_keywords: Optional[List[str]] = None,
    transit_access: Optional[TransitAccessResult] = None,
    urban_access: Optional[UrbanAccessProfile] = None,
) -> Tier2Score:
    """Score urban access via rail transit (0-10 points).

    When a pre-computed TransitAccessResult is supplied its score is used
    directly for the frequency component (replacing the old review-count
    proxy).  When urban_access is supplied, reuses its primary_transit and
    major_hub instead of making duplicate API calls.
    """
    def walkability_points(walk_time: int) -> int:
        if walk_time <= 10:
            return 4
        if walk_time <= 20:
            return 3
        if walk_time <= 30:
            return 2
        if walk_time <= 45:
            return 1
        return 0

    def hub_travel_points(travel_time: Optional[int]) -> int:
        if travel_time is None or travel_time <= 0:
            return 0
        if travel_time <= 45:
            return 3
        if travel_time <= 75:
            return 2
        if travel_time <= 110:
            return 1
        return 0

    try:
        # Reuse cached urban_access results when available to avoid
        # duplicate find_primary_transit + determine_major_hub API calls
        if urban_access is not None:
            primary_transit = urban_access.primary_transit
            major_hub = urban_access.major_hub
        else:
            primary_transit = find_primary_transit(maps, lat, lng)
            major_hub = determine_major_hub(
                maps,
                lat,
                lng,
                primary_transit.mode if primary_transit else None,
                transit_origin=(primary_transit.lat, primary_transit.lng) if primary_transit else None,
            ) if primary_transit else None

        if not primary_transit:
            return Tier2Score(
                name="Urban access",
                points=0,
                max_points=10,
                details="No rail transit stations found within reach"
            )

        walk_points = walkability_points(primary_transit.walk_time_min)

        # Use smart heuristic bucket when available, else fall back to
        # the original review-count frequency_class.
        if transit_access and transit_access.frequency_bucket:
            frequency_points = {
                "High": 3,
                "Medium": 2,
                "Low": 1,
                "Very low": 0,
            }.get(transit_access.frequency_bucket, 0)
            frequency_label = f"{transit_access.frequency_bucket} frequency"
        else:
            frequency_class = primary_transit.frequency_class or "Very low frequency"
            frequency_points = {
                "High frequency": 3,
                "Medium frequency": 2,
                "Low frequency": 1,
                "Very low frequency": 0,
            }.get(frequency_class, 0)
            frequency_label = frequency_class

        hub_time = major_hub.travel_time_min if major_hub else None
        hub_points = hub_travel_points(hub_time)

        total_points = min(10, walk_points + frequency_points + hub_points)

        drive_note = ""
        if primary_transit.drive_time_min:
            drive_note = f" | {primary_transit.drive_time_min} min drive"

        hub_note = "Hub travel time unavailable"
        if major_hub and hub_time:
            hub_note = f"{major_hub.name} — {hub_time} min"

        return Tier2Score(
            name="Urban access",
            points=total_points,
            max_points=10,
            details=(
                f"{primary_transit.name} — {primary_transit.walk_time_min} min walk"
                f"{drive_note} | "
                f"Service: {frequency_label} | "
                f"Hub: {hub_note}"
            )
        )

    except Exception as e:
        return Tier2Score(
            name="Urban access",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        )


def score_provisioning_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> Tuple[Tier2Score, list]:
    """Score household provisioning store access (0-10 points).

    Returns (Tier2Score, places_list) where places_list contains up to 5
    nearby stores for the neighborhood display.
    """
    try:
        # Search for full-service provisioning stores
        # Use 3000m radius to share cached results with neighborhood snapshot
        all_stores = []
        all_stores.extend(maps.places_nearby(lat, lng, "supermarket", radius_meters=3000))
        all_stores.extend(maps.places_nearby(lat, lng, "grocery_store", radius_meters=3000))
        all_stores = _dedupe_by_place_id(all_stores)

        if not all_stores:
            return (Tier2Score(
                name="Provisioning",
                points=0,
                max_points=10,
                details="No full-service provisioning options within walking distance"
            ), [])

        # Filter for household provisioning quality
        eligible_stores = []
        included_types = ["supermarket", "grocery_store", "warehouse_store", "superstore"]
        excluded_types = ["convenience_store", "gas_station", "pharmacy", "liquor_store", "meal_takeaway", "fast_food"]

        for store in all_stores:
            types = store.get("types", [])

            # Must have at least one provisioning type
            has_provisioning_type = any(t in types for t in included_types)
            if not has_provisioning_type:
                continue

            # Must NOT have any excluded type
            has_excluded_type = any(t in types for t in excluded_types)
            if has_excluded_type:
                continue

            # Must meet quality threshold
            rating = store.get("rating", 0)
            reviews = store.get("user_ratings_total", 0)

            if rating >= 4.0 and reviews >= 50:
                eligible_stores.append(store)

        if not eligible_stores:
            return (Tier2Score(
                name="Provisioning",
                points=0,
                max_points=10,
                details="No full-service provisioning options within walking distance"
            ), [])

        # Batch walking times — 1 API call per 25 stores instead of 1 each
        destinations = [
            (s["geometry"]["location"]["lat"], s["geometry"]["location"]["lng"])
            for s in eligible_stores
        ]
        walk_times = maps.walking_times_batch((lat, lng), destinations)

        # Find best scoring store and collect all scored stores
        best_score = 0
        best_store = None
        best_walk_time = 9999
        scored_stores = []

        for store, walk_time in zip(eligible_stores, walk_times):
            # Score based on walk time
            score = 0
            if walk_time <= 15:
                score = 10
            elif walk_time <= 20:
                score = 7
            elif walk_time <= 30:
                score = 4
            else:
                score = 2

            if score > best_score or (score == best_score and walk_time < best_walk_time):
                best_score = score
                best_store = store
                best_walk_time = walk_time

            scored_stores.append((score, walk_time, store))

        # Sort by score desc, then walk time asc; take top 5
        scored_stores.sort(key=lambda x: (-x[0], x[1]))
        neighborhood_places = [
            {
                "name": s.get("name", "Grocery store"),
                "rating": s.get("rating"),
                "review_count": s.get("user_ratings_total", 0),
                "walk_time_min": wt,
                "lat": s["geometry"]["location"]["lat"],
                "lng": s["geometry"]["location"]["lng"],
                "place_id": s.get("place_id"),
            }
            for _sc, wt, s in scored_stores[:5]
        ]
        neighborhood_places.sort(key=lambda p: p.get("walk_time_min") or 9999)

        # Format details
        name = best_store.get("name", "Provisioning store")
        rating = best_store.get("rating", 0)
        reviews = best_store.get("user_ratings_total", 0)
        details = f"{name} ({rating}★, {reviews} reviews) — {best_walk_time} min walk"

        return (Tier2Score(
            name="Provisioning",
            points=best_score,
            max_points=10,
            details=details
        ), neighborhood_places)

    except Exception as e:
        return (Tier2Score(
            name="Provisioning",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        ), [])


def score_fitness_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> Tuple[Tier2Score, list]:
    """Score fitness/wellness facility access based on rating and distance (0-10 points).

    Returns (Tier2Score, places_list) where places_list contains up to 5
    nearby facilities for the neighborhood display.
    """
    try:
        # Search for gyms and fitness centers
        fitness_places = []

        # Try gym type
        gyms = maps.places_nearby(lat, lng, "gym", radius_meters=3000)
        fitness_places.extend(gyms)

        # Try searching for yoga studios using keyword
        # Note: Google Places API may not have "yoga_studio" as a separate type,
        # so we search with keyword instead
        yoga = maps.places_nearby(lat, lng, "gym", radius_meters=3000, keyword="yoga")
        fitness_places.extend(yoga)
        fitness_places = _dedupe_by_place_id(fitness_places)

        if not fitness_places:
            return (Tier2Score(
                name="Fitness access",
                points=0,
                max_points=10,
                details="No gyms or fitness centers found within 30 min walk"
            ), [])

        # Batch walking times — 1 API call per 25 facilities instead of 1 each
        destinations = [
            (f["geometry"]["location"]["lat"], f["geometry"]["location"]["lng"])
            for f in fitness_places
        ]
        walk_times = maps.walking_times_batch((lat, lng), destinations)

        # Find best scored facility and collect all scored facilities
        best_score = 0
        best_facility = None
        best_details = ""
        scored_facilities = []

        for facility, walk_time in zip(fitness_places, walk_times):
            rating = facility.get("rating", 0)

            # Score based on rating + distance
            score = 0
            if rating >= 4.2 and walk_time <= 15:
                score = 10
            elif rating >= 4.0 and walk_time <= 20:
                score = 6
            elif walk_time <= 30:
                score = 3

            if score > best_score:
                best_score = score
                best_facility = facility
                facility_name = facility.get("name", "Fitness center")
                best_details = f"{facility_name} ({rating}★) — {walk_time} min walk"

            scored_facilities.append((score, walk_time, facility))

        if best_score == 0 and not scored_facilities:
            return (Tier2Score(
                name="Fitness access",
                points=0,
                max_points=10,
                details="No gyms or fitness centers found within 30 min walk"
            ), [])

        # Sort by score desc, then walk time asc; take top 5
        scored_facilities.sort(key=lambda x: (-x[0], x[1]))
        neighborhood_places = [
            {
                "name": f.get("name", "Fitness center"),
                "rating": f.get("rating"),
                "review_count": f.get("user_ratings_total", 0),
                "walk_time_min": wt,
                "lat": f["geometry"]["location"]["lat"],
                "lng": f["geometry"]["location"]["lng"],
                "place_id": f.get("place_id"),
            }
            for _sc, wt, f in scored_facilities[:5]
        ]
        neighborhood_places.sort(key=lambda p: p.get("walk_time_min") or 9999)

        if best_score == 0:
            return (Tier2Score(
                name="Fitness access",
                points=0,
                max_points=10,
                details="No gyms or fitness centers found within 30 min walk"
            ), neighborhood_places)

        return (Tier2Score(
            name="Fitness access",
            points=best_score,
            max_points=10,
            details=best_details
        ), neighborhood_places)

    except Exception as e:
        return (Tier2Score(
            name="Fitness access",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        ), [])


def calculate_bonuses(listing: PropertyListing) -> List[Tier3Bonus]:
    """Calculate tier 3 bonus points"""
    bonuses = []
    
    if listing.has_parking:
        bonuses.append(Tier3Bonus(
            name="Parking",
            points=5,
            details="Parking included"
        ))
    
    if listing.has_outdoor_space:
        bonuses.append(Tier3Bonus(
            name="Outdoor space",
            points=5,
            details="Private yard or balcony"
        ))
    
    if listing.bedrooms and listing.bedrooms >= 3:
        bonuses.append(Tier3Bonus(
            name="Extra bedroom",
            points=5,
            details=f"{listing.bedrooms} bedrooms"
        ))
    
    return bonuses


def calculate_bonus_reasons(listing: PropertyListing) -> List[str]:
    """Explain missing tier 3 bonuses when none are awarded."""
    reasons = []

    if listing.has_parking is None:
        reasons.append("Parking/garage info missing")
    elif not listing.has_parking:
        reasons.append("No garage or parking")

    if listing.has_outdoor_space is None:
        reasons.append("Outdoor space info missing")
    elif not listing.has_outdoor_space:
        reasons.append("No yard or balcony")

    if listing.bedrooms is None:
        reasons.append("Bedroom count missing")
    elif listing.bedrooms < 3:
        reasons.append("Fewer than 3 bedrooms")

    return reasons


def estimate_percentile(score: int) -> Tuple[int, str]:
    """Estimate percentile bucket from a normalized 0-100 score."""
    buckets = [
        (90, 5),
        (85, 10),
        (80, 20),
        (75, 30),
        (70, 40),
        (65, 50),
        (60, 60),
        (55, 70),
        (50, 80),
        (0, 90),
    ]
    for threshold, top_percent in buckets:
        if score >= threshold:
            return top_percent, f"≈ top {top_percent}% nationally for families"
    return 90, "≈ top 90% nationally for families"


# =============================================================================
# MAIN EVALUATION
# =============================================================================

def _timed_stage(stage_name, fn, *args, **kwargs):
    """Run *fn* with timing.  Logs duration and re-raises on failure."""
    trace = get_trace()
    if trace:
        trace.start_stage(stage_name)
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        t1 = time.time()
        if trace:
            trace.record_stage(stage_name, t0, t1)
        else:
            logger.info("  [stage] %s OK (%.1fs)", stage_name, t1 - t0)
        return result
    except Exception as exc:
        t1 = time.time()
        if trace:
            trace.record_stage(
                stage_name, t0, t1,
                error_class=type(exc).__name__,
                error_message=str(exc)[:200],
            )
        else:
            logger.warning("  [stage] %s FAILED (%.1fs)", stage_name, t1 - t0, exc_info=True)
        raise


def evaluate_property(
    listing: PropertyListing,
    api_key: str,
    pre_geocode: Optional[Dict[str, Any]] = None,
    on_stage: Optional[Callable[[str], None]] = None,
    place_id: Optional[str] = None,
    persona: Optional[str] = None,
) -> EvaluationResult:
    """Run full evaluation on a property listing.

    Each enrichment stage is wrapped in try/except so that a single
    failing API call (timeout, quota, etc.) degrades gracefully
    instead of aborting the whole evaluation.

    Args:
        on_stage: Optional callback invoked with stage name as evaluation
            progresses, used by the worker to update job status in the DB.
        place_id: Optional Google place_id (unused in evaluation itself,
            reserved for future use).
        persona: Optional persona key (e.g. "active", "commuter", "quiet").
            Determines dimension weights used for score aggregation.
            Defaults to "balanced" (equal weights).
    """
    def _notify(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    def _staged(stage_name, fn, *args, **kwargs):
        """Notify the frontend of the current stage, then run _timed_stage."""
        _notify(stage_name)
        return _timed_stage(stage_name, fn, *args, **kwargs)

    eval_start = time.time()

    # Resolve persona preset for weighted scoring
    persona_preset = PERSONA_PRESETS.get(persona or DEFAULT_PERSONA,
                                         PERSONA_PRESETS[DEFAULT_PERSONA])

    maps = GoogleMapsClient(api_key)

    # Geocode is the one stage that MUST succeed — without coords nothing
    # else can run. The app route may pre-geocode for dedupe.
    if pre_geocode is not None:
        _notify("geocode")
        lat = pre_geocode["lat"]
        lng = pre_geocode["lng"]
    else:
        lat, lng = _staged("geocode", maps.geocode, listing.address)

    result = EvaluationResult(
        listing=listing,
        lat=lat,
        lng=lng,
        persona=persona_preset,
    )

    # --- Optional enrichments (each fails independently) ---

    try:
        bike_data = _staged("bike_score", get_bike_score, listing.address, lat, lng)
        result.bike_score = bike_data.get("bike_score")
        result.bike_rating = bike_data.get("bike_rating")
        result.bike_metadata = bike_data.get("bike_metadata")
    except Exception:
        pass

    try:
        result.neighborhood_snapshot = _staged(
            "neighborhood", get_neighborhood_snapshot, maps, lat, lng)
    except Exception:
        pass

    if ENABLE_SCHOOLS:
        try:
            result.child_schooling_snapshot = _staged(
                "schools", get_child_and_schooling_snapshot, maps, lat, lng)
        except Exception:
            pass

    try:
        result.urban_access = _staged(
            "urban_access", get_urban_access_profile, maps, lat, lng)
    except Exception:
        pass

    try:
        result.transit_access = _staged(
            "transit_access", evaluate_transit_access, maps, lat, lng)
    except Exception:
        pass

    try:
        result.green_space_evaluation = _staged(
            "green_spaces", evaluate_green_spaces, maps, lat, lng)
    except Exception:
        pass

    try:
        result.green_escape_evaluation = _staged(
            "green_escape", evaluate_green_escape, maps, lat, lng)
    except Exception:
        pass

    try:
        result.transit_score = _staged(
            "transit_score", get_transit_score, listing.address, lat, lng)
    except Exception:
        pass

    try:
        result.walk_scores = _staged(
            "walk_scores", get_walk_scores, listing.address, lat, lng)
    except Exception:
        pass

    # ===================
    # TIER 1 CHECKS
    # ===================

    _notify("tier1_checks")
    trace = get_trace()
    if trace:
        trace.start_stage("tier1_checks")
    _t0_tier1 = time.time()

    # Location-based checks
    result.tier1_checks.append(check_gas_stations(maps, lat, lng))

    # High-traffic road check (HPMS AADT data — local SpatiaLite, no API cost)
    _spatial_store = SpatialDataStore()
    result.tier1_checks.append(check_high_traffic_road(lat, lng, _spatial_store))

    # Environmental health proximity checks (NES-57)
    try:
        env_hazards = _query_environmental_hazards(lat, lng)
    except Exception as e:
        logger.warning("Environmental hazard query failed: %s", e)
        env_hazards = None

    result.tier1_checks.append(check_power_lines(env_hazards, lat, lng))
    result.tier1_checks.append(check_substations(env_hazards, lat, lng))
    result.tier1_checks.append(check_cell_towers(env_hazards, lat, lng))
    result.tier1_checks.append(check_industrial_zones(env_hazards, lat, lng))

    # Flood zone check (local SpatiaLite — no API cost)
    result.tier1_checks.append(check_flood_zones(lat, lng))

    # Superfund NPL containment check (local SpatiaLite — Tier 0 hard fail)
    result.tier1_checks.append(check_superfund_npl(lat, lng))

    # TRI facility proximity check (local SpatiaLite — Tier 0 warning)
    result.tier1_checks.append(
        check_tri_facility_proximity(lat, lng, _spatial_store)
    )

    # EJScreen block group environmental indicators (local SpatiaLite — no API cost)
    ejscreen_data = None
    try:
        ejscreen_data = _query_ejscreen_block_group(lat, lng, _spatial_store)
    except Exception as e:
        logger.warning("EJScreen block group query failed: %s", e)

    if ejscreen_data is not None:
        result.ejscreen_profile = ejscreen_data
        # Find SEMS result for Superfund dedup
        sems_check = next(
            (c for c in result.tier1_checks if c.name == "Superfund (NPL)"), None,
        )
        result.tier1_checks.extend(
            _check_ejscreen_indicators(ejscreen_data, sems_check)
        )

    # Listing-based checks
    result.tier1_checks.extend(check_listing_requirements(listing))

    if trace:
        trace.record_stage("tier1_checks", _t0_tier1, time.time())

    # Determine if passed tier 1
    fail_count = sum(
        1 for c in result.tier1_checks
        if c.result == CheckResult.FAIL and c.required
    )
    result.passed_tier1 = (fail_count == 0)

    # ===================
    # TIER 2 SCORING
    # ===================

    if result.passed_tier1:
        result.tier2_scores.append(
            _staged(
                "score_park_access", score_park_access,
                maps, lat, lng,
                green_space_evaluation=result.green_space_evaluation,
                green_escape_evaluation=result.green_escape_evaluation,
            )
        )
        _coffee_score, _coffee_places = _staged(
            "score_third_place", score_third_place_access, maps, lat, lng)
        result.tier2_scores.append(_coffee_score)

        _grocery_score, _grocery_places = _staged(
            "score_provisioning", score_provisioning_access, maps, lat, lng)
        result.tier2_scores.append(_grocery_score)

        _fitness_score, _fitness_places = _staged(
            "score_fitness", score_fitness_access, maps, lat, lng)
        result.tier2_scores.append(_fitness_score)

        result.tier2_scores.append(score_cost(listing.cost))
        result.tier2_scores.append(
            _staged(
                "score_transit_access", score_transit_access,
                maps, lat, lng,
                transit_access=result.transit_access,
                urban_access=result.urban_access,
            )
        )

        # Assemble neighborhood places from scoring + green escape parks
        _park_places = []
        if result.green_escape_evaluation:
            _all_parks = []
            if result.green_escape_evaluation.best_daily_park:
                _all_parks.append(result.green_escape_evaluation.best_daily_park)
            _all_parks.extend(result.green_escape_evaluation.nearby_green_spaces)
            for gs in _all_parks[:5]:
                _park_places.append({
                    "name": gs.name,
                    "rating": gs.rating,
                    "review_count": gs.user_ratings_total,
                    "walk_time_min": gs.walk_time_min,
                    "lat": gs.lat,
                    "lng": gs.lng,
                    "place_id": gs.place_id,
                })
            _park_places.sort(key=lambda p: p.get("walk_time_min") or 9999)

        result.neighborhood_places = {
            "coffee": _coffee_places,
            "grocery": _grocery_places,
            "fitness": _fitness_places,
            "parks": _park_places,
        }

        # Raw unweighted totals (for display / backward compat)
        result.tier2_total = sum(s.points for s in result.tier2_scores)
        result.tier2_max = sum(s.max_points for s in result.tier2_scores)

        # Weighted normalization using persona lens.
        # Map internal Tier2Score names to persona dimension names so
        # weights resolve correctly (e.g. "Third Place" -> "Coffee & Social Spots").
        _weights = persona_preset.weights
        _weighted_total = sum(
            s.points * _weights.get(TIER2_NAME_TO_DIMENSION.get(s.name, s.name), 1.0)
            for s in result.tier2_scores
        )
        _weighted_max = sum(
            s.max_points * _weights.get(TIER2_NAME_TO_DIMENSION.get(s.name, s.name), 1.0)
            for s in result.tier2_scores
        )
        if _weighted_max > 0:
            result.tier2_normalized = int(_weighted_total / _weighted_max * 100 + 0.5)
        else:
            result.tier2_normalized = 0

    # ===================
    # TIER 3 BONUSES
    # ===================

    _notify("tier3_bonuses")
    if result.passed_tier1:
        result.tier3_bonuses = calculate_bonuses(listing)
        result.tier3_total = sum(b.points for b in result.tier3_bonuses)
        result.tier3_bonus_reasons = calculate_bonus_reasons(listing)

    # ===================
    # FINAL SCORE + PERCENTILE
    # ===================

    result.final_score = min(100, result.tier2_normalized + result.tier3_total)
    result.percentile_top, result.percentile_label = estimate_percentile(result.final_score)

    elapsed_total = time.time() - eval_start
    logger.info("Evaluation complete for %r  score=%d  (%.1fs total)",
                listing.address, result.final_score, elapsed_total)

    return result


def format_result(result: EvaluationResult) -> str:
    """Format evaluation result as a readable report"""
    lines = []
    
    lines.append("=" * 70)
    lines.append(f"PROPERTY: {result.listing.address}")
    if result.listing.url:
        lines.append(f"LISTING: {result.listing.url}")
    if result.listing.rent:
        lines.append(f"RENT: ${result.listing.rent:,}/month")
    lines.append(f"COORDINATES: {result.lat:.6f}, {result.lng:.6f}")
    lines.append("=" * 70)
    
    # Tier 1
    lines.append("\nTIER 1 CHECKS:")
    for check in result.tier1_checks:
        symbol = "✓" if check.result == CheckResult.PASS else "✗" if check.result == CheckResult.FAIL else "⚠" if check.result == CheckResult.WARNING else "?"
        lines.append(f"  {symbol} {check.name}: {check.result.value} — {check.details}")
    
    if not result.passed_tier1:
        lines.append("\n❌ FAILED TIER 1 — Property disqualified")
        return "\n".join(lines)
    
    lines.append("\n✅ PASSED TIER 1")
    
    # Tier 2
    lines.append(
        f"\nTIER 2 SCORE: {result.tier2_total}/{result.tier2_max} "
        f"(normalized {result.tier2_normalized}/100)"
    )
    for score in result.tier2_scores:
        lines.append(f"  - {score.name}: {score.points} pts — {score.details}")
    
    # Tier 3
    if result.tier3_bonuses:
        lines.append(f"\nTIER 3 BONUS: +{result.tier3_total} pts")
        for bonus in result.tier3_bonuses:
            lines.append(f"  - {bonus.name}: +{bonus.points} — {bonus.details}")
    else:
        if result.tier3_bonus_reasons:
            lines.append("\nTIER 3 BONUS: +0 pts")
            lines.append(f"  No bonus points because: {', '.join(result.tier3_bonus_reasons)}")
        else:
            lines.append("\nTIER 3 BONUS: +0 pts")
    
    # Final
    lines.append(f"\n{'=' * 70}")
    lines.append(f"LIVABILITY SCORE: {result.final_score}/100 ({result.percentile_label})")
    lines.append(f"Tier 3 Bonus: +{result.tier3_total} pts (capped at 100)")
    lines.append("=" * 70)
    
    # Notes
    if result.notes:
        lines.append("\nNOTES:")
        for note in result.notes:
            lines.append(f"  • {note}")
    
    return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate a property against health, lifestyle, and budget criteria"
    )
    parser.add_argument(
        "address",
        nargs="?",
        help="Property address to evaluate"
    )
    parser.add_argument(
        "--cost",
        type=int,
        help="Monthly cost in dollars (rent or estimated mortgage+expenses)"
    )
    parser.add_argument(
        "--sqft",
        type=int,
        help="Square footage"
    )
    parser.add_argument(
        "--bedrooms",
        type=int,
        help="Number of bedrooms"
    )
    parser.add_argument(
        "--washer-dryer",
        action="store_true",
        help="Has washer/dryer in unit"
    )
    parser.add_argument(
        "--central-air",
        action="store_true",
        help="Has central air"
    )
    parser.add_argument(
        "--parking",
        action="store_true",
        help="Has parking"
    )
    parser.add_argument(
        "--outdoor-space",
        action="store_true",
        help="Has outdoor space (yard/balcony)"
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("GOOGLE_MAPS_API_KEY"),
        help="Google Maps API key (or set GOOGLE_MAPS_API_KEY env var)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text"
    )
    
    args = parser.parse_args()
    
    if not args.address:
        parser.print_help()
        sys.exit(1)
    
    if not args.api_key:
        print("Error: Google Maps API key required. Set GOOGLE_MAPS_API_KEY or use --api-key")
        sys.exit(1)
    
    # Build listing
    listing = PropertyListing(
        address=args.address,
        cost=args.cost,
        sqft=args.sqft,
        bedrooms=args.bedrooms,
        has_washer_dryer_in_unit=args.washer_dryer if args.washer_dryer else None,
        has_central_air=args.central_air if args.central_air else None,
        has_parking=args.parking if args.parking else None,
        has_outdoor_space=args.outdoor_space if args.outdoor_space else None,
    )
    
    # Evaluate
    result = evaluate_property(listing, args.api_key)
    
    # Output
    if args.json:
        # Convert to dict for JSON output
        output = {
            "address": result.listing.address,
            "coordinates": {"lat": result.lat, "lng": result.lng},
            "walk_scores": result.walk_scores,
            "neighborhood_snapshot": [
                {
                    "category": p.category,
                    "name": p.name,
                    "rating": p.rating,
                    "walk_time_min": p.walk_time_min,
                    "place_type": p.place_type
                }
                for p in (result.neighborhood_snapshot.places if result.neighborhood_snapshot else [])
            ],
            "child_schooling_snapshot": {
                "childcare": [
                    {
                        "name": p.name,
                        "rating": p.rating,
                        "user_ratings_total": p.user_ratings_total,
                        "walk_time_min": p.walk_time_min,
                        "website": p.website
                    }
                    for p in (result.child_schooling_snapshot.childcare if result.child_schooling_snapshot else [])
                ],
                "schools_by_level": {
                    level: (
                        {
                            "name": place.name,
                            "rating": place.rating,
                            "user_ratings_total": place.user_ratings_total,
                            "walk_time_min": place.walk_time_min,
                            "website": place.website,
                            "level": place.level,
                        }
                        if place else None
                    )
                    for level, place in (
                        result.child_schooling_snapshot.schools_by_level.items()
                        if result.child_schooling_snapshot else {}
                    )
                }
            },
            "urban_access": {
                "primary_transit": {
                    "name": result.urban_access.primary_transit.name,
                    "mode": result.urban_access.primary_transit.mode,
                    "lat": result.urban_access.primary_transit.lat,
                    "lng": result.urban_access.primary_transit.lng,
                    "walk_time_min": result.urban_access.primary_transit.walk_time_min,
                    "drive_time_min": result.urban_access.primary_transit.drive_time_min,
                    "parking_available": result.urban_access.primary_transit.parking_available,
                    "user_ratings_total": result.urban_access.primary_transit.user_ratings_total,
                    "frequency_class": result.urban_access.primary_transit.frequency_class,
                } if result.urban_access and result.urban_access.primary_transit else None,
                "major_hub": {
                    "name": result.urban_access.major_hub.name,
                    "travel_time_min": result.urban_access.major_hub.travel_time_min,
                    "transit_mode": result.urban_access.major_hub.transit_mode,
                    "route_summary": result.urban_access.major_hub.route_summary,
                } if result.urban_access and result.urban_access.major_hub else None,
            },
            "transit_access": {
                "primary_stop": result.transit_access.primary_stop,
                "walk_minutes": result.transit_access.walk_minutes,
                "mode": result.transit_access.mode,
                "frequency_bucket": result.transit_access.frequency_bucket,
                "score_0_10": result.transit_access.score_0_10,
                "reasons": result.transit_access.reasons,
                "nearby_node_count": result.transit_access.nearby_node_count,
                "density_node_count": result.transit_access.density_node_count,
            } if result.transit_access else None,
            "green_space_evaluation": {
                "green_escape": {
                    "name": result.green_space_evaluation.green_escape.name,
                    "rating": result.green_space_evaluation.green_escape.rating,
                    "user_ratings_total": result.green_space_evaluation.green_escape.user_ratings_total,
                    "walk_time_min": result.green_space_evaluation.green_escape.walk_time_min,
                    "types": result.green_space_evaluation.green_escape.types,
                    "types_display": result.green_space_evaluation.green_escape.types_display,
                } if result.green_space_evaluation and result.green_space_evaluation.green_escape else None,
                "green_escape_message": (
                    result.green_space_evaluation.green_escape_message
                    if result.green_space_evaluation else None
                ),
                "green_spaces": [
                    {
                        "name": space.name,
                        "rating": space.rating,
                        "user_ratings_total": space.user_ratings_total,
                        "walk_time_min": space.walk_time_min,
                        "types": space.types,
                        "types_display": space.types_display,
                    }
                    for space in (result.green_space_evaluation.green_spaces if result.green_space_evaluation else [])
                ],
                "other_green_spaces": [
                    {
                        "name": space.name,
                        "rating": space.rating,
                        "user_ratings_total": space.user_ratings_total,
                        "walk_time_min": space.walk_time_min,
                        "types": space.types,
                        "types_display": space.types_display,
                    }
                    for space in (result.green_space_evaluation.other_green_spaces if result.green_space_evaluation else [])
                ],
                "green_spaces_message": (
                    result.green_space_evaluation.green_spaces_message
                    if result.green_space_evaluation else None
                ),
            },
            "transit_score": result.transit_score,
            "bike_score": result.bike_score,
            "bike_rating": result.bike_rating,
            "bike_metadata": result.bike_metadata,
            "passed_tier1": result.passed_tier1,
            "tier1_checks": [
                {
                    "name": c.name,
                    "result": c.result.value,
                    "details": c.details,
                    "required": c.required,
                }
                for c in result.tier1_checks
            ],
            "tier2_score": result.tier2_total,
            "tier2_max": result.tier2_max,
            "tier2_normalized": result.tier2_normalized,
            "tier2_scores": [
                {"name": s.name, "points": s.points, "max": s.max_points, "details": s.details}
                for s in result.tier2_scores
            ],
            "tier3_bonus": result.tier3_total,
            "tier3_bonuses": [
                {"name": b.name, "points": b.points, "details": b.details}
                for b in result.tier3_bonuses
            ],
            "tier3_bonus_reasons": result.tier3_bonus_reasons,
            "final_score": result.final_score,
            "percentile_top": result.percentile_top,
            "percentile_label": result.percentile_label,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_result(result))


if __name__ == "__main__":
    main()
