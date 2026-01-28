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
import argparse
import re
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict, Any
from enum import Enum
import requests
from urllib.parse import quote
from dotenv import load_dotenv
from green_space import (
    evaluate_green_escape,
    green_escape_to_dict,
    green_escape_to_legacy_format,
    GreenEscapeEvaluation,
)

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

# Health & Safety Thresholds (in feet)
GAS_STATION_MIN_DISTANCE_FT = 500
HIGHWAY_MIN_DISTANCE_FT = 500
HIGH_VOLUME_ROAD_MIN_DISTANCE_FT = 500

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
# DATA CLASSES
# =============================================================================

class CheckResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
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

    # Keep these from main
    final_score: int = 0
    percentile_top: int = 0
    percentile_label: str = ""
    notes: List[str] = field(default_factory=list)


# =============================================================================
# API CLIENTS
# =============================================================================

class GoogleMapsClient:
    """Client for Google Maps APIs"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://maps.googleapis.com/maps/api"
        self.session = requests.Session()
        self.session.trust_env = False
    
    def geocode(self, address: str) -> Tuple[float, float]:
        """Convert address to lat/lng coordinates"""
        url = f"{self.base_url}/geocode/json"
        params = {
            "address": address,
            "key": self.api_key
        }
        response = self.session.get(url, params=params)
        data = response.json()
        
        if data["status"] != "OK":
            raise ValueError(f"Geocoding failed: {data['status']}")
        
        location = data["results"][0]["geometry"]["location"]
        return location["lat"], location["lng"]
    
    def places_nearby(
        self, 
        lat: float, 
        lng: float, 
        place_type: str,
        radius_meters: int = 2000,
        keyword: Optional[str] = None
    ) -> List[Dict]:
        """Search for places near a location"""
        url = f"{self.base_url}/place/nearbysearch/json"
        params = {
            "location": f"{lat},{lng}",
            "radius": radius_meters,
            "type": place_type,
            "key": self.api_key
        }
        if keyword:
            params["keyword"] = keyword
        
        response = self.session.get(url, params=params)
        data = response.json()
        
        if data["status"] not in ["OK", "ZERO_RESULTS"]:
            raise ValueError(f"Places API failed: {data['status']}")
        
        return data.get("results", [])
    
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
        response = self.session.get(url, params=params)
        data = response.json()
        
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
        response = self.session.get(url, params=params)
        data = response.json()
        
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
        response = self.session.get(url, params=params)
        data = response.json()

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
        response = self.session.get(url, params=params)
        data = response.json()

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
        response = self.session.get(url, params=params)
        data = response.json()

        if data["status"] not in ["OK", "ZERO_RESULTS"]:
            raise ValueError(f"Text Search API failed: {data['status']}")

        return data.get("results", [])
    
    def distance_feet(self, origin: Tuple[float, float], dest: Tuple[float, float]) -> int:
        """Calculate straight-line distance in feet"""
        # Haversine formula
        R = 20902231  # Earth's radius in feet
        lat1, lon1 = math.radians(origin[0]), math.radians(origin[1])
        lat2, lon2 = math.radians(dest[0]), math.radians(dest[1])
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        return int(R * c)


class OverpassClient:
    """Client for OpenStreetMap Overpass API - for road data"""
    
    def __init__(self):
        self.base_url = "https://overpass-api.de/api/interpreter"
        self.session = requests.Session()
        self.session.trust_env = False
    
    def get_nearby_roads(self, lat: float, lng: float, radius_meters: int = 200) -> List[Dict]:
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
        response = self.session.post(self.base_url, data={"data": query})
        data = response.json()
        
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
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
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
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
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
        return Tier1Check(
            name="Gas station",
            result=CheckResult.UNKNOWN,
            details=f"Error checking: {str(e)}"
        )


def check_highways(
    maps: GoogleMapsClient,
    overpass: OverpassClient,
    lat: float, 
    lng: float
) -> Tier1Check:
    """Check distance to highways and major parkways"""
    try:
        # Use Overpass to find major roads nearby
        roads = overpass.get_nearby_roads(lat, lng, radius_meters=200)
        
        # Filter for highways (motorway, trunk)
        highways_nearby = [
            r for r in roads 
            if r["highway_type"] in ["motorway", "trunk"]
        ]
        
        if not highways_nearby:
            return Tier1Check(
                name="Highway",
                result=CheckResult.PASS,
                details="No highways within 500 feet",
                value=None
            )
        
        # Found highways nearby - this is a fail
        highway_names = [r["name"] or r["ref"] or "Unnamed highway" for r in highways_nearby]
        return Tier1Check(
            name="Highway",
            result=CheckResult.FAIL,
            details=f"TOO CLOSE to: {', '.join(set(highway_names))}",
            value=0
        )
        
    except Exception as e:
        return Tier1Check(
            name="Highway",
            result=CheckResult.UNKNOWN,
            details=f"Error checking: {str(e)}"
        )


def check_high_volume_roads(
    overpass: OverpassClient,
    lat: float,
    lng: float
) -> Tier1Check:
    """Check distance to high-volume roads (4+ lanes or primary/secondary classification)"""
    try:
        roads = overpass.get_nearby_roads(lat, lng, radius_meters=200)

        problem_roads = []
        for road in roads:
            # Check lane count (if available)
            lanes = road.get("lanes", "")
            has_many_lanes = False
            if lanes:
                try:
                    if int(lanes) >= 4:
                        has_many_lanes = True
                except ValueError:
                    pass

            # Primary/secondary roads are typically high-volume
            is_primary = road["highway_type"] in ["primary", "secondary"]

            if has_many_lanes or is_primary:
                problem_roads.append(road.get("name") or road.get("ref") or "Unnamed road")
        
        if not problem_roads:
            return Tier1Check(
                name="High-volume road",
                result=CheckResult.PASS,
                details="No high-volume roads within 500 feet",
                value=None
            )
        
        return Tier1Check(
            name="High-volume road",
            result=CheckResult.FAIL,
            details=f"TOO CLOSE to: {', '.join(set(problem_roads))}",
            value=0
        )
        
    except Exception as e:
        return Tier1Check(
            name="High-volume road",
            result=CheckResult.UNKNOWN,
            details=f"Error checking: {str(e)}"
        )


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
                # Find closest
                best = None
                best_time = 9999
                for place in places:
                    p_lat = place["geometry"]["location"]["lat"]
                    p_lng = place["geometry"]["location"]["lng"]
                    walk_time = maps.walking_time((lat, lng), (p_lat, p_lng))
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
            response = requests.get(website, timeout=6)
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

    candidates: List[Tuple[int, int, Dict, str]] = []
    for place_type, mode, priority in search_types:
        try:
            places = maps.places_nearby(lat, lng, place_type, radius_meters=5000)
        except Exception:
            continue
        for place in places:
            place_lat = place["geometry"]["location"]["lat"]
            place_lng = place["geometry"]["location"]["lng"]
            walk_time = maps.walking_time((lat, lng), (place_lat, place_lng))
            candidates.append((priority, walk_time, place, mode))

    if not candidates:
        return None

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
        major_hub=major_hub
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

    green_spaces: List[GreenSpace] = []
    for entry in places_by_id.values():
        place = entry["place"]
        place_id = place.get("place_id")
        place_lat = place["geometry"]["location"]["lat"]
        place_lng = place["geometry"]["location"]["lng"]
        walk_time = maps.walking_time((lat, lng), (place_lat, place_lng))
        if walk_time > GREEN_SPACE_WALK_MAX_MIN or walk_time == 9999:
            continue

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
) -> Tier2Score:
    """Score third-place access based on third-place quality (0-10 points)"""
    try:
        # Search for cafes, coffee shops, and bakeries
        all_places = []
        all_places.extend(maps.places_nearby(lat, lng, "cafe", radius_meters=2500))
        all_places.extend(maps.places_nearby(lat, lng, "bakery", radius_meters=2500))

        if not all_places:
            return Tier2Score(
                name="Third Place",
                points=0,
                max_points=10,
                details="No high-quality third places within walking distance"
            )

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
            return Tier2Score(
                name="Third Place",
                points=0,
                max_points=10,
                details="No high-quality third places within walking distance"
            )

        # Find best scoring place
        best_score = 0
        best_place = None
        best_walk_time = 9999

        for place in eligible_places:
            place_lat = place["geometry"]["location"]["lat"]
            place_lng = place["geometry"]["location"]["lng"]
            walk_time = maps.walking_time((lat, lng), (place_lat, place_lng))

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

        # Format details
        name = best_place.get("name", "Third place")
        rating = best_place.get("rating", 0)
        reviews = best_place.get("user_ratings_total", 0)
        details = f"{name} ({rating}★, {reviews} reviews) — {best_walk_time} min walk"

        return Tier2Score(
            name="Third Place",
            points=best_score,
            max_points=10,
            details=details
        )

    except Exception as e:
        return Tier2Score(
            name="Third Place",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        )


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
    transit_keywords: Optional[List[str]] = None
) -> Tier2Score:
    """Score urban access via rail transit (0-10 points)."""
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
        primary_transit = find_primary_transit(maps, lat, lng)
        if not primary_transit:
            return Tier2Score(
                name="Urban access",
                points=0,
                max_points=10,
                details="No rail transit stations found within reach"
            )

        major_hub = determine_major_hub(
            maps,
            lat,
            lng,
            primary_transit.mode,
            transit_origin=(primary_transit.lat, primary_transit.lng),
        )

        walk_points = walkability_points(primary_transit.walk_time_min)
        frequency_class = primary_transit.frequency_class or "Very low frequency"
        frequency_points = {
            "High frequency": 3,
            "Medium frequency": 2,
            "Low frequency": 1,
            "Very low frequency": 0,
        }.get(frequency_class, 0)
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
                f"Frequency: {frequency_class} | "
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
) -> Tier2Score:
    """Score household provisioning store access (0-10 points)"""
    try:
        # Search for full-service provisioning stores
        all_stores = []
        all_stores.extend(maps.places_nearby(lat, lng, "supermarket", radius_meters=2500))
        all_stores.extend(maps.places_nearby(lat, lng, "grocery_store", radius_meters=2500))

        if not all_stores:
            return Tier2Score(
                name="Provisioning",
                points=0,
                max_points=10,
                details="No full-service provisioning options within walking distance"
            )

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
            return Tier2Score(
                name="Provisioning",
                points=0,
                max_points=10,
                details="No full-service provisioning options within walking distance"
            )

        # Find best scoring store
        best_score = 0
        best_store = None
        best_walk_time = 9999

        for store in eligible_stores:
            store_lat = store["geometry"]["location"]["lat"]
            store_lng = store["geometry"]["location"]["lng"]
            walk_time = maps.walking_time((lat, lng), (store_lat, store_lng))

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

        # Format details
        name = best_store.get("name", "Provisioning store")
        rating = best_store.get("rating", 0)
        reviews = best_store.get("user_ratings_total", 0)
        details = f"{name} ({rating}★, {reviews} reviews) — {best_walk_time} min walk"

        return Tier2Score(
            name="Provisioning",
            points=best_score,
            max_points=10,
            details=details
        )

    except Exception as e:
        return Tier2Score(
            name="Provisioning",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        )


def score_fitness_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> Tier2Score:
    """Score fitness/wellness facility access based on rating and distance (0-10 points)"""
    try:
        # Search for gyms and fitness centers
        fitness_places = []

        # Try gym type
        gyms = maps.places_nearby(lat, lng, "gym", radius_meters=2500)
        fitness_places.extend(gyms)

        # Try searching for yoga studios using keyword
        # Note: Google Places API may not have "yoga_studio" as a separate type,
        # so we search with keyword instead
        yoga = maps.places_nearby(lat, lng, "gym", radius_meters=2500, keyword="yoga")
        fitness_places.extend(yoga)

        if not fitness_places:
            return Tier2Score(
                name="Fitness access",
                points=0,
                max_points=10,
                details="No gyms or fitness centers found within 30 min walk"
            )

        # Find best scored facility
        best_score = 0
        best_facility = None
        best_details = ""

        for facility in fitness_places:
            rating = facility.get("rating", 0)
            facility_lat = facility["geometry"]["location"]["lat"]
            facility_lng = facility["geometry"]["location"]["lng"]
            walk_time = maps.walking_time((lat, lng), (facility_lat, facility_lng))

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

        if best_score == 0:
            return Tier2Score(
                name="Fitness access",
                points=0,
                max_points=10,
                details="No gyms or fitness centers found within 30 min walk"
            )

        return Tier2Score(
            name="Fitness access",
            points=best_score,
            max_points=10,
            details=best_details
        )

    except Exception as e:
        return Tier2Score(
            name="Fitness access",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        )


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


def estimate_percentile(final_score: int) -> Tuple[int, str]:
    """Estimate percentile ranking for a final score (0-100)."""
    bounded_score = max(0, min(100, final_score))
    percentile_map = [
        (90, 5),
        (85, 10),
        (80, 15),
        (75, 20),
        (70, 25),
        (65, 30),
        (60, 35),
        (55, 40),
        (50, 50),
        (0, 60),
    ]

    for threshold, percentile in percentile_map:
        if bounded_score >= threshold:
            return percentile, f"Top {percentile}% nationally for families"

    return 60, "Top 60% nationally for families"
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

def evaluate_property(
    listing: PropertyListing,
    api_key: str
) -> EvaluationResult:
    """Run full evaluation on a property listing"""
    
    maps = GoogleMapsClient(api_key)
    overpass = OverpassClient()
    
    # Geocode the address
    lat, lng = maps.geocode(listing.address)

    result = EvaluationResult(
        listing=listing,
        lat=lat,
        lng=lng
    )

    bike_data = get_bike_score(listing.address, lat, lng)
    result.bike_score = bike_data.get("bike_score")
    result.bike_rating = bike_data.get("bike_rating")
    result.bike_metadata = bike_data.get("bike_metadata")

    # ===================
    # NEIGHBORHOOD SNAPSHOT
    # ===================

    result.neighborhood_snapshot = get_neighborhood_snapshot(maps, lat, lng)
    result.child_schooling_snapshot = get_child_and_schooling_snapshot(maps, lat, lng)
    result.urban_access = get_urban_access_profile(maps, lat, lng)
    result.green_space_evaluation = evaluate_green_spaces(maps, lat, lng)
    result.green_escape_evaluation = evaluate_green_escape(maps, lat, lng)
    result.transit_score = get_transit_score(listing.address, lat, lng)
    result.walk_scores = get_walk_scores(listing.address, lat, lng)

    # ===================
    # TIER 1 CHECKS
    # ===================
    
    # Location-based checks
    result.tier1_checks.append(check_gas_stations(maps, lat, lng))
    result.tier1_checks.append(check_highways(maps, overpass, lat, lng))
    result.tier1_checks.append(check_high_volume_roads(overpass, lat, lng))
    
    # Listing-based checks
    result.tier1_checks.extend(check_listing_requirements(listing))
    
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
            score_park_access(
                maps, lat, lng,
                green_space_evaluation=result.green_space_evaluation,
                green_escape_evaluation=result.green_escape_evaluation,
            )
        )
        result.tier2_scores.append(score_third_place_access(maps, lat, lng))
        result.tier2_scores.append(score_provisioning_access(maps, lat, lng))
        result.tier2_scores.append(score_fitness_access(maps, lat, lng))
        result.tier2_scores.append(score_cost(listing.cost))
        result.tier2_scores.append(score_transit_access(maps, lat, lng))

        result.tier2_total = sum(s.points for s in result.tier2_scores)
        result.tier2_max = sum(s.max_points for s in result.tier2_scores)
        if result.tier2_max > 0:
            result.tier2_normalized = round((result.tier2_total / result.tier2_max) * 100)
        else:
            result.tier2_normalized = 0
    
    # ===================
    # TIER 3 BONUSES
    # ===================
    
    if result.passed_tier1:
        result.tier3_bonuses = calculate_bonuses(listing)
        result.tier3_total = sum(b.points for b in result.tier3_bonuses)
        result.tier3_bonus_reasons = calculate_bonus_reasons(listing)
    
    # ===================
    # FINAL SCORE + PERCENTILE
    # ===================
    
    if result.tier2_max > 0:
        result.tier2_normalized = round((result.tier2_total / result.tier2_max) * 100)
    else:
        result.tier2_normalized = 0

    result.final_score = min(100, result.tier2_normalized + result.tier3_total)
    result.percentile_top, result.percentile_label = estimate_percentile(result.final_score)
    
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
        symbol = "✓" if check.result == CheckResult.PASS else "✗" if check.result == CheckResult.FAIL else "?"
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
    lines.append(f"Tier 3 Bonus: +{result.tier3_total} pts")
    lines.append(f"Tier 3 Bonus: +{result.tier3_total} (already capped at 100)")
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
            "green_space_evaluation": (
                green_escape_to_legacy_format(result.green_escape_evaluation)
                if result.green_escape_evaluation
                else {
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
                    "green_spaces": [],
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
                }
            ),
            "green_escape": (
                green_escape_to_dict(result.green_escape_evaluation)
                if result.green_escape_evaluation else None
            ),
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
