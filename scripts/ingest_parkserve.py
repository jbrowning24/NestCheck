#!/usr/bin/env python3
"""
Ingest Trust for Public Land ParkServe park polygon data into the NestCheck spatial database.

Data source: ParkServe Shareable MapServer (ArcGIS REST service)
URL: https://server7.tplgis.org/arcgis7/rest/services/ParkServe/ParkServe_Shareable/MapServer/0
Format: ArcGIS REST API with JSON pagination
Records: ~250K+ park polygons covering 14,000+ cities

This script:
1. Queries the ParkServe MapServer with pagination (chunks of 1000)
2. Converts polygon rings to WKT MULTIPOLYGON
3. Loads into spatial.db as facilities_parkserve table
4. Creates spatial index for point-in-polygon and proximity queries

Idempotent: per-state DELETE + INSERT preserves other states' data.

Usage:
    python scripts/ingest_parkserve.py --discover
    python scripts/ingest_parkserve.py --limit 5   # 5 pages = 5,000 records
    python scripts/ingest_parkserve.py --state NY
    python scripts/ingest_parkserve.py --states NY,NJ,CT
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

from spatial_data import init_spatial_db, _connect

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PARKSERVE_ENDPOINT = (
    "https://server7.tplgis.org/arcgis7/rest/services/ParkServe"
    "/ParkServe_Shareable/MapServer/0/query"
)

PAGE_SIZE = 1000  # This endpoint's max record count

# State FIPS → 2-letter code for deriving state from park_place_fips.
# The API removed the "State" field; park_place_fips first 2 digits = state FIPS.
_FIPS_TO_STATE = {
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA",
    "17": "IL", "24": "MD", "25": "MA", "26": "MI", "34": "NJ",
    "36": "NY", "42": "PA", "48": "TX", "51": "VA", "06": "CA",
    "53": "WA", "01": "AL", "02": "AK", "04": "AZ", "05": "AR",
    "08": "CO", "15": "HI", "16": "ID", "18": "IN", "19": "IA",
    "20": "KS", "21": "KY", "22": "LA", "23": "ME", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV",
    "33": "NH", "35": "NM", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "49": "UT", "50": "VT", "54": "WV", "55": "WI",
    "56": "WY",
}


def _rings_to_multipolygon_wkt(rings: list, decimals: int = 6) -> str | None:
    """Convert ArcGIS rings array to MULTIPOLYGON WKT."""
    if not rings or not isinstance(rings, list):
        return None
    try:
        coord_strings = []
        for ring in rings:
            if not ring or len(ring) < 3:
                continue
            coords = ", ".join(
                f"{round(p[0], decimals)} {round(p[1], decimals)}" for p in ring
            )
            coord_strings.append(coords)
        if not coord_strings:
            return None
        inner = "), (".join(coord_strings)
        return f"MULTIPOLYGON((({inner})))"
    except (TypeError, IndexError, KeyError):
        return None


def _ensure_parkserve_table(conn) -> None:
    """Create facilities_parkserve table if it doesn't exist.

    Uses CREATE TABLE IF NOT EXISTS + SpatiaLite DDL wrapped in try/except,
    same pattern as VenueCache._ensure_table() in spatial_data.py.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS facilities_parkserve (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    try:
        conn.execute(
            "SELECT AddGeometryColumn('facilities_parkserve', 'geometry', 4326, 'MULTIPOLYGON', 'XY')"
        )
    except Exception:
        pass  # Column already exists
    try:
        conn.execute(
            "SELECT CreateSpatialIndex('facilities_parkserve', 'geometry')"
        )
    except Exception:
        pass  # Index already exists
    conn.commit()


def fetch_page(offset: int, where_clause: str = "1=1") -> dict:
    """Fetch one page of ParkServe park records."""
    params = {
        "where": where_clause,
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    for attempt in range(3):
        try:
            resp = requests.get(PARKSERVE_ENDPOINT, params=params, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"ArcGIS error: {data['error']}")
            return data
        except Exception as e:
            if attempt < 2:
                wait = 5 * (attempt + 1)
                logger.warning(
                    "Fetch failed (attempt %d): %s — retrying in %ds",
                    attempt + 1, e, wait,
                )
                time.sleep(wait)
            else:
                raise


def _process_features(conn, features: list) -> tuple[int, int]:
    """Process a batch of ArcGIS features: extract name/metadata, build WKT, INSERT.

    Returns (inserted_count, skipped_count).
    """
    inserted = 0
    skipped = 0

    for feat in features:
        attrs = feat.get("attributes", {})
        geom = feat.get("geometry") or {}

        rings = geom.get("rings")
        if not rings:
            skipped += 1
            continue

        wkt = _rings_to_multipolygon_wkt(rings)
        if not wkt:
            skipped += 1
            continue

        name = (
            attrs.get("park_name")
            or attrs.get("Park_Name")
            or attrs.get("ParkName")
            or attrs.get("NAME")
            or "Unknown Park"
        )
        if isinstance(name, str):
            name = name.strip()
        else:
            name = str(name).strip()

        # Derive state from park_place_fips (first 2 digits = state FIPS)
        place_fips = attrs.get("park_place_fips") or ""
        state_from_fips = _FIPS_TO_STATE.get(place_fips[:2], "") if len(place_fips) >= 2 else ""
        # Fall back to old field names for backwards compatibility
        state_val = state_from_fips or attrs.get("State", "")

        metadata = {
            "park_type": attrs.get("park_designation") or attrs.get("Park_Type", ""),
            "acres": attrs.get("park_size_acres") or attrs.get("Acres") or attrs.get("ACRES"),
            "city": attrs.get("park_place") or attrs.get("City", ""),
            "state": state_val,
            "agency": attrs.get("park_local_owner") or attrs.get("Agency", ""),
            "park_id": attrs.get("parkid") or attrs.get("Park_ID") or attrs.get("ParkID"),
        }

        try:
            conn.execute(
                """INSERT INTO facilities_parkserve (name, geometry, metadata_json)
                   VALUES (?, GeomFromText(?, 4326), ?)""",
                (name, wkt, json.dumps(metadata)),
            )
            inserted += 1
        except Exception as e:
            logger.warning("Insert failed for %s: %s", name[:50], e)
            skipped += 1

    conn.commit()
    return inserted, skipped


_STATE_TO_FIPS = {v: k for k, v in _FIPS_TO_STATE.items()}


def _ingest_state(conn, st: str, limit_pages: int = 0) -> tuple[int, int]:
    """Ingest records for a single state. Returns (inserted, skipped)."""
    fips = _STATE_TO_FIPS.get(st)
    if fips:
        # API removed "State" field (ArcGIS field drift, NES-401).
        # Filter by park_place_fips prefix (first 2 digits = state FIPS).
        where = f"park_place_fips LIKE '{fips}%'"
    else:
        # Fallback for unknown states
        where = f"park_urbanarea LIKE '%, {st}'"
    logger.info("  Deleting existing rows for state %s...", st)
    conn.execute(
        "DELETE FROM facilities_parkserve WHERE json_extract(metadata_json, '$.state') = ?",
        (st,),
    )
    conn.commit()

    total_inserted = 0
    total_skipped = 0
    offset = 0
    batch_num = 0

    while True:
        batch_num += 1
        logger.info("  [%s] Fetching batch %d (offset %d)...", st, batch_num, offset)
        data = fetch_page(offset, where)

        features = data.get("features", [])
        if not features:
            logger.info("  [%s] No more features — done.", st)
            break

        inserted, skipped = _process_features(conn, features)
        total_inserted += inserted
        total_skipped += skipped
        logger.info(
            "  [%s] Batch %d: inserted %d, skipped so far: %d, total: %d",
            st, batch_num, inserted, total_skipped, total_inserted,
        )

        if limit_pages and batch_num >= limit_pages:
            logger.info("  [%s] Page limit reached (%d) — stopping.", st, limit_pages)
            break

        if len(features) < PAGE_SIZE and not data.get("exceededTransferLimit", False):
            logger.info("  [%s] Last page received — done.", st)
            break

        offset += PAGE_SIZE

    return total_inserted, total_skipped


def _ingest_all(conn, limit_pages: int = 0) -> tuple[int, int]:
    """Ingest all records (no state filter). Returns (inserted, skipped)."""
    where = "1=1"
    total_inserted = 0
    total_skipped = 0
    offset = 0
    batch_num = 0

    while True:
        batch_num += 1
        logger.info("Fetching batch %d (offset %d)...", batch_num, offset)
        data = fetch_page(offset, where)

        features = data.get("features", [])
        if not features:
            logger.info("No more features — done.")
            break

        inserted, skipped = _process_features(conn, features)
        total_inserted += inserted
        total_skipped += skipped
        logger.info(
            "  Batch %d: inserted %d, skipped so far: %d, total: %d",
            batch_num, inserted, total_skipped, total_inserted,
        )

        if limit_pages and batch_num >= limit_pages:
            logger.info("Page limit reached (%d) — stopping.", limit_pages)
            break

        if len(features) < PAGE_SIZE and not data.get("exceededTransferLimit", False):
            logger.info("Last page received — done.")
            break

        offset += PAGE_SIZE

    return total_inserted, total_skipped


def ingest(
    limit_pages: int = 0,
    state: str = "",
    states: list[str] | None = None,
    discover: bool = False,
):
    """Main ingestion loop."""

    if discover:
        params = {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
            "resultRecordCount": 1,
        }
        try:
            resp = requests.get(PARKSERVE_ENDPOINT, params=params, timeout=60)
        except Exception as e:
            logger.error("Discover request failed: %s", e)
            return
        if resp.status_code != 200:
            logger.error("HTTP %d from ParkServe endpoint", resp.status_code)
            return
        data = resp.json()
        if "error" in data:
            logger.error("ArcGIS error: %s", json.dumps(data["error"], indent=2))
            return
        if "features" in data and data["features"]:
            feat = data["features"][0]
            attrs = feat.get("attributes", {})
            logger.info("Sample attributes: %.1500s", json.dumps(attrs, indent=2))
            logger.info("Sample geometry keys: %s", list(feat.get("geometry", {}).keys()))
            if feat.get("geometry", {}).get("rings"):
                logger.info("Ring count: %d", len(feat["geometry"]["rings"]))
        return

    # Build state list from params
    state_list: list[str] = []
    if states:
        for s in states:
            st = s.strip().upper()
            if len(st) == 2 and st.isalpha():
                state_list.append(st)
            else:
                raise ValueError(f"Invalid state abbreviation: {s!r} (expected 2-letter code, e.g. NY)")
    elif state:
        st = state.upper()
        if not (len(st) == 2 and st.isalpha()):
            raise ValueError(f"Invalid state abbreviation: {state!r} (expected 2-letter code, e.g. NY)")
        state_list.append(st)

    logger.info("Starting ParkServe park polygon ingestion")
    if state_list:
        logger.info("  States: %s", ", ".join(state_list))
    else:
        logger.info("  States: ALL (no filter)")
    if limit_pages:
        logger.info("  LIMIT: %d pages (%d records)", limit_pages, limit_pages * PAGE_SIZE)

    init_spatial_db()
    conn = _connect()
    _ensure_parkserve_table(conn)
    logger.info("Ensured facilities_parkserve table exists")

    total_inserted = 0
    total_skipped = 0

    try:
        if state_list:
            for st in state_list:
                logger.info("Ingesting state: %s", st)
                inserted, skipped = _ingest_state(conn, st, limit_pages)
                total_inserted += inserted
                total_skipped += skipped
                logger.info("  State %s: inserted %d, skipped %d", st, inserted, skipped)
        else:
            total_inserted, total_skipped = _ingest_all(conn, limit_pages)

        where_desc = ", ".join(state_list) if state_list else "1=1"
        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "parkserve",
                PARKSERVE_ENDPOINT,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                f"WHERE: {where_desc}" + (f", LIMIT: {limit_pages} pages" if limit_pages else ""),
            ),
        )
        conn.commit()

    finally:
        conn.close()

    db_path = (
        os.path.join(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ""), "spatial.db")
        if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
        else os.environ.get("NESTCHECK_SPATIAL_DB_PATH", "data/spatial.db")
    )
    db_size_mb = os.path.getsize(db_path) / (1024 * 1024) if os.path.exists(db_path) else 0

    logger.info("=" * 50)
    logger.info("PARKSERVE INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    logger.info("  DB size:       %.1f MB", db_size_mb)
    logger.info("=" * 50)


def verify():
    """Quick verification: point-in-polygon at Central Park, NYC."""
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    # Central Park — should be inside a park polygon
    results = store.point_in_polygons(40.7829, -73.9654, "parkserve")
    logger.info("Verification: %d parks at Central Park (40.7829, -73.9654)", len(results))
    for r in results[:5]:
        logger.info("  %s — %s acres", r.name, r.metadata.get("acres", ""))

    # Negative: Times Square (not a park)
    results_neg = store.point_in_polygons(40.7580, -73.9855, "parkserve")
    logger.info("Negative test: %d parks at Times Square — expected 0", len(results_neg))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest ParkServe park polygons")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max pages to ingest (0 = all). Each page = 1000 records.",
    )
    parser.add_argument(
        "--state", type=str, default="",
        help="Filter to a single state (e.g., NY, CA).",
    )
    parser.add_argument(
        "--states", type=str, default="",
        help="Comma-separated list of states (e.g., NY,NJ,CT).",
    )
    parser.add_argument(
        "--discover", action="store_true",
        help="Print sample record and exit.",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Run verification after ingestion.",
    )
    args = parser.parse_args()

    if args.discover:
        ingest(discover=True)
    else:
        states_list = [s.strip() for s in args.states.split(",") if s.strip()] if args.states else None
        ingest(limit_pages=args.limit, state=args.state, states=states_list)
        if args.verify:
            verify()
