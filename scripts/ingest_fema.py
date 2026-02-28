#!/usr/bin/env python3
"""
Ingest FEMA NFHL (National Flood Hazard Layer) flood zone polygons into the NestCheck spatial database.

Data source: FEMA NFHL Flood Hazard Zones (ArcGIS MapServer, Layer 28)
URL: https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28
Format: ArcGIS REST API with JSON pagination
Records: Millions nationally — ingest by state/bounding box

This script:
1. Queries the NFHL MapServer with spatial/attribute pagination
2. Converts polygon rings to WKT MULTIPOLYGON
3. Loads into spatial.db as facilities_fema_nfhl table
4. Stores FLD_ZONE for health disqualifier logic (Zone A/V = hard fail)

Idempotent: drops and recreates the table on each run.

Usage:
    python scripts/ingest_fema.py --discover
    python scripts/ingest_fema.py --bbox -74.05,40.68,-73.90,40.82  # Manhattan
    python scripts/ingest_fema.py --bbox -74.3,40.5,-73.7,40.9      # NYC area
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

FEMA_ENDPOINT = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL"
    "/MapServer/28/query"
)

PAGE_SIZE = 2000

# PRD launch metro bounding boxes (lng_min, lat_min, lng_max, lat_max)
METRO_BBOXES = {
    "nyc": (-74.3, 40.45, -73.65, 40.95),
    "sf": (-122.55, 37.65, -122.30, 37.85),
    "chicago": (-87.95, 41.60, -87.50, 42.10),
    "la": (-118.70, 33.65, -117.65, 34.35),
    "seattle": (-122.50, 47.40, -122.15, 47.80),
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


def fetch_page(offset: int, where_clause: str = "1=1", bbox: tuple | None = None) -> dict:
    """Fetch one page of NFHL flood zone records."""
    params = {
        "where": where_clause,
        "outFields": "OBJECTID,FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,DEPTH,DFIRM_ID",
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
            resp = requests.get(FEMA_ENDPOINT, params=params, timeout=120)
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
    bbox: tuple | None = None,
    metro: str = "",
    limit_pages: int = 0,
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
        # Use Manhattan bbox for discover to get a result
        params["geometry"] = "-74.02,40.72,-73.97,40.76"
        params["geometryType"] = "esriGeometryEnvelope"
        params["inSR"] = "4326"
        params["spatialRel"] = "esriSpatialRelIntersects"
        try:
            resp = requests.get(FEMA_ENDPOINT, params=params, timeout=60)
        except Exception as e:
            logger.error("Discover request failed: %s", e)
            return
        if resp.status_code != 200:
            logger.error("HTTP %d from FEMA endpoint", resp.status_code)
            return
        data = resp.json()
        if "error" in data:
            logger.error("ArcGIS error: %s", json.dumps(data["error"], indent=2))
            return
        if "features" in data and data["features"]:
            feat = data["features"][0]
            logger.info("Sample attributes: %s", json.dumps(feat.get("attributes", {}), indent=2))
            logger.info("Sample geometry keys: %s", list(feat.get("geometry", {}).keys()))
            if feat.get("geometry", {}).get("rings"):
                logger.info("Ring count: %d", len(feat["geometry"]["rings"]))
        return

    if not metro and bbox is None:
        metro = "nyc"
        logger.info("No --metro or --bbox provided; defaulting to --metro nyc")

    if metro:
        metro_key = metro.lower()
        if metro_key not in METRO_BBOXES:
            logger.error("Unknown metro: %s. Available: %s", metro, list(METRO_BBOXES.keys()))
            return
        bbox = METRO_BBOXES[metro_key]
        logger.info("Using metro bbox for %s: %s", metro, bbox)

    logger.info("Starting FEMA NFHL flood zone ingestion")
    if bbox:
        logger.info("  BBOX: %s", bbox)
    if limit_pages:
        logger.info("  LIMIT: %d pages (%d records)", limit_pages, limit_pages * PAGE_SIZE)

    init_spatial_db()
    create_facility_table("fema_nfhl", geometry_type="MULTIPOLYGON")
    logger.info("Created facilities_fema_nfhl table")

    conn = _connect()
    total_inserted = 0
    total_skipped = 0
    offset = 0
    batch_num = 0

    try:
        while True:
            batch_num += 1
            logger.info("Fetching batch %d (offset %d)...", batch_num, offset)
            data = fetch_page(offset, bbox=bbox)

            features = data.get("features", [])
            if not features:
                logger.info("No more features — done.")
                break

            inserted_this_batch = 0
            for feat in features:
                attrs = feat.get("attributes", {})
                geom = feat.get("geometry") or {}

                rings = geom.get("rings")
                if not rings:
                    total_skipped += 1
                    continue

                wkt = _rings_to_multipolygon_wkt(rings)
                if not wkt:
                    total_skipped += 1
                    continue

                fld_zone = attrs.get("FLD_ZONE") or "Unknown"
                zone_subty = attrs.get("ZONE_SUBTY") or ""
                name = f"Flood Zone {fld_zone}"
                if zone_subty:
                    name = f"{name} - {zone_subty}"

                metadata = {
                    "fld_zone": fld_zone,
                    "zone_subtype": zone_subty,
                    "sfha_tf": attrs.get("SFHA_TF", ""),
                    "static_bfe": attrs.get("STATIC_BFE"),
                    "depth": attrs.get("DEPTH"),
                    "dfirm_id": attrs.get("DFIRM_ID", ""),
                    "object_id": attrs.get("OBJECTID"),
                }

                try:
                    conn.execute(
                        """INSERT INTO facilities_fema_nfhl (name, geometry, metadata_json)
                           VALUES (?, GeomFromText(?, 4326), ?)""",
                        (name, wkt, json.dumps(metadata)),
                    )
                    inserted_this_batch += 1
                    total_inserted += 1
                except Exception as e:
                    logger.warning("Insert failed for %s: %s", name, e)
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

        bbox_note = f"BBOX: {bbox}" if bbox else "no bbox filter"
        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "fema_nfhl",
                FEMA_ENDPOINT,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                bbox_note + (f", LIMIT: {limit_pages} pages" if limit_pages else ""),
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
    logger.info("FEMA NFHL INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    logger.info("  DB size:       %.1f MB", db_size_mb)
    logger.info("=" * 50)


def verify():
    """Quick verification: point-in-polygon at a known flood zone location."""
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    # Lower Manhattan — known flood zone area
    results = store.point_in_polygons(40.7025, -74.0150, "fema_nfhl")
    logger.info("Verification: %d flood zones at Battery Park (40.7025, -74.0150)", len(results))
    for r in results[:5]:
        logger.info(
            "  %s — zone: %s, sfha: %s",
            r.name, r.metadata.get("fld_zone", ""), r.metadata.get("sfha_tf", ""),
        )

    # Negative test: inland midtown
    results_neg = store.point_in_polygons(40.7580, -73.9855, "fema_nfhl")
    logger.info("Negative test: %d flood zones at Midtown (40.7580, -73.9855) — expected 0", len(results_neg))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest FEMA NFHL flood zone polygons")
    parser.add_argument(
        "--bbox", type=str, default="",
        help="Bounding box: lng_min,lat_min,lng_max,lat_max (e.g., -74.05,40.68,-73.90,40.82)",
    )
    parser.add_argument(
        "--metro", type=str, default="",
        help="Use predefined metro bbox (nyc, sf, chicago, la, seattle).",
    )
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

    bbox = None
    if args.bbox:
        parts = [float(x.strip()) for x in args.bbox.split(",")]
        if len(parts) != 4:
            logger.error("bbox must have 4 values: lng_min,lat_min,lng_max,lat_max")
            sys.exit(1)
        bbox = tuple(parts)

    if args.discover:
        ingest(discover=True)
    else:
        ingest(bbox=bbox, metro=args.metro, limit_pages=args.limit)
        if args.verify:
            verify()
