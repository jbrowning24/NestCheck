#!/usr/bin/env python3
"""
Ingest Census TIGER/Line unified school district boundaries into the NestCheck
spatial database.

Data source: TIGERweb Current WMS MapServer — Layer 14 (Unified School Districts)
URL: https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Current/MapServer/14
Format: ArcGIS REST API with JSON pagination
Records: ~700 unified school districts in NY state

This script:
1. Queries the TIGERweb MapServer for unified school district polygons
2. Converts ArcGIS rings to WKT MULTIPOLYGON
3. Loads into spatial.db as facilities_school_districts table
4. Stores GEOID, grade range, and district name in metadata

Idempotent: drops and recreates the table on each run.

Usage:
    python scripts/ingest_school_districts.py --discover
    python scripts/ingest_school_districts.py --state 36       # NY
    python scripts/ingest_school_districts.py --state 36 --limit 5
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

# TIGERweb Current — Unified School Districts (Layer 14)
TIGER_SD_ENDPOINT = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
    "/tigerWMS_Current/MapServer/14/query"
)

OUT_FIELDS = "GEOID,STATE,SDUNI,BASENAME,NAME,MTFCC,FUNCSTAT,HIGRADE,LOGRADE,CENTLAT,CENTLON"

PAGE_SIZE = 100  # School district polygons are large; keep pages small


def _ring_is_clockwise(ring: list) -> bool:
    """Return True if an ArcGIS ring is clockwise (outer boundary).

    ArcGIS convention: clockwise = outer boundary, counter-clockwise = hole.
    Uses the shoelace formula to compute signed area.
    """
    area = 0.0
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        area += ring[i][0] * ring[j][1]
        area -= ring[j][0] * ring[i][1]
    return area < 0  # Negative signed area = clockwise in lon/lat space


def _rings_to_multipolygon_wkt(rings: list, decimals: int = 6) -> str | None:
    """Convert ArcGIS rings array to MULTIPOLYGON WKT.

    ArcGIS uses ring orientation: clockwise = outer boundary,
    counter-clockwise = hole. School districts commonly have disjoint
    parts (multiple outer rings), so we group each outer ring with its
    subsequent holes into separate polygon elements.

    WKT: MULTIPOLYGON(((outer1),(hole1)), ((outer2)))
    """
    if not rings or not isinstance(rings, list):
        return None
    try:
        # Build coordinate strings and classify rings
        polygons: list[list[str]] = []  # Each element: [outer, hole1, hole2, ...]
        for ring in rings:
            if not ring or len(ring) < 4:
                continue
            coords = ", ".join(
                f"{round(p[0], decimals)} {round(p[1], decimals)}" for p in ring
            )
            if _ring_is_clockwise(ring):
                # New outer boundary → start a new polygon
                polygons.append([f"({coords})"])
            else:
                # Hole → attach to the most recent outer boundary
                if polygons:
                    polygons[-1].append(f"({coords})")
                else:
                    # Hole without a preceding outer ring — treat as outer
                    polygons.append([f"({coords})"])
        if not polygons:
            return None
        # Build MULTIPOLYGON WKT: each polygon is (outer, hole1, hole2, ...)
        poly_strs = [f"({','.join(rings_group)})" for rings_group in polygons]
        return f"MULTIPOLYGON({','.join(poly_strs)})"
    except (TypeError, IndexError, KeyError):
        return None


def fetch_page(offset: int, where_clause: str = "1=1") -> dict:
    """Fetch one page of school district records."""
    params = {
        "where": where_clause,
        "outFields": OUT_FIELDS,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    for attempt in range(3):
        try:
            resp = requests.get(TIGER_SD_ENDPOINT, params=params, timeout=120)
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
    state: str = "36",
    states: list[str] | None = None,
    limit: int = 0,
    discover: bool = False,
    **kwargs,
):
    """Main ingestion loop.

    Args:
        state: State FIPS code (default "36" for NY).
        states: List of FIPS codes to ingest (overrides state if provided).
        limit: Max pages to ingest (0 = all).
        discover: Print sample record and exit.
    """
    if states:
        in_list = ", ".join(f"'{s}'" for s in states)
        where = f"STATE IN ({in_list})"
        state_label = "+".join(states)
    else:
        where = f"STATE='{state}'" if state else "1=1"
        state_label = state

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
            resp = requests.get(TIGER_SD_ENDPOINT, params=params, timeout=60)
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
            logger.info(
                "Sample attributes:\n%s",
                json.dumps(feat.get("attributes", {}), indent=2),
            )
            geom = feat.get("geometry", {})
            rings = geom.get("rings", [])
            logger.info("Geometry: %d rings", len(rings))
            if rings:
                logger.info("First ring: %d points", len(rings[0]))
        return

    logger.info("Starting school district boundary ingestion (state=%s)", state_label)
    if limit:
        logger.info("  LIMIT: %d pages (%d records)", limit, limit * PAGE_SIZE)

    init_spatial_db()
    create_facility_table("school_districts", geometry_type="MULTIPOLYGON")
    logger.info("Created facilities_school_districts table")

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

                rings = geom.get("rings")
                if not rings:
                    total_skipped += 1
                    continue

                wkt = _rings_to_multipolygon_wkt(rings)
                if not wkt:
                    total_skipped += 1
                    continue

                name = attrs.get("NAME") or attrs.get("BASENAME") or "Unknown District"
                if isinstance(name, str):
                    name = name.strip()

                metadata = {
                    "geoid": attrs.get("GEOID", ""),
                    "sduni": attrs.get("SDUNI", ""),
                    "basename": attrs.get("BASENAME", ""),
                    "funcstat": attrs.get("FUNCSTAT", ""),
                    "higrade": attrs.get("HIGRADE", ""),
                    "lograde": attrs.get("LOGRADE", ""),
                    "centlat": attrs.get("CENTLAT", ""),
                    "centlon": attrs.get("CENTLON", ""),
                }

                try:
                    conn.execute(
                        """INSERT INTO facilities_school_districts
                           (name, geometry, metadata_json)
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

            if limit and batch_num >= limit:
                logger.info("Page limit reached (%d) — stopping.", limit)
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
                "school_districts",
                TIGER_SD_ENDPOINT,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                f"State FIPS: {state_label}" + (f", LIMIT: {limit} pages" if limit else ""),
            ),
        )
        conn.commit()

    finally:
        conn.close()

    logger.info("=" * 50)
    logger.info("SCHOOL DISTRICT INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    logger.info("=" * 50)


def verify():
    """Quick verification: school district for White Plains, NY."""
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    # White Plains, NY
    results = store.point_in_polygons(41.034, -73.7629, "school_districts")
    if results:
        for r in results:
            logger.info(
                "  District: %s (GEOID: %s, grades %s–%s)",
                r.name,
                r.metadata.get("geoid", ""),
                r.metadata.get("lograde", ""),
                r.metadata.get("higrade", ""),
            )
    else:
        logger.warning("No school district found for White Plains coordinates")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest Census TIGER unified school district boundaries"
    )
    parser.add_argument(
        "--state", type=str, default="36",
        help="State FIPS code (default: 36 for NY).",
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
        ingest(discover=True, state=args.state)
    else:
        ingest(state=args.state, limit=args.limit)
        if args.verify:
            verify()
