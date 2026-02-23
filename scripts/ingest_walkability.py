#!/usr/bin/env python3
"""
Ingest EPA National Walkability Index data into the NestCheck spatial database.

Data source: EPA Smart Location Database / National Walkability Index
URL: https://geodata.epa.gov/arcgis/rest/services/OA/WalkabilityIndex/MapServer/0
Format: ArcGIS REST API with JSON pagination
Records: ~220K census block groups with walkability scores 1-20

This script:
1. Queries the EPA ArcGIS service with pagination
2. Stores block group centroids as POINT geometry with walkability score in metadata
3. Loads into spatial.db as facilities_walkability table

Idempotent: drops and recreates the table on each run.

Usage:
    python scripts/ingest_walkability.py --discover
    python scripts/ingest_walkability.py --limit 5000
    python scripts/ingest_walkability.py --state NY
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

# EPA ArcGIS endpoint for Walkability Index
WALKABILITY_ENDPOINTS = [
    "https://geodata.epa.gov/arcgis/rest/services/OA/WalkabilityIndex/MapServer/0/query",
    "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Walkability_Index/FeatureServer/0/query",
    "https://geopub.epa.gov/arcgis/rest/services/OA/WalkabilityIndex/MapServer/0/query",
]

PAGE_SIZE = 2000


def _probe_endpoint() -> str:
    """Try available walkability endpoints and return the one that works."""
    for url in WALKABILITY_ENDPOINTS:
        try:
            params = {
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "json",
                "resultRecordCount": 1,
            }
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if "features" in data and data["features"]:
                    logger.info("Walkability endpoint found: %s", url[:80])
                    return url
        except Exception:
            logger.warning("Walkability endpoint probe failed: %s", url[:80])
            continue
    logger.warning("All walkability endpoints failed probing — falling back to default")
    return WALKABILITY_ENDPOINTS[0]


def fetch_page(offset: int, where_clause: str = "1=1", endpoint: str = "") -> dict:
    """Fetch one page of Walkability Index records."""
    url = endpoint or WALKABILITY_ENDPOINTS[0]
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
            resp = requests.get(url, params=params, timeout=120)
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


def _attr(attrs: dict, *keys: str, default=None):
    """Get attribute case-insensitively."""
    for k in keys:
        if k in attrs:
            return attrs[k]
        for key in attrs:
            if key.upper() == k.upper():
                return attrs[key]
    return default


def ingest(
    limit: int = 0,
    state: str = "",
    discover: bool = False,
):
    """Main ingestion loop."""

    if discover:
        endpoint = _probe_endpoint()
        params = {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
            "resultRecordCount": 1,
        }
        try:
            resp = requests.get(endpoint, params=params, timeout=60)
        except Exception as e:
            logger.error("Discover request failed: %s", e)
            return
        if resp.status_code != 200:
            logger.error("HTTP %d from walkability endpoint", resp.status_code)
            return
        data = resp.json()
        if "error" in data:
            logger.error("ArcGIS error: %s", json.dumps(data["error"], indent=2))
            return
        if "fields" in data:
            logger.info("Available fields:")
            for field in data["fields"][:30]:
                logger.info("  %s (%s)", field["name"], field.get("type", ""))
        if "features" in data and data["features"]:
            feat = data["features"][0]
            logger.info("Sample geometry: %s", feat.get("geometry", {}))
            attrs = feat.get("attributes", {})
            logger.info("Sample key values:")
            for k in ["NatWalkInd", "GEOID20", "CBSA_Name", "TotPop",
                       "D2A_Ranked", "D3B_Ranked", "STATEFP"]:
                val = _attr(attrs, k)
                if val is not None:
                    logger.info("  %s: %s", k, val)
        logger.info("Endpoint used: %s", endpoint)
        return

    endpoint = _probe_endpoint()
    where = "1=1"
    if state:
        if not (state.isdigit() and len(state) <= 2):
            raise ValueError(f"Invalid state FIPS code: {state!r} (expected 1-2 digit code, e.g. 36 for NY)")
        where = f"STATEFP = '{state}'"

    logger.info("Starting Walkability Index ingestion")
    logger.info("  Endpoint: %s", endpoint[:80])
    logger.info("  WHERE: %s", where)
    if limit:
        logger.info("  LIMIT: %d records", limit)

    init_spatial_db()
    create_facility_table("walkability")
    logger.info("Created facilities_walkability table")

    conn = _connect()
    total_inserted = 0
    total_skipped = 0
    offset = 0
    batch_num = 0

    try:
        while True:
            batch_num += 1
            logger.info("Fetching batch %d (offset %d)...", batch_num, offset)
            data = fetch_page(offset, where, endpoint)

            features = data.get("features", [])
            if not features:
                logger.info("No more features — done.")
                break

            inserted_this_batch = 0
            for feat in features:
                attrs = feat.get("attributes", {})
                geom = feat.get("geometry", {})

                # Handle both point (x,y) and polygon (rings) geometry
                lng = geom.get("x")
                lat = geom.get("y")

                if lng is None or lat is None:
                    # Try polygon centroid (rings)
                    rings = geom.get("rings")
                    if rings and rings[0]:
                        xs = [p[0] for p in rings[0]]
                        ys = [p[1] for p in rings[0]]
                        lng = sum(xs) / len(xs)
                        lat = sum(ys) / len(ys)

                if lng is None or lat is None:
                    total_skipped += 1
                    continue
                if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                    total_skipped += 1
                    continue

                geoid = _attr(attrs, "GEOID20", "GEOID10", "GEOID", default="")
                walk_ind = _attr(attrs, "NatWalkInd", default=None)
                cbsa = _attr(attrs, "CBSA_Name", "CBSA", default="")
                name = f"BG {geoid}" if geoid else f"Walkability {attrs.get('OBJECTID', '')}"

                metadata = {
                    "geoid": str(geoid),
                    "nat_walk_ind": walk_ind,
                    "cbsa_name": cbsa,
                    "total_pop": _attr(attrs, "TotPop"),
                    "d2a_ranked": _attr(attrs, "D2A_Ranked"),
                    "d3b_ranked": _attr(attrs, "D3B_Ranked"),
                    "state_fips": _attr(attrs, "STATEFP"),
                }

                try:
                    conn.execute(
                        """INSERT INTO facilities_walkability
                           (name, geometry, metadata_json)
                           VALUES (?, MakePoint(?, ?, 4326), ?)""",
                        (name, lng, lat, json.dumps(metadata)),
                    )
                    inserted_this_batch += 1
                    total_inserted += 1
                except Exception as e:
                    logger.warning("Insert failed for %s: %s", name, e)
                    total_skipped += 1

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

            if len(features) < PAGE_SIZE and not data.get("exceededTransferLimit", False):
                logger.info("Last page received — done.")
                break

            offset += PAGE_SIZE

        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "walkability",
                endpoint,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                f"WHERE: {where}" + (f", LIMIT: {limit}" if limit else ""),
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
    logger.info("WALKABILITY INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    logger.info("  DB size:       %.1f MB", db_size_mb)
    logger.info("=" * 50)


def verify():
    """Quick verification: query near Manhattan."""
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    results = store.find_facilities_within(40.7128, -74.0060, 2000, "walkability")
    logger.info("Verification: %d walkability block groups within 2km of Manhattan", len(results))
    for r in results[:3]:
        logger.info(
            "  %s — %.0f m — walk score: %s",
            r.name[:40], r.distance_meters,
            r.metadata.get("nat_walk_ind", "N/A"),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest EPA Walkability Index data")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max records to ingest (0 = all).",
    )
    parser.add_argument(
        "--state", type=str, default="",
        help="State FIPS code (e.g., 36 for NY, 06 for CA).",
    )
    parser.add_argument(
        "--discover", action="store_true",
        help="Print available fields and sample record, then exit.",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Run verification after ingestion.",
    )
    args = parser.parse_args()

    if args.discover:
        ingest(discover=True)
    else:
        ingest(limit=args.limit, state=args.state)
        if args.verify:
            verify()
