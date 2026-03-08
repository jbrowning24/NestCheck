#!/usr/bin/env python3
"""
Ingest NCES public school locations into the NestCheck spatial database.

Data source: NCES EDGE Administrative Data for Public Schools (2022-23)
URL: https://nces.ed.gov/opengis/rest/services/K12_School_Locations/EDGE_ADMINDATA_PUBLICSCH_2223/MapServer/0
Format: ArcGIS REST API with JSON pagination
Records: ~200-400 schools per state within the tri-state bbox (NY+CT+NJ)

This script:
1. Queries the NCES EDGE MapServer for public school point locations
2. Inserts as POINT geometry into spatial.db as facilities_nces_schools table
3. Stores NCESSCH ID, school level, grade range, enrollment, FRL count in metadata

Idempotent: drops and recreates the table on each run.

Usage:
    python scripts/ingest_nces_schools.py --discover
    python scripts/ingest_nces_schools.py --bbox "-75.6,38.9,-71.8,42.1" --stabr NY
    python scripts/ingest_nces_schools.py --bbox "-75.6,38.9,-71.8,42.1" --stabr CT --verify
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

# NCES EDGE — Public School Administrative Data 2022-23 (Layer 0)
NCES_ENDPOINT = (
    "https://nces.ed.gov/opengis/rest/services/K12_School_Locations"
    "/EDGE_ADMINDATA_PUBLICSCH_2223/MapServer/0/query"
)

OUT_FIELDS = (
    "NCESSCH,SCH_NAME,LEVEL,SCH_TYPE_TEXT,GSLO,GSHI,"
    "MEMBER,TOTFRL,CHARTER_TEXT,LEAID,LAT,LON"
)

PAGE_SIZE = 2000  # NCES max record count per page


def fetch_page(
    offset: int, where_clause: str = "1=1", bbox: str = "",
) -> dict:
    """Fetch one page of NCES school records."""
    params = {
        "where": where_clause,
        "outFields": OUT_FIELDS,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    if bbox:
        parts = [float(x) for x in bbox.split(",")]
        params["geometry"] = json.dumps({
            "xmin": parts[0], "ymin": parts[1],
            "xmax": parts[2], "ymax": parts[3],
            "spatialReference": {"wkid": 4326},
        })
        params["geometryType"] = "esriGeometryEnvelope"
        params["inSR"] = "4326"
    for attempt in range(3):
        try:
            resp = requests.get(NCES_ENDPOINT, params=params, timeout=120)
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
    bbox: str = "",
    stabr: str = "NY",
    limit_pages: int = 0,
    discover: bool = False,
    _skip_table_create: bool = False,
    **kwargs,
):
    """Main ingestion loop.

    Args:
        bbox: Bounding box 'min_lng,min_lat,max_lng,max_lat'.
        stabr: State postal abbreviation for STABR filter (default 'NY').
        limit_pages: Max pages to ingest (0 = all).
        discover: Print sample record and exit.
        _skip_table_create: If True, skip init_spatial_db/create_facility_table
            (used when caller handles table creation for multi-state loops).
    """
    st = stabr.upper()
    if not (len(st) == 2 and st.isalpha()):
        raise ValueError(f"Invalid state abbreviation: {stabr!r} (expected 2-letter code, e.g. NY)")
    where = f"STABR='{st}'"

    if discover:
        params = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "json",
            "resultRecordCount": 1,
        }
        try:
            resp = requests.get(NCES_ENDPOINT, params=params, timeout=60)
        except Exception as e:
            logger.error("Discover request failed: %s", e)
            return
        if resp.status_code != 200:
            logger.error("HTTP %d from NCES endpoint", resp.status_code)
            return
        data = resp.json()
        if "error" in data:
            logger.error("ArcGIS error: %s", json.dumps(data["error"], indent=2))
            return
        if "features" in data and data["features"]:
            feat = data["features"][0]
            logger.info(
                "Sample attributes:\n%s",
                json.dumps(feat.get("attributes", {}), indent=2),
            )
            geom = feat.get("geometry", {})
            logger.info("Geometry: x=%s, y=%s", geom.get("x"), geom.get("y"))
        return

    logger.info("Starting NCES public school ingestion (STABR=%s)", stabr.upper())
    if bbox:
        logger.info("  BBOX: %s", bbox)
    if limit_pages:
        logger.info(
            "  LIMIT: %d pages (%d records)", limit_pages, limit_pages * PAGE_SIZE,
        )

    if not _skip_table_create:
        init_spatial_db()
        create_facility_table("nces_schools")  # POINT geometry (default)
        logger.info("Created facilities_nces_schools table")

    conn = _connect()
    total_inserted = 0
    total_skipped = 0
    offset = 0
    batch_num = 0

    try:
        while True:
            batch_num += 1
            logger.info("Fetching batch %d (offset %d)...", batch_num, offset)
            data = fetch_page(offset, where, bbox)

            features = data.get("features", [])
            if not features:
                logger.info("No more features — done.")
                break

            inserted_this_batch = 0
            for feat in features:
                attrs = feat.get("attributes", {})
                geom = feat.get("geometry", {})

                # Point geometry: {x: lon, y: lat}
                lon = geom.get("x")
                lat = geom.get("y")
                if lon is None or lat is None:
                    # Fallback to attribute fields
                    lon = attrs.get("LON")
                    lat = attrs.get("LAT")
                if lon is None or lat is None:
                    total_skipped += 1
                    continue

                try:
                    lon = float(lon)
                    lat = float(lat)
                except (TypeError, ValueError):
                    total_skipped += 1
                    continue

                name = attrs.get("SCH_NAME") or "Unknown School"
                if isinstance(name, str):
                    name = name.strip()

                metadata = {
                    "ncessch": attrs.get("NCESSCH", ""),
                    "level": attrs.get("LEVEL", ""),
                    "sch_type": attrs.get("SCH_TYPE_TEXT", ""),
                    "gslo": attrs.get("GSLO", ""),
                    "gshi": attrs.get("GSHI", ""),
                    "member": attrs.get("MEMBER"),
                    "totfrl": attrs.get("TOTFRL"),
                    "charter": attrs.get("CHARTER_TEXT", ""),
                    "leaid": attrs.get("LEAID", ""),
                }

                try:
                    conn.execute(
                        """INSERT INTO facilities_nces_schools
                           (name, geometry, metadata_json)
                           VALUES (?, MakePoint(?, ?, 4326), ?)""",
                        (name, lon, lat, json.dumps(metadata)),
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

            if (
                len(features) < PAGE_SIZE
                and not data.get("exceededTransferLimit", False)
            ):
                logger.info("Last page received — done.")
                break

            offset += PAGE_SIZE

        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "nces_schools",
                NCES_ENDPOINT,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                ", ".join(filter(None, [
                    "2022-23 school year",
                    f"STABR: {stabr.upper()}",
                    f"BBOX: {bbox}" if bbox else None,
                    f"LIMIT: {limit_pages} pages" if limit_pages else None,
                ])),
            ),
        )
        conn.commit()

    finally:
        conn.close()

    logger.info("=" * 50)
    logger.info("NCES SCHOOL INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    logger.info("=" * 50)


def verify():
    """Quick verification: schools near White Plains, NY."""
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    # White Plains, NY — 2 mile radius
    results = store.find_facilities_within(41.034, -73.7629, 3219, "nces_schools")
    logger.info(
        "Verification: %d schools within 2 miles of White Plains",
        len(results),
    )
    for r in results[:10]:
        meta = r.metadata
        logger.info(
            "  %s — %.0f ft — %s (grades %s–%s, enrollment: %s)",
            r.name[:50],
            r.distance_feet,
            meta.get("level", ""),
            meta.get("gslo", ""),
            meta.get("gshi", ""),
            meta.get("member", "?"),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest NCES public school locations (2022-23)",
    )
    parser.add_argument(
        "--bbox", type=str, default="",
        help=(
            "Bounding box filter: 'min_lng,min_lat,max_lng,max_lat' "
            "(e.g., '-75.6,38.9,-71.8,42.1')."
        ),
    )
    parser.add_argument(
        "--stabr", type=str, default="NY",
        help="State postal abbreviation for STABR filter (default: NY).",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max pages to ingest (0 = all). Each page = %d records." % PAGE_SIZE,
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
        ingest(discover=True, stabr=args.stabr)
    else:
        ingest(bbox=args.bbox, stabr=args.stabr, limit_pages=args.limit)
        if args.verify:
            verify()
