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

# High-volume road detection is done via OSM tags (highway type, lane count)
# No hardcoded road names needed - works anywhere in the US

# Coffee shop exclusions (chains to avoid)
COFFEE_EXCLUDE = [
    "starbucks",
    "dunkin",
    "dunkin' donuts",
    "dunkin donuts",
    "tim hortons",
    "mcdonald",
    "burger king",
    "wendy's",
    "panera",  # debatable but more fast-casual
]

# Coffee shop approved chains
COFFEE_APPROVED_CHAINS = [
    "blue bottle",
    "bluestone lane",
    "la colombe",
    "birch coffee",
    "joe coffee",
    "think coffee",
    "gregorys coffee",
    "gregory's coffee",
    "black fox",
    "variety coffee",
]



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
    
    def geocode(self, address: str) -> Tuple[float, float]:
        """Convert address to lat/lng coordinates"""
        url = f"{self.base_url}/geocode/json"
        params = {
            "address": address,
            "key": self.api_key
        }
        response = requests.get(url, params=params)
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
        
        response = requests.get(url, params=params)
        data = response.json()
        
        if data["status"] not in ["OK", "ZERO_RESULTS"]:
            raise ValueError(f"Places API failed: {data['status']}")
        
        return data.get("results", [])
    
    def place_details(self, place_id: str) -> Dict:
        """Get detailed information about a place"""
        url = f"{self.base_url}/place/details/json"
        params = {
            "place_id": place_id,
            "fields": "name,rating,user_ratings_total,types,formatted_address",
            "key": self.api_key
        }
        response = requests.get(url, params=params)
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
        response = requests.get(url, params=params)
        data = response.json()
        
        if data["status"] != "OK":
            raise ValueError(f"Distance Matrix API failed: {data['status']}")
        
        element = data["rows"][0]["elements"][0]
        if element["status"] != "OK":
            return 9999  # Unreachable
        
        return element["duration"]["value"] // 60  # Convert seconds to minutes
    
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
        response = requests.post(self.base_url, data={"data": query})
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
        ("Grocery", "grocery_store", "supermarket"),
        ("Coffee", "cafe", None),
        ("Park", "park", None),
        ("School", "school", "primary_school")
    ]

    for category, primary_type, secondary_type in categories:
        try:
            places = maps.places_nearby(lat, lng, primary_type, radius_meters=3000)
            if secondary_type:
                places.extend(maps.places_nearby(lat, lng, secondary_type, radius_meters=3000))

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
    lng: float
) -> Tier2Score:
    """Score park access based on rating and distance (0-10 points)"""
    try:
        # Search for parks within walking distance (~2.5km for 30 min walk)
        parks = maps.places_nearby(lat, lng, "park", radius_meters=2500)

        if not parks:
            return Tier2Score(
                name="Park access",
                points=0,
                max_points=10,
                details="No parks found within 30 min walk"
            )

        # Find best scored park
        best_score = 0
        best_park = None
        best_details = ""

        for park in parks:
            rating = park.get("rating", 0)
            park_lat = park["geometry"]["location"]["lat"]
            park_lng = park["geometry"]["location"]["lng"]
            walk_time = maps.walking_time((lat, lng), (park_lat, park_lng))

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
                best_park = park
                park_name = park.get("name", "Unknown park")
                best_details = f"{park_name} ({rating}★) — {walk_time} min walk"

        if best_score == 0:
            return Tier2Score(
                name="Park access",
                points=0,
                max_points=10,
                details="No parks found within 30 min walk"
            )

        return Tier2Score(
            name="Park access",
            points=best_score,
            max_points=10,
            details=best_details
        )

    except Exception as e:
        return Tier2Score(
            name="Park access",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        )


def is_acceptable_coffee_shop(place: Dict) -> Tuple[bool, str]:
    """Check if coffee shop meets criteria (local/approved chain, not Dunkin/Starbucks)"""
    name = place.get("name", "").lower()
    
    # Check exclusions first
    for excluded in COFFEE_EXCLUDE:
        if excluded in name:
            return False, f"Excluded chain: {place.get('name')}"
    
    # Check if it's an approved chain
    for approved in COFFEE_APPROVED_CHAINS:
        if approved in name:
            return True, f"Approved chain: {place.get('name')}"
    
    # Otherwise assume it's a local shop (acceptable)
    return True, f"Local: {place.get('name')}"


def score_coffee_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> Tier2Score:
    """Score coffee shop access based on rating and distance (0-10 points)"""
    try:
        # Search for cafes
        cafes = maps.places_nearby(lat, lng, "cafe", radius_meters=2500)

        if not cafes:
            return Tier2Score(
                name="Coffee shop access",
                points=0,
                max_points=10,
                details="No coffee shops found within 30 min walk"
            )

        # Find best scored shop (excluding chains like Starbucks/Dunkin)
        best_score = 0
        best_shop = None
        best_details = ""

        for cafe in cafes:
            # Filter out excluded chains (Starbucks, Dunkin, etc.)
            is_acceptable, _ = is_acceptable_coffee_shop(cafe)
            if not is_acceptable:
                continue

            rating = cafe.get("rating", 0)
            cafe_lat = cafe["geometry"]["location"]["lat"]
            cafe_lng = cafe["geometry"]["location"]["lng"]
            walk_time = maps.walking_time((lat, lng), (cafe_lat, cafe_lng))

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
                best_shop = cafe
                cafe_name = cafe.get("name", "Coffee shop")
                best_details = f"{cafe_name} ({rating}★) — {walk_time} min walk"

        if best_score == 0:
            return Tier2Score(
                name="Coffee shop access",
                points=0,
                max_points=10,
                details="Only chain coffee (Starbucks/Dunkin) or low-rated shops nearby"
            )

        return Tier2Score(
            name="Coffee shop access",
            points=best_score,
            max_points=10,
            details=best_details
        )

    except Exception as e:
        return Tier2Score(
            name="Coffee shop access",
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

        return Tier2Score(
            name="Transit access",
            points=points,
            max_points=10,
            details=f"{best_station.get('name')} — {best_walk_time} min walk"
        )

    except Exception as e:
        return Tier2Score(
            name="Transit access",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        )


def score_grocery_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> Tier2Score:
    """Score grocery store access based on rating and distance (0-10 points)"""
    try:
        # Search for grocery stores and supermarkets
        groceries = []

        # Try grocery_store type
        grocery_stores = maps.places_nearby(lat, lng, "grocery_store", radius_meters=2500)
        groceries.extend(grocery_stores)

        # Try supermarket type
        supermarkets = maps.places_nearby(lat, lng, "supermarket", radius_meters=2500)
        groceries.extend(supermarkets)

        if not groceries:
            return Tier2Score(
                name="Grocery access",
                points=0,
                max_points=10,
                details="No grocery stores found within 30 min walk"
            )

        # Find best scored store
        best_score = 0
        best_store = None
        best_details = ""

        for store in groceries:
            rating = store.get("rating", 0)
            store_lat = store["geometry"]["location"]["lat"]
            store_lng = store["geometry"]["location"]["lng"]
            walk_time = maps.walking_time((lat, lng), (store_lat, store_lng))

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
                best_store = store
                store_name = store.get("name", "Grocery store")
                best_details = f"{store_name} ({rating}★) — {walk_time} min walk"

        if best_score == 0:
            return Tier2Score(
                name="Grocery access",
                points=0,
                max_points=10,
                details="No grocery stores found within 30 min walk"
            )

        return Tier2Score(
            name="Grocery access",
            points=best_score,
            max_points=10,
            details=best_details
        )

    except Exception as e:
        return Tier2Score(
            name="Grocery access",
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
        result.tier2_scores.append(score_park_access(maps, lat, lng))
        result.tier2_scores.append(score_coffee_access(maps, lat, lng))
        result.tier2_scores.append(score_grocery_access(maps, lat, lng))
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
