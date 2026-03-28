"""
NLCD Tree Canopy Cover — address-level vegetation analysis.

Queries MRLC's WMS endpoint for NLCD 30m tree canopy data within a
configurable buffer around an address. Returns mean canopy percentage.

Data source: USGS NLCD Tree Canopy Cover (2021), served via MRLC GeoServer.
Resolution: 30m pixels, CONUS coverage, no API key required.

Standalone module — no Flask or evaluation pipeline dependencies.
"""

import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Cache helpers — imported from models.py at module level.
# If models.py is unavailable (e.g., standalone testing), cache is a no-op.
try:
    from models import get_canopy_cache, set_canopy_cache
except ImportError:
    def get_canopy_cache(cache_key):
        return None

    def set_canopy_cache(cache_key, data_json):
        pass


# MRLC WMS endpoint for NLCD Tree Canopy Cover
_WMS_BASE_URL = (
    "https://www.mrlc.gov/geoserver/mrlc_display"
    "/nlcd_tcc_conus_2021_v2021-4/wms"
)

_WMS_TIMEOUT = 15  # seconds per request
_THREAD_WORKERS = 5
_REQUEST_RETRIES = 1


@dataclass
class CanopyCoverResult:
    """Result of a canopy cover analysis within a buffer around an address."""
    canopy_pct: float       # Mean canopy % (0-100) across valid sample points
    sample_count: int       # Number of valid samples obtained
    buffer_m: int           # Buffer radius used
    source: str             # Data source identifier


def _generate_sample_grid(
    lat: float, lng: float, buffer_m: int,
) -> List[Tuple[float, float]]:
    """Generate a grid of sample points within a circular buffer.

    Returns ~21-25 points in a 5x5 grid, pruned to the buffer circle.
    Uses latitude-corrected longitude spacing.
    """
    # Convert buffer to degrees — use 0.8× buffer so the 5×5 grid fits
    # comfortably within the circle (corners at ~1.13× buffer, pruned by check)
    lat_step = buffer_m * 0.8 / 111320.0  # meters per degree latitude
    lng_step = buffer_m * 0.8 / (111320.0 * math.cos(math.radians(lat)))

    points = []
    for i in range(-2, 3):
        for j in range(-2, 3):
            plat = lat + i * lat_step / 2.0
            plng = lng + j * lng_step / 2.0
            # Check if point is within the buffer circle
            dlat_m = (plat - lat) * 111320.0
            dlng_m = (plng - lng) * 111320.0 * math.cos(math.radians(lat))
            dist_m = math.sqrt(dlat_m ** 2 + dlng_m ** 2)
            if dist_m <= buffer_m * 1.02:
                points.append((plat, plng))
    return points


def _query_wms_canopy(lat: float, lng: float) -> Optional[int]:
    """Query MRLC WMS for canopy % at a single point.

    Returns canopy percentage (0-100) or None on failure.
    """
    # Small bbox centered on the point (WMS 1.1.1: x=lng, y=lat)
    delta = 0.001
    params = {
        "service": "WMS",
        "version": "1.1.1",
        "request": "GetFeatureInfo",
        "layers": "nlcd_tcc_conus_2021_v2021-4",
        "query_layers": "nlcd_tcc_conus_2021_v2021-4",
        "info_format": "application/json",
        "srs": "EPSG:4326",
        "bbox": f"{lng - delta},{lat - delta},{lng + delta},{lat + delta}",
        "width": "3",
        "height": "3",
        "x": "1",
        "y": "1",
    }

    for attempt in range(_REQUEST_RETRIES + 1):
        try:
            resp = requests.get(_WMS_BASE_URL, params=params, timeout=_WMS_TIMEOUT)
            if resp.status_code != 200:
                if attempt < _REQUEST_RETRIES:
                    continue
                return None
            data = resp.json()
            features = data.get("features", [])
            if not features:
                return None
            props = features[0].get("properties", {})
            value = props.get("PALETTE_INDEX")
            if value is not None and 0 <= value <= 100:
                return int(value)
            return None
        except Exception:
            if attempt < _REQUEST_RETRIES:
                continue
            return None
    return None


def get_canopy_cover(
    lat: float, lng: float, buffer_m: int = 500,
) -> Optional[CanopyCoverResult]:
    """Query NLCD tree canopy cover within a buffer around coordinates.

    1. Check canopy_cache -> return if fresh
    2. Generate ~25 sample points in a grid within buffer
    3. Query MRLC WMS GetFeatureInfo for each point (parallel)
    4. Compute mean canopy %, cache result, return

    Returns None on endpoint failure or if no valid samples obtained.
    Never raises — all errors are logged and swallowed.
    """
    cache_key = f"canopy:{lat:.4f},{lng:.4f}"

    # Check cache
    try:
        cached = get_canopy_cache(cache_key)
        if cached:
            data = json.loads(cached)
            return CanopyCoverResult(
                canopy_pct=data["canopy_pct"],
                sample_count=data["sample_count"],
                buffer_m=data["buffer_m"],
                source=data["source"],
            )
    except Exception:
        logger.warning("Canopy cache parse failed", exc_info=True)

    # Generate sample grid
    points = _generate_sample_grid(lat, lng, buffer_m)
    if not points:
        return None

    # Query WMS in parallel
    valid_values = []
    try:
        with ThreadPoolExecutor(max_workers=_THREAD_WORKERS) as executor:
            futures = {
                executor.submit(_query_wms_canopy, plat, plng): (plat, plng)
                for plat, plng in points
            }
            for future in as_completed(futures):
                try:
                    value = future.result()
                    if value is not None:
                        valid_values.append(value)
                except Exception:
                    pass
    except Exception:
        logger.warning("Canopy WMS query failed", exc_info=True)
        return None

    if not valid_values:
        logger.info("No valid canopy samples obtained for %.4f, %.4f", lat, lng)
        return None

    mean_pct = round(sum(valid_values) / len(valid_values), 1)

    result = CanopyCoverResult(
        canopy_pct=mean_pct,
        sample_count=len(valid_values),
        buffer_m=buffer_m,
        source="nlcd_2021",
    )

    # Cache the result
    try:
        set_canopy_cache(cache_key, json.dumps({
            "canopy_pct": result.canopy_pct,
            "sample_count": result.sample_count,
            "buffer_m": result.buffer_m,
            "source": result.source,
        }))
    except Exception:
        logger.warning("Canopy cache write failed", exc_info=True)

    return result
