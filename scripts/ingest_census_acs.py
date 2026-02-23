#!/usr/bin/env python3
"""
Ingest Census ACS 5-year block group data into the NestCheck spatial database.

Data source: US Census Bureau ACS 5-Year API + TIGERweb centroids
API: https://api.census.gov/data/2022/acs/acs5
Format: JSON API with geographic hierarchy queries
Records: ~240K census block groups

Key variables: median income, education, age, housing tenure, commute mode.

NOTE: PRD requires demographic data be architecturally separated from
evaluation scores (Fair Housing guardrails). This data is stored but NOT
used in scoring.

Idempotent: drops and recreates the table on each run.

Usage:
    python scripts/ingest_census_acs.py --discover
    python scripts/ingest_census_acs.py --state 36     # NY (FIPS code)
    python scripts/ingest_census_acs.py --limit 5000
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

# Census ACS 5-Year API base
ACS_BASE = "https://api.census.gov/data/2022/acs/acs5"

# TIGERweb for block group centroids
TIGERWEB_BG_ENDPOINT = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
    "/tigerWMS_ACS2022/MapServer/10/query"
)

# Key ACS variables
ACS_VARIABLES = [
    "B19013_001E",  # Median household income
    "B01003_001E",  # Total population
    "B25003_001E",  # Total housing units (tenure)
    "B25003_002E",  # Owner-occupied
    "B25003_003E",  # Renter-occupied
    "B01002_001E",  # Median age
    "B15003_022E",  # Bachelor's degree
    "B15003_023E",  # Master's degree
    "B15003_024E",  # Professional degree
    "B15003_025E",  # Doctorate
    "B08301_001E",  # Total commuters
    "B08301_010E",  # Public transit
    "B08301_019E",  # Walked
    "B08301_021E",  # Worked from home
]

# States FIPS codes
STATES_FIPS = [
    "01", "02", "04", "05", "06", "08", "09", "10", "11", "12",
    "13", "15", "16", "17", "18", "19", "20", "21", "22", "23",
    "24", "25", "26", "27", "28", "29", "30", "31", "32", "33",
    "34", "35", "36", "37", "38", "39", "40", "41", "42", "44",
    "45", "46", "47", "48", "49", "50", "51", "53", "54", "55", "56",
    "72",
]

PAGE_SIZE = 2000

# Census API uses this sentinel for missing/suppressed data
CENSUS_MISSING_VALUE = "-666666666"


def fetch_acs_state(state_fips: str, api_key: str = "") -> list[dict]:
    """Fetch ACS data for all block groups in a state."""
    variables = ",".join(ACS_VARIABLES)
    url = ACS_BASE
    params = {
        "get": f"NAME,{variables}",
        "for": "block group:*",
        "in": f"state:{state_fips}&in=county:*&in=tract:*",
    }
    if api_key:
        params["key"] = api_key

    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            if not data or len(data) < 2:
                return []
            headers = data[0]
            rows = []
            for row in data[1:]:
                rows.append(dict(zip(headers, row)))
            return rows
        except Exception as e:
            if attempt < 2:
                wait = 5 * (attempt + 1)
                logger.warning(
                    "[%s] ACS fetch failed (attempt %d): %s — retrying in %ds",
                    state_fips, attempt + 1, e, wait,
                )
                time.sleep(wait)
            else:
                logger.error("[%s] ACS fetch failed after 3 attempts: %s", state_fips, e)
                raise


def fetch_centroids_state(state_fips: str) -> dict[str, tuple[float, float]]:
    """Fetch block group centroids from TIGERweb for a state.
    Returns dict of GEOID -> (lat, lng)."""
    centroids = {}
    offset = 0
    while True:
        params = {
            "where": f"STATE='{state_fips}'",
            "outFields": "GEOID,CENTLAT,CENTLON,STATE,COUNTY,TRACT,BLKGRP",
            "returnGeometry": "false",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
        }
        for attempt in range(3):
            try:
                resp = requests.get(TIGERWEB_BG_ENDPOINT, params=params, timeout=90)
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    logger.warning("[%s] TIGERweb error: %s", state_fips, data["error"])
                    return centroids
                break  # success
            except Exception as e:
                if attempt < 2:
                    wait = 5 * (attempt + 1)
                    logger.warning(
                        "[%s] TIGERweb fetch failed (attempt %d): %s — retrying in %ds",
                        state_fips, attempt + 1, e, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.error("[%s] TIGERweb fetch failed after 3 attempts: %s", state_fips, e)
                    raise
        features = data.get("features", [])
        if not features:
            break
        for feat in features:
            attrs = feat.get("attributes", {})
            geoid = attrs.get("GEOID", "")
            lat_str = attrs.get("CENTLAT", "")
            lng_str = attrs.get("CENTLON", "")
            try:
                lat = float(lat_str.replace("+", "")) if lat_str else None
                lng = float(lng_str) if lng_str else None
                if lat is not None and lng is not None:
                    centroids[geoid] = (lat, lng)
            except (ValueError, TypeError):
                pass
        if len(features) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return centroids


def _safe_float(val, default=None):
    """Convert Census API value to float."""
    if val is None or val == "" or val == CENSUS_MISSING_VALUE or val == f"{CENSUS_MISSING_VALUE}.0":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=None):
    """Convert Census API value to int."""
    if val is None or val == "" or val == CENSUS_MISSING_VALUE:
        return default
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def ingest(
    limit: int = 0,
    state: str = "",
    api_key: str = "",
    discover: bool = False,
):
    """Main ingestion loop."""

    if discover:
        # Probe the ACS API
        test_state = state or "36"  # Default: NY
        params = {
            "get": f"NAME,{','.join(ACS_VARIABLES[:5])}",
            "for": "block group:*",
            "in": f"state:{test_state}&in=county:001&in=tract:*",
        }
        if api_key:
            params["key"] = api_key
        try:
            resp = requests.get(ACS_BASE, params=params, timeout=30)
        except Exception as e:
            logger.error("Discover request failed: %s", e)
            return
        logger.info("ACS API status: %d", resp.status_code)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                logger.info("Headers: %s", data[0])
                if len(data) > 1:
                    logger.info("Sample row: %s", data[1])
                    logger.info("Total rows: %d", len(data) - 1)
        # Also probe TIGERweb
        try:
            centroids = fetch_centroids_state(test_state)
        except Exception as e:
            logger.error("TIGERweb probe failed: %s", e)
            return
        logger.info("TIGERweb centroids for state %s: %d", test_state, len(centroids))
        if centroids:
            sample = list(centroids.items())[:3]
            for geoid, (lat, lng) in sample:
                logger.info("  %s: (%s, %s)", geoid, lat, lng)
        return

    if state and state not in STATES_FIPS:
        if not (state.isdigit() and len(state) <= 2):
            raise ValueError(f"Invalid FIPS code: {state!r} (expected 2-digit code, e.g. 36 for NY)")
        logger.warning("State FIPS %s not in standard list — proceeding anyway", state)

    states_to_run = [state] if state else STATES_FIPS

    logger.info("Starting Census ACS 5-year block group ingestion")
    logger.info("  States: %d", len(states_to_run))
    if limit:
        logger.info("  LIMIT: %d records total", limit)

    init_spatial_db()
    create_facility_table("census_acs")
    logger.info("Created facilities_census_acs table")

    conn = _connect()
    total_inserted = 0
    total_skipped = 0
    state_counts = {}

    try:
        for i, st in enumerate(states_to_run):
            if limit and total_inserted >= limit:
                break

            logger.info("[%s] Fetching centroids... (%d/%d)", st, i + 1, len(states_to_run))
            centroids = fetch_centroids_state(st)
            if not centroids:
                logger.warning("[%s] No centroids found — skipping", st)
                state_counts[st] = 0
                continue

            logger.info("[%s] Got %d centroids. Fetching ACS data...", st, len(centroids))
            rows = fetch_acs_state(st, api_key)
            if not rows:
                logger.warning("[%s] No ACS data returned — skipping", st)
                state_counts[st] = 0
                continue

            inserted_state = 0
            for row in rows:
                st_fips = row.get("state", st)
                county = row.get("county", "")
                tract = row.get("tract", "")
                blkgrp = row.get("block group", "")
                geoid = f"{st_fips}{county}{tract}{blkgrp}"

                coords = centroids.get(geoid)
                if not coords:
                    total_skipped += 1
                    continue

                lat, lng = coords
                name = row.get("NAME", f"BG {geoid}")

                median_income = _safe_int(row.get("B19013_001E"))
                total_pop = _safe_int(row.get("B01003_001E"))
                median_age = _safe_float(row.get("B01002_001E"))
                owner_occ = _safe_int(row.get("B25003_002E"))
                renter_occ = _safe_int(row.get("B25003_003E"))
                bachelors = _safe_int(row.get("B15003_022E"), 0)
                masters = _safe_int(row.get("B15003_023E"), 0)
                professional = _safe_int(row.get("B15003_024E"), 0)
                doctorate = _safe_int(row.get("B15003_025E"), 0)
                total_commuters = _safe_int(row.get("B08301_001E"))
                transit = _safe_int(row.get("B08301_010E"))
                walked = _safe_int(row.get("B08301_019E"))
                wfh = _safe_int(row.get("B08301_021E"))

                metadata = {
                    "geoid": geoid,
                    "median_income": median_income,
                    "total_pop": total_pop,
                    "median_age": median_age,
                    "owner_occupied": owner_occ,
                    "renter_occupied": renter_occ,
                    "college_plus": (bachelors or 0) + (masters or 0) + (professional or 0) + (doctorate or 0),
                    "total_commuters": total_commuters,
                    "transit_commuters": transit,
                    "walked_commuters": walked,
                    "wfh": wfh,
                }

                try:
                    conn.execute(
                        """INSERT INTO facilities_census_acs
                           (name, geometry, metadata_json)
                           VALUES (?, MakePoint(?, ?, 4326), ?)""",
                        (name, lng, lat, json.dumps(metadata)),
                    )
                    inserted_state += 1
                    total_inserted += 1
                except Exception as e:
                    logger.warning("Insert failed for %s: %s", geoid, e)
                    total_skipped += 1

                if limit and total_inserted >= limit:
                    break

            conn.commit()
            state_counts[st] = inserted_state
            logger.info("[%s] Inserted %d block groups", st, inserted_state)

            # Brief pause between states
            if i < len(states_to_run) - 1:
                time.sleep(0.5)

        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "census_acs",
                ACS_BASE,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                f"states={len(states_to_run)}" + (f", LIMIT: {limit}" if limit else ""),
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
    logger.info("CENSUS ACS INGESTION COMPLETE")
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

    results = store.find_facilities_within(40.7128, -74.0060, 2000, "census_acs")
    logger.info("Verification: %d Census block groups within 2km of Manhattan", len(results))
    for r in results[:3]:
        logger.info(
            "  %s — %.0f m — income: $%s, pop: %s",
            r.name[:40], r.distance_meters,
            r.metadata.get("median_income", "N/A"),
            r.metadata.get("total_pop", "N/A"),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest Census ACS 5-year block group data")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max records to ingest (0 = all).",
    )
    parser.add_argument(
        "--state", type=str, default="",
        help="State FIPS code (e.g., 36 for NY, 06 for CA).",
    )
    parser.add_argument(
        "--api-key", type=str, default="",
        help="Census API key (optional but recommended for large queries).",
    )
    parser.add_argument(
        "--discover", action="store_true",
        help="Print sample data and exit.",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Run verification after ingestion.",
    )
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("CENSUS_API_KEY", "")

    if args.discover:
        ingest(discover=True, state=args.state, api_key=api_key)
    else:
        ingest(limit=args.limit, state=args.state, api_key=api_key)
        if args.verify:
            verify()
