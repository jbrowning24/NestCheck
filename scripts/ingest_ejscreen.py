#!/usr/bin/env python3
"""
Ingest EPA EJScreen environmental justice block group data into the NestCheck spatial database.

Data source: EPA EJScreen ArcGIS FeatureServer
URL: https://ejscreen.epa.gov/mapper/
Format: ArcGIS REST API with JSON pagination
Records: ~220K census block groups nationally

EJScreen is NestCheck's "single most valuable free data source" per the PRD.
It pre-combines 13 environmental indicators with demographic data at the
census block group level.

This script:
1. Queries the EJScreen ArcGIS service with pagination
2. Stores block group centroids as POINT geometry with indicator values in metadata
3. Loads into spatial.db as facilities_ejscreen table

Idempotent: drops and recreates the table on each run.

Usage:
    python scripts/ingest_ejscreen.py --discover
    python scripts/ingest_ejscreen.py --state NY
    python scripts/ingest_ejscreen.py --limit 5000
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

# EJScreen ArcGIS FeatureServer — block group level data
EJSCREEN_ENDPOINT = (
    "https://ejscreen.epa.gov/mapper/ejscreenRESTbroker1.aspx"
)

# Alternative: EPA GeoPlatform EJScreen service
EJSCREEN_GEOPLATFORM = (
    "https://geopub.epa.gov/arcgis/rest/services/EJSCREEN"
    "/EJSCREEN_Combined_2024/MapServer/1/query"
)

PAGE_SIZE = 2000


def fetch_page(offset: int, where_clause: str = "1=1", endpoint: str = "") -> dict:
    """Fetch one page of EJScreen block group records."""
    url = endpoint or EJSCREEN_GEOPLATFORM
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


def _probe_endpoint() -> str:
    """Try available EJScreen endpoints and return the one that works."""
    endpoints = [
        EJSCREEN_GEOPLATFORM,
        # Fallback endpoints
        "https://geopub.epa.gov/arcgis/rest/services/EJSCREEN/EJSCREEN_Combined_2024/MapServer/0/query",
        "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/EJScreen_2024/FeatureServer/0/query",
    ]
    for url in endpoints:
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
                    logger.info("EJScreen endpoint found: %s", url[:80])
                    return url
        except Exception:
            logger.warning("EJScreen endpoint probe failed: %s", url[:80])
            continue
    logger.warning("All EJScreen endpoints failed probing — falling back to default")
    return EJSCREEN_GEOPLATFORM


def _get_indicator_fields(attrs: dict) -> dict:
    """Extract environmental indicator fields from attributes, handling name variations."""
    indicators = {}
    # Map common field name patterns to standard names
    field_map = {
        "PM25": ["PM25", "pm25", "P_PM25", "ACSTOTPOP"],
        "OZONE": ["OZONE", "ozone", "P_OZONE"],
        "DSLPM": ["DSLPM", "dslpm", "P_DSLPM", "DIESEL"],
        "CANCER": ["CANCER", "cancer", "P_CANCER"],
        "RESP": ["RESP", "resp", "P_RESP"],
        "PTRAF": ["PTRAF", "ptraf", "P_PTRAF", "TRAFFIC"],
        "PNPL": ["PNPL", "pnpl", "P_PNPL", "SUPERFUND"],
        "PRMP": ["PRMP", "prmp", "P_PRMP", "RMP"],
        "PTSDF": ["PTSDF", "ptsdf", "P_PTSDF", "TSDF", "HAZWASTE"],
        "UST": ["UST_RAW", "UST", "ust", "P_UST", "UNDERGRNDSTOR"],
        "PWDIS": ["PWDIS", "pwdis", "P_PWDIS", "WASTEWATER"],
        "LEAD": ["PRE1960", "LEAD", "lead", "P_LDPNT", "LEADPAINT"],
        "DEMOGIDX": ["DEMOGIDX_2", "DEMOGIDX", "demogidx"],
    }
    for std_name, candidates in field_map.items():
        for cand in candidates:
            if cand in attrs:
                indicators[std_name] = attrs[cand]
                break
            # Case-insensitive fallback
            for key in attrs:
                if key.upper() == cand.upper():
                    indicators[std_name] = attrs[key]
                    break
            if std_name in indicators:
                break
    return indicators


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
            logger.error("HTTP %d from EJScreen endpoint", resp.status_code)
            return
        data = resp.json()
        if "error" in data:
            logger.error("ArcGIS error: %s", json.dumps(data["error"], indent=2))
            return
        if "fields" in data:
            logger.info("Available fields:")
            for field in data["fields"][:40]:
                logger.info("  %s (%s)", field["name"], field.get("type", ""))
            if len(data["fields"]) > 40:
                logger.info("  ... and %d more fields", len(data["fields"]) - 40)
        if "features" in data and data["features"]:
            feat = data["features"][0]
            logger.info("Sample geometry: %s", feat.get("geometry", {}))
            attrs = feat.get("attributes", {})
            indicators = _get_indicator_fields(attrs)
            logger.info("Extracted indicators: %s", json.dumps(indicators, indent=2))
        logger.info("Endpoint used: %s", endpoint)
        return

    endpoint = _probe_endpoint()
    where = "1=1"
    if state:
        st = state.upper()
        if not (len(st) == 2 and st.isalpha()):
            raise ValueError(f"Invalid state abbreviation: {state!r} (expected 2-letter code, e.g. NY)")
        where = f"ST_ABBREV = '{st}'"

    logger.info("Starting EJScreen block group ingestion")
    logger.info("  Endpoint: %s", endpoint[:80])
    logger.info("  WHERE: %s", where)
    if limit:
        logger.info("  LIMIT: %d records", limit)

    init_spatial_db()
    create_facility_table("ejscreen")
    logger.info("Created facilities_ejscreen table")

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

                lng = geom.get("x")
                lat = geom.get("y")

                if lng is None or lat is None:
                    total_skipped += 1
                    continue
                if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                    total_skipped += 1
                    continue

                # Block group ID
                bg_id = (
                    attrs.get("ID")
                    or attrs.get("GEOID")
                    or attrs.get("BLOCKGROUPID")
                    or attrs.get("OBJECTID", "")
                )
                name = f"Block Group {bg_id}"

                indicators = _get_indicator_fields(attrs)
                metadata = {
                    "block_group_id": str(bg_id),
                    "state": attrs.get("ST_ABBREV", attrs.get("STATE_NAME", "")),
                    "population": attrs.get("ACSTOTPOP", attrs.get("TOTPOP")),
                    **indicators,
                }

                try:
                    conn.execute(
                        """INSERT INTO facilities_ejscreen
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
                "ejscreen",
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
    logger.info("EJSCREEN INGESTION COMPLETE")
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

    results = store.find_facilities_within(40.7128, -74.0060, 2000, "ejscreen")
    logger.info("Verification: %d EJScreen block groups within 2km of Manhattan", len(results))
    for r in results[:3]:
        logger.info(
            "  %s — %.0f m — PM2.5: %s, Traffic: %s",
            r.name[:40], r.distance_meters,
            r.metadata.get("PM25", "N/A"),
            r.metadata.get("PTRAF", "N/A"),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest EPA EJScreen block group data")
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
