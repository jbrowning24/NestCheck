"""Lightweight health-risk comparison for multiple addresses.

Runs all spatial Tier 1 checks without the full evaluate_property() pipeline.
Used by the /compare route for instant side-by-side health screening.

No Flask dependencies, no template rendering, no database writes.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from property_evaluator import (
    CheckResult,
    GoogleMapsClient,
    Tier1Check,
    check_flood_zones,
    check_hifld_power_lines,
    check_high_traffic_road,
    check_rail_proximity,
    check_superfund_npl,
    check_tri_proximity,
    check_ust_proximity,
)
from spatial_data import SpatialDataStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# EJScreen spatial check — reads directly from SpatiaLite
# ---------------------------------------------------------------------------

# Human-readable labels for each EJScreen indicator.
# The *_PCT keys in metadata_json hold pre-computed national percentiles
# (0–100) from the EPA EJScreen ArcGIS service.
_EJSCREEN_LABELS = {
    "PTRAF": "Traffic Proximity",
    "PNPL": "Superfund Proximity",
    "PRMP": "RMP Facility Proximity",
    "PTSDF": "Hazardous Waste Proximity",
    "UST": "Underground Storage Tanks",
    "PM25": "Particulate Matter (PM2.5)",
    "OZONE": "Ozone",
    "DSLPM": "Diesel Particulate Matter",
    "CANCER": "Air Toxics Cancer Risk",
    "RESP": "Air Toxics Respiratory Risk",
    "PWDIS": "Wastewater Discharge",
    "LEAD": "Lead Paint Indicator",
}


def check_ejscreen_spatial(
    lat: float, lng: float, spatial_store: SpatialDataStore,
) -> List[Tier1Check]:
    """EJScreen check using national percentiles from local SpatiaLite data.

    Finds the nearest census block group centroid and flags any
    environmental indicators at or above the 80th national percentile.
    Percentiles >= 95 are annotated as "very high".

    Returns a single summary Tier1Check (wrapped in a list for consistency
    with _check_ejscreen_indicators).
    """
    if spatial_store is None or not spatial_store.is_available():
        return [Tier1Check(
            name="ejscreen_environmental",
            result=CheckResult.UNKNOWN,
            details="EJScreen data unavailable for this location",
            value=None,
            required=False,
        )]

    results = spatial_store.find_facilities_within(lat, lng, 2000, "ejscreen")
    if not results:
        return [Tier1Check(
            name="ejscreen_environmental",
            result=CheckResult.UNKNOWN,
            details="EJScreen data unavailable for this location",
            value=None,
            required=False,
        )]

    nearest = results[0]
    meta = nearest.metadata

    elevated: List[str] = []
    highest_pct = 0.0
    has_percentile_data = False

    for key, label in _EJSCREEN_LABELS.items():
        pct_key = f"{key}_PCT"
        raw_pct = meta.get(pct_key)
        if raw_pct is None:
            continue
        try:
            pct = float(raw_pct)
        except (ValueError, TypeError):
            continue
        has_percentile_data = True

        if pct >= 80:
            if pct > highest_pct:
                highest_pct = pct
            note = label
            if pct >= 95:
                note += " (very high)"
            elevated.append(note)

    if elevated:
        return [Tier1Check(
            name="ejscreen_environmental",
            result=CheckResult.WARNING,
            details=(
                f"Elevated environmental indicators: {', '.join(elevated)}"
            ),
            value=round(highest_pct, 1),
            required=False,
        )]

    if not has_percentile_data:
        return [Tier1Check(
            name="ejscreen_environmental",
            result=CheckResult.UNKNOWN,
            details="EJScreen percentile data unavailable for this location",
            value=None,
            required=False,
        )]

    return [Tier1Check(
        name="ejscreen_environmental",
        result=CheckResult.PASS,
        details="Environmental indicators within normal ranges for this area",
        value=None,
        required=False,
    )]


# ---------------------------------------------------------------------------
# Batch runner — all spatial Tier 1 checks for a single address
# ---------------------------------------------------------------------------

def run_health_checks(
    lat: float,
    lng: float,
    formatted_address: str,
    spatial_store: SpatialDataStore,
) -> Dict[str, Any]:
    """Run all spatial health checks for one address.

    Returns a dict with address, coordinates, checks list, and summary.
    The checks list contains Tier1Check instances compatible with
    app.present_checks() after serialisation.
    """
    checks: List[Tier1Check] = []

    # --- High-traffic roads (HPMS) ---
    try:
        checks.append(check_high_traffic_road(lat, lng, spatial_store))
    except Exception as e:
        logger.warning("Health compare: high traffic road check failed: %s", e)
        checks.append(Tier1Check(
            name="High-traffic road",
            result=CheckResult.UNKNOWN,
            details="Traffic data unavailable",
            value=None,
        ))

    # --- Flood zones (FEMA) ---
    try:
        checks.append(check_flood_zones(lat, lng))
    except Exception as e:
        logger.warning("Health compare: flood zone check failed: %s", e)
        checks.append(Tier1Check(
            name="Flood zone",
            result=CheckResult.UNKNOWN,
            details="Flood zone data unavailable",
            value=None,
        ))

    # --- Superfund (SEMS) ---
    try:
        checks.append(check_superfund_npl(lat, lng))
    except Exception as e:
        logger.warning("Health compare: superfund check failed: %s", e)
        checks.append(Tier1Check(
            name="Superfund (NPL)",
            result=CheckResult.UNKNOWN,
            details="Superfund data unavailable",
            value=None,
        ))

    # --- UST ---
    try:
        checks.append(check_ust_proximity(lat, lng, spatial_store))
    except Exception as e:
        logger.warning("Health compare: UST check failed: %s", e)
        checks.append(Tier1Check(
            name="ust_proximity",
            result=CheckResult.UNKNOWN,
            details="UST data unavailable",
            value=None,
        ))

    # --- TRI ---
    try:
        checks.append(check_tri_proximity(lat, lng, spatial_store))
    except Exception as e:
        logger.warning("Health compare: TRI check failed: %s", e)
        checks.append(Tier1Check(
            name="tri_proximity",
            result=CheckResult.UNKNOWN,
            details="TRI data unavailable",
            value=None,
        ))

    # --- Power lines (HIFLD) ---
    try:
        checks.append(check_hifld_power_lines(lat, lng, spatial_store))
    except Exception as e:
        logger.warning("Health compare: power lines check failed: %s", e)
        checks.append(Tier1Check(
            name="hifld_power_lines",
            result=CheckResult.UNKNOWN,
            details="Power line data unavailable",
            value=None,
        ))

    # --- Rail (FRA) ---
    try:
        checks.append(check_rail_proximity(lat, lng, spatial_store))
    except Exception as e:
        logger.warning("Health compare: rail check failed: %s", e)
        checks.append(Tier1Check(
            name="rail_proximity",
            result=CheckResult.UNKNOWN,
            details="Rail data unavailable",
            value=None,
        ))

    # --- EJScreen (spatial) ---
    try:
        checks.extend(check_ejscreen_spatial(lat, lng, spatial_store))
    except Exception as e:
        logger.warning("Health compare: EJScreen check failed: %s", e)
        checks.append(Tier1Check(
            name="ejscreen_environmental",
            result=CheckResult.UNKNOWN,
            details="Environmental indicator data unavailable",
            value=None,
            required=False,
        ))

    # --- Summary ---
    fails = sum(1 for c in checks if c.result == CheckResult.FAIL)
    warnings = sum(1 for c in checks if c.result == CheckResult.WARNING)
    clear = sum(1 for c in checks if c.result == CheckResult.PASS)
    unknown = sum(1 for c in checks if c.result == CheckResult.UNKNOWN)

    if fails > 0:
        worst_result = "FAIL"
    elif warnings > 0:
        worst_result = "WARNING"
    elif unknown > 0:
        worst_result = "UNKNOWN"
    else:
        worst_result = "PASS"

    return {
        "address": formatted_address,
        "lat": lat,
        "lng": lng,
        "checks": checks,
        "summary": {
            "fails": fails,
            "warnings": warnings,
            "clear": clear,
            "unknown": unknown,
            "worst_result": worst_result,
        },
    }


# ---------------------------------------------------------------------------
# Top-level orchestrator — geocode + health checks for multiple addresses
# ---------------------------------------------------------------------------

def compare_addresses(
    addresses: List[str], api_key: str,
) -> Dict[str, Any]:
    """Geocode and run health checks for 2-5 addresses in parallel.

    Returns a dict with results (one per address, in input order),
    total_addresses count, and spatial_available flag.
    """
    spatial_store = SpatialDataStore()
    if not spatial_store.is_available():
        return {
            "results": [
                {
                    "address": addr,
                    "error": "Spatial database not available",
                    "checks": [],
                    "summary": None,
                }
                for addr in addresses
            ],
            "total_addresses": len(addresses),
            "spatial_available": False,
        }

    gmaps = GoogleMapsClient(api_key)

    def _process_single(
        address: str,
        gmaps_client: GoogleMapsClient,
        store: SpatialDataStore,
    ) -> Dict[str, Any]:
        try:
            geo = gmaps_client.geocode_details(address)
            if not geo or not geo.get("lat") or not geo.get("lng"):
                return {
                    "address": address,
                    "error": "Could not geocode this address",
                    "checks": [],
                    "summary": None,
                }
            return run_health_checks(
                geo["lat"], geo["lng"], geo["formatted_address"], store,
            )
        except Exception as e:
            logger.error("Health compare failed for %s: %s", address, e)
            return {
                "address": address,
                "error": str(e),
                "checks": [],
                "summary": None,
            }

    # Map input index → result for order preservation
    index_result: Dict[int, Dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=min(len(addresses), 5)) as executor:
        future_to_idx = {
            executor.submit(
                _process_single, addr, gmaps, spatial_store,
            ): idx
            for idx, addr in enumerate(addresses)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            index_result[idx] = future.result()

    # Restore input order
    results = [index_result[i] for i in range(len(addresses))]

    return {
        "results": results,
        "total_addresses": len(addresses),
        "spatial_available": True,
    }
