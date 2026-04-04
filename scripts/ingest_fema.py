#!/usr/bin/env python3
"""
Ingest FEMA NFHL (National Flood Hazard Layer) flood zone polygons into the NestCheck spatial database.

Two ingestion methods:
  1. REST API — ArcGIS MapServer Layer 28, paginated with spatial bbox queries.
     Works for most metros but fails for dense areas (DMV) due to query complexity limits.
  2. Bulk NDJSON — Pre-converted from state-level FEMA GDB downloads (NES-404).
     Used for metros where REST is unreliable. See scripts/prepare_fema_bulk.sh.

Per-metro routing: ingest_metros() checks for bulk files first, falls back to REST.

Usage:
    python scripts/ingest_fema.py --discover
    python scripts/ingest_fema.py --bbox -74.05,40.68,-73.90,40.82  # Manhattan
    python scripts/ingest_fema.py --metros --states MD,DC,VA         # DMV via bulk
    python scripts/ingest_fema.py --verify                           # Verify test points
"""

import argparse
import gzip
import json
import logging
import math
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

# Bump this to force re-ingestion when metro bboxes change or
# new ingestion methods are added (e.g., bulk download for dense metros).
# startup_ingest.py compares this against the version stored in dataset_registry.
FEMA_INGEST_VERSION = 4

# PRD launch metro bounding boxes (lng_min, lat_min, lng_max, lat_max)
METRO_BBOXES = {
    # NYC metro: five boroughs, northern NJ (incl. Morristown), Long Island (incl. Huntington), Westchester up to Putnam
    "nyc": (-74.55, 40.45, -73.35, 41.40),
    # Detroit-Ann Arbor corridor
    "detroit": (-83.8, 42.0, -82.9, 42.8),
    # SF Bay Area: Oakland, Berkeley, San Jose, Marin
    "sf": (-122.55, 37.20, -121.75, 38.05),
    "chicago": (-87.95, 41.60, -87.50, 42.10),
    "la": (-118.70, 33.65, -117.65, 34.35),
    # Seattle metro: Tacoma, Everett, Bellevue/Eastside
    "seattle": (-122.50, 47.15, -122.00, 47.85),
    # Houston: city center + Sugar Land, Pasadena, Katy corridor
    "houston": (-95.80, 29.50, -95.05, 30.10),
    # Dallas: core + Arlington + Fort Worth east
    "dallas": (-97.05, 32.55, -96.45, 33.05),
    # Miami-Dade + Fort Lauderdale corridor
    "miami": (-80.50, 25.60, -80.05, 26.25),
    # Tampa + St. Petersburg + Clearwater
    "tampa": (-82.80, 27.70, -82.35, 28.15),
    # DC-Baltimore-NoVA: DC proper, Arlington, Alexandria, Fairfax, Bethesda, Silver Spring, Columbia, Baltimore
    "dmv": (-77.55, 38.55, -76.50, 39.50),
}

METRO_TO_STATES = {
    "nyc": ["NY", "NJ", "CT"],
    "detroit": ["MI"],
    "sf": ["CA"],
    "chicago": ["IL"],
    "la": ["CA"],
    "seattle": ["WA"],
    "houston": ["TX"],
    "dallas": ["TX"],
    "miami": ["FL"],
    "tampa": ["FL"],
    "dmv": ["MD", "DC", "VA"],
}

_GRID_CELL_SIZE = 0.5


def get_stored_fema_version() -> int:
    """Read the FEMA ingest version from dataset_registry.notes.

    The notes field is written as "v=N, metros: ..." by ingest_metros().
    Returns 0 if no version is found (triggers re-ingest).
    """
    try:
        conn = _connect()
        try:
            cursor = conn.execute(
                "SELECT notes FROM dataset_registry WHERE facility_type = 'fema_nfhl'"
            )
            row = cursor.fetchone()
            if not row or not row[0]:
                return 0
            notes = row[0]
            # Parse "v=N" prefix from notes
            if notes.startswith("v="):
                parts = notes.split(",", 1)
                return int(parts[0].split("=")[1].strip())
            return 0
        finally:
            conn.close()
    except Exception:
        return 0

def _generate_grid_cells(bbox, cell_size=_GRID_CELL_SIZE):
    lng_min, lat_min, lng_max, lat_max = bbox
    cols = math.ceil((lng_max - lng_min) / cell_size)
    rows = math.ceil((lat_max - lat_min) / cell_size)
    for col in range(cols):
        for row in range(rows):
            yield (
                lng_min + col * cell_size,
                lat_min + row * cell_size,
                min(lng_min + (col + 1) * cell_size, lng_max),
                min(lat_min + (row + 1) * cell_size, lat_max),
            )


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


def _geojson_to_multipolygon_wkt(geom: dict, decimals: int = 6) -> str | None:
    """Convert a GeoJSON geometry dict to MULTIPOLYGON WKT.

    Handles both "Polygon" and "MultiPolygon" geometry types.
    GeoJSON coordinates are [lng, lat] — same order as ArcGIS rings,
    so no coordinate swapping is needed.
    """
    if not geom or not isinstance(geom, dict):
        return None
    geom_type = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return None

    try:
        # Normalize Polygon → list-of-one-polygon for uniform handling
        if geom_type == "Polygon":
            polygons = [coords]
        elif geom_type == "MultiPolygon":
            polygons = coords
        else:
            return None

        polygon_strs = []
        for polygon in polygons:
            ring_strs = []
            for ring in polygon:
                if not ring or len(ring) < 3:
                    continue
                pts = ", ".join(
                    f"{round(p[0], decimals)} {round(p[1], decimals)}"
                    for p in ring
                )
                ring_strs.append(f"({pts})")
            if ring_strs:
                polygon_strs.append(f"({', '.join(ring_strs)})")

        if not polygon_strs:
            return None
        return f"MULTIPOLYGON({', '.join(polygon_strs)})"
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


def _ingest_bbox(conn, bbox, limit_pages=0):
    """Fetch+insert loop for a single bbox. Returns (total_inserted, total_skipped)."""
    total_inserted = 0
    total_skipped = 0
    offset = 0
    batch_num = 0

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

    return total_inserted, total_skipped


# -- Bulk ingestion (NES-404) -------------------------------------------------
# FEMA REST API fails for dense metros (DMV). Pre-converted NDJSON files
# (from state-level GDB via ogr2ogr) provide a reliable alternative.
# See scripts/prepare_fema_bulk.sh for the conversion recipe.

# Sentinel value used in FEMA GDB for null numeric fields
_FEMA_NULL_SENTINEL = -9999.0

# GDB uses T/F for SFHA_TF; REST API uses Y/N. Normalize to Y/N.
_SFHA_NORMALIZE = {"T": "Y", "F": "N"}

# Metros with pre-converted bulk NDJSON files.
# Files live in data/fema_nfhl/ (gitignored, like spatial.db).
METRO_BULK_FILES = {
    "dmv": ["dc_dmv.ndjson.gz", "md_dmv.ndjson.gz", "va_dmv.ndjson.gz"],
}

_BULK_COMMIT_BATCH = 500


def _bulk_data_dir() -> str:
    """Return the directory containing FEMA bulk NDJSON files."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "data", "fema_nfhl")


def _ingest_bulk(conn, filepath: str) -> tuple[int, int]:
    """Ingest flood zones from a gzipped NDJSON (GeoJSONSeq) file.

    Produces identical (name, geometry, metadata_json) rows to the REST path.
    Returns (total_inserted, total_skipped).
    """
    total_inserted = 0
    total_skipped = 0
    basename = os.path.basename(filepath)

    with gzip.open(filepath, "rt", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                feat = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("[%s] line %d: invalid JSON, skipping", basename, line_num)
                total_skipped += 1
                continue

            props = feat.get("properties") or {}
            geom = feat.get("geometry")

            wkt = _geojson_to_multipolygon_wkt(geom)
            if not wkt:
                total_skipped += 1
                continue

            fld_zone = props.get("FLD_ZONE") or "Unknown"
            zone_subty = props.get("ZONE_SUBTY") or ""
            name = f"Flood Zone {fld_zone}"
            if zone_subty:
                name = f"{name} - {zone_subty}"

            # Normalize GDB field differences to match REST output
            raw_sfha = props.get("SFHA_TF") or ""
            static_bfe = props.get("STATIC_BFE")
            depth = props.get("DEPTH")

            metadata = {
                "fld_zone": fld_zone,
                "zone_subtype": zone_subty,
                "sfha_tf": _SFHA_NORMALIZE.get(raw_sfha, raw_sfha),
                "static_bfe": None if static_bfe == _FEMA_NULL_SENTINEL else static_bfe,
                "depth": None if depth == _FEMA_NULL_SENTINEL else depth,
                "dfirm_id": props.get("DFIRM_ID") or "",
                "object_id": None,  # GDB OBJECTID is the FID, not a regular field
            }

            try:
                conn.execute(
                    """INSERT INTO facilities_fema_nfhl (name, geometry, metadata_json)
                       VALUES (?, GeomFromText(?, 4326), ?)""",
                    (name, wkt, json.dumps(metadata)),
                )
                total_inserted += 1
            except Exception as e:
                logger.warning("[%s] line %d insert failed: %s", basename, line_num, e)
                total_skipped += 1

            if total_inserted % _BULK_COMMIT_BATCH == 0:
                conn.commit()

    conn.commit()  # Final batch
    logger.info(
        "[%s] bulk ingest: %d inserted, %d skipped",
        basename, total_inserted, total_skipped,
    )
    return total_inserted, total_skipped


def _log_db_size():
    db_path = (
        os.path.join(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", ""), "spatial.db")
        if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
        else os.environ.get("NESTCHECK_SPATIAL_DB_PATH", "data/spatial.db")
    )
    db_size_mb = os.path.getsize(db_path) / (1024 * 1024) if os.path.exists(db_path) else 0
    logger.info("  DB size:       %.1f MB", db_size_mb)


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
    try:
        total_inserted, total_skipped = _ingest_bbox(conn, bbox, limit_pages)

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

    logger.info("=" * 50)
    logger.info("FEMA NFHL INGESTION COMPLETE")
    logger.info("  Total inserted: %d", total_inserted)
    logger.info("  Total skipped:  %d", total_skipped)
    _log_db_size()
    logger.info("=" * 50)


def _metro_has_bulk_files(metro_key: str) -> list[str] | None:
    """Check if all bulk NDJSON files exist for a metro.

    Returns list of absolute file paths if all files are present,
    None otherwise (triggers REST fallback).
    """
    filenames = METRO_BULK_FILES.get(metro_key)
    if not filenames:
        return None
    bulk_dir = _bulk_data_dir()
    paths = [os.path.join(bulk_dir, f) for f in filenames]
    if all(os.path.exists(p) for p in paths):
        return paths
    return None


def _ingest_metro_bulk(conn, metro_key: str, bulk_paths: list[str]) -> tuple[int, int]:
    """Ingest a metro via bulk NDJSON files. Returns (inserted, skipped)."""
    total_inserted = 0
    total_skipped = 0
    logger.info("[%s] using BULK ingestion (%d files)", metro_key, len(bulk_paths))
    for path in bulk_paths:
        inserted, skipped = _ingest_bulk(conn, path)
        total_inserted += inserted
        total_skipped += skipped
    return total_inserted, total_skipped


def _ingest_metro_rest(conn, metro_key: str) -> tuple[int, int, int, int]:
    """Ingest a metro via REST API grid cells. Returns (inserted, skipped, ok, failed)."""
    metro_bbox = METRO_BBOXES[metro_key]
    cells = list(_generate_grid_cells(metro_bbox))
    logger.info("[%s] using REST API (%d grid cells from bbox %s)", metro_key, len(cells), metro_bbox)

    total_inserted = 0
    total_skipped = 0
    chunks_ok = 0
    chunks_fail = 0

    for i, cell in enumerate(cells, 1):
        try:
            logger.info("  [%s] chunk %d/%d: %s", metro_key, i, len(cells), cell)
            inserted, skipped = _ingest_bbox(conn, cell)
            total_inserted += inserted
            total_skipped += skipped
            chunks_ok += 1
            logger.info("  [%s] chunk %d: inserted %d, skipped %d", metro_key, i, inserted, skipped)
        except Exception:
            chunks_fail += 1
            logger.warning("  [%s] chunk %d FAILED", metro_key, i, exc_info=True)

    return total_inserted, total_skipped, chunks_ok, chunks_fail


def ingest_metros(target_states=None):
    """Ingest FEMA NFHL for all metros matching target_states.

    Per-metro routing: uses bulk NDJSON files when available (e.g., DMV
    where REST API fails due to polygon density), REST API otherwise.
    """
    if target_states:
        state_set = set(target_states)
        metros = [m for m in METRO_BBOXES if state_set & set(METRO_TO_STATES.get(m, []))]
    else:
        metros = list(METRO_BBOXES.keys())

    logger.info("ingest_metros: target_states=%s, metros=%s", target_states, metros)

    init_spatial_db()
    create_facility_table("fema_nfhl", geometry_type="MULTIPOLYGON")
    logger.info("Created facilities_fema_nfhl table")

    conn = _connect()
    total_features = 0
    rest_chunks_ok = 0
    rest_chunks_fail = 0
    metro_methods = []  # e.g., ["nyc(rest)", "dmv(bulk)"]

    try:
        for metro_key in metros:
            bulk_paths = _metro_has_bulk_files(metro_key)

            if bulk_paths:
                try:
                    inserted, _skipped = _ingest_metro_bulk(conn, metro_key, bulk_paths)
                    total_features += inserted
                    metro_methods.append(f"{metro_key}(bulk)")
                except Exception:
                    logger.warning(
                        "[%s] bulk ingestion failed, falling back to REST API",
                        metro_key, exc_info=True,
                    )
                    # Fall through to REST on corrupt/invalid bulk files
                    bulk_paths = None

            if not bulk_paths:
                inserted, _skipped, ok, fail = _ingest_metro_rest(conn, metro_key)
                total_features += inserted
                rest_chunks_ok += ok
                rest_chunks_fail += fail
                metro_methods.append(f"{metro_key}(rest)")

        # Write dataset_registry with per-metro method summary
        metro_note = (
            f"v={FEMA_INGEST_VERSION}, "
            f"metros: {','.join(metro_methods)}, "
            f"rest_chunks: {rest_chunks_ok} ok / {rest_chunks_fail} failed"
        )
        conn.execute(
            """INSERT OR REPLACE INTO dataset_registry
               (facility_type, source_url, ingested_at, record_count, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "fema_nfhl",
                FEMA_ENDPOINT,
                datetime.now(timezone.utc).isoformat(),
                total_features,
                metro_note,
            ),
        )
        conn.commit()

    finally:
        conn.close()

    logger.info("=" * 50)
    logger.info("FEMA NFHL METRO INGESTION COMPLETE")
    logger.info("  Metros processed: %s", metro_methods)
    logger.info("  Total features:   %d", total_features)
    logger.info("  REST chunks:      %d ok / %d failed", rest_chunks_ok, rest_chunks_fail)
    _log_db_size()
    logger.info("=" * 50)

    return {
        "metros_processed": metro_methods,
        "total_features": total_features,
        "rest_chunks_ok": rest_chunks_ok,
        "rest_chunks_failed": rest_chunks_fail,
    }


def verify():
    """Quick verification: point-in-polygon at known flood zone locations.

    Tests both NYC (REST-ingested) and DMV (bulk-ingested) metros.
    """
    from spatial_data import SpatialDataStore

    store = SpatialDataStore()
    if not store.is_available():
        logger.error("Spatial DB not available")
        return

    # Test points: (label, lat, lng, expected_zone_prefix_or_None)
    # Zone prefix: "A" or "V" = high-risk SFHA, "X" = minimal, None = no polygon expected.
    # Note: Battery Park requires NYC REST data to be ingested.
    test_points = [
        # NYC metro (REST API) — only passes if NYC was ingested
        ("Battery Park, Manhattan", 40.7025, -74.0150, "AE"),
        ("Midtown, Manhattan", 40.7580, -73.9855, None),
        # DMV metro (bulk ingestion, NES-404)
        ("Georgetown waterfront, DC", 38.9025, -77.0597, "AE"),
        ("Old Town Alexandria waterfront, VA", 38.8048, -77.0469, "X"),
        ("Arlington inland, VA", 38.8816, -77.0910, "X"),
    ]

    passed = 0
    skipped = 0
    failed = 0

    for label, lat, lng, expected_zone in test_points:
        results = store.point_in_polygons(lat, lng, "fema_nfhl")
        actual_zone = results[0].metadata.get("fld_zone", "") if results else None

        if expected_zone is None:
            # Expect no polygon match
            status = "PASS" if not results else "FAIL"
        elif not results:
            # Expected a zone but got nothing — data may not be ingested
            status = "SKIP"
        else:
            status = "PASS" if actual_zone == expected_zone else "FAIL"

        if status == "PASS":
            passed += 1
        elif status == "SKIP":
            skipped += 1
        else:
            failed += 1

        logger.info(
            "[%s] %s (%.4f, %.4f): zone=%s (expected %s)",
            status, label, lat, lng,
            actual_zone or "none",
            expected_zone or "none",
        )
        for r in results[:3]:
            logger.info(
                "  %s — zone: %s, sfha: %s",
                r.name, r.metadata.get("fld_zone", ""), r.metadata.get("sfha_tf", ""),
            )

    logger.info(
        "Verification: %d passed, %d skipped (data not ingested), %d failed",
        passed, skipped, failed,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest FEMA NFHL flood zone polygons")
    parser.add_argument(
        "--bbox", type=str, default="",
        help="Bounding box: lng_min,lat_min,lng_max,lat_max (e.g., -74.05,40.68,-73.90,40.82)",
    )
    parser.add_argument(
        "--metro", type=str, default="",
        help="Use predefined metro bbox (nyc, sf, chicago, la, seattle, detroit, houston, dallas, miami, tampa).",
    )
    parser.add_argument(
        "--metros", action="store_true",
        help="Ingest all metros matching --states (or all defined metros).",
    )
    parser.add_argument(
        "--states", type=str, default="",
        help="Comma-separated state codes to filter metros (e.g., NY,NJ,CT,MI).",
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
    elif args.verify and not args.metros and not args.bbox and not args.metro:
        # Standalone --verify: just run verification on existing data
        verify()
    elif args.metros:
        target = [s.strip() for s in args.states.split(",") if s.strip()] if args.states else None
        ingest_metros(target_states=target)
        if args.verify:
            verify()
    else:
        ingest(bbox=bbox, metro=args.metro, limit_pages=args.limit)
        if args.verify:
            verify()
