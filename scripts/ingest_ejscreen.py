#!/usr/bin/env python3
"""
Ingest EPA EJScreen environmental justice block group data into the NestCheck spatial database.

Data source: EPA EJScreen ArcGIS FeatureServer (primary)
Fallback: ArcGIS Online per-indicator EJScreen layers (after EPA removed
          the combined endpoint in February 2025)
Format: ArcGIS REST API with JSON pagination
Records: ~220K census block groups nationally

EJScreen is NestCheck's "single most valuable free data source" per the PRD.
It pre-combines 13 environmental indicators with demographic data at the
census block group level.

This script:
1. Tries the combined EPA endpoint first
2. Falls back to ArcGIS Online individual indicator layers if the combined
   endpoint is unavailable (queries 12 separate services, merges by block
   group GEOID, computes polygon centroid for POINT geometry)
3. Loads into spatial.db as facilities_ejscreen table

Idempotent: drops and recreates the table on each run.

Usage:
    python scripts/ingest_ejscreen.py --discover
    python scripts/ingest_ejscreen.py --state NY
    python scripts/ingest_ejscreen.py --bbox "-75.6,38.9,-71.8,42.1"
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

# ── Primary endpoints (EPA combined service) ─────────────────────────
# These were taken offline by EPA in February 2025.

EJSCREEN_GEOPLATFORM = (
    "https://geopub.epa.gov/arcgis/rest/services/EJSCREEN"
    "/EJSCREEN_Combined_2024/MapServer/1/query"
)

_COMBINED_ENDPOINTS = [
    EJSCREEN_GEOPLATFORM,
    "https://geopub.epa.gov/arcgis/rest/services/EJSCREEN/EJSCREEN_Combined_2024/MapServer/0/query",
    "https://geopub.epa.gov/arcgis/rest/services/EJSCREEN/EJSCREEN_Combined_2025/MapServer/1/query",
]

# ── Fallback: PEDP (Public Environmental Data Partners) mirror ────────
# After EPA removed EJScreen in Feb 2025, PEDP hosts a V2.32 mirror of
# the national block-group-level dataset with all indicators combined.
# Single service, single layer — same schema as the original EPA data.

_PEDP_ENDPOINT = (
    "https://services2.arcgis.com/w4yiQqB14ZaAGzJq"
    "/arcgis/rest/services"
    "/EJScreen_US_Percentiles_Block_Group_gdb_V_2.32_(Parent)_view"
    "/FeatureServer/0/query"
)

PAGE_SIZE = 2000


def _polygon_centroid(rings: list) -> tuple[float, float] | None:
    """Compute approximate centroid from ArcGIS polygon rings.

    Uses the vertex-average of the first (outer) ring. Not a true
    area-weighted centroid, but sufficient for nearest-block-group
    queries within 2 km.
    """
    if not rings or not rings[0]:
        return None
    outer = rings[0]
    if len(outer) < 3:
        return None
    sum_x = sum(p[0] for p in outer)
    sum_y = sum(p[1] for p in outer)
    n = len(outer)
    return (sum_x / n, sum_y / n)


# ── Combined endpoint helpers ────────────────────────────────────────


def fetch_page(offset: int, where_clause: str = "1=1", endpoint: str = "") -> dict:
    """Fetch one page of EJScreen block group records from the combined endpoint."""
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


def _probe_combined_endpoint() -> str | None:
    """Try combined EJScreen endpoints; return first working URL or None."""
    for url in _COMBINED_ENDPOINTS:
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
                    logger.info("EJScreen combined endpoint found: %s", url[:80])
                    return url
        except Exception:
            pass
    return None


def _get_indicator_fields(attrs: dict) -> dict:
    """Extract environmental indicator fields from combined-endpoint attributes."""
    indicators = {}

    raw_field_map = {
        "PM25": ["PM25", "pm25"],
        "OZONE": ["OZONE", "ozone"],
        "DSLPM": ["DSLPM", "dslpm", "DIESEL"],
        "CANCER": ["CANCER", "cancer"],
        "RESP": ["RESP", "resp"],
        "PTRAF": ["PTRAF", "ptraf", "TRAFFIC"],
        "PNPL": ["PNPL", "pnpl", "SUPERFUND"],
        "PRMP": ["PRMP", "prmp", "RMP"],
        "PTSDF": ["PTSDF", "ptsdf", "TSDF", "HAZWASTE"],
        "UST": ["UST_RAW", "UST", "ust", "UNDERGRNDSTOR"],
        "PWDIS": ["PWDIS", "pwdis", "WASTEWATER"],
        "LEAD": ["PRE1960", "LEAD", "lead", "LEADPAINT"],
        "DEMOGIDX": ["DEMOGIDX_2", "DEMOGIDX", "demogidx"],
    }

    pct_field_map = {
        "PM25_PCT": ["P_PM25"],
        "OZONE_PCT": ["P_OZONE"],
        "DSLPM_PCT": ["P_DSLPM"],
        "CANCER_PCT": ["P_CANCER"],
        "RESP_PCT": ["P_RESP"],
        "PTRAF_PCT": ["P_PTRAF"],
        "PNPL_PCT": ["P_PNPL"],
        "PRMP_PCT": ["P_PRMP"],
        "PTSDF_PCT": ["P_PTSDF"],
        "UST_PCT": ["P_UST"],
        "PWDIS_PCT": ["P_PWDIS"],
        "LEAD_PCT": ["P_LDPNT"],
    }

    def _find_value(candidates):
        for cand in candidates:
            if cand in attrs:
                return attrs[cand]
            for key in attrs:
                if key.upper() == cand.upper():
                    return attrs[key]
        return None

    for std_name, candidates in raw_field_map.items():
        val = _find_value(candidates)
        if val is not None:
            indicators[std_name] = val

    for std_name, candidates in pct_field_map.items():
        val = _find_value(candidates)
        if val is not None:
            indicators[std_name] = val

    return indicators


# ── PEDP fallback helpers ─────────────────────────────────────────────

# Mapping from PEDP field names to our standard indicator names.
# The PEDP service uses ``P_<field>`` for national percentile (int 0–100)
# and raw indicator values directly (``PM25``, ``OZONE``, etc.).
_PEDP_PCT_FIELDS = {
    "PM25_PCT":   "P_PM25",
    "OZONE_PCT":  "P_OZONE",
    "DSLPM_PCT":  "P_DSLPM",
    # CANCER and RESP were removed in EJScreen V2.32; RSEI_AIR replaced them.
    # Store RSEI_AIR under CANCER_PCT so downstream checks still trigger.
    # RESP_PCT has no V2.32 equivalent — evaluator returns None (no check).
    "CANCER_PCT": "P_RSEI_AIR",
    "PTRAF_PCT":  "P_PTRAF",
    "PNPL_PCT":   "P_PNPL",
    "PRMP_PCT":   "P_PRMP",
    "PTSDF_PCT":  "P_PTSDF",
    "UST_PCT":    "P_UST",
    "PWDIS_PCT":  "P_PWDIS",
    "LEAD_PCT":   "P_LDPNT",
}

# Out-fields to request — keeps response size manageable.
_PEDP_OUT_FIELDS = ",".join([
    "ID", "ST_ABBREV", "ACSTOTPOP",
    "PM25", "OZONE", "DSLPM", "PTRAF", "PNPL", "PRMP", "PTSDF", "UST", "PWDIS",
    "RSEI_AIR",
    *dict.fromkeys(_PEDP_PCT_FIELDS.values()),
])


def _fetch_pedp_page(
    offset: int,
    where_clause: str = "1=1",
) -> dict:
    """Fetch one page from the PEDP EJScreen block group service."""
    params = {
        "where": where_clause,
        "outFields": _PEDP_OUT_FIELDS,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    for attempt in range(5):
        try:
            resp = requests.get(_PEDP_ENDPOINT, params=params, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"ArcGIS error: {data['error']}")
            return data
        except Exception as e:
            if attempt < 4:
                wait = 10 * (attempt + 1)
                logger.warning(
                    "PEDP fetch failed (attempt %d): %s — retrying in %ds",
                    attempt + 1, e, wait,
                )
                time.sleep(wait)
            else:
                raise


def _ingest_from_pedp(
    conn,
    states: list[str] | None = None,
    limit: int = 0,
) -> tuple[int, int]:
    """Ingest EJScreen data from the PEDP community mirror.

    The PEDP service mirrors EPA's EJScreen V2.32 national block-group
    dataset with all indicators in a single layer.  Polygon geometry is
    converted to a centroid POINT for the spatial query pattern used by
    ``find_facilities_within()``.

    Returns (total_inserted, total_skipped).
    """
    where = "1=1"
    if states:
        in_list = ", ".join(f"'{s.upper()}'" for s in states)
        where = f"ST_ABBREV IN ({in_list})"

    logger.info("Starting EJScreen ingestion from PEDP mirror")
    logger.info("  WHERE: %s", where)

    total_inserted = 0
    total_skipped = 0
    offset = 0
    batch_num = 0

    while True:
        batch_num += 1
        logger.info("Fetching batch %d (offset %d)...", batch_num, offset)
        data = _fetch_pedp_page(offset, where)

        features = data.get("features", [])
        if not features:
            logger.info("No more features — done.")
            break

        inserted_this_batch = 0
        for feat in features:
            attrs = feat.get("attributes", {})
            geom = feat.get("geometry", {})

            # Compute centroid from polygon rings
            rings = geom.get("rings")
            centroid = _polygon_centroid(rings) if rings else None
            if centroid is None:
                total_skipped += 1
                continue
            lng, lat = centroid
            if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                total_skipped += 1
                continue

            bg_id = str(attrs.get("ID", ""))
            name = f"Block Group {bg_id}"

            # Extract percentile values
            indicators: dict = {}
            for our_key, pedp_field in _PEDP_PCT_FIELDS.items():
                val = attrs.get(pedp_field)
                if val is not None:
                    try:
                        indicators[our_key] = float(val)
                    except (ValueError, TypeError):
                        pass

            metadata = {
                "block_group_id": bg_id,
                "state": attrs.get("ST_ABBREV", ""),
                "population": attrs.get("ACSTOTPOP"),
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

    return total_inserted, total_skipped


# ── Main ingest function ─────────────────────────────────────────────


def ingest(
    limit: int = 0,
    state: str = "",
    states: list[str] | None = None,
    discover: bool = False,
    bbox: str = "",
):
    """Main ingestion entry point.

    Tries the combined EPA endpoint first; falls back to the PEDP
    community mirror if the combined endpoint is unavailable.
    """

    if discover:
        # Try combined endpoint
        endpoint = _probe_combined_endpoint()
        if endpoint:
            logger.info("Combined endpoint available: %s", endpoint[:80])
            params = {
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "json",
                "resultRecordCount": 1,
            }
            resp = requests.get(endpoint, params=params, timeout=60)
            data = resp.json()
            if "features" in data and data["features"]:
                feat = data["features"][0]
                attrs = feat.get("attributes", {})
                indicators = _get_indicator_fields(attrs)
                logger.info("Extracted indicators: %s", json.dumps(indicators, indent=2))
            return

        # Fall back to PEDP mirror
        logger.warning("Combined endpoint unavailable — probing PEDP mirror")
        params = {
            "where": "OBJECTID=1",
            "outFields": _PEDP_OUT_FIELDS,
            "returnGeometry": "false",
            "f": "json",
        }
        try:
            resp = requests.get(_PEDP_ENDPOINT, params=params, timeout=60)
            data = resp.json()
            if "features" in data and data["features"]:
                attrs = data["features"][0]["attributes"]
                logger.info("PEDP mirror sample:")
                for k, v in list(attrs.items())[:20]:
                    logger.info("  %s: %s", k, v)
                logger.info("PEDP endpoint: %s", _PEDP_ENDPOINT[:80])
        except Exception as e:
            logger.error("PEDP probe failed: %s", e)
        return

    # --- Full ingestion ---

    source_url = ""
    use_combined = False

    endpoint = _probe_combined_endpoint()
    if endpoint:
        use_combined = True
        source_url = endpoint
        logger.info("Using combined EPA endpoint")
    else:
        logger.warning(
            "EPA combined EJScreen endpoint unavailable (removed Feb 2025). "
            "Falling back to PEDP community mirror."
        )
        source_url = _PEDP_ENDPOINT

    init_spatial_db()
    create_facility_table("ejscreen")
    logger.info("Created facilities_ejscreen table")

    conn = _connect()
    total_inserted = 0
    total_skipped = 0

    try:
        if use_combined:
            # Original combined-endpoint path
            where = "1=1"
            if states:
                for st in states:
                    st_upper = st.upper()
                    if not (len(st_upper) == 2 and st_upper.isalpha()):
                        raise ValueError(f"Invalid state abbreviation: {st!r}")
                in_list = ", ".join(f"'{s.upper()}'" for s in states)
                where = f"ST_ABBREV IN ({in_list})"
            elif state:
                st = state.upper()
                if not (len(st) == 2 and st.isalpha()):
                    raise ValueError(f"Invalid state abbreviation: {state!r}")
                where = f"ST_ABBREV = '{st}'"

            logger.info("Starting EJScreen ingestion (combined endpoint)")
            logger.info("  WHERE: %s", where)

            offset = 0
            batch_num = 0
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

        else:
            # PEDP mirror path — single combined service
            logger.info("Starting EJScreen ingestion (PEDP mirror)")
            total_inserted, total_skipped = _ingest_from_pedp(
                conn, states=states or ([state] if state else ["NY", "CT", "NJ"]),
                limit=limit,
            )

        # Update dataset registry
        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "ejscreen",
                source_url,
                datetime.now(timezone.utc).isoformat(),
                total_inserted,
                "PEDP community mirror V2.32 (EPA endpoint removed Feb 2025)"
                if not use_combined
                else "Combined endpoint",
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
            r.metadata.get("PM25_PCT", r.metadata.get("PM25", "N/A")),
            r.metadata.get("PTRAF_PCT", r.metadata.get("PTRAF", "N/A")),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest EPA EJScreen block group data")
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Max records to ingest (0 = all).",
    )
    parser.add_argument(
        "--state", type=str, default="",
        help="Filter to a single state (e.g., NY, CA). Combined endpoint only.",
    )
    parser.add_argument(
        "--bbox", type=str, default="",
        help="Bounding box: lng_min,lat_min,lng_max,lat_max. Used by ArcGIS Online fallback.",
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
        ingest(limit=args.limit, state=args.state, bbox=args.bbox)
        if args.verify:
            verify()
