#!/usr/bin/env python3
"""
Ingest HIFLD electric power transmission lines into the NestCheck spatial database.

Data source: HIFLD US Electric Power Transmission Lines (ArcGIS REST service)
URL: https://services2.arcgis.com/LYMgRMwHfrWWEg3s/arcgis/rest/services/HIFLD_US_Electric_Power_Transmission_Lines/FeatureServer/0
Format: ArcGIS REST API with JSON pagination
Records: ~94,000 transmission line segments nationally (69kV–765kV)

This script:
1. Queries the ArcGIS REST endpoint with pagination (chunks of 2000)
2. Converts polyline paths to WKT MULTILINESTRING
3. Loads into spatial.db as facilities_hifld table
4. Creates spatial index for distance-to-line queries

Idempotent: drops and recreates the table on each run.
Run time: ~5–15 minutes for full national dataset.

Usage:
    python scripts/ingest_hifld.py
    python scripts/ingest_hifld.py --limit 5   # 5 pages = 10,000 records
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

HIFLD_ENDPOINT = (
    "https://services2.arcgis.com/LYMgRMwHfrWWEg3s"
    "/arcgis/rest/services/HIFLD_US_Electric_Power_Transmission_Lines"
    "/FeatureServer/0/query"
)

PAGE_SIZE = 2000


def _paths_to_multilinestring_wkt(paths: list, decimals: int = 6) -> str | None:
    """
    Convert ArcGIS paths array to MULTILINESTRING WKT.
    ArcGIS paths: [x,y] = [lng, lat]. Each path is a line segment.
    WKT: lng lat (comma-separated between points). Do not swap order.
    Coordinates rounded to decimals for SpatiaLite compatibility.
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
    """Fetch one page of HIFLD transmission line records."""
    params = {
        "where": where_clause,
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",  # Critical: source is Web Mercator (102100)
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    for attempt in range(3):
        try:
            resp = requests.get(HIFLD_ENDPOINT, params=params, timeout=90)
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


def ingest(limit_pages: int = 0, discover: bool = False):
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
        resp = requests.get(HIFLD_ENDPOINT, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"ERROR: HTTP {resp.status_code}")
            return
        data = resp.json()
        if "error" in data:
            print(f"ERROR: {json.dumps(data['error'], indent=2)}")
            return
        if "features" in data and data["features"]:
            feat = data["features"][0]
            print("Sample attributes:", json.dumps(feat.get("attributes", {}), indent=2)[:500])
            print("Sample geometry keys:", list(feat.get("geometry", {}).keys()))
        return

    logger.info("Starting HIFLD transmission line ingestion")
    if limit_pages:
        logger.info("  LIMIT: %d pages (%d records)", limit_pages, limit_pages * PAGE_SIZE)

    init_spatial_db()
    create_facility_table("hifld", geometry_type="MULTILINESTRING")
    logger.info("Created facilities_hifld table")

    conn = _connect()
    total_inserted = 0
    total_skipped = 0
    offset = 0
    batch_num = 0

    try:
        while True:
            batch_num += 1
            logger.info("Fetching batch %d (offset %d)...", batch_num, offset)
            data = fetch_page(offset)

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

                owner = attrs.get("OWNER") or ""
                volt_class = attrs.get("VOLT_CLASS") or ""
                if owner:
                    name = f"{volt_class} - {owner}".strip(" - ") if volt_class else owner
                else:
                    name = volt_class or "Unknown"
                if isinstance(name, str):
                    name = name.strip()
                else:
                    name = str(name).strip() or "Unknown"

                metadata = {
                    "voltage": attrs.get("VOLTAGE"),
                    "volt_class": volt_class,
                    "owner": owner,
                    "sub_1": attrs.get("SUB_1", ""),
                    "sub_2": attrs.get("SUB_2", ""),
                    "shape_length": attrs.get("SHAPE__Length"),
                }

                try:
                    conn.execute(
                        """INSERT INTO facilities_hifld (name, geometry, metadata_json)
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
                "hifld",
                HIFLD_ENDPOINT,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                f"LIMIT: {limit_pages} pages" if limit_pages else "full",
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
    logger.info("HIFLD INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    logger.info("  DB size:       %.1f MB", db_size_mb)
    logger.info("=" * 50)


def verify():
    """Quick verification: lines near Manhattan."""
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    results = store.lines_within(40.7128, -74.0060, 2000, "hifld")
    logger.info("Verification: %d transmission lines within 2km of Manhattan", len(results))
    for r in results[:5]:
        logger.info(
            "  %s — %.0f m — %s kV",
            r.name[:50], r.distance_meters,
            r.metadata.get("voltage", ""),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest HIFLD transmission lines")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max pages to ingest (0 = all). Each page = 2000 records.",
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
        ingest(limit_pages=args.limit)
        if args.verify:
            verify()
