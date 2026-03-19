#!/usr/bin/env python3
"""
Generate ground-truth test cases for HIFLD power line proximity checks.

Samples real HIFLD transmission line segments from spatial.db and generates
test points at controlled perpendicular offsets from segment midpoints.

Simpler than HPMS because:
- Single axis: distance only (no AADT threshold)
- Two result states: WARNING (≤60m) and PASS (>60m), no FAIL
- Single pool (all lines are treated equally)

No API calls — everything comes from spatial.db.

Usage:
    python scripts/generate_ground_truth_hifld.py
    python scripts/generate_ground_truth_hifld.py --count 50
    python scripts/generate_ground_truth_hifld.py --seed 42
    python scripts/generate_ground_truth_hifld.py --output data/ground_truth/hifld.json
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
# Thresholds — canonical values live in property_evaluator.py check_hifld_power_lines().
# WARNING_RADIUS_M = 60  (~200ft)
# SEARCH_RADIUS_M  = 300
# These must stay in sync with property_evaluator.py.
# ---------------------------------------------------------------------------
HIFLD_WARNING_RADIUS_M = 60
HIFLD_SEARCH_RADIUS_M = 300

# Test distances in meters (perpendicular offset from segment midpoint)
CLOSE_M = 15   # Well inside WARNING zone (threshold 60m)
MIDDLE_M = 45  # Still inside WARNING zone
FAR_M = 150    # Well outside WARNING zone


def _expected_result(distance_m: float) -> tuple:
    """Return (expected_result, expected_pass, notes_suffix) for a test point."""
    if distance_m <= HIFLD_WARNING_RADIUS_M:
        return ("WARNING", False, f"inside {HIFLD_WARNING_RADIUS_M}m warning radius")
    else:
        return ("PASS", True, "outside warning radius")


def _offset_point(lat: float, lng: float, distance_m: float, bearing_deg: float):
    """Generate a point at distance_m from (lat, lng) along bearing_deg.

    Uses simplified haversine offset (accurate for short distances < 1km).
    """
    bearing_rad = math.radians(bearing_deg)
    lat_rad = math.radians(lat)

    dlat = (distance_m / 111320.0) * math.cos(bearing_rad)
    dlng = (distance_m / (111320.0 * math.cos(lat_rad))) * math.sin(bearing_rad)

    return (lat + dlat, lng + dlng)


def _segment_bearing(start_lat, start_lng, end_lat, end_lng):
    """Calculate bearing from start to end point in degrees [0, 360).

    Standard forward-azimuth formula.
    """
    lat1 = math.radians(start_lat)
    lat2 = math.radians(end_lat)
    dlon = math.radians(end_lng - start_lng)

    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(x, y))
    return bearing % 360


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


def _query_lines(db_path: str) -> list:
    """Query facilities_hifld from spatial.db, return list of line segment dicts.

    Each dict: {name, voltage, volt_class, mid_lat, mid_lng,
                start_lat, start_lng, end_lat, end_lng, metadata}

    HIFLD geometry is MULTILINESTRING. We extract the first component
    via ST_GeometryN for bearing calculation.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.enable_load_extension(True)
        conn.load_extension("mod_spatialite")
    except Exception:
        pass

    try:
        rows = conn.execute(
            """SELECT
                    name,
                    Y(ST_Centroid(geometry)) as mid_lat,
                    X(ST_Centroid(geometry)) as mid_lng,
                    Y(ST_StartPoint(ST_GeometryN(geometry, 1))) as start_lat,
                    X(ST_StartPoint(ST_GeometryN(geometry, 1))) as start_lng,
                    Y(ST_EndPoint(ST_GeometryN(geometry, 1))) as end_lat,
                    X(ST_EndPoint(ST_GeometryN(geometry, 1))) as end_lng,
                    metadata_json
                FROM facilities_hifld"""
        ).fetchall()

        lines = []
        for r in rows:
            mid_lat, mid_lng = r["mid_lat"], r["mid_lng"]
            if mid_lat is None or mid_lng is None:
                continue
            # Continental US sanity check (HIFLD is national data)
            if not (24.0 <= mid_lat <= 50.0 and -125.0 <= mid_lng <= -66.0):
                continue

            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except (json.JSONDecodeError, TypeError):
                    pass

            voltage = meta.get("voltage", "")
            if voltage:
                try:
                    voltage = int(float(voltage))
                    # HIFLD uses -999999 as missing-data sentinel
                    if voltage < 0:
                        voltage = ""
                except (ValueError, TypeError):
                    voltage = ""

            volt_class = meta.get("volt_class", "")

            # Start/end for bearing — fall back to midpoint if missing
            start_lat = r["start_lat"] or mid_lat
            start_lng = r["start_lng"] or mid_lng
            end_lat = r["end_lat"] or mid_lat
            end_lng = r["end_lng"] or mid_lng

            lines.append({
                "name": r["name"] or volt_class or "Unknown Line",
                "voltage": voltage,
                "volt_class": volt_class,
                "mid_lat": mid_lat,
                "mid_lng": mid_lng,
                "start_lat": start_lat,
                "start_lng": start_lng,
                "end_lat": end_lat,
                "end_lng": end_lng,
                "metadata": meta,
            })
        return lines
    finally:
        conn.close()


def _nearest_line_distance(conn, lat: float, lng: float) -> tuple:
    """Find distance (meters) to the nearest HIFLD line from (lat, lng).

    Returns (distance_m, name, voltage) or (None, None, None) if none found.
    Uses the same spatial query pattern as lines_within() in spatial_data.py.
    """
    try:
        search_radius_m = HIFLD_SEARCH_RADIUS_M
        radius_deg = search_radius_m / 80000.0
        rows = conn.execute(
            """SELECT
                    name,
                    ST_Distance(
                        geometry,
                        MakePoint(?, ?, 4326),
                        1
                    ) as distance_m,
                    metadata_json
                FROM facilities_hifld
                WHERE ROWID IN (
                    SELECT ROWID FROM SpatialIndex
                    WHERE f_table_name = 'facilities_hifld'
                    AND f_geometry_column = 'geometry'
                    AND search_frame = BuildCircleMbr(?, ?, ?, 4326)
                )
                AND ST_Distance(
                    geometry,
                    MakePoint(?, ?, 4326),
                    1
                ) <= ?
                ORDER BY distance_m ASC
                LIMIT 1""",
            (lng, lat, lng, lat, radius_deg, lng, lat, search_radius_m),
        ).fetchall()

        if rows:
            name, dist_m, meta_json = rows[0]
            voltage = ""
            if meta_json:
                try:
                    meta = json.loads(meta_json)
                    voltage = meta.get("voltage", "")
                except (json.JSONDecodeError, TypeError):
                    pass
            return (dist_m, name or "Unknown Line", voltage)
        return (None, None, None)
    except Exception:
        return (None, None, None)


def main():
    parser = argparse.ArgumentParser(
        description="Generate ground-truth test cases for HIFLD power line proximity checks"
    )
    parser.add_argument(
        "--count", type=int, default=50,
        help="Number of line segments to sample (default: 50)",
    )
    parser.add_argument(
        "--output", type=str, default="data/ground_truth/hifld.json",
        help="Output file path (default: data/ground_truth/hifld.json)",
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

    print(f"Loading HIFLD lines from {db_path}...", flush=True)
    print(
        f"  WARNING radius: {HIFLD_WARNING_RADIUS_M}m  "
        f"Search radius: {HIFLD_SEARCH_RADIUS_M}m",
        flush=True,
    )

    lines = _query_lines(db_path)

    if not lines:
        print("Error: No HIFLD line segments found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(lines)} HIFLD line segments.", flush=True)

    # Sample from available lines
    if args.count > len(lines):
        print(
            f"Warning: requested {args.count} but only "
            f"{len(lines)} available. Using all.",
            file=sys.stderr,
        )
        sampled = lines
    else:
        sampled = random.sample(lines, args.count)

    total_expected = len(sampled) * 3  # 3 test points per segment
    print(
        f"Sampled {len(sampled)} segments. "
        f"Generating {total_expected} test points...",
        flush=True,
    )

    # Open a SpatiaLite connection for nearest-neighbor validation
    nn_conn = sqlite3.connect(db_path)
    try:
        nn_conn.enable_load_extension(True)
        nn_conn.load_extension("mod_spatialite")
    except Exception:
        nn_conn = None

    # Generate 3 test points per segment: CLOSE / MIDDLE / FAR
    test_distances = [
        ("close", CLOSE_M),
        ("middle", MIDDLE_M),
        ("far", FAR_M),
    ]

    addresses = []
    idx = 0
    adjusted_count = 0

    for seg in sampled:
        # Compute bearing of segment, then offset perpendicular (+90°)
        bearing = _segment_bearing(
            seg["start_lat"], seg["start_lng"],
            seg["end_lat"], seg["end_lng"],
        )
        perp_bearing = (bearing + 90) % 360

        for label, dist_m in test_distances:
            idx += 1
            new_lat, new_lng = _offset_point(
                seg["mid_lat"], seg["mid_lng"], dist_m, perp_bearing,
            )

            # Nearest-neighbor adjustment: check if ANY HIFLD line is closer
            # to this test point than the intended offset distance
            expected_result, expected_pass, notes_suffix = _expected_result(dist_m)
            nn_dist, nn_name, nn_voltage = (None, None, None)

            if nn_conn is not None:
                nn_dist, nn_name, nn_voltage = _nearest_line_distance(
                    nn_conn, new_lat, new_lng,
                )

            if nn_dist is not None:
                # A line was found — use real distance for expected result
                adj_result, adj_pass, adj_suffix = _expected_result(nn_dist)
                if adj_result != expected_result:
                    adjusted_count += 1
                    expected_result = adj_result
                    expected_pass = adj_pass
                    notes_suffix = (
                        f"{adj_suffix} (adjusted: nearest line "
                        f"is {nn_name} at {nn_dist:.0f}m, "
                        f"not {dist_m}m as generated)"
                    )
            else:
                # No line found nearby — point should PASS
                if expected_result != "PASS":
                    adjusted_count += 1
                    expected_result = "PASS"
                    expected_pass = True
                    notes_suffix = (
                        "adjusted to PASS: no HIFLD line found "
                        f"within {HIFLD_SEARCH_RADIUS_M}m of generated point"
                    )

            voltage_label = f"{seg['voltage']}kV" if seg["voltage"] else seg["volt_class"] or "unknown voltage"
            addresses.append({
                "id": f"gt-hifld-{idx:04d}",
                "coordinates": {
                    "lat": round(new_lat, 7),
                    "lng": round(new_lng, 7),
                },
                "layer": 4,
                "layer_notes": (
                    f"Synthetic — {dist_m}m perpendicular from "
                    f"{seg['name']} ({voltage_label})"
                ),
                "source_segment": {
                    "name": seg["name"],
                    "voltage": seg["voltage"],
                    "volt_class": seg["volt_class"],
                    "midpoint": {
                        "lat": round(seg["mid_lat"], 7),
                        "lng": round(seg["mid_lng"], 7),
                    },
                    "distance_m": dist_m,
                    "bearing_deg": round(perp_bearing, 2),
                },
                "tier1_health_checks": {
                    "hifld_power_lines": {
                        "expected_result": expected_result,
                        "expected_pass": expected_pass,
                        "notes": (
                            f"{dist_m}m from {seg['name']} "
                            f"({voltage_label}) — {notes_suffix}"
                        ),
                        "source": "synthetic from spatial.db facilities_hifld",
                    },
                },
                "tier2_scored_dimensions": {},
            })

    if nn_conn is not None:
        nn_conn.close()

    output = {
        "_schema_version": "0.1.0",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_generator": "generate_ground_truth_hifld.py",
        "_segment_count": len(sampled),
        "_test_count": len(addresses),
        "_thresholds": {
            "warning_radius_m": HIFLD_WARNING_RADIUS_M,
            "search_radius_m": HIFLD_SEARCH_RADIUS_M,
            "source": "property_evaluator.py check_hifld_power_lines() — WARNING ≤ 60m",
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

    print(f"\nGenerated {len(addresses)} test points from "
          f"{len(sampled)} segments.")
    if adjusted_count:
        print(f"Adjusted {adjusted_count} expected results due to nearby lines.")
    print(f"Output: {out_path}")

    # Quick breakdown
    by_result = {}
    for a in addresses:
        r = a["tier1_health_checks"]["hifld_power_lines"]["expected_result"]
        by_result[r] = by_result.get(r, 0) + 1
    for r, c in sorted(by_result.items()):
        print(f"  {r}: {c}")


if __name__ == "__main__":
    main()
