#!/usr/bin/env python3
"""
Ingest FRA/BTS North American Rail Network lines into the NestCheck spatial database.

Data source: NTAD North American Rail Network Lines (ArcGIS REST service)
URL: https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_North_American_Rail_Network_Lines/FeatureServer/0
Format: ArcGIS REST API with JSON pagination
Records: ~100K+ rail line segments (US, Canada, Mexico)

This script:
1. Queries the ArcGIS REST endpoint with pagination (chunks of 2000)
2. Converts polyline paths to WKT MULTILINESTRING
3. Loads into spatial.db as facilities_fra table
4. Creates spatial index for distance-to-line queries

Idempotent: drops and recreates the table on each run.

Usage:
    python scripts/ingest_fra.py
    python scripts/ingest_fra.py --limit 5     # 5 pages = 10,000 records
    python scripts/ingest_fra.py --us-only      # Filter to US rail lines only
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

FRA_ENDPOINT = (
    "https://services.arcgis.com/xOi1kZaI0eWDREZv"
    "/arcgis/rest/services/NTAD_North_American_Rail_Network_Lines"
    "/FeatureServer/0/query"
)

PAGE_SIZE = 2000


def _paths_to_multilinestring_wkt(paths: list, decimals: int = 6) -> str | None:
    """
    Convert ArcGIS paths array to MULTILINESTRING WKT.
    ArcGIS paths: [x,y] = [lng, lat]. Each path is a line segment.
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


def fetch_page(offset: int, where_clause: str = "1=1") -> dict:
    """Fetch one page of FRA rail line records."""
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
            resp = requests.get(FRA_ENDPOINT, params=params, timeout=90)
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


def ingest(limit_pages: int = 0, us_only: bool = False, discover: bool = False):
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
        resp = requests.get(FRA_ENDPOINT, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"ERROR: HTTP {resp.status_code}")
            return
        data = resp.json()
        if "error" in data:
            print(f"ERROR: {json.dumps(data['error'], indent=2)}")
            return
        if "features" in data and data["features"]:
            feat = data["features"][0]
            print("Sample attributes:", json.dumps(feat.get("attributes", {}), indent=2)[:1000])
            print("Sample geometry keys:", list(feat.get("geometry", {}).keys()))
        return

    where = "COUNTRY = 'US'" if us_only else "1=1"

    logger.info("Starting FRA rail line ingestion")
    logger.info("  WHERE: %s", where)
    if limit_pages:
        logger.info("  LIMIT: %d pages (%d records)", limit_pages, limit_pages * PAGE_SIZE)

    init_spatial_db()
    create_facility_table("fra", geometry_type="MULTILINESTRING")
    logger.info("Created facilities_fra table")

    conn = _connect()
    total_inserted = 0
    total_skipped = 0
    offset = 0
    batch_num = 0

    try:
        while True:
            batch_num += 1
            logger.info("Fetching batch %d (offset %d)...", batch_num, offset)
            data = fetch_page(offset, where)

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

                owner = attrs.get("RROWNER1") or ""
                net = attrs.get("NET") or ""
                if owner:
                    name = f"{owner} ({net})" if net else owner
                else:
                    name = net or "Unknown"
                if isinstance(name, str):
                    name = name.strip()
                else:
                    name = str(name).strip() or "Unknown"

                metadata = {
                    "owner": owner,
                    "owner2": attrs.get("RROWNER2", ""),
                    "net": net,
                    "passenger": attrs.get("PASSNGR", ""),
                    "stracnet": attrs.get("STRACNET", ""),
                    "miles": attrs.get("MILES"),
                    "km": attrs.get("KM"),
                }

                try:
                    conn.execute(
                        """INSERT INTO facilities_fra (name, geometry, metadata_json)
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

            if len(features) < PAGE_SIZE:
                logger.info("Last page received — done.")
                break

            offset += PAGE_SIZE

        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "fra",
                FRA_ENDPOINT,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                f"LIMIT: {limit_pages} pages" if limit_pages else ("US only" if us_only else "full"),
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
    logger.info("FRA INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    logger.info("  DB size:       %.1f MB", db_size_mb)
    logger.info("=" * 50)


def verify():
    """Quick verification: lines near Penn Station, NYC."""
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    results = store.lines_within(40.7505, -73.9935, 2000, "fra")
    logger.info("Verification: %d rail lines within 2km of Penn Station", len(results))
    for r in results[:5]:
        logger.info(
            "  %s — %.0f m — passenger: %s",
            r.name[:50], r.distance_meters,
            r.metadata.get("passenger", ""),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest FRA/BTS rail network lines")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max pages to ingest (0 = all). Each page = 2000 records.",
    )
    parser.add_argument(
        "--us-only", action="store_true",
        help="Filter to US rail lines only (exclude Canada/Mexico).",
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
        ingest(limit_pages=args.limit, us_only=args.us_only)
        if args.verify:
            verify()
