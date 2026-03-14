#!/usr/bin/env python3
"""
Generate ground-truth test cases for HPMS high-traffic road proximity checks.

Samples real HPMS road segments from spatial.db, partitions by AADT into
HIGH_TRAFFIC (>= 50K) and LOW_TRAFFIC (10K–50K) pools, and generates test
points at controlled perpendicular offsets from segment midpoints.

More complex than UST because:
- Geometry is LINESTRING, not POINT — distance is to the nearest point on the
  line, not a single coordinate
- Two conditions: distance AND AADT above threshold
- Test points vary on both axes (distance and AADT)

No API calls — everything comes from spatial.db.

Usage:
    python scripts/generate_ground_truth_hpms.py
    python scripts/generate_ground_truth_hpms.py --count 50
    python scripts/generate_ground_truth_hpms.py --state NY
    python scripts/generate_ground_truth_hpms.py --seed 42
    python scripts/generate_ground_truth_hpms.py --output data/ground_truth_hpms.json
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
# Thresholds — canonical values live in property_evaluator.py at ~line 1289.
# HIGH_TRAFFIC_AADT_THRESHOLD = 50_000
# HIGH_TRAFFIC_FAIL_RADIUS_M = 150
# HIGH_TRAFFIC_WARN_RADIUS_M = 300
# These must stay in sync with property_evaluator.py.
# ---------------------------------------------------------------------------
try:
    from property_evaluator import (
        HIGH_TRAFFIC_AADT_THRESHOLD,
        HIGH_TRAFFIC_FAIL_RADIUS_M,
        HIGH_TRAFFIC_WARN_RADIUS_M,
    )

    _THRESHOLDS_IMPORTED = True
except Exception:
    # property_evaluator.py imports Flask/app machinery that may not be
    # available in a standalone script context.
    HIGH_TRAFFIC_AADT_THRESHOLD = 50_000
    HIGH_TRAFFIC_FAIL_RADIUS_M = 150
    HIGH_TRAFFIC_WARN_RADIUS_M = 300
    _THRESHOLDS_IMPORTED = False

# AADT floor for the LOW_TRAFFIC pool — real roads, not dirt roads
LOW_TRAFFIC_AADT_FLOOR = 10_000

# Test distances in meters (perpendicular offset from segment midpoint)
CLOSE_M = 75    # Well inside FAIL zone (threshold 150m)
MIDDLE_M = 225  # WARNING zone (between 150m and 300m)
FAR_M = 500     # Well outside all buffers


def _expected_result_high_traffic(distance_m: float) -> tuple:
    """Return (expected_result, expected_pass, notes_suffix) for a high-traffic point."""
    if distance_m <= HIGH_TRAFFIC_FAIL_RADIUS_M:
        return ("FAIL", False, f"inside {HIGH_TRAFFIC_FAIL_RADIUS_M}m fail radius")
    elif distance_m <= HIGH_TRAFFIC_WARN_RADIUS_M:
        return ("WARNING", False, f"inside {HIGH_TRAFFIC_WARN_RADIUS_M}m warning radius")
    else:
        return ("PASS", True, "outside all buffers")


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


def _query_segments(db_path: str, state_filter: str = None) -> list:
    """Query facilities_hpms from spatial.db, return list of segment dicts.

    Each dict: {name, aadt, start_lat, start_lng, end_lat, end_lng,
                mid_lat, mid_lng, route_name, route_id, metadata}
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.enable_load_extension(True)
        conn.load_extension("mod_spatialite")
    except Exception:
        pass

    try:
        # Extract start/end points of each linestring for bearing computation,
        # plus centroid for midpoint. Filter to segments with non-null AADT.
        where_clause = "WHERE json_extract(metadata_json, '$.aadt') IS NOT NULL"
        params = []

        if state_filter:
            where_clause += " AND json_extract(metadata_json, '$.state') = ?"
            params.append(state_filter.upper())

        rows = conn.execute(
            f"""SELECT
                    name,
                    Y(ST_Centroid(geometry)) as mid_lat,
                    X(ST_Centroid(geometry)) as mid_lng,
                    Y(ST_StartPoint(geometry)) as start_lat,
                    X(ST_StartPoint(geometry)) as start_lng,
                    Y(ST_EndPoint(geometry)) as end_lat,
                    X(ST_EndPoint(geometry)) as end_lng,
                    metadata_json
                FROM facilities_hpms
                {where_clause}""",
            params,
        ).fetchall()

        segments = []
        for r in rows:
            mid_lat, mid_lng = r["mid_lat"], r["mid_lng"]
            if mid_lat is None or mid_lng is None:
                continue
            # Tri-state area sanity check
            if not (38.0 <= mid_lat <= 43.0 and -76.0 <= mid_lng <= -71.0):
                continue

            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except (json.JSONDecodeError, TypeError):
                    continue  # No metadata means no AADT — skip

            aadt = meta.get("aadt")
            if aadt is None:
                continue
            # Cast to float then int — values may arrive as strings after
            # JSON round-tripping (per CLAUDE.md spatial metadata note)
            try:
                aadt = int(float(aadt))
            except (ValueError, TypeError):
                continue

            if aadt <= 0:
                continue

            route_name = meta.get("route_name", "")
            route_id = meta.get("route_id", "")

            # Start/end for bearing — fall back to midpoint if missing
            start_lat = r["start_lat"] or mid_lat
            start_lng = r["start_lng"] or mid_lng
            end_lat = r["end_lat"] or mid_lat
            end_lng = r["end_lng"] or mid_lng

            segments.append({
                "name": r["name"] or route_name or route_id or "Unknown Road",
                "aadt": aadt,
                "mid_lat": mid_lat,
                "mid_lng": mid_lng,
                "start_lat": start_lat,
                "start_lng": start_lng,
                "end_lat": end_lat,
                "end_lng": end_lng,
                "route_name": route_name,
                "route_id": route_id,
                "metadata": meta,
            })
        return segments
    finally:
        conn.close()


def _nearest_high_traffic_distance(conn, lat: float, lng: float) -> tuple:
    """Find distance (meters) and AADT to the nearest HPMS segment with
    AADT >= HIGH_TRAFFIC_AADT_THRESHOLD from (lat, lng).

    Returns (distance_m, aadt, name) or (None, None, None) if none found.
    Uses the same spatial query pattern as lines_within() in spatial_data.py.
    """
    try:
        search_radius_m = 600  # Same as check_high_traffic_road search radius
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
                FROM facilities_hpms
                WHERE ROWID IN (
                    SELECT ROWID FROM SpatialIndex
                    WHERE f_table_name = 'facilities_hpms'
                    AND f_geometry_column = 'geometry'
                    AND search_frame = BuildCircleMbr(?, ?, ?, 4326)
                )
                AND ST_Distance(
                    geometry,
                    MakePoint(?, ?, 4326),
                    1
                ) <= ?
                ORDER BY distance_m ASC""",
            (lng, lat, lng, lat, radius_deg, lng, lat, search_radius_m),
        ).fetchall()

        for row in rows:
            name, dist_m, meta_json = row
            if meta_json:
                try:
                    meta = json.loads(meta_json)
                except (json.JSONDecodeError, TypeError):
                    continue
                aadt = meta.get("aadt")
                if aadt is not None:
                    try:
                        aadt = int(float(aadt))
                    except (ValueError, TypeError):
                        continue
                    if aadt >= HIGH_TRAFFIC_AADT_THRESHOLD:
                        return (dist_m, aadt, name or "Unknown Road")
        return (None, None, None)
    except Exception:
        return (None, None, None)


def main():
    parser = argparse.ArgumentParser(
        description="Generate ground-truth test cases for HPMS high-traffic road proximity checks"
    )
    parser.add_argument(
        "--count", type=int, default=25,
        help="Number of segments to sample per pool (default: 25)",
    )
    parser.add_argument(
        "--state", type=str, default=None,
        help="Filter by state abbreviation (NY, NJ, CT)",
    )
    parser.add_argument(
        "--output", type=str, default="data/ground_truth_hpms.json",
        help="Output file path (default: data/ground_truth_hpms.json)",
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

    print(f"Loading HPMS segments from {db_path}...", flush=True)
    if _THRESHOLDS_IMPORTED:
        print("Thresholds imported from property_evaluator.py", flush=True)
    else:
        print("Thresholds hardcoded (property_evaluator.py import failed)", flush=True)
    print(
        f"  AADT threshold: {HIGH_TRAFFIC_AADT_THRESHOLD:,}  "
        f"FAIL radius: {HIGH_TRAFFIC_FAIL_RADIUS_M}m  "
        f"WARN radius: {HIGH_TRAFFIC_WARN_RADIUS_M}m",
        flush=True,
    )

    segments = _query_segments(db_path, state_filter=args.state)

    if not segments:
        state_msg = f" for state '{args.state}'" if args.state else ""
        print(f"Error: No HPMS segments found{state_msg}.", file=sys.stderr)
        sys.exit(1)

    # Partition into HIGH_TRAFFIC and LOW_TRAFFIC pools
    high_traffic = [s for s in segments if s["aadt"] >= HIGH_TRAFFIC_AADT_THRESHOLD]
    low_traffic = [
        s for s in segments
        if LOW_TRAFFIC_AADT_FLOOR <= s["aadt"] < HIGH_TRAFFIC_AADT_THRESHOLD
    ]

    print(f"Found {len(segments)} segments with AADT data.", flush=True)
    print(f"  HIGH_TRAFFIC (AADT >= {HIGH_TRAFFIC_AADT_THRESHOLD:,}): {len(high_traffic)}", flush=True)
    print(f"  LOW_TRAFFIC (AADT {LOW_TRAFFIC_AADT_FLOOR:,}–{HIGH_TRAFFIC_AADT_THRESHOLD:,}): {len(low_traffic)}", flush=True)

    # Sample from each pool
    if args.count > len(high_traffic):
        print(
            f"Warning: requested {args.count} high-traffic but only "
            f"{len(high_traffic)} available. Using all.",
            file=sys.stderr,
        )
        sampled_high = high_traffic
    else:
        sampled_high = random.sample(high_traffic, args.count)

    if args.count > len(low_traffic):
        print(
            f"Warning: requested {args.count} low-traffic but only "
            f"{len(low_traffic)} available. Using all.",
            file=sys.stderr,
        )
        sampled_low = low_traffic
    else:
        sampled_low = random.sample(low_traffic, args.count)

    total_expected = len(sampled_high) * 3 + len(sampled_low) * 1
    print(
        f"Sampled {len(sampled_high)} high-traffic + {len(sampled_low)} low-traffic "
        f"segments. Generating {total_expected} test points...",
        flush=True,
    )

    # Open a SpatiaLite connection for nearest-neighbor validation
    nn_conn = sqlite3.connect(db_path)
    try:
        nn_conn.enable_load_extension(True)
        nn_conn.load_extension("mod_spatialite")
    except Exception:
        nn_conn = None

    # --- HIGH_TRAFFIC test points: 3 per segment (CLOSE/MIDDLE/FAR) ---
    high_traffic_distances = [
        ("close", CLOSE_M),
        ("middle", MIDDLE_M),
        ("far", FAR_M),
    ]

    addresses = []
    idx = 0
    adjusted_count = 0

    for seg in sampled_high:
        # Compute bearing of segment at midpoint, then offset perpendicular
        bearing = _segment_bearing(
            seg["start_lat"], seg["start_lng"],
            seg["end_lat"], seg["end_lng"],
        )
        # Perpendicular: +90 degrees from segment bearing
        perp_bearing = (bearing + 90) % 360

        for label, dist_m in high_traffic_distances:
            idx += 1
            new_lat, new_lng = _offset_point(
                seg["mid_lat"], seg["mid_lng"], dist_m, perp_bearing,
            )

            # Nearest-neighbor adjustment: check if ANY high-traffic segment
            # (AADT >= 50K) is closer to this test point than expected
            expected_result, expected_pass, notes_suffix = _expected_result_high_traffic(dist_m)
            nn_dist, nn_aadt, nn_name = (None, None, None)

            if nn_conn is not None:
                nn_dist, nn_aadt, nn_name = _nearest_high_traffic_distance(
                    nn_conn, new_lat, new_lng,
                )

            if nn_dist is not None:
                # A high-traffic segment was found — use real distance
                adj_result, adj_pass, adj_suffix = _expected_result_high_traffic(nn_dist)
                if adj_result != expected_result:
                    adjusted_count += 1
                    expected_result = adj_result
                    expected_pass = adj_pass
                    notes_suffix = (
                        f"{adj_suffix} (adjusted: nearest high-traffic segment "
                        f"is {nn_name} at {nn_dist:.0f}m with AADT {nn_aadt:,}, "
                        f"not {dist_m}m as generated)"
                    )
            else:
                # No high-traffic segment found nearby — this means the
                # segment we offset from isn't in the spatial index results.
                # The point should PASS regardless of intended distance.
                if expected_result != "PASS":
                    adjusted_count += 1
                    expected_result = "PASS"
                    expected_pass = True
                    notes_suffix = (
                        "adjusted to PASS: no high-traffic segment found "
                        "within 600m of generated point"
                    )

            display_name = seg["route_name"] or seg["name"]
            addresses.append({
                "id": f"gt-hpms-{idx:04d}",
                "coordinates": {
                    "lat": round(new_lat, 7),
                    "lng": round(new_lng, 7),
                },
                "layer": 4,
                "layer_notes": (
                    f"Synthetic — {dist_m}m perpendicular from "
                    f"{display_name} segment (AADT {seg['aadt']:,})"
                ),
                "source_segment": {
                    "name": display_name,
                    "aadt": seg["aadt"],
                    "midpoint": {
                        "lat": round(seg["mid_lat"], 7),
                        "lng": round(seg["mid_lng"], 7),
                    },
                    "distance_m": dist_m,
                    "bearing_deg": round(perp_bearing, 2),
                },
                "tier1_health_checks": {
                    "high_traffic_road": {
                        "expected_result": expected_result,
                        "expected_pass": expected_pass,
                        "notes": (
                            f"{dist_m}m from {display_name} "
                            f"(AADT {seg['aadt']:,}) — {notes_suffix}"
                        ),
                        "source": "synthetic from spatial.db facilities_hpms",
                    },
                },
                "tier2_scored_dimensions": {},
            })

    # --- LOW_TRAFFIC test points: 1 per segment (CLOSE only) ---
    for seg in sampled_low:
        idx += 1
        bearing = _segment_bearing(
            seg["start_lat"], seg["start_lng"],
            seg["end_lat"], seg["end_lng"],
        )
        perp_bearing = (bearing + 90) % 360
        new_lat, new_lng = _offset_point(
            seg["mid_lat"], seg["mid_lng"], CLOSE_M, perp_bearing,
        )

        # Default: PASS because AADT < threshold even at close range
        expected_result = "PASS"
        expected_pass = True
        notes_suffix = (
            f"AADT {seg['aadt']:,} below {HIGH_TRAFFIC_AADT_THRESHOLD:,} threshold "
            f"— no trigger regardless of distance"
        )

        # Nearest-neighbor adjustment: a different high-traffic segment
        # might be nearby
        if nn_conn is not None:
            nn_dist, nn_aadt, nn_name = _nearest_high_traffic_distance(
                nn_conn, new_lat, new_lng,
            )
            if nn_dist is not None:
                adj_result, adj_pass, adj_suffix = _expected_result_high_traffic(nn_dist)
                if adj_result != "PASS":
                    adjusted_count += 1
                    expected_result = adj_result
                    expected_pass = adj_pass
                    notes_suffix = (
                        f"{adj_suffix} (adjusted: nearby high-traffic segment "
                        f"{nn_name} at {nn_dist:.0f}m with AADT {nn_aadt:,} "
                        f"overrides low-traffic source segment)"
                    )

        display_name = seg["route_name"] or seg["name"]
        addresses.append({
            "id": f"gt-hpms-{idx:04d}",
            "coordinates": {
                "lat": round(new_lat, 7),
                "lng": round(new_lng, 7),
            },
            "layer": 4,
            "layer_notes": (
                f"Synthetic — {CLOSE_M}m perpendicular from "
                f"{display_name} segment (AADT {seg['aadt']:,}, below threshold)"
            ),
            "source_segment": {
                "name": display_name,
                "aadt": seg["aadt"],
                "midpoint": {
                    "lat": round(seg["mid_lat"], 7),
                    "lng": round(seg["mid_lng"], 7),
                },
                "distance_m": CLOSE_M,
                "bearing_deg": round(perp_bearing, 2),
            },
            "tier1_health_checks": {
                "high_traffic_road": {
                    "expected_result": expected_result,
                    "expected_pass": expected_pass,
                    "notes": (
                        f"{CLOSE_M}m from {display_name} "
                        f"(AADT {seg['aadt']:,}) — {notes_suffix}"
                    ),
                    "source": "synthetic from spatial.db facilities_hpms",
                },
            },
            "tier2_scored_dimensions": {},
        })

    if nn_conn is not None:
        nn_conn.close()

    output = {
        "_schema_version": "0.1.0",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_generator": "generate_ground_truth_hpms.py",
        "_segment_count": len(sampled_high) + len(sampled_low),
        "_test_count": len(addresses),
        "_thresholds": {
            "aadt_threshold": HIGH_TRAFFIC_AADT_THRESHOLD,
            "fail_radius_m": HIGH_TRAFFIC_FAIL_RADIUS_M,
            "warn_radius_m": HIGH_TRAFFIC_WARN_RADIUS_M,
            "source": "property_evaluator.py HIGH_TRAFFIC_* constants",
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
          f"{len(sampled_high) + len(sampled_low)} segments.")
    if adjusted_count:
        print(f"Adjusted {adjusted_count} expected results due to nearby segments.")
    print(f"Output: {out_path}")

    # Quick breakdown
    by_result = {}
    for a in addresses:
        r = a["tier1_health_checks"]["high_traffic_road"]["expected_result"]
        by_result[r] = by_result.get(r, 0) + 1
    for r, c in sorted(by_result.items()):
        print(f"  {r}: {c}")


if __name__ == "__main__":
    main()
