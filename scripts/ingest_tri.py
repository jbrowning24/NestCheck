#!/usr/bin/env python3
"""
Ingest EPA Toxic Release Inventory (TRI) facility data into the NestCheck spatial database.

Data source: EPA TRI Reporting Facilities (ArcGIS REST service)
URL: https://gispub.epa.gov/arcgis/rest/services/OEI/TRI_Reporting_Facilities/MapServer/0
Format: ArcGIS REST API with JSON pagination (fallback: Envirofacts REST)
Records: ~21K facilities nationally (most recent reporting year)

This script:
1. Tries ArcGIS REST endpoint first; falls back to Envirofacts if ArcGIS fails
2. Extracts facility name, coordinates, industry, and release data
3. Loads into spatial.db as facilities_tri table
4. Creates spatial index for proximity queries

Idempotent: drops and recreates the table on each run.
Run time: ~2-5 minutes for full national dataset.

Usage:
    python scripts/ingest_tri.py
    python scripts/ingest_tri.py --limit 500   # dev/test: first 500 only
    python scripts/ingest_tri.py --state MA   # single state
"""

import argparse
import json
import logging
import os
import re
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

# ArcGIS REST endpoint for TRI Reporting Facilities
TRI_ARCGIS_ENDPOINT = (
    "https://gispub.epa.gov/arcgis/rest/services"
    "/OEI/TRI_Reporting_Facilities/MapServer/0/query"
)

# Envirofacts fallback (no key, 10K row default)
TRI_ENVIROFACTS_BASE = "https://data.epa.gov/efservice/tri.tri_facility"

# Fields to fetch from ArcGIS
OUT_FIELDS = [
    "OBJECTID",
    "FACILITY_NAME",
    "STREET_ADDRESS",
    "CITY",
    "STATE",
    "INDUSTRY",
    "TRI_FACILITY_ID",
    "EPA_REGISTRY_ID",
    "REPORTING_YEAR",
    "TOTAL_RELEASES_lb",
]

PAGE_SIZE_ARCGIS = 2000
PAGE_SIZE_ENVIROFACTS = 10000


def _strip_html_tri_id(raw: str) -> str:
    """Strip HTML tags from TRI_FACILITY_ID (ArcGIS returns <a href=...>id</a>)."""
    if not raw:
        return ""
    return re.sub(r"<[^>]+>", "", str(raw)).strip()


def fetch_page_arcgis(offset: int, where_clause: str = "1=1") -> dict:
    """Fetch one page of TRI records from the ArcGIS REST API."""
    params = {
        "where": where_clause,
        "outFields": ",".join(OUT_FIELDS),
        "returnGeometry": "true",
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "outSR": "4326",  # WGS84
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE_ARCGIS,
    }
    for attempt in range(3):
        try:
            resp = requests.get(TRI_ARCGIS_ENDPOINT, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"ArcGIS error: {data['error']}")
            return data
        except Exception as e:
            if attempt < 2:
                wait = 5 * (attempt + 1)
                logger.warning(
                    "ArcGIS fetch failed (attempt %d): %s — retrying in %ds",
                    attempt + 1, e, wait,
                )
                time.sleep(wait)
            else:
                raise


def fetch_page_envirofacts(start: int, state: str = "") -> list:
    """Fetch one page of TRI records from Envirofacts REST API.
    Returns list of row dicts. Envirofacts uses 1-based row indexing."""
    end = start + PAGE_SIZE_ENVIROFACTS - 1
    if state:
        url = f"{TRI_ENVIROFACTS_BASE}/state/equals/{state}/rows/{start}:{end}/JSON"
    else:
        url = f"{TRI_ENVIROFACTS_BASE}/rows/{start}:{end}/JSON"
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            if attempt < 2:
                wait = 5 * (attempt + 1)
                logger.warning(
                    "Envirofacts fetch failed (attempt %d): %s — retrying in %ds",
                    attempt + 1, e, wait,
                )
                time.sleep(wait)
            else:
                raise


def _get_coords_from_envirofacts(row: dict) -> tuple:
    """Extract (lat, lng) from Envirofacts row. Try common column names."""
    lat = row.get("LATITUDE83") or row.get("PREF_LATITUDE")
    lng = row.get("LONGITUDE83") or row.get("PREF_LONGITUDE")
    if lat is not None and lng is not None:
        try:
            return float(lat), float(lng)
        except (TypeError, ValueError):
            pass
    return None, None


def discover_fields():
    """Hit ArcGIS endpoint to discover fields; if it fails, try Envirofacts."""
    # Try ArcGIS first
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultRecordCount": 1,
    }
    resp = requests.get(TRI_ARCGIS_ENDPOINT, params=params, timeout=30)
    if resp.status_code != 200:
        print(f"ERROR: ArcGIS HTTP {resp.status_code}")
        print(resp.text[:500])
        print("\nTrying Envirofacts fallback...")
    else:
        data = resp.json()
        if "error" in data:
            print(f"ERROR from ArcGIS: {json.dumps(data['error'], indent=2)}")
            print("\nTrying Envirofacts fallback...")
        else:
            if "fields" in data:
                print("ArcGIS available fields:")
                for field in data["fields"]:
                    print(f"  {field['name']} ({field['type']})")
            if "features" in data and data["features"]:
                print("\nArcGIS sample record:")
                feat = data["features"][0]
                print(f"  Attributes: {json.dumps(feat.get('attributes', {}), indent=2)}")
                print(f"  Geometry: {feat.get('geometry', {})}")
            return

    # Envirofacts fallback
    try:
        rows = fetch_page_envirofacts(1)
        if rows:
            print("Envirofacts sample record (keys):")
            print(f"  {list(rows[0].keys())}")
            print(f"  Sample: {json.dumps(rows[0], indent=2, default=str)[:1000]}...")
        else:
            print("Envirofacts returned empty list")
    except Exception as e:
        print(f"Envirofacts discover failed: {e}")


def _try_arcgis_first() -> bool:
    """Probe ArcGIS endpoint. Returns True if it works."""
    try:
        data = fetch_page_arcgis(0, "1=1")
        return "features" in data and (not data.get("error"))
    except Exception as e:
        logger.warning("ArcGIS probe failed: %s — will use Envirofacts", e)
        return False


def ingest(limit: int = 0, state: str = "", discover: bool = False):
    """Main ingestion loop."""

    if discover:
        discover_fields()
        return

    # Build WHERE clause for ArcGIS (STATE uses 2-letter abbrev, e.g. MA)
    where = "1=1"
    if state:
        where = f"STATE = '{state.upper()}'"

    logger.info("Starting TRI facility ingestion")
    logger.info("  WHERE: %s", where)
    if limit:
        logger.info("  LIMIT: %d records", limit)

    # Step 1: Initialize spatial DB and create table
    init_spatial_db()
    create_facility_table("tri")
    logger.info("Created facilities_tri table")

    conn = _connect()
    total_inserted = 0
    total_skipped = 0
    source_url = ""

    try:
        if _try_arcgis_first():
            source_url = TRI_ARCGIS_ENDPOINT
            total_inserted, total_skipped = _ingest_from_arcgis(
                conn, where, limit, total_inserted, total_skipped
            )
        else:
            source_url = TRI_ENVIROFACTS_BASE
            total_inserted, total_skipped = _ingest_from_envirofacts(
                conn, state, limit, total_inserted, total_skipped
            )

        # Update dataset registry
        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "tri",
                source_url,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                f"WHERE: {where}" + (f", LIMIT: {limit}" if limit else ""),
            ),
        )
        conn.commit()

    finally:
        conn.close()

    # Report
    db_path = (
        os.path.join(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ""), "spatial.db")
        if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
        else os.environ.get("NESTCHECK_SPATIAL_DB_PATH", "data/spatial.db")
    )
    db_size_mb = os.path.getsize(db_path) / (1024 * 1024) if os.path.exists(db_path) else 0

    logger.info("=" * 50)
    logger.info("TRI INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    logger.info("  DB size:        %.1f MB", db_size_mb)
    logger.info("=" * 50)


def _ingest_from_arcgis(conn, where: str, limit: int, total_inserted: int, total_skipped: int):
    """Ingest from ArcGIS. Returns (total_inserted, total_skipped)."""
    offset = 0
    batch_num = 0

    while True:
        batch_num += 1
        logger.info("Fetching batch %d (offset %d)...", batch_num, offset)
        data = fetch_page_arcgis(offset, where)

        features = data.get("features", [])
        if not features:
            logger.info("No more features — done.")
            break

        inserted_this_batch = 0
        for feat in features:
            attrs = feat.get("attributes", {})
            geom = feat.get("geometry", {})

            lng = geom.get("x")
            lat = geom.get("y")

            if lng is None or lat is None:
                total_skipped += 1
                continue
            if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                total_skipped += 1
                continue

            name = (attrs.get("FACILITY_NAME") or "Unknown").strip()
            metadata = {
                "tri_facility_id": _strip_html_tri_id(attrs.get("TRI_FACILITY_ID", "")),
                "address": attrs.get("STREET_ADDRESS", ""),
                "city": attrs.get("CITY", ""),
                "state": attrs.get("STATE", ""),
                "zip": "",
                "industry_sector": attrs.get("INDUSTRY", ""),
                "reporting_year": attrs.get("REPORTING_YEAR", ""),
                "total_releases_lb": attrs.get("TOTAL_RELEASES_lb"),
                "epa_registry_id": attrs.get("EPA_REGISTRY_ID", ""),
            }

            conn.execute(
                """INSERT INTO facilities_tri
                   (name, geometry, metadata_json)
                   VALUES (?, MakePoint(?, ?, 4326), ?)""",
                (name, lng, lat, json.dumps(metadata)),
            )
            inserted_this_batch += 1
            total_inserted += 1

            if limit and total_inserted >= limit:
                break

        conn.commit()
        logger.info(
            "  Batch %d: inserted %d, skipped so far: %d, total: %d",
            batch_num, inserted_this_batch, total_skipped, total_inserted,
        )

        if limit and total_inserted >= limit:
            logger.info("Limit reached (%d) — stopping.", limit)
            break

        if len(features) < PAGE_SIZE_ARCGIS:
            logger.info("Last page received — done.")
            break

        offset += PAGE_SIZE_ARCGIS

    return total_inserted, total_skipped


def _ingest_from_envirofacts(conn, state: str, limit: int, total_inserted: int, total_skipped: int):
    """Ingest from Envirofacts. Returns (total_inserted, total_skipped)."""
    start = 1  # Envirofacts uses 1-based indexing
    batch_num = 0

    while True:
        batch_num += 1
        logger.info("Fetching Envirofacts batch %d (rows %d-%d)...", batch_num, start, start + PAGE_SIZE_ENVIROFACTS - 1)
        rows = fetch_page_envirofacts(start, state.upper() if state else "")

        if not rows:
            logger.info("No more rows — done.")
            break

        inserted_this_batch = 0
        for row in rows:
            lat, lng = _get_coords_from_envirofacts(row)
            if lat is None or lng is None:
                total_skipped += 1
                continue
            if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                total_skipped += 1
                continue

            name = (row.get("FACILITY_NAME") or row.get("facility_name") or "Unknown")
            if isinstance(name, str):
                name = name.strip()
            else:
                name = str(name).strip()

            metadata = {
                "tri_facility_id": _strip_html_tri_id(
                    row.get("TRI_FACILITY_ID", row.get("tri_facility_id", ""))
                ),
                "address": row.get("STREET_ADDRESS", row.get("street_address", "")),
                "city": row.get("CITY", row.get("city_name", "")),
                "state": row.get("STATE_ABBR", row.get("state_abbr", "")),
                "zip": row.get("ZIP_CODE", row.get("zip_code", "")),
                "industry_sector": row.get("INDUSTRY_SECTOR", row.get("industry_sector", "")),
                "reporting_year": row.get("REPORTING_YEAR", row.get("reporting_year", "")),
                "total_releases_lb": row.get("TOTAL_RELEASES_LB"),
                "epa_registry_id": row.get("EPA_REGISTRY_ID", row.get("epa_registry_id", "")),
            }

            conn.execute(
                """INSERT INTO facilities_tri
                   (name, geometry, metadata_json)
                   VALUES (?, MakePoint(?, ?, 4326), ?)""",
                (name, lng, lat, json.dumps(metadata)),
            )
            inserted_this_batch += 1
            total_inserted += 1

            if limit and total_inserted >= limit:
                break

        conn.commit()
        logger.info(
            "  Batch %d: inserted %d, skipped so far: %d, total: %d",
            batch_num, inserted_this_batch, total_skipped, total_inserted,
        )

        if limit and total_inserted >= limit:
            logger.info("Limit reached (%d) — stopping.", limit)
            break

        if len(rows) < PAGE_SIZE_ENVIROFACTS:
            logger.info("Last page received — done.")
            break

        start += PAGE_SIZE_ENVIROFACTS

    return total_inserted, total_skipped


def verify():
    """Quick verification: query a known TRI-heavy location."""
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    # Boston area — TRI facilities in MA/NH region; Houston for full national ingest
    results = store.find_facilities_within(42.3601, -71.0589, 5000, "tri")
    logger.info("Verification: %d TRI facilities within 5km of Boston", len(results))
    for r in results[:5]:
        logger.info(
            "  %s — %.0f ft (%.0f m) — %s",
            r.name, r.distance_feet, r.distance_meters,
            r.metadata.get("industry_sector", ""),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest EPA TRI facility data")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max records to ingest (0 = all). Use for dev/testing.",
    )
    parser.add_argument(
        "--state", type=str, default="",
        help="Filter to a single state (e.g., MA, TX). Default: all states.",
    )
    parser.add_argument(
        "--discover", action="store_true",
        help="Print available fields and a sample record, then exit.",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Run a verification query after ingestion.",
    )
    args = parser.parse_args()

    if args.discover:
        discover_fields()
    else:
        ingest(limit=args.limit, state=args.state)
        if args.verify:
            verify()
