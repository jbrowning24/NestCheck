#!/usr/bin/env python3
"""
Ingest EPA UST Finder data into the NestCheck spatial database.

Data source: EPA UST Finder (ArcGIS REST service)
URL: https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/US_Underground_Storage_Tank_2019/FeatureServer/0
Format: ArcGIS REST API with JSON pagination
Records: ~800K facilities nationally (data as of 2018-2020)

This script:
1. Queries the ArcGIS REST endpoint with pagination (chunks of 2000)
2. Extracts facility name, coordinates, status, and address
3. Loads into spatial.db as facilities_ust table
4. Creates spatial index for proximity queries

Idempotent: drops and recreates the table on each run.
Run time: ~10-30 minutes depending on network speed.

Usage:
    python scripts/ingest_ust.py
    python scripts/ingest_ust.py --limit 5000   # dev/test: first 5000 only
    python scripts/ingest_ust.py --state "New York"  # single state
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

# ArcGIS REST endpoint for UST Finder (ArcGIS Online)
UST_ENDPOINT = (
    "https://services.arcgis.com/cJ9YHowT8TU7DUyn"
    "/arcgis/rest/services/US_Underground_Storage_Tank_2019"
    "/FeatureServer/0/query"
)

# Fields to fetch (minimize payload — only what we need)
OUT_FIELDS = [
    "OBJECTID",
    "Facility_ID",
    "Name",
    "Address",
    "City",
    "County",
    "State",
    "Zip_Code",
    "Latitude",
    "Longitude",
    "Open_USTs",
    "Closed_USTs",
    "TOS_USTs",
    "Facility_Status",
]

PAGE_SIZE = 2000  # ArcGIS default max is usually 1000-2000


def fetch_page(offset: int, where_clause: str = "1=1") -> dict:
    """Fetch one page of UST records from the ArcGIS REST API."""
    params = {
        "where": where_clause,
        "outFields": ",".join(OUT_FIELDS),
        "returnGeometry": "true",
        "geometryType": "esriGeometryPoint",
        "spatialRel": "esriSpatialRelIntersects",
        "outSR": "4326",  # WGS84
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    for attempt in range(3):
        try:
            resp = requests.get(UST_ENDPOINT, params=params, timeout=60)
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


def discover_fields():
    """Hit the endpoint once to discover available field names."""
    params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultRecordCount": 1,
    }
    resp = requests.get(UST_ENDPOINT, params=params, timeout=30)
    if resp.status_code != 200:
        print(f"ERROR: HTTP {resp.status_code}")
        print(resp.text[:500])
        return None
    data = resp.json()
    if "error" in data:
        print(f"ERROR from ArcGIS: {json.dumps(data['error'], indent=2)}")
        return None
    if "fields" in data:
        print("Available fields:")
        for field in data["fields"]:
            print(f"  {field['name']} ({field['type']})")
    if "features" in data and data["features"]:
        print("\nSample record:")
        feat = data["features"][0]
        print(f"  Attributes: {json.dumps(feat.get('attributes', {}), indent=2)}")
        print(f"  Geometry: {feat.get('geometry', {})}")
    return data


def ingest(limit: int = 0, state: str = "", discover: bool = False):
    """Main ingestion loop."""

    if discover:
        discover_fields()
        return

    # Build WHERE clause (State field uses full names, e.g. "New York")
    where = "1=1"
    if state:
        where = f"State = '{state}'"

    logger.info("Starting UST Finder ingestion")
    logger.info("  WHERE: %s", where)
    if limit:
        logger.info("  LIMIT: %d records", limit)

    # Step 1: Initialize spatial DB and create table
    init_spatial_db()
    create_facility_table("ust")
    logger.info("Created facilities_ust table")

    # Step 2: Paginate through the API
    conn = _connect()
    total_inserted = 0
    total_skipped = 0
    offset = 0
    batch_num = 0

    try:
        while True:
            batch_num += 1
            logger.info(
                "Fetching batch %d (offset %d)...", batch_num, offset
            )
            data = fetch_page(offset, where)

            features = data.get("features", [])
            if not features:
                logger.info("No more features — done.")
                break

            # Insert batch
            inserted_this_batch = 0
            for feat in features:
                attrs = feat.get("attributes", {})
                geom = feat.get("geometry", {})

                lng = geom.get("x")
                lat = geom.get("y")

                # Skip records without valid coordinates
                if lng is None or lat is None:
                    total_skipped += 1
                    continue

                # Skip obviously bad coordinates
                if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                    total_skipped += 1
                    continue

                name = (attrs.get("Name") or "Unknown").strip()

                metadata = {
                    "address": attrs.get("Address", ""),
                    "city": attrs.get("City", ""),
                    "state": attrs.get("State", ""),
                    "zip": attrs.get("Zip_Code", ""),
                    "status": attrs.get("Facility_Status", ""),
                    "object_id": attrs.get("OBJECTID"),
                    "facility_id": attrs.get("Facility_ID", ""),
                    "county": attrs.get("County", ""),
                    "open_usts": attrs.get("Open_USTs", 0),
                    "closed_usts": attrs.get("Closed_USTs", 0),
                    "tos_usts": attrs.get("TOS_USTs", 0),
                }

                conn.execute(
                    """INSERT INTO facilities_ust
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

            # Check if there are more results
            if not data.get("exceededTransferLimit", False):
                # ArcGIS signals no more pages
                if len(features) < PAGE_SIZE:
                    logger.info("Last page received — done.")
                    break

            offset += PAGE_SIZE

        # Step 3: Update dataset registry
        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "ust",
                UST_ENDPOINT,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                f"WHERE: {where}" + (f", LIMIT: {limit}" if limit else ""),
            ),
        )
        conn.commit()

    finally:
        conn.close()

    # Step 4: Report
    db_path = os.path.join(
        os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ""),
        "spatial.db",
    ) if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") else "data/spatial.db"

    db_size_mb = 0
    if os.path.exists(db_path):
        db_size_mb = os.path.getsize(db_path) / (1024 * 1024)

    logger.info("=" * 50)
    logger.info("UST INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    logger.info("  DB size:        %.1f MB", db_size_mb)
    logger.info("=" * 50)


def verify():
    """Quick verification: query a known location."""
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    # Lower Manhattan — should have USTs nearby
    results = store.find_facilities_within(40.7128, -74.0060, 500, "ust")
    logger.info("Verification: %d UST facilities within 500m of lower Manhattan", len(results))
    for r in results[:5]:
        logger.info(
            "  %s — %.0f ft (%.0f m) — %s",
            r.name, r.distance_feet, r.distance_meters,
            r.metadata.get("status", ""),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest EPA UST Finder data")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max records to ingest (0 = all). Use for dev/testing.",
    )
    parser.add_argument(
        "--state", type=str, default="",
        help="Filter to a single state (e.g., 'Alabama', 'New York'). Default: all states.",
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
