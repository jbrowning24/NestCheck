"""
Walk Quality Assessment — MAPS-Mini Pipeline via GSV Computer Vision.

Evaluates pedestrian environment quality around a property using a hybrid
approach: Google Street View (GSV) image analysis for visual features
combined with OpenStreetMap infrastructure data for MAPS-Mini features.

Framework: MAPS-Mini (Microscale Audit of Pedestrian Streetscapes, 15-item
version) developed by James Sallis and colleagues at UC San Diego.  Validated
for GSV-based audits by Kim & Cho (2023, Sustainable Cities and Society) and
Adams et al. (2022, EfficientNetB5 for 8 MAPS-Mini features).

Features scored:
  - Sidewalk presence & coverage (OSM + GSV)
  - Tree canopy / greenery (GSV image analysis)
  - Street lighting density (OSM + GSV brightness)
  - Crosswalk presence (OSM)
  - Curb cuts / accessibility (OSM)
  - Pedestrian signals (OSM)
  - Buffer zones / street enclosure (GSV image analysis)

Data sources:
  - Google Street View Static API (image capture at sample points)
  - OpenStreetMap Overpass API (infrastructure features)
  - Existing sidewalk_coverage.py (sidewalk/cycleway tag analysis)

API costs:
  - GSV Static API: ~$0.007/image × 8 sample points = ~$0.056/evaluation
  - GSV Metadata: free (determines availability before fetching images)
  - Overpass API: free (community OSM data)

Graceful degradation:
  - Without GSV API: scores OSM-only features (sidewalks, crossings, lights)
  - Without Overpass: scores GSV-only features (greenery, brightness)
  - Fully offline: returns None (caller handles absence)
"""

import io
import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Sample points: 8 directions at ~200m from property (N, NE, E, SE, S, SW, W, NW)
SAMPLE_DISTANCE_M = 200
SAMPLE_DIRECTIONS = [0, 45, 90, 135, 180, 225, 270, 315]

# GSV image parameters
GSV_IMAGE_WIDTH = 600
GSV_IMAGE_HEIGHT = 400
GSV_FOV = 90  # field of view in degrees
GSV_PITCH = 0  # level with horizon

# Overpass query radius for infrastructure features
INFRA_RADIUS_M = 500

# Scoring weights (total = 100)
WEIGHT_SIDEWALK = 25       # sidewalk presence & coverage
WEIGHT_GREENERY = 20       # tree canopy / vegetation from GSV
WEIGHT_LIGHTING = 15       # street lighting density
WEIGHT_CROSSWALKS = 15     # crosswalk presence
WEIGHT_BUFFER = 10         # street enclosure / buffer from GSV
WEIGHT_CURB_CUTS = 10      # curb cut / accessibility
WEIGHT_PED_SIGNALS = 5     # pedestrian signals

# Greenery analysis thresholds (HSV color space)
# Green hue range: 35-85 degrees (out of 180 in OpenCV convention, ~70-170 out of 360)
GREEN_HUE_MIN = 35
GREEN_HUE_MAX = 85
GREEN_SAT_MIN = 30   # minimum saturation (0-255) to count as green
GREEN_VAL_MIN = 30   # minimum value (0-255) to avoid dark patches

# Sky detection (upper portion of image)
SKY_REGION_FRACTION = 0.35  # top 35% of image for sky analysis

# Confidence thresholds
GSV_COVERAGE_HIGH = 0.75     # >= 75% of sample points have GSV imagery
GSV_COVERAGE_MEDIUM = 0.50   # >= 50%
OSM_FEATURES_HIGH = 10       # >= 10 infrastructure features found
OSM_FEATURES_MEDIUM = 3      # >= 3 features

# API timeout
API_TIMEOUT = 10


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class GSVSamplePoint:
    """A single GSV sample point with analysis results."""
    lat: float
    lng: float
    heading: int               # compass direction from property
    has_coverage: bool         # GSV imagery available
    greenery_pct: float = 0.0  # percentage of green pixels (0-100)
    sky_pct: float = 0.0       # percentage of sky pixels in upper region (0-100)
    brightness: float = 0.0    # mean brightness (0-255)
    pano_date: Optional[str] = None  # date of GSV imagery (YYYY-MM)


@dataclass
class InfrastructureFeatures:
    """MAPS-Mini infrastructure features from OSM within the search radius."""
    crosswalk_count: int = 0        # highway=crossing nodes
    streetlight_count: int = 0      # highway=street_lamp nodes
    curb_cut_count: int = 0         # kerb=lowered or tactile_paving=yes
    ped_signal_count: int = 0       # crossing=traffic_signals
    bench_count: int = 0            # amenity=bench
    total_features: int = 0         # sum of all above


@dataclass
class WalkQualityFeatureScore:
    """Individual feature score within the walk quality assessment."""
    feature: str           # human-readable feature name
    score: float           # 0-100 score for this feature
    weight: float          # weight in overall score (0-1)
    detail: str            # explanation
    source: str            # "GSV", "OSM", or "Combined"


@dataclass
class WalkQualityAssessment:
    """Complete walk quality assessment for a property."""

    # Overall score
    walk_quality_score: int         # 0-100 composite score
    walk_quality_rating: str        # "Excellent" / "Good" / "Fair" / "Poor"

    # Feature breakdown
    feature_scores: List[WalkQualityFeatureScore] = field(default_factory=list)

    # Sample point data
    sample_points_total: int = 0
    sample_points_with_coverage: int = 0
    avg_greenery_pct: float = 0.0
    avg_brightness: float = 0.0

    # Infrastructure
    infrastructure: Optional[InfrastructureFeatures] = None

    # Data quality
    data_confidence: str = "LOW"             # "HIGH" / "MEDIUM" / "LOW"
    data_confidence_note: str = ""
    gsv_available: bool = False              # whether any GSV data was used

    # Methodology
    methodology_note: str = ""

    # Comparison with Walk Score
    walk_score_comparison: Optional[str] = None


# =============================================================================
# SCORING HELPERS
# =============================================================================

_RATING_BANDS = [
    (80, "Excellent"),
    (60, "Good"),
    (40, "Fair"),
    (0, "Poor"),
]


def _walk_quality_rating(score: int) -> str:
    """Map a 0-100 score to a human-readable rating."""
    for threshold, label in _RATING_BANDS:
        if score >= threshold:
            return label
    return "Poor"


METHODOLOGY_NOTE = (
    "Walk quality is assessed using a MAPS-Mini (Microscale Audit of "
    "Pedestrian Streetscapes) inspired framework. Eight sample points at "
    "~200 m intervals around the property are analyzed for pedestrian "
    "infrastructure (sidewalks, crosswalks, lighting, signals) via "
    "OpenStreetMap data, and for environmental quality (greenery, street "
    "enclosure, lighting conditions) via Google Street View imagery. "
    "Unlike Walk Score, which measures proximity to amenities, this metric "
    "evaluates the actual walking experience — sidewalk condition, shade, "
    "lighting, and perceived safety of the pedestrian environment."
)


# =============================================================================
# GEOMETRY HELPERS
# =============================================================================

def _offset_point(lat: float, lng: float, bearing_deg: float,
                  distance_m: float) -> Tuple[float, float]:
    """Calculate a new lat/lng given bearing and distance from origin.

    Uses the Haversine formula for short distances.
    """
    R = 6371000  # Earth's radius in meters
    lat_r = math.radians(lat)
    lng_r = math.radians(lng)
    bearing_r = math.radians(bearing_deg)

    d_r = distance_m / R

    new_lat_r = math.asin(
        math.sin(lat_r) * math.cos(d_r) +
        math.cos(lat_r) * math.sin(d_r) * math.cos(bearing_r)
    )
    new_lng_r = lng_r + math.atan2(
        math.sin(bearing_r) * math.sin(d_r) * math.cos(lat_r),
        math.cos(d_r) - math.sin(lat_r) * math.sin(new_lat_r)
    )

    return math.degrees(new_lat_r), math.degrees(new_lng_r)


def _generate_sample_points(lat: float, lng: float) -> List[Tuple[float, float, int]]:
    """Generate 8 sample points around the property.

    Returns list of (lat, lng, heading) tuples.
    """
    points = []
    for bearing in SAMPLE_DIRECTIONS:
        pt_lat, pt_lng = _offset_point(lat, lng, bearing, SAMPLE_DISTANCE_M)
        # Heading points back towards the property from the sample point
        reverse_heading = (bearing + 180) % 360
        points.append((pt_lat, pt_lng, reverse_heading))
    return points


# =============================================================================
# GSV API HELPERS
# =============================================================================

def _gsv_metadata(lat: float, lng: float, api_key: str) -> Optional[dict]:
    """Check GSV metadata at a location. Returns metadata dict or None."""
    url = "https://maps.googleapis.com/maps/api/streetview/metadata"
    params = {
        "location": f"{lat},{lng}",
        "key": api_key,
    }
    try:
        t0 = time.time()
        resp = requests.get(url, params=params, timeout=API_TIMEOUT)
        elapsed = int((time.time() - t0) * 1000)
        data = resp.json()

        from nc_trace import get_trace
        trace = get_trace()
        if trace:
            trace.record_api_call(
                service="google_maps",
                endpoint="gsv_metadata",
                elapsed_ms=elapsed,
                status_code=resp.status_code,
                provider_status=data.get("status", ""),
            )

        if data.get("status") == "OK":
            return data
        return None
    except (requests.RequestException, ValueError):
        return None


def _gsv_image(lat: float, lng: float, heading: int,
               api_key: str) -> Optional[bytes]:
    """Fetch a GSV static image. Returns raw image bytes or None."""
    url = "https://maps.googleapis.com/maps/api/streetview"
    params = {
        "size": f"{GSV_IMAGE_WIDTH}x{GSV_IMAGE_HEIGHT}",
        "location": f"{lat},{lng}",
        "heading": heading,
        "fov": GSV_FOV,
        "pitch": GSV_PITCH,
        "key": api_key,
    }
    try:
        t0 = time.time()
        resp = requests.get(url, params=params, timeout=API_TIMEOUT)
        elapsed = int((time.time() - t0) * 1000)

        from nc_trace import get_trace
        trace = get_trace()
        if trace:
            trace.record_api_call(
                service="google_maps",
                endpoint="gsv_image",
                elapsed_ms=elapsed,
                status_code=resp.status_code,
                provider_status="OK" if resp.status_code == 200 else "ERROR",
            )

        if resp.status_code == 200 and len(resp.content) > 1000:
            # GSV returns a small grey image when no imagery is available;
            # real images are always > 1 KB.
            return resp.content
        return None
    except requests.RequestException:
        return None


# =============================================================================
# IMAGE ANALYSIS (Pillow-based)
# =============================================================================

def _analyze_image(image_bytes: bytes) -> dict:
    """Analyze a GSV image for MAPS-Mini visual features using Pillow.

    Returns dict with:
      - greenery_pct: percentage of green pixels (proxy for tree canopy)
      - sky_pct: percentage of sky-like pixels in upper image region
      - brightness: mean brightness (0-255)
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed; skipping GSV image analysis")
        return {"greenery_pct": 0.0, "sky_pct": 0.0, "brightness": 0.0}

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        logger.warning("Failed to decode GSV image", exc_info=True)
        return {"greenery_pct": 0.0, "sky_pct": 0.0, "brightness": 0.0}

    width, height = img.size
    total_pixels = width * height

    if total_pixels == 0:
        return {"greenery_pct": 0.0, "sky_pct": 0.0, "brightness": 0.0}

    # --- Greenery detection (full image) ---
    # Convert to HSV for green detection
    hsv_img = img.convert("HSV")
    # Use get_flattened_data (Pillow 12+) with getdata fallback
    _get_data = getattr(hsv_img, "get_flattened_data", None) or hsv_img.getdata
    hsv_pixels = list(_get_data())

    green_count = 0
    brightness_sum = 0

    for h, s, v in hsv_pixels:
        brightness_sum += v
        if GREEN_HUE_MIN <= h <= GREEN_HUE_MAX and s >= GREEN_SAT_MIN and v >= GREEN_VAL_MIN:
            green_count += 1

    greenery_pct = round(green_count / total_pixels * 100, 1)
    brightness = round(brightness_sum / total_pixels, 1)

    # --- Sky detection (upper portion only) ---
    sky_row_limit = int(height * SKY_REGION_FRACTION)
    sky_pixels = hsv_pixels[:sky_row_limit * width]
    sky_count = 0

    for h, s, v in sky_pixels:
        # Sky: high brightness, low-to-moderate saturation
        # Blue sky: H ~130-170 (Pillow HSV H is 0-255 mapped from 0-360)
        # Overcast: H any, S < 30, V > 150
        is_blue_sky = (100 <= h <= 170) and (s >= 30) and (v >= 120)
        is_overcast = (s < 30) and (v > 150)
        if is_blue_sky or is_overcast:
            sky_count += 1

    sky_total = len(sky_pixels) if sky_pixels else 1
    sky_pct = round(sky_count / sky_total * 100, 1)

    return {
        "greenery_pct": greenery_pct,
        "sky_pct": sky_pct,
        "brightness": brightness,
    }


# =============================================================================
# OSM INFRASTRUCTURE QUERY
# =============================================================================

def _build_infra_query(lat: float, lng: float, radius_m: int) -> str:
    """Build Overpass QL query for MAPS-Mini infrastructure features."""
    return f"""
    [out:json][timeout:25];
    (
      node["highway"="crossing"](around:{radius_m},{lat},{lng});
      node["highway"="street_lamp"](around:{radius_m},{lat},{lng});
      node["kerb"="lowered"](around:{radius_m},{lat},{lng});
      node["tactile_paving"="yes"](around:{radius_m},{lat},{lng});
      node["crossing"="traffic_signals"](around:{radius_m},{lat},{lng});
      node["amenity"="bench"](around:{radius_m},{lat},{lng});
    );
    out count;
    """


def _build_infra_detail_query(lat: float, lng: float, radius_m: int) -> str:
    """Build Overpass query that returns individual elements for counting."""
    return f"""
    [out:json][timeout:25];
    (
      node["highway"="crossing"](around:{radius_m},{lat},{lng});
      node["highway"="street_lamp"](around:{radius_m},{lat},{lng});
      node["kerb"="lowered"](around:{radius_m},{lat},{lng});
      node["tactile_paving"="yes"](around:{radius_m},{lat},{lng});
      node["crossing"="traffic_signals"](around:{radius_m},{lat},{lng});
      node["amenity"="bench"](around:{radius_m},{lat},{lng});
    );
    out tags;
    """


def _fetch_infrastructure(lat: float, lng: float,
                          radius_m: int = INFRA_RADIUS_M) -> Optional[InfrastructureFeatures]:
    """Query Overpass for MAPS-Mini infrastructure features.

    Returns InfrastructureFeatures or None on failure.
    """
    try:
        from overpass_http import overpass_query
    except ImportError:
        logger.warning("overpass_http not available; skipping infrastructure query")
        return None

    query = _build_infra_detail_query(lat, lng, radius_m)

    try:
        data = overpass_query(query, caller="walk_quality", timeout=25)
    except Exception:
        logger.warning("Overpass walk quality infrastructure query failed",
                       exc_info=True)
        return None

    crosswalks = 0
    streetlights = 0
    curb_cuts = 0
    ped_signals = 0
    benches = 0

    for el in data.get("elements", []):
        if el.get("type") != "node":
            continue
        tags = el.get("tags", {})

        if tags.get("highway") == "crossing":
            crosswalks += 1
        if tags.get("highway") == "street_lamp":
            streetlights += 1
        if tags.get("kerb") == "lowered" or tags.get("tactile_paving") == "yes":
            curb_cuts += 1
        if tags.get("crossing") == "traffic_signals":
            ped_signals += 1
        if tags.get("amenity") == "bench":
            benches += 1

    total = crosswalks + streetlights + curb_cuts + ped_signals + benches

    return InfrastructureFeatures(
        crosswalk_count=crosswalks,
        streetlight_count=streetlights,
        curb_cut_count=curb_cuts,
        ped_signal_count=ped_signals,
        bench_count=benches,
        total_features=total,
    )


# =============================================================================
# SCORING PIPELINE
# =============================================================================

def _score_sidewalks(sidewalk_pct: Optional[float],
                     data_confidence: Optional[str]) -> WalkQualityFeatureScore:
    """Score sidewalk presence from existing sidewalk_coverage data.

    Uses the sidewalk_pct (0-100) from sidewalk_coverage.py.
    """
    if sidewalk_pct is None:
        return WalkQualityFeatureScore(
            feature="Sidewalk Coverage",
            score=0,
            weight=WEIGHT_SIDEWALK / 100,
            detail="Sidewalk data unavailable",
            source="OSM",
        )

    # Linear scale: 0% → 0, 80%+ → 100
    raw = min(100, sidewalk_pct / 80 * 100)

    # Penalize low confidence — sidewalk data absence in OSM is ambiguous
    if data_confidence == "LOW":
        detail = f"{sidewalk_pct:.0f}% of roads have sidewalk tags (sparse OSM data)"
    elif data_confidence == "MEDIUM":
        detail = f"{sidewalk_pct:.0f}% of roads have sidewalk tags (moderate OSM data)"
    else:
        detail = f"{sidewalk_pct:.0f}% of roads have sidewalk tags"

    return WalkQualityFeatureScore(
        feature="Sidewalk Coverage",
        score=round(raw),
        weight=WEIGHT_SIDEWALK / 100,
        detail=detail,
        source="OSM",
    )


def _score_greenery(avg_greenery_pct: float,
                    gsv_available: bool) -> WalkQualityFeatureScore:
    """Score tree canopy / greenery from GSV image analysis.

    Greenery percentage maps to score:
      >= 25% green pixels → 100 (excellent canopy)
      15-25% → 60-100 (good canopy)
      5-15% → 20-60 (sparse)
      < 5% → 0-20 (minimal)
    """
    if not gsv_available:
        return WalkQualityFeatureScore(
            feature="Tree Canopy & Greenery",
            score=0,
            weight=WEIGHT_GREENERY / 100,
            detail="No Street View imagery available",
            source="GSV",
        )

    if avg_greenery_pct >= 25:
        raw = 100
    elif avg_greenery_pct >= 15:
        raw = 60 + (avg_greenery_pct - 15) / 10 * 40
    elif avg_greenery_pct >= 5:
        raw = 20 + (avg_greenery_pct - 5) / 10 * 40
    else:
        raw = avg_greenery_pct / 5 * 20

    return WalkQualityFeatureScore(
        feature="Tree Canopy & Greenery",
        score=round(raw),
        weight=WEIGHT_GREENERY / 100,
        detail=f"{avg_greenery_pct:.0f}% average green coverage from Street View imagery",
        source="GSV",
    )


def _score_lighting(streetlight_count: int,
                    avg_brightness: float,
                    gsv_available: bool) -> WalkQualityFeatureScore:
    """Score street lighting from OSM density + GSV brightness.

    Combines streetlight node count with image brightness.
    """
    # OSM streetlight density: 0 = 0, 20+ = 50 (max from OSM alone)
    osm_score = min(50, streetlight_count / 20 * 50)

    # GSV brightness: supplement OSM with actual visibility
    # Brightness 100-180 is typical daylight; < 80 suggests poor conditions
    if gsv_available and avg_brightness > 0:
        if avg_brightness >= 140:
            gsv_score = 50
        elif avg_brightness >= 100:
            gsv_score = 25 + (avg_brightness - 100) / 40 * 25
        else:
            gsv_score = avg_brightness / 100 * 25
    else:
        gsv_score = 0

    raw = osm_score + gsv_score
    source = "Combined" if gsv_available else "OSM"

    parts = []
    if streetlight_count > 0:
        parts.append(f"{streetlight_count} street lights mapped in OSM")
    if gsv_available:
        parts.append(f"avg brightness {avg_brightness:.0f}/255 from Street View")
    if not parts:
        parts.append("No street lighting data available")

    return WalkQualityFeatureScore(
        feature="Street Lighting",
        score=round(raw),
        weight=WEIGHT_LIGHTING / 100,
        detail=" · ".join(parts),
        source=source,
    )


def _score_crosswalks(crosswalk_count: int) -> WalkQualityFeatureScore:
    """Score crosswalk presence from OSM data.

    Crosswalk count maps to score:
      >= 15 → 100 (well-connected network)
      8-15 → 50-100
      1-8 → 10-50
      0 → 0
    """
    if crosswalk_count >= 15:
        raw = 100
    elif crosswalk_count >= 8:
        raw = 50 + (crosswalk_count - 8) / 7 * 50
    elif crosswalk_count >= 1:
        raw = 10 + (crosswalk_count - 1) / 7 * 40
    else:
        raw = 0

    return WalkQualityFeatureScore(
        feature="Crosswalks",
        score=round(raw),
        weight=WEIGHT_CROSSWALKS / 100,
        detail=f"{crosswalk_count} marked crossings within {INFRA_RADIUS_M} m",
        source="OSM",
    )


def _score_buffer(avg_sky_pct: float,
                  avg_greenery_pct: float,
                  gsv_available: bool) -> WalkQualityFeatureScore:
    """Score buffer / street enclosure from GSV analysis.

    Lower sky percentage + higher greenery suggests trees/buildings forming
    a comfortable buffer between pedestrians and vehicles.
    """
    if not gsv_available:
        return WalkQualityFeatureScore(
            feature="Street Enclosure & Buffer",
            score=0,
            weight=WEIGHT_BUFFER / 100,
            detail="No Street View imagery available",
            source="GSV",
        )

    # Good enclosure: low sky (< 30%), decent greenery (> 10%)
    # Open/exposed: high sky (> 60%), low greenery
    enclosure = max(0, 100 - avg_sky_pct)  # 100% sky → 0, 0% sky → 100
    greenery_bonus = min(30, avg_greenery_pct)  # up to 30 bonus points

    raw = min(100, enclosure * 0.7 + greenery_bonus)

    return WalkQualityFeatureScore(
        feature="Street Enclosure & Buffer",
        score=round(raw),
        weight=WEIGHT_BUFFER / 100,
        detail=f"{100 - avg_sky_pct:.0f}% street enclosure, {avg_greenery_pct:.0f}% vegetation buffer",
        source="GSV",
    )


def _score_curb_cuts(curb_cut_count: int) -> WalkQualityFeatureScore:
    """Score curb cut / accessibility features from OSM.

    Curb cut count:
      >= 10 → 100
      5-10 → 50-100
      1-5 → 10-50
      0 → 0
    """
    if curb_cut_count >= 10:
        raw = 100
    elif curb_cut_count >= 5:
        raw = 50 + (curb_cut_count - 5) / 5 * 50
    elif curb_cut_count >= 1:
        raw = 10 + (curb_cut_count - 1) / 4 * 40
    else:
        raw = 0

    return WalkQualityFeatureScore(
        feature="Curb Cuts & Accessibility",
        score=round(raw),
        weight=WEIGHT_CURB_CUTS / 100,
        detail=f"{curb_cut_count} accessible curb cuts / tactile paving within {INFRA_RADIUS_M} m",
        source="OSM",
    )


def _score_ped_signals(ped_signal_count: int) -> WalkQualityFeatureScore:
    """Score pedestrian signals from OSM.

    Signal count:
      >= 5 → 100
      2-5 → 40-100
      1 → 20
      0 → 0
    """
    if ped_signal_count >= 5:
        raw = 100
    elif ped_signal_count >= 2:
        raw = 40 + (ped_signal_count - 2) / 3 * 60
    elif ped_signal_count >= 1:
        raw = 20
    else:
        raw = 0

    return WalkQualityFeatureScore(
        feature="Pedestrian Signals",
        score=round(raw),
        weight=WEIGHT_PED_SIGNALS / 100,
        detail=f"{ped_signal_count} pedestrian signal crossings within {INFRA_RADIUS_M} m",
        source="OSM",
    )


def _classify_confidence(
    sample_points_with_coverage: int,
    sample_points_total: int,
    infra: Optional[InfrastructureFeatures],
) -> Tuple[str, str]:
    """Determine data confidence for the walk quality assessment.

    Considers both GSV coverage and OSM infrastructure data richness.
    """
    gsv_frac = (
        sample_points_with_coverage / sample_points_total
        if sample_points_total > 0 else 0
    )
    infra_count = infra.total_features if infra else 0

    has_good_gsv = gsv_frac >= GSV_COVERAGE_HIGH
    has_good_osm = infra_count >= OSM_FEATURES_HIGH
    has_some_gsv = gsv_frac >= GSV_COVERAGE_MEDIUM
    has_some_osm = infra_count >= OSM_FEATURES_MEDIUM

    if has_good_gsv and has_good_osm:
        return (
            "HIGH",
            f"Street View available at {gsv_frac:.0%} of sample points, "
            f"{infra_count} infrastructure features mapped in OSM"
        )
    elif has_some_gsv or has_good_osm:
        parts = []
        if has_some_gsv:
            parts.append(f"Street View at {gsv_frac:.0%} of points")
        if has_some_osm or has_good_osm:
            parts.append(f"{infra_count} OSM infrastructure features")
        return ("MEDIUM", " · ".join(parts))
    else:
        parts = []
        if sample_points_with_coverage > 0:
            parts.append(f"Street View at only {gsv_frac:.0%} of points")
        else:
            parts.append("No Street View imagery available")
        if infra_count > 0:
            parts.append(f"only {infra_count} OSM features found")
        else:
            parts.append("no pedestrian infrastructure mapped in OSM")
        return ("LOW", " · ".join(parts))


def _walk_score_comparison(walk_quality_score: int,
                           walk_score: Optional[int]) -> Optional[str]:
    """Generate a comparison note between walk quality and Walk Score."""
    if walk_score is None:
        return None

    diff = walk_quality_score - walk_score
    if abs(diff) <= 10:
        return (
            f"Walk quality ({walk_quality_score}) aligns with Walk Score "
            f"({walk_score}) — the walking experience matches amenity proximity."
        )
    elif diff > 10:
        return (
            f"Walk quality ({walk_quality_score}) exceeds Walk Score "
            f"({walk_score}) — the pedestrian environment is better than "
            f"amenity proximity alone suggests."
        )
    else:
        return (
            f"Walk quality ({walk_quality_score}) is lower than Walk Score "
            f"({walk_score}) — despite nearby amenities, the pedestrian "
            f"environment has gaps (sidewalks, lighting, or shade)."
        )


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def assess_walk_quality(
    lat: float,
    lng: float,
    api_key: str,
    sidewalk_pct: Optional[float] = None,
    sidewalk_confidence: Optional[str] = None,
    walk_score: Optional[int] = None,
) -> Optional[WalkQualityAssessment]:
    """Assess walk quality around a property using MAPS-Mini pipeline.

    Combines GSV computer vision with OSM infrastructure data to produce
    a walk quality score (0-100) that evaluates the actual pedestrian
    experience, not just proximity to amenities.

    Args:
        lat: Property latitude.
        lng: Property longitude.
        api_key: Google Maps API key (for GSV Static API).
        sidewalk_pct: Optional sidewalk coverage percentage from
            sidewalk_coverage.py (avoids duplicate Overpass query).
        sidewalk_confidence: Optional data confidence level for sidewalk
            data ("HIGH" / "MEDIUM" / "LOW").
        walk_score: Optional Walk Score value for comparison.

    Returns:
        WalkQualityAssessment or None on complete failure.
    """
    t0 = time.time()

    # 1. Generate sample points
    sample_specs = _generate_sample_points(lat, lng)

    # 2. Check GSV metadata & fetch images at sample points
    sample_points: List[GSVSamplePoint] = []
    total_greenery = 0.0
    total_sky = 0.0
    total_brightness = 0.0
    points_with_coverage = 0

    for pt_lat, pt_lng, heading in sample_specs:
        meta = _gsv_metadata(pt_lat, pt_lng, api_key)
        has_coverage = meta is not None

        point = GSVSamplePoint(
            lat=pt_lat,
            lng=pt_lng,
            heading=heading,
            has_coverage=has_coverage,
            pano_date=meta.get("date") if meta else None,
        )

        if has_coverage:
            # Fetch and analyze GSV image
            img_bytes = _gsv_image(pt_lat, pt_lng, heading, api_key)
            if img_bytes:
                analysis = _analyze_image(img_bytes)
                point.greenery_pct = analysis["greenery_pct"]
                point.sky_pct = analysis["sky_pct"]
                point.brightness = analysis["brightness"]
                total_greenery += point.greenery_pct
                total_sky += point.sky_pct
                total_brightness += point.brightness
                points_with_coverage += 1
            else:
                point.has_coverage = False

        sample_points.append(point)

    gsv_available = points_with_coverage > 0
    avg_greenery = total_greenery / points_with_coverage if points_with_coverage else 0
    avg_sky = total_sky / points_with_coverage if points_with_coverage else 0
    avg_brightness = total_brightness / points_with_coverage if points_with_coverage else 0

    # 3. Query OSM for infrastructure features
    infrastructure = _fetch_infrastructure(lat, lng)

    # 4. Score each feature
    feature_scores = []

    # Sidewalks (from existing sidewalk_coverage or OSM)
    feature_scores.append(_score_sidewalks(sidewalk_pct, sidewalk_confidence))

    # Greenery (GSV)
    feature_scores.append(_score_greenery(avg_greenery, gsv_available))

    # Lighting (OSM + GSV)
    streetlights = infrastructure.streetlight_count if infrastructure else 0
    feature_scores.append(_score_lighting(streetlights, avg_brightness, gsv_available))

    # Crosswalks (OSM)
    crosswalks = infrastructure.crosswalk_count if infrastructure else 0
    feature_scores.append(_score_crosswalks(crosswalks))

    # Buffer / enclosure (GSV)
    feature_scores.append(_score_buffer(avg_sky, avg_greenery, gsv_available))

    # Curb cuts (OSM)
    curb_cuts = infrastructure.curb_cut_count if infrastructure else 0
    feature_scores.append(_score_curb_cuts(curb_cuts))

    # Pedestrian signals (OSM)
    ped_signals = infrastructure.ped_signal_count if infrastructure else 0
    feature_scores.append(_score_ped_signals(ped_signals))

    # 5. Compute weighted overall score
    weighted_sum = sum(fs.score * fs.weight for fs in feature_scores)
    overall_score = round(weighted_sum)
    overall_score = max(0, min(100, overall_score))

    # 6. Classify confidence
    confidence, confidence_note = _classify_confidence(
        points_with_coverage, len(sample_specs), infrastructure
    )

    # 7. Walk Score comparison
    comparison = _walk_score_comparison(overall_score, walk_score)

    elapsed = time.time() - t0
    logger.info(
        "Walk quality assessment: score=%d rating=%s confidence=%s (%.1fs)",
        overall_score, _walk_quality_rating(overall_score), confidence, elapsed,
    )

    return WalkQualityAssessment(
        walk_quality_score=overall_score,
        walk_quality_rating=_walk_quality_rating(overall_score),
        feature_scores=feature_scores,
        sample_points_total=len(sample_specs),
        sample_points_with_coverage=points_with_coverage,
        avg_greenery_pct=round(avg_greenery, 1),
        avg_brightness=round(avg_brightness, 1),
        infrastructure=infrastructure,
        data_confidence=confidence,
        data_confidence_note=confidence_note,
        gsv_available=gsv_available,
        methodology_note=METHODOLOGY_NOTE,
        walk_score_comparison=comparison,
    )
