#!/usr/bin/env python3
"""
Ingest Census TIGER/Line street network data into the NestCheck spatial database.

Data source: TIGERweb Transportation MapServer (ArcGIS REST)
URL: https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer
Format: ArcGIS REST API with JSON pagination
Records: Millions nationally — ingest by state/county

This script:
1. Queries the TIGERweb Transportation MapServer with pagination
2. Converts polyline paths to WKT MULTILINESTRING
3. Loads into spatial.db as facilities_tiger_streets table
4. Creates spatial index for intersection density calculations

Idempotent: drops and recreates the table on each run.
Note: ~2GB nationally. Recommend ingesting target metros only.

Usage:
    python scripts/ingest_tiger.py --discover
    python scripts/ingest_tiger.py --state 36              # NY
    python scripts/ingest_tiger.py --state 36 --county 061 # Manhattan
    python scripts/ingest_tiger.py --limit 5
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

# TIGERweb Transportation — roads layer
# Layer 2 = All Roads (Primary + Secondary + Local)
TIGER_ENDPOINT = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
    "/Transportation/MapServer/2/query"
)

PAGE_SIZE = 2000


def _paths_to_multilinestring_wkt(paths: list, decimals: int = 6) -> str | None:
    """Convert ArcGIS paths array to MULTILINESTRING WKT."""
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


def fetch_page(offset: int, where_clause: str = "1=1", bbox: tuple | None = None) -> dict:
    """Fetch one page of TIGER street records."""
    params = {
        "where": where_clause,
        "outFields": "OID,BASENAME,MTFCC,NAME",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    if bbox:
        lng_min, lat_min, lng_max, lat_max = bbox
        params["geometry"] = f"{lng_min},{lat_min},{lng_max},{lat_max}"
        params["geometryType"] = "esriGeometryEnvelope"
        params["inSR"] = "4326"
        params["spatialRel"] = "esriSpatialRelIntersects"
    for attempt in range(3):
        try:
            resp = requests.get(TIGER_ENDPOINT, params=params, timeout=120)
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


def ingest(
    limit_pages: int = 0,
    state: str = "",
    county: str = "",
    bbox: tuple | None = None,
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
            "geometry": "-74.01,40.74,-73.98,40.76",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        }
        try:
            resp = requests.get(TIGER_ENDPOINT, params=params, timeout=60)
        except Exception as e:
            logger.error("Discover request failed: %s", e)
            return
        if resp.status_code != 200:
            logger.error("HTTP %d from TIGER endpoint", resp.status_code)
            return
        data = resp.json()
        if "error" in data:
            logger.error("ArcGIS error: %s", json.dumps(data["error"], indent=2))
            return
        if "features" in data and data["features"]:
            feat = data["features"][0]
            logger.info("Sample attributes: %.1000s", json.dumps(feat.get("attributes", {}), indent=2))
            logger.info("Sample geometry keys: %s", list(feat.get("geometry", {}).keys()))
        return

    # TIGER roads layer doesn't have STATE/COUNTY attribute fields
    # Must use bounding box spatial queries
    if state or county:
        if not bbox:
            logger.warning("TIGER roads use bbox filtering, not state/county attributes.")
            logger.warning("Use --bbox instead. Ignoring state/county filters.")

    logger.info("Starting TIGER street network ingestion")
    if bbox:
        logger.info("  BBOX: %s", bbox)
    if limit_pages:
        logger.info("  LIMIT: %d pages (%d records)", limit_pages, limit_pages * PAGE_SIZE)

    if not bbox:
        logger.error("TIGER streets requires --bbox. Use e.g. --bbox=\"-74.05,40.68,-73.90,40.82\"")
        return

    init_spatial_db()
    create_facility_table("tiger_streets", geometry_type="MULTILINESTRING")
    logger.info("Created facilities_tiger_streets table")

    conn = _connect()
    total_inserted = 0
    total_skipped = 0
    offset = 0
    batch_num = 0

    try:
        while True:
            batch_num += 1
            logger.info("Fetching batch %d (offset %d)...", batch_num, offset)
            data = fetch_page(offset, "1=1", bbox)

            features = data.get("features", [])
            if not features:
                logger.info("No more features — done.")
                break

            inserted_this_batch = 0
            for feat in features:
                attrs = feat.get("attributes", {})
                geom = feat.get("geometry", {})

                paths = geom.get("paths")
                if not paths:
                    total_skipped += 1
                    continue

                wkt = _paths_to_multilinestring_wkt(paths)
                if not wkt:
                    total_skipped += 1
                    continue

                name = attrs.get("NAME") or attrs.get("BASENAME") or "Unnamed Road"
                if isinstance(name, str):
                    name = name.strip()
                else:
                    name = str(name).strip()

                metadata = {
                    "mtfcc": attrs.get("MTFCC", ""),
                    "oid": attrs.get("OID", ""),
                }

                try:
                    conn.execute(
                        """INSERT INTO facilities_tiger_streets (name, geometry, metadata_json)
                           VALUES (?, GeomFromText(?, 4326), ?)""",
                        (name, wkt, json.dumps(metadata)),
                    )
                    inserted_this_batch += 1
                    total_inserted += 1
                except Exception as e:
                    logger.warning("Insert failed for %s: %s", name[:50], e)
                    total_skipped += 1

            conn.commit()
            logger.info(
                "  Batch %d: inserted %d, skipped so far: %d, total: %d",
                batch_num, inserted_this_batch, total_skipped, total_inserted,
            )

            if limit_pages and batch_num >= limit_pages:
                logger.info("Page limit reached (%d) — stopping.", limit_pages)
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
                "tiger_streets",
                TIGER_ENDPOINT,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                f"BBOX: {bbox}" + (f", LIMIT: {limit_pages} pages" if limit_pages else ""),
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
    logger.info("TIGER STREETS INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    logger.info("  DB size:       %.1f MB", db_size_mb)
    logger.info("=" * 50)


def verify():
    """Quick verification: streets near Times Square."""
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    results = store.lines_within(40.7580, -73.9855, 500, "tiger_streets")
    logger.info("Verification: %d street segments within 500m of Times Square", len(results))
    for r in results[:5]:
        logger.info(
            "  %s — %.0f m — MTFCC: %s",
            r.name[:40], r.distance_meters,
            r.metadata.get("mtfcc", ""),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Census TIGER/Line street network")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max pages to ingest (0 = all). Each page = 2000 records.",
    )
    parser.add_argument(
        "--state", type=str, default="",
        help="State FIPS code (e.g., 36 for NY, 06 for CA).",
    )
    parser.add_argument(
        "--county", type=str, default="",
        help="County FIPS code (e.g., 061 for Manhattan). Requires --state.",
    )
    parser.add_argument(
        "--bbox", type=str, default="",
        help="Bounding box: lng_min,lat_min,lng_max,lat_max (e.g., -74.05,40.68,-73.90,40.82).",
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

    bbox = None
    if args.bbox:
        parts = [float(x.strip()) for x in args.bbox.split(",")]
        if len(parts) == 4:
            bbox = tuple(parts)

    if args.discover:
        ingest(discover=True)
    else:
        ingest(limit_pages=args.limit, state=args.state, county=args.county, bbox=bbox)
        if args.verify:
            verify()
