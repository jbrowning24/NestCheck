#!/usr/bin/env python3
"""
Generate ground-truth test cases for UST proximity checks.

Samples real UST facilities from spatial.db and creates test points at
controlled distances (CLOSE/MIDDLE/FAR) with known expected results.

No API calls — everything comes from spatial.db.

Usage:
    python scripts/generate_ground_truth_ust.py
    python scripts/generate_ground_truth_ust.py --count 100
    python scripts/generate_ground_truth_ust.py --state NY
    python scripts/generate_ground_truth_ust.py --seed 42
    python scripts/generate_ground_truth_ust.py --output data/ground_truth_ust.json
"""

import argparse
import json
import math
import os
import random
import sqlite3
import sys
from datetime import datetime, timezone

# Project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Thresholds — canonical source: scoring_config.py Tier1Thresholds
#   ust_fail_m = 90   (FAIL <= 90m)
#   ust_warn_m = 150  (WARNING <= 150m)
# property_evaluator.py imports via _T1 = SCORING_MODEL.tier1.
# These hardcoded fallbacks must stay in sync with Tier1Thresholds.
# ---------------------------------------------------------------------------
UST_FAIL_METERS = 90      # <= 90m → FAIL
UST_WARN_METERS = 150     # <= 150m → WARNING
UST_SEARCH_METERS = 500   # search radius used by evaluator

# Test distances in feet
CLOSE_FT = 75     # Well inside FAIL zone (75ft ≈ 22.9m, threshold 90m ≈ 295ft)
MIDDLE_FT = 400   # WARNING zone (400ft ≈ 121.9m, between 90m and 150m)
FAR_FT = 1000     # Well outside all buffers (1000ft ≈ 304.8m)

FEET_TO_METERS = 0.3048

# Full state name mapping for --state filter
# ArcGIS UST dataset uses no-space state names ("NewYork", not "New York")
_STATE_ABBREV_TO_FULL = {
    "NY": "NewYork",
    "NJ": "NewJersey",
    "CT": "Connecticut",
}


def _expected_result(distance_ft: float) -> tuple:
    """Return (expected_result, expected_pass, notes_suffix) for a distance."""
    distance_m = distance_ft * FEET_TO_METERS
    if distance_m <= UST_FAIL_METERS:
        return ("FAIL", False, "inside hard-fail buffer")
    elif distance_m <= UST_WARN_METERS:
        return ("WARNING", False, "inside warning buffer")
    else:
        return ("PASS", True, "outside all buffers")


def _offset_point(lat: float, lng: float, distance_ft: float, bearing_deg: float):
    """Generate a point at distance_ft from (lat, lng) along bearing_deg.

    Uses simplified haversine offset (accurate for short distances).
    """
    distance_m = distance_ft * FEET_TO_METERS
    bearing_rad = math.radians(bearing_deg)
    lat_rad = math.radians(lat)

    dlat = (distance_m / 111320.0) * math.cos(bearing_rad)
    dlng = (distance_m / (111320.0 * math.cos(lat_rad))) * math.sin(bearing_rad)

    return (lat + dlat, lng + dlng)


def _query_facilities(db_path: str, state_filter: str = None) -> list:
    """Query facilities_ust from spatial.db, return list of dicts.

    Each dict: {name, lat, lng, state, metadata}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Load SpatiaLite for Y()/X() geometry functions
        conn.enable_load_extension(True)
        conn.load_extension("mod_spatialite")
    except Exception:
        pass  # May already be available or fail gracefully
    try:
        # Use Y(geometry)/X(geometry) for lat/lng extraction (SpatiaLite)
        if state_filter:
            full_state = _STATE_ABBREV_TO_FULL.get(
                state_filter.upper(), state_filter
            )
            rows = conn.execute(
                """SELECT name, Y(geometry) as lat, X(geometry) as lng,
                          metadata_json
                   FROM facilities_ust
                   WHERE json_extract(metadata_json, '$.state') = ?""",
                (full_state,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT name, Y(geometry) as lat, X(geometry) as lng,
                          metadata_json
                   FROM facilities_ust"""
            ).fetchall()

        facilities = []
        for r in rows:
            lat, lng = r["lat"], r["lng"]
            if lat is None or lng is None:
                continue
            # Basic coordinate sanity — tri-state area
            if not (38.0 <= lat <= 43.0 and -76.0 <= lng <= -71.0):
                continue
            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            facilities.append({
                "name": r["name"] or "Unknown UST Facility",
                "lat": lat,
                "lng": lng,
                "state": meta.get("state", ""),
                "metadata": meta,
            })
        return facilities
    finally:
        conn.close()


def _nearest_facility_distance(conn, lat: float, lng: float) -> float | None:
    """Find distance (meters) to the nearest UST facility from (lat, lng).

    Returns None if SpatiaLite spatial query fails or no facilities nearby.
    """
    try:
        row = conn.execute(
            """SELECT MIN(ST_Distance(geometry, MakePoint(?, ?, 4326), 1))
               FROM facilities_ust
               WHERE ROWID IN (
                   SELECT ROWID FROM SpatialIndex
                   WHERE f_table_name = 'facilities_ust'
                   AND f_geometry_column = 'geometry'
                   AND search_frame = BuildCircleMbr(?, ?, 0.01, 4326)
               )""",
            (lng, lat, lng, lat),
        ).fetchone()
        return row[0] if row and row[0] is not None else None
    except Exception:
        return None


def _find_spatial_db() -> str:
    """Locate spatial.db using the same resolution as spatial_data.py."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(project_root, "data", "spatial.db"),
        os.path.join(project_root, "spatial.db"),
        "/data/spatial.db",  # Railway volume mount
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]  # Return default for error message


def main():
    parser = argparse.ArgumentParser(
        description="Generate ground-truth test cases for UST proximity checks"
    )
    parser.add_argument(
        "--count", type=int, default=50,
        help="Number of facilities to sample (default: 50)",
    )
    parser.add_argument(
        "--state", type=str, default=None,
        help="Filter by state abbreviation (NY, NJ, CT) or full name",
    )
    parser.add_argument(
        "--output", type=str, default="data/ground_truth_ust.json",
        help="Output file path (default: data/ground_truth_ust.json)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    db_path = _find_spatial_db()
    if not os.path.exists(db_path):
        print(f"Error: spatial.db not found at {db_path}", file=sys.stderr)
        print("Run ingest scripts first or set correct path.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading facilities from {db_path}...", flush=True)
    facilities = _query_facilities(db_path, state_filter=args.state)

    if not facilities:
        state_msg = f" for state '{args.state}'" if args.state else ""
        print(f"Error: No UST facilities found{state_msg}.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(facilities)} UST facilities.", flush=True)

    if args.count > len(facilities):
        print(
            f"Warning: requested {args.count} but only {len(facilities)} "
            f"available. Using all.",
            file=sys.stderr,
        )
        sampled = facilities
    else:
        sampled = random.sample(facilities, args.count)

    print(f"Sampled {len(sampled)} facilities. Generating test points...", flush=True)

    # Open a SpatiaLite connection for nearest-neighbor validation
    nn_conn = sqlite3.connect(db_path)
    try:
        nn_conn.enable_load_extension(True)
        nn_conn.load_extension("mod_spatialite")
    except Exception:
        nn_conn = None

    test_distances = [
        ("close", CLOSE_FT),
        ("middle", MIDDLE_FT),
        ("far", FAR_FT),
    ]

    addresses = []
    idx = 0
    adjusted_count = 0
    for facility in sampled:
        for label, dist_ft in test_distances:
            idx += 1
            bearing = random.uniform(0, 360)
            new_lat, new_lng = _offset_point(
                facility["lat"], facility["lng"], dist_ft, bearing
            )

            # Check actual nearest facility distance at the generated point.
            # The test point may be closer to a DIFFERENT facility than the
            # one we generated from — use the real nearest distance for the
            # expected result to avoid false mismatches.
            actual_nearest_m = None
            if nn_conn is not None:
                actual_nearest_m = _nearest_facility_distance(
                    nn_conn, new_lat, new_lng
                )

            if actual_nearest_m is not None:
                actual_nearest_ft = actual_nearest_m / FEET_TO_METERS
                expected_result, expected_pass, notes_suffix = _expected_result(
                    actual_nearest_ft
                )
                if expected_result != _expected_result(dist_ft)[0]:
                    adjusted_count += 1
                    notes_suffix += (
                        f" (adjusted: nearest facility is "
                        f"{actual_nearest_ft:.0f}ft away, not "
                        f"{dist_ft}ft as generated)"
                    )
            else:
                actual_nearest_ft = None
                expected_result, expected_pass, notes_suffix = _expected_result(
                    dist_ft
                )

            addresses.append({
                "id": f"gt-ust-{idx:04d}",
                "coordinates": {
                    "lat": round(new_lat, 7),
                    "lng": round(new_lng, 7),
                },
                "layer": 4,
                "layer_notes": (
                    f"Synthetic — generated at {dist_ft}ft ({label}) "
                    f"from UST facility {facility['name']}"
                ),
                "source_facility": {
                    "name": facility["name"],
                    "coordinates": {
                        "lat": round(facility["lat"], 7),
                        "lng": round(facility["lng"], 7),
                    },
                    "distance_ft": dist_ft,
                    "distance_meters": round(dist_ft * FEET_TO_METERS, 2),
                    "bearing_deg": round(bearing, 2),
                    "actual_nearest_ft": (
                        round(actual_nearest_ft, 1)
                        if actual_nearest_ft is not None
                        else None
                    ),
                },
                "tier1_health_checks": {
                    "ust_proximity": {
                        "expected_result": expected_result,
                        "expected_pass": expected_pass,
                        "notes": (
                            f"Generated {dist_ft}ft from {facility['name']} "
                            f"— {notes_suffix}"
                        ),
                        "source": "synthetic from spatial.db facilities_ust",
                    },
                },
                "tier2_scored_dimensions": {},
            })

    if nn_conn is not None:
        nn_conn.close()

    output = {
        "_schema_version": "0.1.0",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_generator": "generate_ground_truth_ust.py",
        "_facility_count": len(sampled),
        "_test_count": len(addresses),
        "_thresholds": {
            "fail_meters": UST_FAIL_METERS,
            "warn_meters": UST_WARN_METERS,
            "search_meters": UST_SEARCH_METERS,
            "source": "property_evaluator.py check_ust_proximity()",
        },
        "addresses": addresses,
    }

    # Ensure output directory exists
    out_path = args.output
    if not os.path.isabs(out_path):
        project_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        out_path = os.path.join(project_root, out_path)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nGenerated {len(addresses)} test points from {len(sampled)} facilities.")
    if adjusted_count:
        print(f"Adjusted {adjusted_count} expected results due to nearby facilities.")
    print(f"Output: {out_path}")

    # Quick breakdown
    by_result = {}
    for a in addresses:
        r = a["tier1_health_checks"]["ust_proximity"]["expected_result"]
        by_result[r] = by_result.get(r, 0) + 1
    for r, c in sorted(by_result.items()):
        print(f"  {r}: {c}")


if __name__ == "__main__":
    main()
