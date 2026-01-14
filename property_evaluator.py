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
COFFEE_WALK_IDEAL_MIN = 20
COFFEE_WALK_ACCEPTABLE_MIN = 30
METRO_NORTH_WALK_IDEAL_MIN = 20
METRO_NORTH_WALK_ACCEPTABLE_MIN = 30
GROCERY_WALK_IDEAL_MIN = 15
GROCERY_WALK_ACCEPTABLE_MIN = 30
FITNESS_WALK_IDEAL_MIN = 15
FITNESS_WALK_ACCEPTABLE_MIN = 30

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
    "playground",
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
    category: str  # "Grocery", "Coffee", "Park", "School"
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


@dataclass
class ChildSchoolingSnapshot:
    childcare: List[ChildcarePlace] = field(default_factory=list)
    schools: List[SchoolPlace] = field(default_factory=list)


@dataclass
class PrimaryTransitOption:
    name: str
    mode: str
    walk_time_min: int
    drive_time_min: Optional[int] = None
    parking_available: Optional[bool] = None


@dataclass
class MajorHubAccess:
    name: str
    travel_time_min: int
    transit_mode: str


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
    tier1_checks: List[Tier1Check] = field(default_factory=list)
    tier2_scores: List[Tier2Score] = field(default_factory=list)
    tier3_bonuses: List[Tier3Bonus] = field(default_factory=list)
    passed_tier1: bool = False
    tier2_total: int = 0
    tier2_max: int = 0
    tier3_total: int = 0
    total_score: int = 0
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


# =============================================================================
# EVALUATION FUNCTIONS
# =============================================================================

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
    
    # Washer/dryer
    if listing.has_washer_dryer_in_unit is None:
        checks.append(Tier1Check(
            name="W/D in unit",
            result=CheckResult.UNKNOWN,
            details="Not specified - verify manually"
        ))
    elif listing.has_washer_dryer_in_unit:
        checks.append(Tier1Check(
            name="W/D in unit",
            result=CheckResult.PASS,
            details="Washer/dryer in unit confirmed"
        ))
    else:
        checks.append(Tier1Check(
            name="W/D in unit",
            result=CheckResult.FAIL,
            details="No washer/dryer in unit"
        ))
    
    # Central air
    if listing.has_central_air is None:
        checks.append(Tier1Check(
            name="Central air",
            result=CheckResult.UNKNOWN,
            details="Not specified - verify manually"
        ))
    elif listing.has_central_air:
        checks.append(Tier1Check(
            name="Central air",
            result=CheckResult.PASS,
            details="Central air confirmed"
        ))
    else:
        checks.append(Tier1Check(
            name="Central air",
            result=CheckResult.FAIL,
            details="No central air"
        ))
    
    # Size
    if listing.sqft is None:
        checks.append(Tier1Check(
            name="Size",
            result=CheckResult.UNKNOWN,
            details="Square footage not specified"
        ))
    elif listing.sqft >= MIN_SQFT:
        checks.append(Tier1Check(
            name="Size",
            result=CheckResult.PASS,
            details=f"{listing.sqft:,} sq ft",
            value=listing.sqft
        ))
    else:
        checks.append(Tier1Check(
            name="Size",
            result=CheckResult.FAIL,
            details=f"{listing.sqft:,} sq ft < {MIN_SQFT:,} sq ft minimum",
            value=listing.sqft
        ))
    
    # Bedrooms
    if listing.bedrooms is None:
        checks.append(Tier1Check(
            name="Bedrooms",
            result=CheckResult.UNKNOWN,
            details="Bedroom count not specified"
        ))
    elif listing.bedrooms >= MIN_BEDROOMS:
        checks.append(Tier1Check(
            name="Bedrooms",
            result=CheckResult.PASS,
            details=f"{listing.bedrooms} BR",
            value=listing.bedrooms
        ))
    else:
        checks.append(Tier1Check(
            name="Bedrooms",
            result=CheckResult.FAIL,
            details=f"{listing.bedrooms} BR < {MIN_BEDROOMS} BR minimum",
            value=listing.bedrooms
        ))
    
    # Cost (monthly - rent or estimated)
    if listing.cost is None:
        checks.append(Tier1Check(
            name="Cost",
            result=CheckResult.UNKNOWN,
            details="Monthly cost not specified"
        ))
    elif listing.cost <= COST_MAX:
        checks.append(Tier1Check(
            name="Cost",
            result=CheckResult.PASS,
            details=f"${listing.cost:,}/month",
            value=listing.cost
        ))
    else:
        checks.append(Tier1Check(
            name="Cost",
            result=CheckResult.FAIL,
            details=f"${listing.cost:,}/month > ${COST_MAX:,} max",
            value=listing.cost
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
        ("Coffee", "cafe", "bakery"),
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
                        name="No full-service grocery stores nearby",
                        rating=None,
                        walk_time_min=0,
                        place_type="none"
                    ))
                    continue

            # Special handling for Coffee - apply third-space quality filter
            if category == "Coffee":
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
                        name="No good third-space cafés nearby",
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

    childcare_types = {"preschool", "kindergarten", "child_care"}
    school_types = {"primary_school", "secondary_school", "school"}
    excluded_school_types = {"university", "college", "driving_school", "language_school"}
    search_types = list(childcare_types | school_types)

    nearby_places: Dict[str, Dict] = {}
    for place_type in search_types:
        try:
            places = maps.places_nearby(lat, lng, place_type, radius_meters=3000)
        except Exception:
            continue
        for place in places:
            place_id = place.get("place_id")
            if place_id and place_id not in nearby_places:
                nearby_places[place_id] = place

    candidates = list(nearby_places.values())
    childcare_candidates = [
        place for place in candidates
        if any(t in childcare_types for t in place.get("types", []))
    ]
    school_candidates = [
        place for place in candidates
        if any(t in school_types for t in place.get("types", []))
        and not any(t in excluded_school_types for t in place.get("types", []))
    ]

    def build_places(
        places: List[Dict],
        max_results: int,
        place_cls
    ) -> List[Any]:
        scored_places = []
        for place in places:
            p_lat = place["geometry"]["location"]["lat"]
            p_lng = place["geometry"]["location"]["lng"]
            walk_time = maps.walking_time((lat, lng), (p_lat, p_lng))
            scored_places.append((walk_time, place))

        scored_places.sort(key=lambda item: item[0])
        selected = scored_places[:max_results]
        results = []

        for walk_time, place in selected:
            website = None
            place_id = place.get("place_id")
            if place_id:
                try:
                    details = maps.place_details(place_id)
                    website = details.get("website")
                except Exception:
                    website = None

            results.append(place_cls(
                name=place.get("name", "Unknown"),
                rating=place.get("rating"),
                user_ratings_total=place.get("user_ratings_total"),
                walk_time_min=walk_time,
                website=website
            ))

        return results

    snapshot.childcare = build_places(childcare_candidates, 5, ChildcarePlace)
    snapshot.schools = build_places(school_candidates, 5, SchoolPlace)

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


def find_primary_transit(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> Optional[PrimaryTransitOption]:
    """Find the best nearby transit option with preference for rail."""
    search_types = [
        ("train_station", "Train", 1),
        ("subway_station", "Subway", 1),
        ("bus_station", "Bus", 2),
        ("transit_station", "Transit", 3),
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

    drive_time = None
    if walk_time > 30:
        drive_time = maps.driving_time(
            (lat, lng),
            (place["geometry"]["location"]["lat"], place["geometry"]["location"]["lng"])
        )

    parking_available = get_parking_availability(maps, place.get("place_id"))

    return PrimaryTransitOption(
        name=place.get("name", "Unknown"),
        mode=mode,
        walk_time_min=walk_time,
        drive_time_min=drive_time if drive_time and drive_time != 9999 else None,
        parking_available=parking_available
    )


def miles_between(maps: GoogleMapsClient, origin: Tuple[float, float], dest: Tuple[float, float]) -> float:
    return maps.distance_feet(origin, dest) / 5280


def determine_major_hub(
    maps: GoogleMapsClient,
    lat: float,
    lng: float,
    primary_mode: Optional[str]
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

    travel_time = maps.transit_time((lat, lng), hub_coords)
    transit_mode = "transit"
    if primary_mode in {"Train", "Subway"}:
        transit_mode = "train"
    elif primary_mode == "Bus":
        transit_mode = "bus"

    return MajorHubAccess(
        name=hub_name,
        travel_time_min=travel_time if travel_time != 9999 else 0,
        transit_mode=transit_mode
    )


def get_urban_access_profile(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> UrbanAccessProfile:
    primary_transit = find_primary_transit(maps, lat, lng)
    major_hub = determine_major_hub(maps, lat, lng, primary_transit.mode if primary_transit else None)

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
    if any(keyword in name_lower for keyword in EXCLUDED_PRIMARY_KEYWORDS):
        return True
    if any(space_type in EXCLUDED_PRIMARY_TYPES for space_type in types):
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
    green_space_evaluation: Optional[GreenSpaceEvaluation] = None
) -> Tier2Score:
    """Score primary green escape access (0-10 points)"""
    try:
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


def score_coffee_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> Tier2Score:
    """Score coffee shop access based on third-space quality (0-10 points)"""
    try:
        # Search for cafes, coffee shops, and bakeries
        all_places = []
        all_places.extend(maps.places_nearby(lat, lng, "cafe", radius_meters=2500))
        all_places.extend(maps.places_nearby(lat, lng, "bakery", radius_meters=2500))

        if not all_places:
            return Tier2Score(
                name="Coffee",
                points=0,
                max_points=10,
                details="No high-quality coffee shops within walking distance"
            )

        # Filter for third-space quality
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
                name="Coffee",
                points=0,
                max_points=10,
                details="No high-quality coffee shops within walking distance"
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
        name = best_place.get("name", "Coffee shop")
        rating = best_place.get("rating", 0)
        reviews = best_place.get("user_ratings_total", 0)
        details = f"{name} ({rating}★, {reviews} reviews) — {best_walk_time} min walk"

        return Tier2Score(
            name="Coffee",
            points=best_score,
            max_points=10,
            details=details
        )

    except Exception as e:
        return Tier2Score(
            name="Coffee",
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
    """Score public transit access (0-10 points)"""
    def service_quality_label(review_count: int) -> str:
        if review_count > 5000:
            return "High frequency"
        if review_count >= 1000:
            return "Medium frequency"
        if review_count >= 200:
            return "Low frequency"
        return "Very low frequency"

    def network_type_label(name: str, types: Optional[List[str]]) -> str:
        name_lower = name.lower()
        types_lower = [t.lower() for t in (types or [])]

        if (
            any(keyword in name_lower for keyword in ["subway", "metro", "underground"])
            or "subway_station" in types_lower
        ):
            return "Rapid transit"
        if (
            any(keyword in name_lower for keyword in ["amtrak", "metro-north", "bart", "caltrain"])
            or "train_station" in types_lower
            or "light_rail_station" in types_lower
        ):
            return "Regional rail"
        if "bus" in name_lower or "bus_station" in types_lower:
            return "Bus"

        if "transit_station" in types_lower:
            return "Bus"

        return "Regional rail"

    def urban_access_score(network_type: str, walk_time: int, service_quality: str) -> int:
        base_scores = {
            "Rapid transit": 6,
            "Regional rail": 5,
            "Bus": 3,
        }
        score = base_scores.get(network_type, 3)

        if walk_time <= 10:
            score += 2
        elif walk_time <= 20:
            score += 1

        if service_quality == "High frequency":
            score += 2
        elif service_quality == "Medium frequency":
            score += 1

        return min(score, 10)

    try:
        # Search for transit stations (generic)
        stations = []

        # Search for transit_station type
        transit_stations = maps.places_nearby(
            lat, lng,
            "transit_station",
            radius_meters=3000
        )
        stations.extend(transit_stations)

        # Also search for train_station type
        train_stations = maps.places_nearby(
            lat, lng,
            "train_station",
            radius_meters=3000
        )
        stations.extend(train_stations)

        if not stations:
            return Tier2Score(
                name="Transit access",
                points=0,
                max_points=10,
                details="No transit stations found within 30 min walk"
            )

        # Filter by keywords if provided (e.g., ["Metro-North"] for Westchester)
        if transit_keywords:
            filtered = []
            for station in stations:
                name = station.get("name", "").lower()
                if any(keyword.lower() in name for keyword in transit_keywords):
                    filtered.append(station)
            if filtered:
                stations = filtered

        # Find closest station
        best_walk_time = 9999
        best_station = None

        for station in stations:
            station_lat = station["geometry"]["location"]["lat"]
            station_lng = station["geometry"]["location"]["lng"]
            walk_time = maps.walking_time((lat, lng), (station_lat, station_lng))

            if walk_time < best_walk_time:
                best_walk_time = walk_time
                best_station = station

        if best_station is None:
            return Tier2Score(
                name="Transit access",
                points=0,
                max_points=10,
                details="No transit stations found within 30 min walk"
            )

        # Score based on walk time
        if best_walk_time <= 20:
            points = 10
        elif best_walk_time <= 30:
            points = 5
        else:
            points = 0

        station_name = best_station.get("name", "Transit station")
        reviews = best_station.get("user_ratings_total", 0)
        service_quality = service_quality_label(reviews)
        network_type = network_type_label(station_name, best_station.get("types", []))
        access_score = urban_access_score(network_type, best_walk_time, service_quality)

        return Tier2Score(
            name="Transit access",
            points=points,
            max_points=10,
            details=(
                f"{station_name} — {best_walk_time} min walk | "
                f"Service: {service_quality} | "
                f"Network: {network_type} | "
                f"Urban Access Score: {access_score}/10"
            )
        )

    except Exception as e:
        return Tier2Score(
            name="Transit access",
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
        # Search for full-service grocery stores
        all_stores = []
        all_stores.extend(maps.places_nearby(lat, lng, "supermarket", radius_meters=2500))
        all_stores.extend(maps.places_nearby(lat, lng, "grocery_store", radius_meters=2500))

        if not all_stores:
            return Tier2Score(
                name="Provisioning",
                points=0,
                max_points=10,
                details="No full-service grocery stores within walking distance"
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
                details="No full-service grocery stores within walking distance"
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
        name = best_store.get("name", "Grocery store")
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

    # ===================
    # NEIGHBORHOOD SNAPSHOT
    # ===================

    result.neighborhood_snapshot = get_neighborhood_snapshot(maps, lat, lng)
    result.child_schooling_snapshot = get_child_and_schooling_snapshot(maps, lat, lng)
    result.urban_access = get_urban_access_profile(maps, lat, lng)
    result.green_space_evaluation = evaluate_green_spaces(maps, lat, lng)

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
    fail_count = sum(1 for c in result.tier1_checks if c.result == CheckResult.FAIL)
    result.passed_tier1 = (fail_count == 0)
    
    # ===================
    # TIER 2 SCORING
    # ===================
    
    if result.passed_tier1:
        result.tier2_scores.append(
            score_park_access(maps, lat, lng, result.green_space_evaluation)
        )
        result.tier2_scores.append(score_coffee_access(maps, lat, lng))
        result.tier2_scores.append(score_provisioning_access(maps, lat, lng))
        result.tier2_scores.append(score_fitness_access(maps, lat, lng))
        result.tier2_scores.append(score_cost(listing.cost))
        result.tier2_scores.append(score_transit_access(maps, lat, lng))

        result.tier2_total = sum(s.points for s in result.tier2_scores)
        result.tier2_max = sum(s.max_points for s in result.tier2_scores)
    
    # ===================
    # TIER 3 BONUSES
    # ===================
    
    if result.passed_tier1:
        result.tier3_bonuses = calculate_bonuses(listing)
        result.tier3_total = sum(b.points for b in result.tier3_bonuses)
    
    # ===================
    # TOTAL SCORE
    # ===================
    
    result.total_score = result.tier2_total + result.tier3_total
    
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
    lines.append(f"\nTIER 2 SCORE: {result.tier2_total}/{result.tier2_max}")
    for score in result.tier2_scores:
        lines.append(f"  - {score.name}: {score.points} pts — {score.details}")
    
    # Tier 3
    if result.tier3_bonuses:
        lines.append(f"\nTIER 3 BONUS: +{result.tier3_total} pts")
        for bonus in result.tier3_bonuses:
            lines.append(f"  - {bonus.name}: +{bonus.points} — {bonus.details}")
    else:
        lines.append("\nTIER 3 BONUS: +0 pts")
    
    # Total
    lines.append(f"\n{'=' * 70}")
    lines.append(f"TOTAL SCORE: {result.total_score}")
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
                "schools": [
                    {
                        "name": p.name,
                        "rating": p.rating,
                        "user_ratings_total": p.user_ratings_total,
                        "walk_time_min": p.walk_time_min,
                        "website": p.website
                    }
                    for p in (result.child_schooling_snapshot.schools if result.child_schooling_snapshot else [])
                ]
            },
            "urban_access": {
                "primary_transit": {
                    "name": result.urban_access.primary_transit.name,
                    "mode": result.urban_access.primary_transit.mode,
                    "walk_time_min": result.urban_access.primary_transit.walk_time_min,
                    "drive_time_min": result.urban_access.primary_transit.drive_time_min,
                    "parking_available": result.urban_access.primary_transit.parking_available,
                } if result.urban_access and result.urban_access.primary_transit else None,
                "major_hub": {
                    "name": result.urban_access.major_hub.name,
                    "travel_time_min": result.urban_access.major_hub.travel_time_min,
                    "transit_mode": result.urban_access.major_hub.transit_mode,
                } if result.urban_access and result.urban_access.major_hub else None,
            },
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
            "passed_tier1": result.passed_tier1,
            "tier1_checks": [
                {"name": c.name, "result": c.result.value, "details": c.details}
                for c in result.tier1_checks
            ],
            "tier2_score": result.tier2_total,
            "tier2_max": result.tier2_max,
            "tier2_scores": [
                {"name": s.name, "points": s.points, "max": s.max_points, "details": s.details}
                for s in result.tier2_scores
            ],
            "tier3_bonus": result.tier3_total,
            "tier3_bonuses": [
                {"name": b.name, "points": b.points, "details": b.details}
                for b in result.tier3_bonuses
            ],
            "total_score": result.total_score,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_result(result))


if __name__ == "__main__":
    main()
