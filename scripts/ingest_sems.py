#!/usr/bin/env python3
"""
Ingest EPA Superfund site boundary polygons into the NestCheck spatial database.

Data source: EPA Superfund Site Boundaries (ArcGIS REST service)
URL: https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/FAC_Superfund_Site_Boundaries_EPA_Public/FeatureServer/0
Format: ArcGIS REST API with JSON pagination
Records: ~1,300–2,000 Superfund site boundaries nationally

This script:
1. Queries the ArcGIS REST endpoint with pagination (chunks of 2000)
2. Converts polygon rings to WKT MULTIPOLYGON
3. Loads into spatial.db as facilities_sems table
4. Creates spatial index for point-in-polygon queries

Idempotent: drops and recreates the table on each run.
Run time: ~2–5 minutes for full national dataset.

Usage:
    python scripts/ingest_sems.py
    python scripts/ingest_sems.py --state NY
    python scripts/ingest_sems.py --limit 100
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

SEMS_ENDPOINT = (
    "https://services.arcgis.com/cJ9YHowT8TU7DUyn"
    "/arcgis/rest/services/FAC_Superfund_Site_Boundaries_EPA_Public"
    "/FeatureServer/0/query"
)

PAGE_SIZE = 2000


def _rings_to_multipolygon_wkt(rings: list, decimals: int = 6) -> str | None:
    """
    Convert ArcGIS rings array to MULTIPOLYGON WKT.
    ArcGIS rings: [x,y] = [lng, lat]. First ring is exterior, rest are holes.
    ArcGIS order used as-is; SpatiaLite accepts both orientations.
    WKT: MULTIPOLYGON(((exterior),(hole1),(hole2))). Coordinates rounded for compatibility.
    """
    if not rings or not isinstance(rings, list):
        return None
    try:
        coord_strings = []
        for ring in rings:
            if not ring or len(ring) < 3:
                continue
            # Use ArcGIS order as-is. SpatiaLite accepts both orientations.
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


def fetch_page(offset: int, where_clause: str = "1=1") -> dict:
    """Fetch one page of Superfund boundary records from the ArcGIS REST API."""
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
            resp = requests.get(SEMS_ENDPOINT, params=params, timeout=60)
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


def ingest(limit: int = 0, state: str = "", discover: bool = False):
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
        resp = requests.get(SEMS_ENDPOINT, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"ERROR: HTTP {resp.status_code}")
            return
        data = resp.json()
        if "error" in data:
            print(f"ERROR: {json.dumps(data['error'], indent=2)}")
            return
        if "features" in data and data["features"]:
            feat = data["features"][0]
            print("Sample attributes:", json.dumps(feat.get("attributes", {}), indent=2))
            print("Sample geometry keys:", list(feat.get("geometry", {}).keys()))
        return

    where = "1=1"
    if state:
        where = f"STATE_CODE = '{state.upper()}'"

    logger.info("Starting EPA Superfund boundary ingestion")
    logger.info("  WHERE: %s", where)
    if limit:
        logger.info("  LIMIT: %d records", limit)

    init_spatial_db()
    create_facility_table("sems", geometry_type="MULTIPOLYGON")
    logger.info("Created facilities_sems table")

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
                geom = feat.get("geometry") or {}

                rings = geom.get("rings")
                if not rings:
                    total_skipped += 1
                    continue

                wkt = _rings_to_multipolygon_wkt(rings)
                if not wkt:
                    total_skipped += 1
                    continue

                name = (attrs.get("SITE_NAME") or attrs.get("SITE_FEATURE_NAME") or "Unknown")
                if isinstance(name, str):
                    name = name.strip()
                else:
                    name = str(name).strip()

                metadata = {
                    "site_name": attrs.get("SITE_NAME", ""),
                    "epa_id": attrs.get("EPA_ID", ""),
                    "npl_status_code": attrs.get("NPL_STATUS_CODE", ""),
                    "state_code": attrs.get("STATE_CODE", ""),
                    "federal_facility_deter_code": attrs.get("FEDERAL_FACILITY_DETER_CODE", ""),
                    "epa_program": attrs.get("EPA_PROGRAM", ""),
                    "site_feature_class": attrs.get("SITE_FEATURE_CLASS"),
                    "site_feature_name": attrs.get("SITE_FEATURE_NAME", ""),
                    "city_name": attrs.get("CITY_NAME", ""),
                    "county": attrs.get("COUNTY", ""),
                    "zip_code": attrs.get("ZIP_CODE", ""),
                    "object_id": attrs.get("OBJECTID"),
                }

                try:
                    conn.execute(
                        """INSERT INTO facilities_sems (name, geometry, metadata_json)
                           VALUES (?, GeomFromText(?, 4326), ?)""",
                        (name, wkt, json.dumps(metadata)),
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

            if len(features) < PAGE_SIZE:
                logger.info("Last page received — done.")
                break

            offset += PAGE_SIZE

        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "sems",
                SEMS_ENDPOINT,
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
    logger.info("SEMS INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    logger.info("  DB size:       %.1f MB", db_size_mb)
    logger.info("=" * 50)


def verify():
    """Quick verification: point-in-polygon at Gowanus Canal (Brooklyn)."""
    from spatial_data import SpatialDataStore, _connect

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    # Gowanus Canal — use PointOnSurface (guaranteed inside) for positive test
    conn = _connect()
    row = conn.execute(
        "SELECT ST_Y(ST_PointOnSurface(geometry)), ST_X(ST_PointOnSurface(geometry)) "
        "FROM facilities_sems WHERE name LIKE '%Gowanus%' LIMIT 1"
    ).fetchone()
    conn.close()
    if row:
        lat, lng = row[0], row[1]
        results = store.point_in_polygons(lat, lng, "sems")
        logger.info(
            "Verification: %d Superfund sites at Gowanus (%.4f, %.4f)",
            len(results), lat, lng,
        )
        for r in results[:5]:
            logger.info("  %s — %s", r.name, r.metadata.get("epa_id", ""))
    else:
        logger.warning("Gowanus site not found — skipping positive test")

    # Negative: Boston
    results_boston = store.point_in_polygons(42.35, -71.05, "sems")
    logger.info("Negative test: %d sites at Boston (42.35, -71.05) — expected 0", len(results_boston))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest EPA Superfund site boundaries")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max records to ingest (0 = all).",
    )
    parser.add_argument(
        "--state", type=str, default="",
        help="Filter to a single state (e.g., NY, CA).",
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
        ingest(limit=args.limit, state=args.state)
        if args.verify:
            verify()
