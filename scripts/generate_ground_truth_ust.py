"""Generate ground-truth test cases for UST proximity checks.

Samples real UST facilities from spatial.db and creates synthetic test
points at controlled distances for scoring calibration.

Usage:
    python scripts/generate_ground_truth_ust.py
    python scripts/generate_ground_truth_ust.py --count 100
    python scripts/generate_ground_truth_ust.py --state "New York"
    python scripts/generate_ground_truth_ust.py --output data/ground_truth_ust.json
    python scripts/generate_ground_truth_ust.py --seed 42
"""

import argparse
import json
import logging
import math
import os
import random
import sys
from datetime import datetime, timezone

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spatial_data import _connect, _spatial_db_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── UST proximity thresholds ──────────────────────────────────────────────
# Canonical values live in property_evaluator.py check_ust_proximity() ~L2319/2328.
# The evaluator uses meters directly (not the scoring_config Tier1Thresholds
# which are in feet). These must stay in sync with the evaluator.
UST_FAIL_METERS = 90      # <= 90m  → FAIL  (~300 ft, CA setback)
UST_WARN_METERS = 150     # <= 150m → WARNING (~500 ft, MD setback)
# Beyond 150m → PASS

# Test point distances (feet) — chosen to land clearly within each zone
CLOSE_DISTANCE_FT = 75     # Well inside FAIL zone (90m ≈ 295ft)
MIDDLE_DISTANCE_FT = 400   # Inside WARNING zone (150m ≈ 492ft)
FAR_DISTANCE_FT = 1000     # Well outside WARNING zone → PASS

FEET_TO_METERS = 0.3048


def _offset_point(
    lat: float, lng: float, distance_ft: float, bearing_deg: float
) -> tuple[float, float]:
    """Compute a new (lat, lng) at distance_ft and bearing from origin.

    Uses a flat-earth approximation valid for short distances (<10 km).
    """
    d_meters = distance_ft * FEET_TO_METERS
    bearing_rad = math.radians(bearing_deg)
    dlat = (d_meters / 111320.0) * math.cos(bearing_rad)
    dlng = (d_meters / (111320.0 * math.cos(math.radians(lat)))) * math.sin(
        bearing_rad
    )
    return (lat + dlat, lng + dlng)


def _expected_result(distance_ft: float) -> tuple[bool, str]:
    """Determine expected pass/fail and notes for a given distance.

    Returns (expected_pass, reason_note).
    """
    d_meters = distance_ft * FEET_TO_METERS
    if d_meters <= UST_FAIL_METERS:
        return (False, f"inside hard-fail buffer ({UST_FAIL_METERS}m / ~300ft)")
    if d_meters <= UST_WARN_METERS:
        return (False, f"inside warning buffer ({UST_WARN_METERS}m / ~500ft)")
    return (True, f"outside warning buffer ({UST_WARN_METERS}m / ~500ft)")


def _expected_check_result(distance_ft: float) -> str:
    """Return the expected CheckResult string for the distance."""
    d_meters = distance_ft * FEET_TO_METERS
    if d_meters <= UST_FAIL_METERS:
        return "FAIL"
    if d_meters <= UST_WARN_METERS:
        return "WARNING"
    return "PASS"


def _query_all_ust_facilities(
    state: str | None = None,
) -> list[dict]:
    """Query all UST facilities from spatial.db.

    Returns list of dicts with name, lat, lng, and metadata.
    """
    db_path = _spatial_db_path()
    if not os.path.exists(db_path):
        logger.error("Spatial DB not found at %s", db_path)
        sys.exit(1)

    conn = _connect()
    try:
        query = """
            SELECT
                name,
                Y(geometry) as lat,
                X(geometry) as lng,
                metadata_json
            FROM facilities_ust
        """
        params: list = []

        if state:
            # metadata_json contains "state" field with full state names
            query += " WHERE json_extract(metadata_json, '$.state') = ?"
            params.append(state)

        cursor = conn.execute(query, params)
        facilities = []
        for row in cursor:
            name, lat, lng, meta_json = row
            if lat is None or lng is None:
                continue
            metadata = json.loads(meta_json) if meta_json else {}
            facilities.append({
                "name": name or "Unknown",
                "lat": lat,
                "lng": lng,
                "metadata": metadata,
            })
        return facilities
    finally:
        conn.close()


def generate_ground_truth(
    count: int = 50,
    state: str | None = None,
    seed: int | None = None,
) -> dict:
    """Generate ground-truth JSON for UST proximity checks.

    Args:
        count: Number of facilities to sample.
        state: Filter by state (full name, e.g. "New York"). None = all.
        seed: Random seed for reproducibility. None = random.

    Returns:
        Ground-truth dict matching the schema.
    """
    rng = random.Random(seed)

    facilities = _query_all_ust_facilities(state)
    logger.info(
        "Found %d UST facilities%s",
        len(facilities),
        f" in {state}" if state else "",
    )

    if not facilities:
        logger.error("No UST facilities found. Check spatial.db.")
        sys.exit(1)

    if count > len(facilities):
        logger.warning(
            "Requested %d facilities but only %d available — using all",
            count,
            len(facilities),
        )
        count = len(facilities)

    sampled = rng.sample(facilities, count)

    test_distances = [
        ("close", CLOSE_DISTANCE_FT),
        ("middle", MIDDLE_DISTANCE_FT),
        ("far", FAR_DISTANCE_FT),
    ]

    addresses = []
    test_id = 0

    for facility in sampled:
        for label, dist_ft in test_distances:
            test_id += 1
            bearing = rng.uniform(0, 360)
            new_lat, new_lng = _offset_point(
                facility["lat"], facility["lng"], dist_ft, bearing
            )
            expected_pass, reason = _expected_result(dist_ft)
            check_result = _expected_check_result(dist_ft)
            fac_name = facility["name"]

            addresses.append({
                "id": f"gt-ust-{test_id:04d}",
                "coordinates": {
                    "lat": round(new_lat, 7),
                    "lng": round(new_lng, 7),
                },
                "layer": 4,
                "layer_notes": (
                    f"Synthetic — generated at {dist_ft}ft "
                    f"({label}) from UST facility {fac_name}"
                ),
                "source_facility": {
                    "name": fac_name,
                    "coordinates": {
                        "lat": round(facility["lat"], 7),
                        "lng": round(facility["lng"], 7),
                    },
                    "distance_ft": dist_ft,
                    "bearing_deg": round(bearing, 2),
                },
                "tier1_health_checks": {
                    "ust_proximity": {
                        "expected_result": check_result,
                        "expected_pass": expected_pass,
                        "notes": (
                            f"Generated {dist_ft}ft from {fac_name} — "
                            f"{reason}"
                        ),
                        "source": "synthetic from spatial.db facilities_ust",
                    },
                },
                "tier2_scored_dimensions": {},
            })

    return {
        "_schema_version": "0.1.0",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_generator": "generate_ground_truth_ust.py",
        "_facility_count": count,
        "_test_count": len(addresses),
        "_thresholds": {
            "fail_meters": UST_FAIL_METERS,
            "warn_meters": UST_WARN_METERS,
            "source": "property_evaluator.py check_ust_proximity() L2319/2328",
        },
        "addresses": addresses,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate ground-truth test cases for UST proximity checks"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=50,
        help="Number of facilities to sample (default: 50)",
    )
    parser.add_argument(
        "--state",
        type=str,
        default=None,
        help='Filter by state (full name, e.g. "New York")',
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/ground_truth_ust.json",
        help="Output file path (default: data/ground_truth_ust.json)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility",
    )

    args = parser.parse_args()
    result = generate_ground_truth(
        count=args.count,
        state=args.state,
        seed=args.seed,
    )

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    logger.info(
        "Wrote %d test points (%d facilities) to %s",
        result["_test_count"],
        result["_facility_count"],
        args.output,
    )


if __name__ == "__main__":
    main()
