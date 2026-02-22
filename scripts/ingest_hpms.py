#!/usr/bin/env python3
"""
Ingest FHWA HPMS road segments with AADT traffic counts into the NestCheck spatial database.

Data source: FHWA Highway Performance Monitoring System (per-state ArcGIS REST)
URL: https://geo.dot.gov/server/rest/services/Hosted/{StateName}_2018_PR/FeatureServer/0/query
Format: ArcGIS REST API with JSON pagination
Records: ~500K–2M+ nationally across 52 states/territories

This script:
1. Iterates over 52 per-state FeatureServer endpoints
2. Converts polyline paths to WKT MULTILINESTRING (same as HIFLD)
3. Loads into spatial.db as facilities_hpms table
4. Stores AADT and road metadata for health proximity scoring

Idempotent: drops and recreates the table on each run.
Run time: 30+ minutes for full national dataset.

Usage:
    python scripts/ingest_hpms.py
    python scripts/ingest_hpms.py --state MA
    python scripts/ingest_hpms.py --states MA,CA,NY
    python scripts/ingest_hpms.py --limit 5   # 5 pages per state
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import requests

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spatial_data import init_spatial_db, create_facility_table, _connect

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

HPMS_BASE_URL = "https://geo.dot.gov/server/rest/services/Hosted"
PAGE_SIZE = 2000
SLEEP_BETWEEN_STATES = 0.75

STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "PR",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY",
]

# geo.dot.gov uses full state names for 2018_PR services (e.g. Massachusetts_2018_PR)
STATE_TO_SERVICE = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "NewHampshire", "NJ": "NewJersey", "NM": "NewMexico",
    "NY": "NewYork", "NC": "NorthCarolina", "ND": "NorthDakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "PR": "PuertoRico",
    "RI": "RhodeIsland", "SC": "SouthCarolina", "SD": "SouthDakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "WestVirginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def _paths_to_multilinestring_wkt(paths: list, decimals: int = 6) -> str | None:
    """
    Convert ArcGIS paths array to MULTILINESTRING WKT.
    ArcGIS paths: [x,y] = [lng, lat]. Same as ingest_hifld.py.
    """
    if not paths or not isinstance(paths, list):
        return None
    try:
        parts = []
        for path in paths:
            if not path or len(path) < 2:
                continue
            coords = ", ".join(
                f"{round(p[0], decimals)} {round(p[1], decimals)}" for p in path
            )
            parts.append(f"({coords})")
        if not parts:
            return None
        return f"MULTILINESTRING({','.join(parts)})"
    except (TypeError, IndexError, KeyError):
        return None


def _state_endpoint(state: str) -> str:
    """Build the query URL for a state (uses full name, e.g. Massachusetts_2018_PR)."""
    service_name = STATE_TO_SERVICE.get(state, state)
    return f"{HPMS_BASE_URL}/{service_name}_2018_PR/FeatureServer/0/query"


def _probe_aadt_field(state: str) -> str | None:
    """
    Probe one page to discover which AADT field exists.
    Prefer exact "AADT" or "aadt"; fall back to any field containing AADT.
    Returns field name or None if not found.
    """
    url = _state_endpoint(state)
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "false",
        "f": "json",
        "resultRecordCount": 1,
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if "error" in data:
            return None
        features = data.get("features", [])
        if not features:
            return None
        attrs = features[0].get("attributes", {})
        # Prefer exact AADT (case-insensitive)
        for key in attrs:
            if key.upper() == "AADT":
                return key
        # Fall back to any field containing AADT
        for key in attrs:
            if "AADT" in key.upper():
                return key
        return None
    except Exception:
        return None


def fetch_page(state: str, offset: int, out_fields: str) -> tuple[dict | None, str | None]:
    """
    Fetch one page of HPMS records for a state.
    Returns (data, error_msg). error_msg is set on 404 or fatal error.
    """
    url = _state_endpoint(state)
    params = {
        "where": "1=1",
        "outFields": out_fields,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=90)
            if resp.status_code == 404:
                return None, "404"
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                err = data["error"]
                msg = err.get("message", err) if isinstance(err, dict) else err
                return None, str(msg)
            return data, None
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return None, "404"
            if attempt < 2:
                wait = 5 * (attempt + 1)
                logger.warning(
                    "[%s] Fetch failed (attempt %d): %s — retrying in %ds",
                    state, attempt + 1, e, wait,
                )
                time.sleep(wait)
            else:
                return None, str(e)
        except Exception as e:
            if attempt < 2:
                wait = 5 * (attempt + 1)
                logger.warning(
                    "[%s] Fetch failed (attempt %d): %s — retrying in %ds",
                    state, attempt + 1, e, wait,
                )
                time.sleep(wait)
            else:
                return None, str(e)
    return None, "Max retries exceeded"


def _attr(attrs: dict, *keys: str, default=None):
    """Get attribute case-insensitively. Tries exact match then uppercase."""
    for k in keys:
        if k in attrs:
            return attrs[k]
        uk = k.upper()
        for key, val in attrs.items():
            if key.upper() == uk:
                return val
    return default


def _safe_int(val) -> int | None:
    """Convert to int, return None for null/invalid."""
    if val is None:
        return None
    try:
        v = int(val)
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None


def ingest_state(
    conn,
    state: str,
    limit_pages: int,
    state_counts: dict,
    state_errors: dict,
    state_skipped: dict,
    aadt_field_cache: dict,
) -> int:
    """
    Ingest one state. Returns count inserted for this state.
    Updates state_counts, state_errors, state_skipped in place.
    """
    total_for_state = 0
    skipped_for_state = 0
    offset = 0
    page_num = 0

    # Probe for AADT field (cache per state)
    if state not in aadt_field_cache:
        aadt_field = _probe_aadt_field(state)
        aadt_field_cache[state] = aadt_field
        if not aadt_field:
            logger.warning("[%s] No AADT field found in schema — storing null for aadt", state)
    aadt_field = aadt_field_cache[state]

    out_fields = "*"  # Use * to handle field name variations across states

    while True:
        page_num += 1
        data, err = fetch_page(state, offset, out_fields)
        if err:
            if err == "404":
                logger.warning("[%s] Error: 404 — skipping", state)
                state_errors[state] = "404"
            else:
                logger.warning("[%s] Error: %s — skipping", state, err[:80])
                state_errors[state] = err[:200]
            state_counts[state] = total_for_state
            state_skipped[state] = skipped_for_state
            return total_for_state

        features = data.get("features", [])
        if not features:
            break

        inserted_this_batch = 0
        for feat in features:
            attrs = feat.get("attributes", {})
            geom = feat.get("geometry") or {}

            paths = geom.get("paths")
            if not paths:
                skipped_for_state += 1
                continue

            wkt = _paths_to_multilinestring_wkt(paths)
            if not wkt:
                skipped_for_state += 1
                continue

            name = _attr(attrs, "ROUTE_ID", "route_id") or "HPMS segment"
            if isinstance(name, str):
                name = name.strip()
            else:
                name = str(name).strip() if name else "HPMS segment"

            aadt_val = None
            if aadt_field:
                raw = attrs.get(aadt_field)
                aadt_val = _safe_int(raw)

            metadata = {
                "aadt": aadt_val,
                "state_code": _attr(attrs, "STATE_CODE", "state_code") or state,
                "route_id": _attr(attrs, "ROUTE_ID", "route_id") or "",
                "f_system": _attr(attrs, "F_SYSTEM", "f_system"),
                "facility_type": _attr(attrs, "FACILITY_TYPE", "facility_type"),
                "through_lanes": _attr(attrs, "THROUGH_LANES", "through_lanes"),
                "speed_limit": _attr(attrs, "SPEED_LIMIT", "speed_limit"),
            }

            try:
                conn.execute(
                    """INSERT INTO facilities_hpms (name, geometry, metadata_json)
                       VALUES (?, GeomFromText(?, 4326), ?)""",
                    (name, wkt, json.dumps(metadata)),
                )
                inserted_this_batch += 1
                total_for_state += 1
            except Exception as e:
                logger.warning("[%s] Insert failed for %s: %s", state, name[:30], e)
                skipped_for_state += 1

        conn.commit()
        logger.info(
            "[%s] Fetching... %s segments ingested",
            state,
            f"{total_for_state:,}",
        )

        if limit_pages and page_num >= limit_pages:
            break

        if len(features) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    state_counts[state] = total_for_state
    state_skipped[state] = skipped_for_state
    return total_for_state


def ingest(
    states_filter: list[str] | None = None,
    limit_pages: int = 0,
    discover: bool = False,
):
    """Main ingestion loop."""

    if discover:
        for state in (states_filter or ["MA"])[:1]:
            url = _state_endpoint(state)
            params = {
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "json",
                "resultRecordCount": 1,
            }
            try:
                resp = requests.get(url, params=params, timeout=30)
                print(f"[{state}] HTTP {resp.status_code}")
                if resp.status_code == 200:
                    data = resp.json()
                    if "error" in data:
                        print(f"  Error: {data['error']}")
                    elif data.get("features"):
                        feat = data["features"][0]
                        print("  Attributes:", json.dumps(feat.get("attributes", {}), indent=2)[:800])
                        print("  Geometry keys:", list(feat.get("geometry", {}).keys()))
                        aadt_field = _probe_aadt_field(state)
                        print(f"  AADT field: {aadt_field}")
            except Exception as e:
                print(f"  Exception: {e}")
        return

    states_to_run = list(dict.fromkeys(states_filter)) if states_filter else STATES
    logger.info("Starting HPMS ingestion")
    logger.info("  States: %s", ", ".join(states_to_run))
    if limit_pages:
        logger.info("  LIMIT: %d pages per state (%d records)", limit_pages, limit_pages * PAGE_SIZE)

    init_spatial_db()
    create_facility_table("hpms", geometry_type="MULTILINESTRING")
    logger.info("Created facilities_hpms table")

    conn = _connect()
    total_inserted = 0
    state_counts = {}
    state_errors = {}
    state_skipped = {}
    aadt_field_cache = {}

    t0 = time.time()

    try:
        for i, state in enumerate(states_to_run):
            if i > 0:
                time.sleep(SLEEP_BETWEEN_STATES)
            count = ingest_state(
                conn, state, limit_pages, state_counts, state_errors,
                state_skipped, aadt_field_cache,
            )
            total_inserted += count

        failed_states = [s for s in states_to_run if s in state_errors]
        notes_parts = [f"states={len(states_to_run)}"]
        if failed_states:
            notes_parts.append(f"failed={','.join(failed_states)}")
        if limit_pages:
            notes_parts.append(f"limit={limit_pages}pages")

        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "hpms",
                f"{HPMS_BASE_URL}/{{State}}_2018_PR/FeatureServer/0/query",
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                "; ".join(notes_parts),
            ),
        )
        conn.commit()

    finally:
        conn.close()

    elapsed = time.time() - t0
    db_path = (
        os.path.join(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ""), "spatial.db")
        if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
        else os.environ.get("NESTCHECK_SPATIAL_DB_PATH", "data/spatial.db")
    )
    db_size_mb = os.path.getsize(db_path) / (1024 * 1024) if os.path.exists(db_path) else 0

    total_skipped = sum(state_skipped.values())

    # Summary table
    logger.info("=" * 60)
    logger.info("HPMS INGESTION COMPLETE")
    logger.info("  Total inserted: %s", f"{total_inserted:,}")
    logger.info("  Total skipped:  %s", f"{total_skipped:,}")
    logger.info("  Wall-clock:     %.1f min", elapsed / 60)
    logger.info("  DB size:       %.1f MB", db_size_mb)
    logger.info("-" * 60)
    logger.info("Per-state summary:")
    for state in states_to_run:
        cnt = state_counts.get(state, 0)
        err = state_errors.get(state, "")
        status = f"{cnt:,} segments" if not err else f"ERROR: {err}"
        logger.info("  [%s] %s", state, status)
    logger.info("=" * 60)


def verify():
    """Quick verification: lines near downtown Boston with AADT."""
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    results = store.lines_within(42.35, -71.05, 1000, "hpms")
    logger.info("Verification: %d HPMS segments within 1km of Boston", len(results))
    for r in results[:10]:
        meta = r.metadata
        logger.info(
            "  %s: AADT=%s, dist=%.0fm",
            r.name[:40], meta.get("aadt"), r.distance_meters,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest FHWA HPMS road segments")
    parser.add_argument(
        "--state", type=str, default="",
        help="Single state (e.g., MA).",
    )
    parser.add_argument(
        "--states", type=str, default="",
        help="Comma-separated states (e.g., MA,CA,NY).",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max pages per state (0 = all). Each page = 2000 records.",
    )
    parser.add_argument(
        "--discover", action="store_true",
        help="Print sample record and schema, then exit.",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Run verification after ingestion.",
    )
    args = parser.parse_args()

    states_filter = None
    if args.state:
        states_filter = [args.state.upper()]
    elif args.states:
        states_filter = [s.strip().upper() for s in args.states.split(",") if s.strip()]

    if args.discover:
        ingest(discover=True, states_filter=states_filter or ["MA"])
    else:
        ingest(states_filter=states_filter, limit_pages=args.limit)
        if args.verify:
            verify()
