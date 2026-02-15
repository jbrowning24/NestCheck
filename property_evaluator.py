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
from typing import Optional, List, Tuple, Dict, Any, Callable, Union
from enum import Enum
import requests

logger = logging.getLogger(__name__)
from concurrent.futures import ThreadPoolExecutor, as_completed
from nc_trace import get_trace, set_trace
from urllib.parse import quote
from dotenv import load_dotenv
from green_space import (
    GreenEscapeEvaluation,
    evaluate_green_escape,
)
from road_noise import assess_road_noise, RoadNoiseAssessment
from weather import get_weather_summary, WeatherSummary
from scoring_config import (
    SCORING_MODEL,
    DimensionConfig,
    DimensionResult,
    apply_piecewise,
    apply_quality_multiplier,
)

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================

# Feature flags
ENABLE_SCHOOLS = os.environ.get("ENABLE_SCHOOLS", "false").lower() == "true"

# Sentinel for a failed shared Overpass fetch — check functions detect this
# and return UNKNOWN immediately instead of retrying a known-down endpoint.
_OVERPASS_FAILED = object()

# Health & Safety Thresholds (in feet) — sourced from scoring_config
GAS_STATION_MIN_DISTANCE_FT = SCORING_MODEL.tier1.gas_station_ft
HIGHWAY_MIN_DISTANCE_FT = SCORING_MODEL.tier1.highway_ft
HIGH_VOLUME_ROAD_MIN_DISTANCE_FT = SCORING_MODEL.tier1.high_volume_road_ft

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
    distance_ft: Optional[float] = None


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
class CheckPresentation:
    """Presentation layer for a Tier 1 check result.

    Separates evaluation logic from user-facing narrative.
    Raw check data is preserved; presentation fields add context.
    """
    check_id: str                   # Slugified name, e.g., "highway", "gas_station"
    display_name: str               # User-facing name, e.g., "Highway Proximity"
    result_type: str                # CONFIRMED_ISSUE | CLEAR | VERIFICATION_NEEDED | NOTED_TRADEOFF | LISTING_GAP
    severity: str                   # HIGH | MEDIUM | LOW | NONE
    category: str                   # SAFETY | LIFESTYLE
    blocks_scoring: bool            # True only for required checks that FAIL
    headline: str                   # One-line summary for the user
    explanation: str                # Why this matters (plain language)
    user_action: Optional[str]      # What the user should do, or None
    raw_result: str                 # Original: PASS / FAIL / UNKNOWN
    raw_details: str                # Original details string
    raw_value: Optional[Any] = None # Original numeric value if any


# =============================================================================
# CHECK PRESENTATION — content dictionaries and transformation
# =============================================================================

CHECK_DISPLAY_NAMES = {
    "Gas station": "Gas Station Proximity",
    "Highway": "Highway Proximity",
    "High-volume road": "High-Traffic Road Proximity",
    "W/D in unit": "Washer/Dryer",
    "Central air": "Central Air Conditioning",
    "Size": "Square Footage",
    "Bedrooms": "Bedroom Count",
    "Cost": "Monthly Cost",
}

CHECK_EXPLANATIONS = {
    # Safety entries removed — now generated dynamically by _proximity_explanation()
    "W/D in unit": "In-unit laundry is a strong quality-of-life factor for families, reducing time spent on a recurring chore.",
    "Central air": "Central air conditioning affects comfort and indoor air quality, particularly during summer months.",
    "Size": "Square footage helps assess whether the space meets your household's needs.",
    "Bedrooms": "Bedroom count is a core factor for families evaluating fit.",
    "Cost": "Monthly cost is needed to assess affordability relative to your budget.",
}

_ACTION_HINTS: Dict[Tuple[str, str], Optional[str]] = {
    # Safety entries removed — proximity explanations are self-contained.
    # Lifestyle entries can be added here as needed.
}

SAFETY_CHECKS = {"Gas station", "Highway", "High-volume road"}
LISTING_CHECKS = {"W/D in unit", "Central air", "Size", "Bedrooms", "Cost"}

# Distance thresholds (in feet) for proximity-band presentation.
# "very_close" = strongly emphasised, "notable" = moderate emphasis.
# Values beyond "notable" (or PASS results) are treated as NEUTRAL.
PROXIMITY_THRESHOLDS = {
    "Gas station":      {"very_close": 200, "notable": 500},
    "Highway":          {"very_close": 500, "notable": 1000},
    "High-volume road": {"very_close": 200, "notable": 500},
}

# Natural prose labels for synthesis sentences, keyed by check_id.
_SYNTHESIS_LABELS = {
    "gas_station": "a gas station",
    "highway": "a highway",
    "high-volume_road": "a high-traffic road",
}


def _classify_check(check: Tier1Check) -> Tuple[str, str]:
    """Classify a Tier1Check into (result_type, severity).

    Categories:
      CLEAR              — check passed, no issue
      CONFIRMED_ISSUE    — required check failed (health/safety concern)
      VERIFICATION_NEEDED — required check returned UNKNOWN (API error etc.)
      NOTED_TRADEOFF     — non-required check explicitly failed (known negative)
      LISTING_GAP        — non-required check is UNKNOWN (data not provided)
    """
    if check.result == CheckResult.PASS:
        return ("CLEAR", "NONE")

    if check.result == CheckResult.FAIL:
        if check.required:
            return ("CONFIRMED_ISSUE", "HIGH")
        else:
            # Listing explicitly states a negative value (e.g. "No central air",
            # "1,200 sqft < 1,700 minimum").  This is a known compromise, not a
            # missing data point.
            return ("NOTED_TRADEOFF", "LOW")

    # UNKNOWN
    if check.name in SAFETY_CHECKS:
        return ("VERIFICATION_NEEDED", "MEDIUM")
    else:
        return ("LISTING_GAP", "NONE")


def _proximity_band(check: Tier1Check) -> str:
    """Assign a visual-emphasis band for proximity-based checks.

    Returns one of: "VERY_CLOSE", "NOTABLE", "NEUTRAL".
    Non-proximity checks (lifestyle) always return "NEUTRAL".
    """
    thresholds = PROXIMITY_THRESHOLDS.get(check.name)
    if thresholds is None:
        return "NEUTRAL"

    if check.result == CheckResult.PASS:
        return "NEUTRAL"

    if check.result == CheckResult.UNKNOWN:
        return "NOTABLE"

    # FAIL — use distance_ft when available, conservative default otherwise
    if check.distance_ft is not None:
        if check.distance_ft < thresholds["very_close"]:
            return "VERY_CLOSE"
        elif check.distance_ft < thresholds["notable"]:
            return "NOTABLE"
        return "NEUTRAL"

    # No distance available (highway / high-volume road radius query) — Decision 2
    return "VERY_CLOSE"


def _proximity_explanation(check: Tier1Check, band: str) -> str:
    """Generate a factual, band-aware explanation for a proximity check.

    Used only for SAFETY checks.  *band* must be one of
    "VERY_CLOSE", "NOTABLE", "NEUTRAL", or "UNKNOWN" (when
    check.result is UNKNOWN).  Lifestyle checks continue to use
    the static CHECK_EXPLANATIONS dict.
    """
    display = CHECK_DISPLAY_NAMES.get(check.name, check.name)
    dist = int(check.distance_ft) if check.distance_ft is not None else None

    # ── UNKNOWN — honest acknowledgment; satellite link is in the template ──
    if check.result == CheckResult.UNKNOWN:
        if check.name == "Gas station":
            return (
                "Nearby business data was unavailable, so we couldn't verify "
                "gas station proximity."
            )
        return (
            f"Automated road data for this area was incomplete, so we couldn't "
            f"verify {check.name.lower()} proximity."
        )

    # ── Gas station ──
    if check.name == "Gas station":
        if band == "VERY_CLOSE":
            if dist is not None:
                return (
                    f"This address is {dist:,} ft from a gas station. "
                    "At this distance, fuel odor may be noticeable and "
                    "studies have measured elevated benzene levels."
                )
            return (
                "A gas station is very close to this address. "
                "At this distance, fuel odor may be noticeable and "
                "studies have measured elevated benzene levels."
            )
        if band == "NOTABLE":
            if dist is not None:
                return (
                    f"A gas station is {dist:,} ft from this address. "
                    "At this distance, air quality impact is typically minimal "
                    "but may be detectable in certain wind conditions."
                )
            return (
                "A gas station is near this address. "
                "At this distance, air quality impact is typically minimal "
                "but may be detectable in certain wind conditions."
            )
        # NEUTRAL / PASS
        if dist is not None:
            return (
                f"Nearest gas station is {dist:,} ft away "
                "\u2014 outside the typical impact zone."
            )
        return ""

    # ── Highway ──
    if check.name == "Highway":
        roads = check.details.replace("TOO CLOSE to: ", "")
        if band == "VERY_CLOSE":
            if dist is not None:
                return (
                    f"A highway is {dist:,} ft from this address. "
                    "At this distance, road noise and particulate matter "
                    "(PM2.5) levels are typically elevated."
                )
            return (
                f"{roads} detected near this address. "
                "At this distance, road noise and particulate matter "
                "(PM2.5) levels are typically elevated."
            )
        if band == "NOTABLE":
            if dist is not None:
                return (
                    f"A highway is {dist:,} ft from this address. "
                    "Some road noise may be audible, especially during "
                    "peak traffic hours."
                )
            return (
                f"{roads} detected within the search area. "
                "Some road noise may be audible, especially during "
                "peak traffic hours."
            )
        # NEUTRAL / PASS
        if dist is not None:
            return (
                f"Nearest highway is {dist:,} ft away "
                "\u2014 outside the typical noise and air quality impact zone."
            )
        return ""

    # ── High-volume road ──
    if check.name == "High-volume road":
        roads = check.details.replace("TOO CLOSE to: ", "")
        if band == "VERY_CLOSE":
            if dist is not None:
                return (
                    f"A high-traffic road is {dist:,} ft from this address. "
                    "At this distance, road noise and reduced air quality "
                    "are typically noticeable."
                )
            return (
                f"{roads} detected near this address. "
                "At this distance, road noise and reduced air quality "
                "are typically noticeable."
            )
        if band == "NOTABLE":
            if dist is not None:
                return (
                    f"A high-traffic road is {dist:,} ft from this address. "
                    "Some road noise may be audible, especially during "
                    "peak traffic hours."
                )
            return (
                f"{roads} detected within the search area. "
                "Some road noise may be audible, especially during "
                "peak traffic hours."
            )
        # NEUTRAL / PASS
        if dist is not None:
            return (
                f"Nearest high-traffic road is {dist:,} ft away "
                "\u2014 outside the typical noise and air quality impact zone."
            )
        return ""

    return ""


def _generate_headline(check: Tier1Check, proximity_band: Optional[str] = None) -> str:
    """Generate a user-facing one-line headline.

    Safety checks use factual distance framing when *proximity_band* is
    provided.  Lifestyle checks are unchanged.
    """
    display = CHECK_DISPLAY_NAMES.get(check.name, check.name)

    # ── Safety checks: factual proximity headlines ──
    if proximity_band is not None and check.name in SAFETY_CHECKS:
        if check.result == CheckResult.PASS:
            return f"{display} — Clear"

        if check.result == CheckResult.UNKNOWN:
            return f"{display} — Unverified"

        # FAIL
        if check.distance_ft is not None:
            return f"{display} — {int(check.distance_ft):,} ft"
        return f"{display} — Nearby"

    # ── Lifestyle / fallback (existing behaviour) ──
    if check.result == CheckResult.PASS:
        return check.details

    if check.result == CheckResult.FAIL:
        if check.required:
            if check.name == "High-volume road":
                roads = check.details.replace("TOO CLOSE to: ", "")
                return f"High-traffic roads nearby: {roads}"
            return check.details.replace("TOO CLOSE to: ", "Nearby: ")
        else:
            return check.details

    # UNKNOWN
    if check.name in SAFETY_CHECKS:
        return "Could not be verified automatically"
    else:
        return "Not specified in listing"


def present_checks(tier1_checks: List[Tier1Check]) -> List[dict]:
    """Transform raw Tier1Check results into presentation dicts.

    This is the boundary between evaluation logic and user-facing narrative.
    Returns dicts (not dataclasses) for direct JSON serialization.
    """
    presented = []
    for check in tier1_checks:
        result_type, severity = _classify_check(check)
        raw_result_str = check.result.value if hasattr(check.result, 'value') else str(check.result)
        category = "SAFETY" if check.name in SAFETY_CHECKS else "LIFESTYLE"
        band = _proximity_band(check) if category == "SAFETY" else None

        # Safety checks: dynamic explanation; lifestyle: static dict + action hints
        if category == "SAFETY":
            explanation = _proximity_explanation(check, band=band) if band else ""
            user_action = None  # explanations are now self-contained
        else:
            explanation = CHECK_EXPLANATIONS.get(check.name, "")
            action_key = (check.name, raw_result_str)
            user_action = _ACTION_HINTS.get(action_key)
            if user_action is None and result_type == "LISTING_GAP":
                user_action = "Check the listing or contact the landlord/agent."
            elif user_action is None and result_type == "NOTED_TRADEOFF":
                user_action = "This is a known trade-off based on listing data. Decide if it's acceptable for your needs."

        presented.append({
            "check_id": check.name.lower().replace(" ", "_").replace("/", ""),
            "display_name": CHECK_DISPLAY_NAMES.get(check.name, check.name),
            "result_type": result_type,
            "severity": severity,
            "category": category,
            "proximity_band": band,
            "blocks_scoring": (check.required and check.result == CheckResult.FAIL),
            "headline": _generate_headline(check, proximity_band=band),
            "explanation": explanation,
            "user_action": user_action,
            "raw_result": raw_result_str,
            "raw_details": check.details,
            "raw_value": check.value if hasattr(check, 'value') else None,
        })
    return presented


def proximity_synthesis(presented_checks: List[dict]) -> str | None:
    """Synthesize a section-level insight for the Proximity & Environment section.

    Takes the full presented_checks list, filters to SAFETY category,
    and returns a plain-English paragraph based on the combination of
    result types across all safety checks.

    Returns None if no safety checks are present (old snapshots without
    presented_checks data).
    """
    safety = [c for c in presented_checks if c.get("category") == "SAFETY"]
    if not safety:
        return None

    clear = [c for c in safety if c["result_type"] == "CLEAR"]
    confirmed = [c for c in safety if c["result_type"] == "CONFIRMED_ISSUE"]
    unverified = [c for c in safety if c["result_type"] == "VERIFICATION_NEEDED"]

    def _label(check: dict) -> str:
        """Return a natural prose label for a check (e.g. 'a highway')."""
        return _SYNTHESIS_LABELS.get(check["check_id"], check["display_name"].lower())

    def _names(checks: list) -> str:
        """Join labels in natural English (e.g. 'a highway and a gas station')."""
        if not checks:
            return ""
        names = [_label(c) for c in checks]
        if len(names) == 1:
            return names[0]
        return f"{names[0]} and {names[1]}" if len(names) == 2 else \
            ", ".join(names[:-1]) + f", and {names[-1]}"

    # ── All clear ──
    if len(clear) == len(safety):
        return "No environmental concerns detected near this address."

    # ── No confirmed issues, some unverified ──
    if not confirmed and unverified:
        if len(unverified) == 1:
            return (
                f"No confirmed concerns. {unverified[0]['display_name']} could not "
                "be verified automatically — worth a quick check on satellite view."
            )
        if len(unverified) == 2:
            return (
                f"No confirmed concerns, but {_names(unverified)} could not be "
                "verified automatically — worth checking on satellite view."
            )
        # All three unverified
        return (
            "None of the proximity checks could be verified automatically. "
            "We recommend reviewing satellite imagery for this address."
        )

    # ── One or more confirmed issues ──
    concern_names = _names(confirmed)
    if not unverified:
        # Confirmed issues only, remaining are clear
        if len(clear) > 0:
            return (
                f"This address is close to {concern_names}. "
                f"Remaining checks are clear."
            )
        return f"This address is close to {concern_names}."

    # Confirmed + unverified mix
    return (
        f"This address is close to {concern_names}. "
        f"{_names(unverified).capitalize()} could not be verified automatically."
    )


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
    # Raw Places API responses keyed by category, for downstream Tier 2 reuse
    raw_places: Dict[str, List[Dict]] = field(default_factory=dict)


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
    # Accessibility attributes (NES-31)
    # True = confirmed accessible, False = confirmed inaccessible, None = unverified
    wheelchair_accessible_entrance: Optional[bool] = None
    elevator_available: Optional[bool] = None


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
class EmergencyService:
    """A nearby emergency service station (fire or police).

    Informational only — not scored.  Displayed to give users a sense
    of emergency-response proximity and infrastructure reliability.
    """
    name: str               # Station name (fallback: "Fire Station" / "Police Station")
    service_type: str        # "fire" or "police"
    drive_time_min: int      # Driving time from station to property, in minutes
    lat: float
    lng: float


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
    green_escape_evaluation: Optional[GreenEscapeEvaluation] = None
    road_noise_assessment: Optional[RoadNoiseAssessment] = None
    transit_score: Optional[Dict[str, Any]] = None
    walk_scores: Dict[str, Optional[Any]] = field(default_factory=dict)
    bike_score: Optional[int] = None
    bike_rating: Optional[str] = None
    bike_metadata: Optional[Dict[str, Any]] = None

    tier1_checks: List[Tier1Check] = field(default_factory=list)
    tier2_scores: List[Union[Tier2Score, DimensionResult]] = field(default_factory=list)
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
    notes: List[str] = field(default_factory=list)

    # Scoring model version used to produce this evaluation
    model_version: str = ""

    # Neighborhood places surfaced from scoring (Phase 3)
    neighborhood_places: Optional[Dict[str, list]] = None

    # Server-rendered neighborhood map (base64 PNG)
    neighborhood_map_b64: Optional[str] = None

    # Nearby emergency services — informational, not scored (NES-50)
    emergency_services: Optional[List[EmergencyService]] = None

    # Weather climate normals — informational, not scored (NES-32)
    weather_summary: Optional[WeatherSummary] = None


# =============================================================================
# API CLIENTS
# =============================================================================

# Timeout in seconds for external API HTTP requests (Maps, Overpass).
# Avoids indefinite hangs when the network or API is slow. If you see repeated
# timeouts, they may be quota-related (e.g. Google Maps API rate or usage limits).
API_REQUEST_TIMEOUT = 25

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

    def geocode(self, address: str, place_id: Optional[str] = None) -> Tuple[float, float]:
        """Convert address to lat/lng coordinates.

        If place_id is provided, attempts geocoding by place_id first (saves
        one address-based geocode call). Falls back to address-based geocoding
        if the place_id lookup fails.
        """
        url = f"{self.base_url}/geocode/json"

        if place_id:
            params = {"place_id": place_id, "key": self.api_key}
            data = self._traced_get("geocode", url, params)
            if data["status"] == "OK" and data.get("results"):
                location = data["results"][0]["geometry"]["location"]
                return location["lat"], location["lng"]
            logger.warning(
                "Geocode by place_id=%s failed (%s), falling back to address",
                place_id, data.get("status"),
            )

        params = {"address": address, "key": self.api_key}
        data = self._traced_get("geocode", url, params)

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

        data = self._traced_get("places_nearby", url, params)

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

    # Google Distance Matrix allows up to 25 origins × 25 destinations per request.
    # Use one origin and up to 25 destinations per call to batch walking-time requests.
    DISTANCE_MATRIX_MAX_DESTINATIONS = 25

    def walking_times_batch(
        self,
        origin: Tuple[float, float],
        destinations: List[Tuple[float, float]],
    ) -> List[int]:
        """
        Get walking times in minutes from one origin to many destinations.
        Batches into requests of up to 25 destinations per call (API limit).
        Returns one value per destination; use 9999 for unreachable.
        """
        if not destinations:
            return []
        results: List[int] = []
        for i in range(0, len(destinations), self.DISTANCE_MATRIX_MAX_DESTINATIONS):
            chunk = destinations[i : i + self.DISTANCE_MATRIX_MAX_DESTINATIONS]
            dest_param = "|".join(f"{d[0]},{d[1]}" for d in chunk)
            url = f"{self.base_url}/distancematrix/json"
            params = {
                "origins": f"{origin[0]},{origin[1]}",
                "destinations": dest_param,
                "mode": "walking",
                "key": self.api_key,
            }
            data = self._traced_get("walking_times_batch", url, params)
            if data["status"] != "OK":
                raise ValueError(f"Distance Matrix API failed: {data['status']}")
            row = data["rows"][0]
            for j, elem in enumerate(row["elements"]):
                if elem["status"] != "OK":
                    results.append(9999)
                else:
                    results.append(elem["duration"]["value"] // 60)
        return results

    def driving_times_batch(
        self,
        origin: Tuple[float, float],
        destinations: List[Tuple[float, float]],
    ) -> List[int]:
        """
        Get driving times in minutes from one origin to many destinations.
        Batches into requests of up to 25 destinations per call (API limit).
        Returns one value per destination; use 9999 for unreachable.
        """
        if not destinations:
            return []
        results: List[int] = []
        for i in range(0, len(destinations), self.DISTANCE_MATRIX_MAX_DESTINATIONS):
            chunk = destinations[i : i + self.DISTANCE_MATRIX_MAX_DESTINATIONS]
            dest_param = "|".join(f"{d[0]},{d[1]}" for d in chunk)
            url = f"{self.base_url}/distancematrix/json"
            params = {
                "origins": f"{origin[0]},{origin[1]}",
                "destinations": dest_param,
                "mode": "driving",
                "key": self.api_key,
            }
            data = self._traced_get("driving_times_batch", url, params)
            if data["status"] != "OK":
                raise ValueError(f"Distance Matrix API failed: {data['status']}")
            row = data["rows"][0]
            for j, elem in enumerate(row["elements"]):
                if elem["status"] != "OK":
                    results.append(9999)
                else:
                    results.append(elem["duration"]["value"] // 60)
        return results

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


def _walking_times_batch(
    maps: "GoogleMapsClient",
    origin: Tuple[float, float],
    destinations: List[Tuple[float, float]],
) -> List[int]:
    """
    Get walking times in minutes from origin to each destination.
    Uses Distance Matrix batch API when available (up to 25 per request).
    """
    if not destinations:
        return []
    if hasattr(maps, "walking_times_batch"):
        return maps.walking_times_batch(origin, destinations)
    return [maps.walking_time(origin, d) for d in destinations]


class OverpassClient:
    """Client for OpenStreetMap Overpass API - for road data.

    Uses a two-level cache:
      1. SQLite overpass_cache table (7-day TTL) — persistent across evals
      2. HTTP fallback when cache misses
    Cache failures never break an evaluation.
    """

    DEFAULT_TIMEOUT = 25

    def __init__(self):
        self.base_url = "https://overpass-api.de/api/interpreter"
        self.session = requests.Session()
        self.session.trust_env = False

    def _traced_post(self, endpoint_name: str, url: str, data_payload: dict) -> dict:
        """POST request with automatic trace recording."""
        t0 = time.time()
        response = self.session.post(url, data=data_payload, timeout=self.DEFAULT_TIMEOUT)
        elapsed_ms = int((time.time() - t0) * 1000)
        # Record trace before raise_for_status so failed calls are visible
        trace = get_trace()
        if trace:
            trace.record_api_call(
                service="overpass",
                endpoint=endpoint_name,
                elapsed_ms=elapsed_ms,
                status_code=response.status_code,
            )
        response.raise_for_status()
        data = response.json()
        return data

    def get_nearby_roads(self, lat: float, lng: float, radius_meters: int = 200) -> List[Dict]:
        """Get roads within radius of a point.

        Checks SQLite persistent cache before making an HTTP request.
        Stores successful responses in the cache. Failures are not cached.
        """
        query = f"""
        [out:json][timeout:25];
        (
          way["highway"~"motorway|trunk|primary|secondary"](around:{radius_meters},{lat},{lng});
        );
        out body;
        >;
        out skel qt;
        """

        # Check SQLite persistent cache
        from models import overpass_cache_key, get_overpass_cache, set_overpass_cache
        db_cache_key = overpass_cache_key(query)
        try:
            cached_json = get_overpass_cache(db_cache_key)
            if cached_json is not None:
                import json as _json
                data = _json.loads(cached_json)
                return self._parse_roads(data)
        except Exception:
            logger.warning("Overpass SQLite cache read failed in get_nearby_roads, falling through to HTTP", exc_info=True)

        data = self._traced_post("get_nearby_roads", self.base_url, {"data": query})

        # Store successful response in cache
        try:
            import json as _json
            set_overpass_cache(db_cache_key, _json.dumps(data))
        except Exception:
            logger.warning("Overpass SQLite cache write failed in get_nearby_roads", exc_info=True)

        return self._parse_roads(data)

    @staticmethod
    def _parse_roads(data: dict) -> List[Dict]:
        """Extract road info from Overpass response data."""
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

    def get_nearby_emergency_services(
        self, lat: float, lng: float, radius_meters: int = 5000
    ) -> List[Dict]:
        """Find fire and police stations within *radius_meters* of a point.

        Queries both node and way elements so we catch stations mapped as
        a point or as a building outline.  ``out center;`` gives us the
        centroid for ways so we always have usable coordinates.

        Returns a list of dicts with keys: name, type ("fire"/"police"),
        lat, lng.  Uses the same SQLite cache pattern as get_nearby_roads().
        """
        query = f"""
        [out:json][timeout:25];
        (
          node["amenity"="fire_station"](around:{radius_meters},{lat},{lng});
          way["amenity"="fire_station"](around:{radius_meters},{lat},{lng});
          node["amenity"="police"](around:{radius_meters},{lat},{lng});
          way["amenity"="police"](around:{radius_meters},{lat},{lng});
        );
        out center;
        """

        # SQLite persistent cache (same pattern as get_nearby_roads)
        from models import overpass_cache_key, get_overpass_cache, set_overpass_cache
        db_cache_key = overpass_cache_key(query)
        try:
            cached_json = get_overpass_cache(db_cache_key)
            if cached_json is not None:
                import json as _json
                data = _json.loads(cached_json)
                return self._parse_emergency_services(data)
        except Exception:
            logger.warning(
                "Overpass SQLite cache read failed in get_nearby_emergency_services, "
                "falling through to HTTP", exc_info=True,
            )

        data = self._traced_post(
            "get_nearby_emergency_services", self.base_url, {"data": query}
        )

        try:
            import json as _json
            set_overpass_cache(db_cache_key, _json.dumps(data))
        except Exception:
            logger.warning(
                "Overpass SQLite cache write failed in get_nearby_emergency_services",
                exc_info=True,
            )

        return self._parse_emergency_services(data)

    @staticmethod
    def _parse_emergency_services(data: dict) -> List[Dict]:
        """Extract emergency service stations from an Overpass response.

        Handles both node elements (lat/lon on the element itself) and way
        elements (lat/lon in the ``center`` sub-object added by ``out center``).
        """
        _AMENITY_TO_TYPE = {"fire_station": "fire", "police": "police"}
        _TYPE_FALLBACK_NAMES = {"fire": "Fire Station", "police": "Police Station"}

        stations: List[Dict] = []
        for element in data.get("elements", []):
            tags = element.get("tags", {})
            amenity = tags.get("amenity", "")
            svc_type = _AMENITY_TO_TYPE.get(amenity)
            if svc_type is None:
                continue

            # Coordinates: nodes carry lat/lon directly; ways carry center.
            if element["type"] == "node":
                s_lat = element.get("lat")
                s_lng = element.get("lon")
            elif "center" in element:
                s_lat = element["center"].get("lat")
                s_lng = element["center"].get("lon")
            else:
                continue  # way without center data — skip

            if s_lat is None or s_lng is None:
                continue

            name = tags.get("name") or ""
            if not name:
                name = _TYPE_FALLBACK_NAMES[svc_type]
                logger.debug(
                    "Unnamed %s station at (%.5f, %.5f) — using fallback name",
                    svc_type, s_lat, s_lng,
                )

            stations.append({
                "name": name,
                "type": svc_type,
                "lat": s_lat,
                "lng": s_lng,
            })

        return stations

    def has_nearby_elevators(self, lat: float, lng: float, radius_meters: int = 150) -> Optional[bool]:
        """Check for elevator nodes near a transit station (NES-31).

        Queries Overpass for ``node["elevator"="yes"]`` within *radius_meters*
        of the given point.  Returns True if at least one elevator node is
        found, None otherwise (unverified — absence of OSM data does not
        confirm absence of elevators).
        """
        query = f"""
        [out:json][timeout:25];
        (
          node["elevator"="yes"](around:{radius_meters},{lat},{lng});
        );
        out count;
        """

        # SQLite persistent cache (same pattern as get_nearby_roads)
        from models import overpass_cache_key, get_overpass_cache, set_overpass_cache
        db_cache_key = overpass_cache_key(query)
        try:
            cached_json = get_overpass_cache(db_cache_key)
            if cached_json is not None:
                import json as _json
                data = _json.loads(cached_json)
                return self._parse_elevator_count(data)
        except Exception:
            logger.warning(
                "Overpass SQLite cache read failed in has_nearby_elevators, "
                "falling through to HTTP", exc_info=True,
            )

        data = self._traced_post(
            "has_nearby_elevators", self.base_url, {"data": query}
        )

        try:
            import json as _json
            set_overpass_cache(db_cache_key, _json.dumps(data))
        except Exception:
            logger.warning(
                "Overpass SQLite cache write failed in has_nearby_elevators",
                exc_info=True,
            )

        return self._parse_elevator_count(data)

    @staticmethod
    def _parse_elevator_count(data: dict) -> Optional[bool]:
        """Extract elevator count from an ``out count`` Overpass response.

        Returns True if elevators found, None if zero or unparseable
        (unverified — not confirmed absent).
        """
        elements = data.get("elements") or []
        if not elements:
            return None
        count = elements[0].get("tags", {}).get("total", 0)
        return True if int(count) > 0 else None


def get_emergency_services(
    maps: GoogleMapsClient,
    overpass: OverpassClient,
    lat: float,
    lng: float,
) -> Optional[List[EmergencyService]]:
    """Find the nearest fire and police stations and their drive times.

    Queries Overpass for stations within 5 km, picks the closest of each
    type by straight-line distance, then fetches driving times via the
    Distance Matrix API.  Returns 0–2 EmergencyService objects.

    Returns [] when no stations are found, None on failure (so the
    template can distinguish "searched, found nothing" from "lookup failed").
    """
    try:
        raw_stations = overpass.get_nearby_emergency_services(lat, lng)
        if not raw_stations:
            return []

        # Pick nearest 1 of each type by haversine distance
        origin = (lat, lng)
        nearest: Dict[str, Dict] = {}  # type -> station dict
        nearest_dist: Dict[str, float] = {}
        for station in raw_stations:
            stype = station["type"]
            dist = maps.distance_feet(origin, (station["lat"], station["lng"]))
            if stype not in nearest or dist < nearest_dist[stype]:
                nearest[stype] = station
                nearest_dist[stype] = dist

        selected = list(nearest.values())  # 1-2 stations

        # Batch drive-time lookup (single API call for 1-2 destinations)
        destinations = [(s["lat"], s["lng"]) for s in selected]
        drive_times = maps.driving_times_batch(origin, destinations)

        results: List[EmergencyService] = []
        for station, drive_min in zip(selected, drive_times):
            results.append(EmergencyService(
                name=station["name"],
                service_type=station["type"],
                drive_time_min=drive_min,
                lat=station["lat"],
                lng=station["lng"],
            ))

        return results

    except Exception:
        logger.warning(
            "Emergency services lookup failed; continuing without", exc_info=True
        )
        return None  # None = failure (section hidden); [] = searched, found nothing


def _coerce_score(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# =============================================================================
# EVALUATION FUNCTIONS
# =============================================================================

def get_all_walk_scores(address: str, lat: float, lon: float) -> Dict[str, Any]:
    """Fetch walk, transit, and bike scores from Walk Score API in a single call.

    Requests transit=1&bike=1 so one HTTP request returns all three scores,
    plus nearby transit lines and bike metadata.
    """
    api_key = os.environ.get("WALKSCORE_API_KEY")
    default_response: Dict[str, Any] = {
        "walk_score": None,
        "walk_description": None,
        "transit_score": None,
        "transit_description": None,
        "transit_rating": None,
        "transit_summary": None,
        "nearby_transit_lines": None,
        "bike_score": None,
        "bike_description": None,
        "bike_rating": None,
        "bike_metadata": None,
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
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        _elapsed = int((time.time() - _t0) * 1000)
        _trace = get_trace()
        if _trace:
            _trace.record_api_call(
                service="walkscore", endpoint="get_all_walk_scores",
                elapsed_ms=_elapsed, status_code=response.status_code,
                provider_status=str(data.get("status", "")),
            )
    except (requests.RequestException, ValueError):
        return default_response

    if not isinstance(data, dict) or data.get("status") != 1:
        return default_response

    # --- Walk score ---
    walk_score = _coerce_score(data.get("walkscore"))
    walk_description = data.get("description")

    # --- Transit score + nearby lines ---
    transit_data = data.get("transit") or {}
    transit_score = _coerce_score(transit_data.get("score"))
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
        nearby_transit_lines.append({
            "name": name,
            "type": route_type_label,
            "distance_miles": distance,
        })

    # --- Bike score + metadata ---
    bike_data = data.get("bike") or {}
    bike_score_val = _coerce_score(bike_data.get("score"))
    bike_description = bike_data.get("description")
    bike_metadata = {
        k: v for k, v in bike_data.items() if k not in {"score", "description"}
    } or None

    return {
        "walk_score": walk_score,
        "walk_description": walk_description,
        "transit_score": transit_score,
        "transit_description": transit_description,
        "transit_rating": transit_description,
        "transit_summary": transit_summary,
        "nearby_transit_lines": nearby_transit_lines or None,
        "bike_score": bike_score_val,
        "bike_description": bike_description,
        "bike_rating": bike_description,
        "bike_metadata": bike_metadata,
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
                value=min_distance,
                distance_ft=min_distance,
            )
        else:
            return Tier1Check(
                name="Gas station",
                result=CheckResult.FAIL,
                details=f"TOO CLOSE: {closest_name} ({min_distance:,} ft < {GAS_STATION_MIN_DISTANCE_FT} ft)",
                value=min_distance,
                distance_ft=min_distance,
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
    lng: float,
    roads_data: Optional[List[Dict]] = None,
) -> Tier1Check:
    """Check distance to highways and major parkways"""
    if roads_data is _OVERPASS_FAILED:
        return Tier1Check(
            name="Highway",
            result=CheckResult.UNKNOWN,
            details="Overpass API unavailable",
        )
    try:
        # Use Overpass to find major roads nearby
        roads = roads_data if roads_data is not None else overpass.get_nearby_roads(lat, lng, radius_meters=200)
        
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
    lng: float,
    roads_data: Optional[List[Dict]] = None,
) -> Tier1Check:
    """Check distance to high-volume roads (4+ lanes or primary/secondary classification)"""
    if roads_data is _OVERPASS_FAILED:
        return Tier1Check(
            name="High-volume road",
            result=CheckResult.UNKNOWN,
            details="Overpass API unavailable",
        )
    try:
        roads = roads_data if roads_data is not None else overpass.get_nearby_roads(lat, lng, radius_meters=200)

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
                places = _dedupe_by_place_id(places)

            # Stash raw Places API results for Tier 2 reuse
            snapshot.raw_places[category] = list(places)

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
                # Find closest (batch walk times)
                destinations = [
                    (p["geometry"]["location"]["lat"], p["geometry"]["location"]["lng"])
                    for p in places
                ]
                walk_times = _walking_times_batch(maps, (lat, lng), destinations)
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
            logger.debug("fetch_website_text failed for %s", website, exc_info=True)
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
        if not places:
            return []
        destinations = [
            (p["geometry"]["location"]["lat"], p["geometry"]["location"]["lng"])
            for p in places
        ]
        walk_times = _walking_times_batch(maps, (lat, lng), destinations)
        scored_places = [
            (wt, place)
            for place, wt in zip(places, walk_times)
            if wt <= SCHOOL_WALK_MAX_MIN
        ]
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

    # Batch walk times for all school candidates
    school_list = list(school_candidates.values())
    if school_list:
        school_dests = [
            (p["geometry"]["location"]["lat"], p["geometry"]["location"]["lng"])
            for p in school_list
        ]
        school_walk_times = _walking_times_batch(maps, (lat, lng), school_dests)
    else:
        school_walk_times = []

    for i, place in enumerate(school_list):
        details = fetch_place_details(place)
        website = details.get("website")
        website_text = fetch_website_text(website)
        if not is_public_school(place, website_text):
            continue
        level = infer_school_level(place, website_text)
        if not level:
            continue
        walk_time = school_walk_times[i] if i < len(school_walk_times) else 9999
        if walk_time > SCHOOL_WALK_MAX_MIN:
            continue
        if level == "K-12":
            for level_name in schools_by_level.keys():
                maybe_set_school(level_name, place, walk_time, website)
        else:
            maybe_set_school(level, place, walk_time, website)

    snapshot.schools_by_level = schools_by_level
    return snapshot


def get_station_details(
    maps: GoogleMapsClient, place_id: Optional[str]
) -> Dict[str, Optional[bool]]:
    """Fetch parking and accessibility attributes for a transit station.

    Single place_details call that extracts:
      - parking_available: whether the station has parking
      - wheelchair_accessible_entrance: step-free entrance (NES-31)

    Returns dict with both keys; values are True/False/None (unverified).
    """
    empty = {"parking_available": None, "wheelchair_accessible_entrance": None}
    if not place_id:
        return empty
    try:
        details = maps.place_details(
            place_id,
            fields=[
                "name",
                "types",
                "parking_options",
                "wheelchair_accessible_parking",
                "wheelchair_accessible_entrance",
            ]
        )
    except Exception:
        return empty

    # --- Parking availability ---
    parking_available = None
    parking_options = details.get("parking_options", {})
    if isinstance(parking_options, dict):
        for value in parking_options.values():
            if value is True:
                parking_available = True
                break
        if parking_available is None and parking_options:
            parking_available = False

    if parking_available is None:
        wheelchair_parking = details.get("wheelchair_accessible_parking")
        if wheelchair_parking is True:
            parking_available = True
        elif wheelchair_parking is False:
            parking_available = False

    # --- Wheelchair-accessible entrance (NES-31) ---
    wae = details.get("wheelchair_accessible_entrance")
    wheelchair_entrance = True if wae is True else (False if wae is False else None)

    return {
        "parking_available": parking_available,
        "wheelchair_accessible_entrance": wheelchair_entrance,
    }


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
    lng: float,
    overpass: Optional[OverpassClient] = None,
) -> Optional[PrimaryTransitOption]:
    """Find the best nearby transit option with preference for rail."""
    search_types = [
        ("train_station", "Train", 1),
        ("subway_station", "Subway", 1),
        ("light_rail_station", "Light Rail", 1),
    ]

    # Collect all transit places then batch walk times
    candidates_meta: List[Tuple[int, Dict, str]] = []  # (priority, place, mode)
    for place_type, mode, priority in search_types:
        try:
            places = maps.places_nearby(lat, lng, place_type, radius_meters=5000)
        except Exception:
            continue
        for place in places:
            candidates_meta.append((priority, place, mode))

    if not candidates_meta:
        return None
    destinations = [
        (p["geometry"]["location"]["lat"], p["geometry"]["location"]["lng"])
        for _, p, _ in candidates_meta
    ]
    walk_times = _walking_times_batch(maps, (lat, lng), destinations)
    candidates: List[Tuple[int, int, Dict, str]] = [
        (priority, walk_times[i], place, mode)
        for i, (priority, place, mode) in enumerate(candidates_meta)
    ]

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

    station_info = get_station_details(maps, place.get("place_id"))
    user_ratings_total = place.get("user_ratings_total")

    # Elevator check via Overpass — 150m around the station (NES-31)
    elevator_available = None
    if overpass:
        try:
            elevator_available = overpass.has_nearby_elevators(place_lat, place_lng)
        except Exception:
            logger.warning("Overpass elevator check failed for %s", place.get("name"), exc_info=True)

    return PrimaryTransitOption(
        name=place.get("name", "Unknown"),
        mode=mode,
        lat=place_lat,
        lng=place_lng,
        walk_time_min=walk_time,
        drive_time_min=drive_time if drive_time and drive_time != 9999 else None,
        parking_available=station_info["parking_available"],
        user_ratings_total=user_ratings_total,
        frequency_class=(
            transit_frequency_class(user_ratings_total)
            if isinstance(user_ratings_total, int)
            else None
        ),
        wheelchair_accessible_entrance=station_info["wheelchair_accessible_entrance"],
        elevator_available=elevator_available,
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
    lng: float,
    overpass: Optional[OverpassClient] = None,
) -> UrbanAccessProfile:
    primary_transit = find_primary_transit(maps, lat, lng, overpass=overpass)
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


def _dedupe_by_place_id(places: List[Dict]) -> List[Dict]:
    """Remove duplicate places by place_id, preserving first occurrence."""
    seen: set = set()
    unique: List[Dict] = []
    for p in places:
        pid = p.get("place_id")
        if pid and pid not in seen:
            seen.add(pid)
            unique.append(p)
    return unique


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
    # Compute walk time for each node (batched)
    if not all_nodes:
        node_walk_times = []
    else:
        node_dests = [
            (n["geometry"]["location"]["lat"], n["geometry"]["location"]["lng"])
            for n in all_nodes
        ]
        try:
            node_times = _walking_times_batch(maps, (lat, lng), node_dests)
        except Exception:
            node_times = [9999] * len(all_nodes)
        node_walk_times = [(node_times[i], all_nodes[i]) for i in range(len(all_nodes))]

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
    green_escape_evaluation: Optional[GreenEscapeEvaluation] = None,
) -> Tier2Score:
    """Score primary green escape access (0-10 points).

    Uses the green_space.py engine's GreenEscapeEvaluation.
    """
    try:
        if green_escape_evaluation is None or green_escape_evaluation.best_daily_park is None:
            return Tier2Score(
                name="Parks & Green Space",
                points=0,
                max_points=10,
                details="No green spaces found within walking distance",
            )

        best = green_escape_evaluation.best_daily_park
        points = round(best.daily_walk_value)
        rating_str = f"{best.rating:.1f}★" if best.rating else "unrated"
        details = (
            f"{best.name} ({rating_str}, {best.user_ratings_total} reviews) "
            f"— {best.walk_time_min} min walk — Daily Value {best.daily_walk_value:.1f}/10 "
            f"[{best.criteria_status}]"
        )
        return Tier2Score(
            name="Parks & Green Space",
            points=points,
            max_points=10,
            details=details,
        )

    except Exception as e:
        return Tier2Score(
            name="Parks & Green Space",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        )


def score_third_place_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float,
    pre_fetched_places: Optional[List[Dict]] = None,
) -> Tuple[DimensionResult, List[Dict]]:
    """Score third-place access using piecewise linear curve (0-10 points).

    Returns (DimensionResult, places_list) where places_list contains up to 5
    eligible places with name, rating, review_count, walk_time_min, lat, lng.
    """
    _dim_name = "Coffee & Social Spots"
    _cfg = SCORING_MODEL.coffee

    def _empty(details: str) -> Tuple[DimensionResult, List[Dict]]:
        return (DimensionResult(
            score=0.0, max_score=10.0, name=_dim_name,
            details=details, scoring_inputs={},
            model_version=SCORING_MODEL.version,
        ), [])

    try:
        # Reuse pre-fetched places from neighborhood snapshot if available
        if pre_fetched_places is not None:
            all_places = list(pre_fetched_places)
        else:
            all_places = []
            all_places.extend(maps.places_nearby(lat, lng, "cafe", radius_meters=2500))
            all_places.extend(maps.places_nearby(lat, lng, "bakery", radius_meters=2500))
            all_places = _dedupe_by_place_id(all_places)

        if not all_places:
            return _empty("No high-quality third places within walking distance")

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
            return _empty("No high-quality third places within walking distance")

        # Find best scoring place (batch walk times)
        destinations = [
            (p["geometry"]["location"]["lat"], p["geometry"]["location"]["lng"])
            for p in eligible_places
        ]
        walk_times = _walking_times_batch(maps, (lat, lng), destinations)
        best_score = 0.0
        best_place = None
        best_walk_time = 9999

        # Collect all scored places for neighborhood display
        scored_places = []

        for place, walk_time in zip(eligible_places, walk_times):
            raw = apply_piecewise(_cfg.knots, walk_time)
            score = max(_cfg.floor, raw)

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
        # Sort cards by distance for display (closest first)
        neighborhood_places.sort(key=lambda p: p.get("walk_time_min") or 9999)

        # Format details
        name = best_place.get("name", "Third place")
        rating = best_place.get("rating", 0)
        reviews = best_place.get("user_ratings_total", 0)
        details = f"{name} ({rating}★, {reviews} reviews) — {best_walk_time} min walk"

        return (DimensionResult(
            score=best_score,
            max_score=10.0,
            name=_dim_name,
            details=details,
            scoring_inputs={"walk_time_min": best_walk_time},
            model_version=SCORING_MODEL.version,
        ), neighborhood_places)

    except Exception as e:
        return _empty(f"Error: {str(e)}")


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
    primary_transit: Optional[PrimaryTransitOption] = None,
    major_hub: Optional[MajorHubAccess] = None,
) -> Tier2Score:
    """Score urban access via transit (0-10 points).

    When pre-computed primary_transit and major_hub are supplied, they are
    reused instead of re-fetching from the API.  When a pre-computed
    TransitAccessResult is supplied its score is used directly for the
    frequency component.

    If no rail station is found (primary_transit is None), falls back to
    bus/transit data from transit_access with a reduced ceiling (max 7/10).
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
        if primary_transit is None:
            primary_transit = find_primary_transit(maps, lat, lng)
        if not primary_transit:
            # Fall back to bus/transit data from evaluate_transit_access.
            # Bus-only areas score on a reduced scale (max 7/10) since bus
            # service is less reliable than rail for daily commuting.
            if transit_access and transit_access.primary_stop:
                bus_walk_pts = 0
                if transit_access.walk_minutes is not None:
                    if transit_access.walk_minutes <= 5:
                        bus_walk_pts = 3
                    elif transit_access.walk_minutes <= 10:
                        bus_walk_pts = 2
                    elif transit_access.walk_minutes <= 15:
                        bus_walk_pts = 1

                bus_freq_pts = {
                    "High": 2, "Medium": 1,
                }.get(transit_access.frequency_bucket, 0)

                hub_time = major_hub.travel_time_min if major_hub else None
                bus_hub_pts = 0
                if hub_time and hub_time > 0:
                    if hub_time <= 30:
                        bus_hub_pts = 2
                    elif hub_time <= 60:
                        bus_hub_pts = 1

                total = min(7, bus_walk_pts + bus_freq_pts + bus_hub_pts)

                freq_label = f"{transit_access.frequency_bucket} frequency"
                hub_note = "Hub travel time unavailable"
                if major_hub and hub_time and hub_time > 0:
                    hub_note = f"{major_hub.name} — {hub_time} min"

                details = f"Bus stop: {transit_access.primary_stop}"
                if transit_access.walk_minutes is not None:
                    details += f" — {transit_access.walk_minutes} min walk"
                details += f" | Service: {freq_label} | Hub: {hub_note}"

                return Tier2Score(
                    name="Getting Around",
                    points=total,
                    max_points=10,
                    details=details,
                )

            return Tier2Score(
                name="Getting Around",
                points=0,
                max_points=10,
                details="No transit stations found within reach",
            )

        if major_hub is None:
            major_hub = determine_major_hub(
                maps,
                lat,
                lng,
                primary_transit.mode,
                transit_origin=(primary_transit.lat, primary_transit.lng),
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
            name="Getting Around",
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
            name="Getting Around",
            points=0,
            max_points=10,
            details=f"Error: {str(e)}"
        )


def score_road_noise(
    road_noise_assessment: Optional[RoadNoiseAssessment],
    config: DimensionConfig,
) -> Tier2Score:
    """Score road noise exposure using piecewise dBA-to-score curve (0-10 points).

    Subtractive scoring — higher estimated dBA yields a lower score.
    Returns a benefit-of-the-doubt score of 7/10 when noise data is
    unavailable (Overpass failure or no roads found).
    """
    if road_noise_assessment is None:
        return Tier2Score(
            name="Road Noise",
            points=7,
            max_points=10,
            details="Road noise data unavailable — default score applied",
        )

    raw = apply_piecewise(config.knots, road_noise_assessment.estimated_dba)
    score = max(config.floor, raw)
    points = int(score + 0.5)

    # Build detail line: include road ref (e.g. "US 9") when available
    road_label = road_noise_assessment.worst_road_name
    if road_noise_assessment.worst_road_ref:
        road_label += f" ({road_noise_assessment.worst_road_ref})"

    details = (
        f"Estimated {road_noise_assessment.estimated_dba:.0f} dBA "
        f"({road_noise_assessment.severity.value.replace('_', ' ').title()}) "
        f"from {road_label}, "
        f"{road_noise_assessment.distance_ft:.0f} ft away"
    )

    return Tier2Score(
        name="Road Noise",
        points=points,
        max_points=10,
        details=details,
    )


def score_provisioning_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float,
    pre_fetched_places: Optional[List[Dict]] = None,
) -> Tuple[DimensionResult, List[Dict]]:
    """Score household provisioning store access using piecewise linear curve (0-10 points).

    Returns (DimensionResult, places_list) where places_list contains up to 5
    eligible stores with name, rating, review_count, walk_time_min, lat, lng.
    """
    _dim_name = "Daily Essentials"
    _cfg = SCORING_MODEL.grocery

    def _empty(details: str) -> Tuple[DimensionResult, List[Dict]]:
        return (DimensionResult(
            score=0.0, max_score=10.0, name=_dim_name,
            details=details, scoring_inputs={},
            model_version=SCORING_MODEL.version,
        ), [])

    try:
        # Reuse pre-fetched places from neighborhood snapshot if available
        if pre_fetched_places is not None:
            all_stores = list(pre_fetched_places)
        else:
            all_stores = []
            all_stores.extend(maps.places_nearby(lat, lng, "supermarket", radius_meters=2500))
            all_stores.extend(maps.places_nearby(lat, lng, "grocery_store", radius_meters=2500))
            all_stores = _dedupe_by_place_id(all_stores)

        if not all_stores:
            return _empty("No full-service provisioning options within walking distance")

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
            return _empty("No full-service provisioning options within walking distance")

        # Find best scoring store (batch walk times)
        store_dests = [
            (s["geometry"]["location"]["lat"], s["geometry"]["location"]["lng"])
            for s in eligible_stores
        ]
        store_walk_times = _walking_times_batch(maps, (lat, lng), store_dests)
        best_score = 0.0
        best_store = None
        best_walk_time = 9999

        # Collect all scored stores for neighborhood display
        scored_stores = []

        for store, walk_time in zip(eligible_stores, store_walk_times):
            raw = apply_piecewise(_cfg.knots, walk_time)
            score = max(_cfg.floor, raw)

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
        # Sort cards by distance for display (closest first)
        neighborhood_places.sort(key=lambda p: p.get("walk_time_min") or 9999)

        # Format details
        name = best_store.get("name", "Provisioning store")
        rating = best_store.get("rating", 0)
        reviews = best_store.get("user_ratings_total", 0)
        details = f"{name} ({rating}★, {reviews} reviews) — {best_walk_time} min walk"

        return (DimensionResult(
            score=best_score,
            max_score=10.0,
            name=_dim_name,
            details=details,
            scoring_inputs={"walk_time_min": best_walk_time},
            model_version=SCORING_MODEL.version,
        ), neighborhood_places)

    except Exception as e:
        return _empty(f"Error: {str(e)}")


def score_fitness_access(
    maps: GoogleMapsClient,
    lat: float,
    lng: float
) -> Tuple[DimensionResult, List[Dict]]:
    """Score fitness/wellness facility access using multiplicative model (0-10 points).

    Score = apply_piecewise(walk_time) × apply_quality_multiplier(rating).
    All gyms are scored regardless of rating; quality multipliers handle
    differentiation post-search.

    Returns (DimensionResult, places_list) where places_list contains up to 5
    eligible facilities with name, rating, review_count, walk_time_min, lat, lng.
    """
    _dim_name = "Fitness & Recreation"
    _cfg = SCORING_MODEL.fitness

    def _empty(details: str) -> Tuple[DimensionResult, List[Dict]]:
        return (DimensionResult(
            score=0.0, max_score=10.0, name=_dim_name,
            details=details, scoring_inputs={},
            model_version=SCORING_MODEL.version,
        ), [])

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
        fitness_places = _dedupe_by_place_id(fitness_places)

        if not fitness_places:
            return _empty("No gyms or fitness centers found within 30 min walk")

        # Find best scored facility (batch walk times)
        facility_dests = [
            (f["geometry"]["location"]["lat"], f["geometry"]["location"]["lng"])
            for f in fitness_places
        ]
        facility_walk_times = _walking_times_batch(maps, (lat, lng), facility_dests)
        best_score = 0.0
        best_facility = None
        best_details = ""
        best_walk_time = 9999
        best_rating = 0.0
        best_proximity = 0.0
        best_quality_mult = 0.0

        # Collect all scored facilities for neighborhood display
        scored_facilities = []

        for facility, walk_time in zip(fitness_places, facility_walk_times):
            rating = facility.get("rating", 0)

            # Multiplicative: proximity curve × quality multiplier
            proximity = apply_piecewise(_cfg.knots, walk_time)
            quality_mult = apply_quality_multiplier(_cfg.quality_multipliers, rating)
            score = max(_cfg.floor, proximity * quality_mult)

            if score > best_score or (score == best_score and walk_time < best_walk_time):
                best_score = score
                best_facility = facility
                best_walk_time = walk_time
                best_rating = rating
                best_proximity = proximity
                best_quality_mult = quality_mult
                facility_name = facility.get("name", "Fitness center")
                best_details = f"{facility_name} ({rating}★) — {walk_time} min walk"

            scored_facilities.append((score, walk_time, facility))

        if best_score == 0 and not scored_facilities:
            return _empty("No gyms or fitness centers found within 30 min walk")

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
        # Sort cards by distance for display (closest first)
        neighborhood_places.sort(key=lambda p: p.get("walk_time_min") or 9999)

        return (DimensionResult(
            score=best_score,
            max_score=10.0,
            name=_dim_name,
            details=best_details,
            scoring_inputs={
                "walk_time_min": best_walk_time,
                "rating": best_rating,
            },
            subscores={
                "proximity": round(best_proximity, 2),
                "quality": round(best_quality_mult, 2),
            },
            model_version=SCORING_MODEL.version,
        ), neighborhood_places)

    except Exception as e:
        return _empty(f"Error: {str(e)}")


def calculate_bonuses(listing: PropertyListing) -> List[Tier3Bonus]:
    """Calculate tier 3 bonus points"""
    _t3 = SCORING_MODEL.tier3
    bonuses = []
    
    if listing.has_parking:
        bonuses.append(Tier3Bonus(
            name="Parking",
            points=_t3.parking,
            details="Parking included"
        ))
    
    if listing.has_outdoor_space:
        bonuses.append(Tier3Bonus(
            name="Outdoor space",
            points=_t3.outdoor,
            details="Private yard or balcony"
        ))
    
    if listing.bedrooms and listing.bedrooms >= _t3.bedroom_threshold:
        bonuses.append(Tier3Bonus(
            name="Extra bedroom",
            points=_t3.bedroom,
            details=f"{listing.bedrooms} bedrooms"
        ))
    
    return bonuses


def calculate_bonus_reasons(listing: PropertyListing) -> List[str]:
    """Explain missing tier 3 bonuses when none are awarded."""
    _t3 = SCORING_MODEL.tier3
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
    elif listing.bedrooms < _t3.bedroom_threshold:
        reasons.append(f"Fewer than {_t3.bedroom_threshold} bedrooms")

    return reasons


# Band thresholds also rendered in templates/_result_sections.html "How We Score"
# Sourced from scoring_config; kept as a module-level list for backwards compat
# with test imports.
SCORE_BANDS = [
    (band.threshold, band.label) for band in SCORING_MODEL.score_bands
]


def get_score_band(score: int) -> dict:
    """Return band info dict for a given score.

    Returns {"label": str, "css_class": str}.
    """
    for band in SCORING_MODEL.score_bands:
        if score >= band.threshold:
            return {"label": band.label, "css_class": band.css_class}
    fallback = SCORING_MODEL.score_bands[-1]
    return {"label": fallback.label, "css_class": fallback.css_class}


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


def _retry_once(check_fn: Callable[..., Tier1Check], *args) -> Tier1Check:
    """Retry a Tier 1 check once if it returns UNKNOWN (likely transient API error)."""
    result = check_fn(*args)
    if result.result == CheckResult.UNKNOWN:
        time.sleep(1)
        result = check_fn(*args)
    return result


def _timed_stage_in_thread(parent_trace, stage_name, fn, *args, **kwargs):
    """Run _timed_stage in a child thread with trace propagation.

    Used for stages that don't need a GoogleMapsClient (e.g. Walk Score).
    """
    set_trace(parent_trace)
    return _timed_stage(stage_name, fn, *args, **kwargs)


def _assign_walk_scores(result: "EvaluationResult", all_scores: Dict[str, Any]):
    """Unpack the combined Walk Score API response into result fields."""
    result.walk_scores = {
        "walk_score": all_scores.get("walk_score"),
        "walk_description": all_scores.get("walk_description"),
        "transit_score": all_scores.get("transit_score"),
        "transit_description": all_scores.get("transit_description"),
        "bike_score": all_scores.get("bike_score"),
        "bike_description": all_scores.get("bike_description"),
    }
    result.transit_score = {
        "transit_score": all_scores.get("transit_score"),
        "transit_rating": all_scores.get("transit_rating"),
        "transit_summary": all_scores.get("transit_summary"),
        "nearby_transit_lines": all_scores.get("nearby_transit_lines"),
    }
    result.bike_score = all_scores.get("bike_score")
    result.bike_rating = all_scores.get("bike_rating")
    result.bike_metadata = all_scores.get("bike_metadata")


def _truncate_snippet(text: str, max_chars: int = 100) -> str:
    """Truncate review text to ~max_chars at a word boundary with ellipsis."""
    if not text or len(text) <= max_chars:
        return text or ""
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return truncated.rstrip(".,!?;:") + "..."


def _fetch_review_snippet(maps: GoogleMapsClient, place_id: str) -> Dict[str, Optional[str]]:
    """Fetch a curated review snippet for a single place.

    Calls Place Details with the 'reviews' field, filters for reviews
    rated >= 4 stars, and returns the first qualifying snippet truncated
    to ~100 characters plus the relative time description.

    Returns dict with 'review_snippet' and 'review_time' keys (both None
    if no qualifying review is found or the API call fails).
    """
    empty = {"review_snippet": None, "review_time": None}
    try:
        details = maps.place_details(place_id, fields=["reviews"])
    except Exception:
        logger.debug("Review snippet fetch failed for %s", place_id, exc_info=True)
        return empty

    reviews = details.get("reviews", [])
    for review in reviews:
        if review.get("rating", 0) >= 4:
            snippet = _truncate_snippet(review.get("text", ""))
            if snippet:
                return {
                    "review_snippet": snippet,
                    "review_time": review.get("relative_time_description"),
                }
    return empty


def _enrich_headline_places_with_snippets(
    api_key: str,
    neighborhood_places: Dict[str, list],
) -> None:
    """Fetch review snippets for the top place in each category (in parallel).

    Mutates the first place dict in each category list by attaching
    'review_snippet' and 'review_time' fields.  Categories with no
    places or whose top place lacks a place_id are silently skipped.
    4 parallel calls max (~400ms wall-clock).
    """
    # Collect (category, place_dict) pairs for headline places that have a place_id
    headlines = []
    for category, places in neighborhood_places.items():
        if places and places[0].get("place_id"):
            headlines.append((category, places[0]))

    if not headlines:
        return

    # Each thread gets its own GoogleMapsClient (requests.Session is not thread-safe)
    parent_trace = get_trace()

    def _fetch_for_place(place: Dict) -> Dict[str, Optional[str]]:
        set_trace(parent_trace)
        thread_maps = GoogleMapsClient(api_key)
        return _fetch_review_snippet(thread_maps, place["place_id"])

    with ThreadPoolExecutor(max_workers=len(headlines)) as pool:
        futures = {
            pool.submit(_fetch_for_place, place): place
            for _cat, place in headlines
        }
        for future in as_completed(futures):
            place = futures[future]
            try:
                snippet_data = future.result()
                place.update(snippet_data)
            except Exception:
                pass  # Graceful degradation — card renders without snippet


def evaluate_property(
    listing: PropertyListing,
    api_key: str,
    on_stage: Optional[Callable[[str], None]] = None,
    place_id: Optional[str] = None,
) -> EvaluationResult:
    """Run full evaluation on a property listing.

    Data-collection stages (walk_scores, neighborhood, schools, urban_access,
    transit_access, green_escape, road_noise) run concurrently after geocoding.  Each is
    independent — a single failing stage degrades gracefully without affecting
    the others.  Tier 1 checks and Tier 2 scoring remain sequential.

    on_stage: optional callback(stage_name: str) called at the start of each
    stage, for progress reporting (e.g. async job queue).
    """
    def _run_stage(name: str, fn, *args, **kwargs):
        if on_stage:
            on_stage(name)
        return _timed_stage(name, fn, *args, **kwargs)

    eval_start = time.time()

    maps = GoogleMapsClient(api_key)
    overpass = OverpassClient()

    # Geocode is the one stage that MUST succeed — without coords nothing
    # else can run.  Let this propagate on failure.
    lat, lng = _run_stage("geocode", maps.geocode, listing.address, place_id=place_id)

    result = EvaluationResult(
        listing=listing,
        lat=lat,
        lng=lng,
        model_version=SCORING_MODEL.version,
    )

    # --- Parallel enrichment stages ---
    # All stages below depend only on lat/lng from geocoding.  Running them
    # concurrently cuts wall-clock time from sum-of-all to max-of-slowest.
    # Each thread gets a fresh GoogleMapsClient (requests.Session is not
    # thread-safe) and the parent TraceContext (list.append is GIL-atomic).

    parent_trace = get_trace()
    if parent_trace:
        parent_trace.model_version = SCORING_MODEL.version

    def _threaded_stage(stage_name, fn, *args, **kwargs):
        """Run a stage in a child thread with trace propagation and a
        per-thread GoogleMapsClient."""
        set_trace(parent_trace)
        thread_maps = GoogleMapsClient(api_key)
        # Swap the maps argument (first positional after stage_name)
        # for stages that receive a GoogleMapsClient.
        new_args = tuple(
            thread_maps if a is maps else a for a in args
        )
        return _timed_stage(stage_name, fn, *new_args, **kwargs)

    if on_stage:
        on_stage("analyzing")

    # Build the futures dict: stage_name -> future
    futures: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        # walk_scores doesn't use maps client — no swap needed
        futures["walk_scores"] = pool.submit(
            _timed_stage_in_thread, parent_trace,
            "walk_scores", get_all_walk_scores, listing.address, lat, lng,
        )
        futures["neighborhood"] = pool.submit(
            _threaded_stage,
            "neighborhood", get_neighborhood_snapshot, maps, lat, lng,
        )
        if ENABLE_SCHOOLS:
            futures["schools"] = pool.submit(
                _threaded_stage,
                "schools", get_child_and_schooling_snapshot, maps, lat, lng,
            )
        futures["urban_access"] = pool.submit(
            _threaded_stage,
            "urban_access", get_urban_access_profile, maps, lat, lng, overpass,
        )
        futures["transit_access"] = pool.submit(
            _threaded_stage,
            "transit_access", evaluate_transit_access, maps, lat, lng,
        )
        futures["green_escape"] = pool.submit(
            _threaded_stage,
            "green_escape", evaluate_green_escape, maps, lat, lng,
        )
        # Emergency services — Overpass query + drive time (NES-50).
        # _threaded_stage auto-swaps `maps` for a per-thread client;
        # `overpass` passes through unchanged (stateless, thread-safe).
        futures["emergency_services"] = pool.submit(
            _threaded_stage,
            "emergency_services", get_emergency_services, maps, overpass, lat, lng,
        )
        # Road noise — standalone Overpass query, no maps client needed.
        futures["road_noise"] = pool.submit(
            _timed_stage_in_thread, parent_trace,
            "road_noise", assess_road_noise, lat, lng,
        )
        # Weather normals — Open-Meteo API, no maps client needed (NES-32).
        futures["weather"] = pool.submit(
            _timed_stage_in_thread, parent_trace,
            "weather", get_weather_summary, lat, lng,
        )

        # Collect results — each stage fails independently
        for stage_name, future in futures.items():
            try:
                stage_result = future.result()
                if stage_name == "walk_scores":
                    _assign_walk_scores(result, stage_result)
                elif stage_name == "neighborhood":
                    result.neighborhood_snapshot = stage_result
                elif stage_name == "schools":
                    result.child_schooling_snapshot = stage_result
                elif stage_name == "urban_access":
                    result.urban_access = stage_result
                elif stage_name == "transit_access":
                    result.transit_access = stage_result
                elif stage_name == "green_escape":
                    result.green_escape_evaluation = stage_result
                elif stage_name == "emergency_services":
                    result.emergency_services = stage_result
                elif stage_name == "road_noise":
                    result.road_noise_assessment = stage_result
                elif stage_name == "weather":
                    result.weather_summary = stage_result
            except Exception:
                pass  # Graceful degradation — same as the sequential path

    # ===================
    # TIER 1 CHECKS
    # ===================
    if on_stage:
        on_stage("tier1_checks")

    trace = get_trace()
    if trace:
        trace.start_stage("tier1_checks")
    _t0_tier1 = time.time()

    # Location-based checks (single retry on UNKNOWN — likely transient API error)
    result.tier1_checks.append(_retry_once(check_gas_stations, maps, lat, lng))

    # Fetch Overpass road data once, reuse for both highway and high-volume checks.
    # Single retry on transient failure before giving up with sentinel.
    try:
        _roads_data = overpass.get_nearby_roads(lat, lng, radius_meters=200)
    except Exception:
        time.sleep(1)
        try:
            _roads_data = overpass.get_nearby_roads(lat, lng, radius_meters=200)
        except Exception:
            _roads_data = _OVERPASS_FAILED

    # When the shared fetch already failed, skip _retry_once — retrying
    # won't help and just adds latency against a down endpoint.
    if _roads_data is _OVERPASS_FAILED:
        result.tier1_checks.append(check_highways(maps, overpass, lat, lng, _roads_data))
        result.tier1_checks.append(check_high_volume_roads(overpass, lat, lng, _roads_data))
    else:
        result.tier1_checks.append(_retry_once(check_highways, maps, overpass, lat, lng, _roads_data))
        result.tier1_checks.append(_retry_once(check_high_volume_roads, overpass, lat, lng, _roads_data))

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
    # TIER 2 SCORING — always runs. passed_tier1 is used for presentation only.
    # ===================

    result.tier2_scores.append(
        _run_stage(
            "score_park_access", score_park_access,
            maps, lat, lng,
            green_escape_evaluation=result.green_escape_evaluation,
        )
    )
    # Reuse raw places from neighborhood snapshot for Tier 2 scoring
    _raw = result.neighborhood_snapshot.raw_places if result.neighborhood_snapshot else {}

    _coffee_score, _coffee_places = _run_stage(
        "score_third_place", score_third_place_access, maps, lat, lng,
        pre_fetched_places=_raw.get("Third Place"))
    result.tier2_scores.append(_coffee_score)

    _grocery_score, _grocery_places = _run_stage(
        "score_provisioning", score_provisioning_access, maps, lat, lng,
        pre_fetched_places=_raw.get("Provisioning"))
    result.tier2_scores.append(_grocery_score)

    _fitness_score, _fitness_places = _run_stage(
        "score_fitness", score_fitness_access, maps, lat, lng)
    result.tier2_scores.append(_fitness_score)

    # Collect neighborhood places from scoring + green escape
    _park_places = []
    if result.green_escape_evaluation and result.green_escape_evaluation.nearby_green_spaces:
        # Include best daily park first if available
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
        # Sort cards by distance for display (closest first)
        _park_places.sort(key=lambda p: p.get("walk_time_min") or p.get("drive_time_min") or 9999)

    result.neighborhood_places = {
        "coffee": _coffee_places,
        "grocery": _grocery_places,
        "fitness": _fitness_places,
        "parks": _park_places,
    }

    # Enrich headline place per category with a Google review snippet.
    # 4 parallel Place Details calls (~400ms wall-clock, ~$0.07 total).
    _run_stage(
        "review_snippets",
        _enrich_headline_places_with_snippets, api_key, result.neighborhood_places,
    )

    # score_cost removed — Cost/Affordability no longer part of scoring
    _cached_primary_transit = (
        result.urban_access.primary_transit if result.urban_access else None
    )
    _cached_major_hub = (
        result.urban_access.major_hub if result.urban_access else None
    )
    result.tier2_scores.append(
        _run_stage(
            "score_transit_access", score_transit_access,
            maps, lat, lng,
            transit_access=result.transit_access,
            primary_transit=_cached_primary_transit,
            major_hub=_cached_major_hub,
        )
    )

    result.tier2_scores.append(
        _run_stage(
            "score_road_noise", score_road_noise,
            road_noise_assessment=result.road_noise_assessment,
            config=SCORING_MODEL.road_noise,
        )
    )

    # "Round then sum" — aggregate from the rounded .points values that
    # consumers actually display, so tier2_total always equals the sum of
    # the per-dimension points shown in the UI/CLI/API output.
    result.tier2_total = sum(s.points for s in result.tier2_scores)
    result.tier2_max = sum(s.max_points for s in result.tier2_scores)
    if result.tier2_max > 0:
        result.tier2_normalized = int(
            (result.tier2_total / result.tier2_max) * 100 + 0.5
        )
    else:
        result.tier2_normalized = 0

    # ===================
    # TIER 3 BONUSES — always runs.
    # ===================
    if on_stage:
        on_stage("tier3_bonuses")

    result.tier3_bonuses = calculate_bonuses(listing)
    result.tier3_total = sum(b.points for b in result.tier3_bonuses)
    result.tier3_bonus_reasons = calculate_bonus_reasons(listing)

    # ===================
    # FINAL SCORE
    # ===================

    result.final_score = min(100, result.tier2_normalized + result.tier3_total)

    # ===================
    # MAP GENERATION — after all data is ready
    # ===================
    try:
        from map_generator import generate_neighborhood_map
        _transit = result.urban_access.primary_transit if result.urban_access else None
        result.neighborhood_map_b64 = _timed_stage(
            "map_generation",
            generate_neighborhood_map,
            property_lat=lat,
            property_lng=lng,
            neighborhood_places=result.neighborhood_places,
            transit_lat=_transit.lat if _transit else None,
            transit_lng=_transit.lng if _transit else None,
        )
    except Exception:
        logger.warning("Map generation failed; continuing without map", exc_info=True)
        result.neighborhood_map_b64 = None

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
    lines.append(f"LIVABILITY SCORE: {result.final_score}/100 ({get_score_band(result.final_score)['label']})")
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
            "score_band": get_score_band(result.final_score)["label"],
            "model_version": result.model_version,
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_result(result))


if __name__ == "__main__":
    main()
