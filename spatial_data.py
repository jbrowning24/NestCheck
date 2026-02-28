"""
SpatiaLite-backed spatial data store for bulk-ingested datasets (NES-156).

Manages a separate SpatiaLite database file for EPA UST, TRI, SEMS, FHWA HPMS,
and other spatial datasets. Queries use SpatiaLite spatial functions and
R-tree indexes. Graceful degradation: if SpatiaLite or DB is unavailable,
returns empty results — never crashes the evaluation.
"""

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


def _spatial_db_path() -> str:
    """Resolve spatial database path. Mirrors models.py DB_PATH logic."""
    if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        return os.path.join(os.environ["RAILWAY_VOLUME_MOUNT_PATH"], "spatial.db")
    return os.environ.get("NESTCHECK_SPATIAL_DB_PATH", "data/spatial.db")


def _connect() -> sqlite3.Connection:
    """Open a SpatiaLite-enabled connection."""
    conn = sqlite3.connect(_spatial_db_path())
    conn.execute("PRAGMA journal_mode=WAL")
    conn.enable_load_extension(True)
    # Try common SpatiaLite library names
    for lib_name in ["mod_spatialite", "libspatialite"]:
        try:
            conn.load_extension(lib_name)
            return conn
        except Exception:
            continue
    raise RuntimeError(
        "SpatiaLite extension not found. "
        "Install libspatialite-dev (apt) or spatialite-tools (brew)."
    )


@dataclass
class FacilityRecord:
    """A spatial record returned from proximity queries."""

    facility_type: str  # "ust", "tri", "sems", "hpms"
    name: str  # Facility/site name
    lat: float
    lng: float
    distance_meters: float  # Distance from query point
    distance_feet: float  # Convenience conversion
    metadata: dict  # Type-specific extra fields

    @property
    def distance_miles(self) -> float:
        return self.distance_meters / 1609.344


class SpatialDataStore:
    """
    Manages a SpatiaLite database of bulk-ingested spatial datasets.

    Usage:
        store = SpatialDataStore()
        if store.is_available():
            results = store.find_facilities_within(40.71, -74.00, 500, "ust")
    """

    def __init__(self):
        self._available: Optional[bool] = None
        self._last_query_error: Optional[str] = None

    def last_query_failed(self) -> bool:
        """Whether the most recent spatial query on this instance failed."""
        return self._last_query_error is not None

    def is_available(self) -> bool:
        """Check if spatial DB exists and SpatiaLite loads.
        Result is cached after first check."""
        if self._available is not None:
            return self._available
        try:
            db_path = _spatial_db_path()
            if not os.path.exists(db_path):
                logger.info(
                    "Spatial DB not found at %s — spatial queries disabled", db_path
                )
                self._available = False
                return False
            conn = _connect()
            conn.close()
            self._available = True
            return True
        except Exception as e:
            logger.warning(
                "SpatiaLite not available: %s — spatial queries disabled", e
            )
            self._available = False
            return False

    def find_facilities_within(
        self,
        lat: float,
        lng: float,
        radius_meters: float,
        facility_type: str,
    ) -> List[FacilityRecord]:
        """
        Find all facilities of the given type within radius_meters of (lat, lng).
        Returns list sorted by distance ascending. Returns empty list on any error.
        """
        if not self.is_available():
            return []

        trace = None
        try:
            from nc_trace import get_trace

            trace = get_trace()
        except Exception:
            pass

        t0 = time.time()
        table_name = f"facilities_{facility_type}"
        query_ok = False

        try:
            conn = _connect()
            try:
                # BuildCircleMbr radius is in degrees for SRID 4326.
                # Use generous overestimate (80000) so R-tree never misses;
                # ST_Distance handles exact filtering.
                radius_deg = radius_meters / 80000.0
                # Use SpatiaLite distance function; R-tree pre-filter if available
                cursor = conn.execute(
                    f"""
                    SELECT
                        name,
                        Y(geometry) as lat,
                        X(geometry) as lng,
                        ST_Distance(
                            geometry,
                            MakePoint(?, ?, 4326),
                            1
                        ) as distance_m,
                        metadata_json
                    FROM {table_name}
                    WHERE ROWID IN (
                        SELECT ROWID FROM SpatialIndex
                        WHERE f_table_name = ?
                        AND f_geometry_column = 'geometry'
                        AND search_frame = BuildCircleMbr(?, ?, ?, 4326)
                    )
                    AND ST_Distance(
                        geometry,
                        MakePoint(?, ?, 4326),
                        1
                    ) <= ?
                    ORDER BY distance_m ASC
                    """,
                    (
                        lng,
                        lat,
                        table_name,
                        lng,
                        lat,
                        radius_deg,
                        lng,
                        lat,
                        radius_meters,
                    ),
                )
                results = []
                for row in cursor:
                    name, rlat, rlng, dist_m, meta_json = row
                    metadata = json.loads(meta_json) if meta_json else {}
                    results.append(
                        FacilityRecord(
                            facility_type=facility_type,
                            name=name or "Unknown",
                            lat=rlat,
                            lng=rlng,
                            distance_meters=dist_m,
                            distance_feet=dist_m * 3.28084,
                            metadata=metadata,
                        )
                    )
                self._last_query_error = None
                query_ok = True
                return results
            finally:
                conn.close()
        except Exception as e:
            self._last_query_error = str(e)
            logger.warning("Spatial query failed for %s: %s", facility_type, e)
            return []
        finally:
            t1 = time.time()
            elapsed_ms = int((t1 - t0) * 1000)
            if trace:
                trace.record_api_call(
                    service="spatial",
                    endpoint=f"find_{facility_type}({lat:.4f},{lng:.4f},r={radius_meters})",
                    elapsed_ms=elapsed_ms,
                    status_code=200 if query_ok else 500,
                    provider_status="ok" if query_ok else "error",
                )

    def nearest_facility(
        self,
        lat: float,
        lng: float,
        facility_type: str,
        max_radius_meters: float = 5000,
    ) -> Optional[FacilityRecord]:
        """Return the single closest facility, or None."""
        results = self.find_facilities_within(
            lat, lng, max_radius_meters, facility_type
        )
        return results[0] if results else None

    def facility_count_within(
        self,
        lat: float,
        lng: float,
        radius_meters: float,
        facility_type: str,
    ) -> int:
        """Count only — avoids hydrating full records when you just need a number."""
        if not self.is_available():
            return 0
        table_name = f"facilities_{facility_type}"
        try:
            conn = _connect()
            try:
                radius_deg = radius_meters / 80000.0
                cursor = conn.execute(
                    f"""
                    SELECT COUNT(*) FROM {table_name}
                    WHERE ROWID IN (
                        SELECT ROWID FROM SpatialIndex
                        WHERE f_table_name = ?
                        AND f_geometry_column = 'geometry'
                        AND search_frame = BuildCircleMbr(?, ?, ?, 4326)
                    )
                    AND ST_Distance(
                        geometry,
                        MakePoint(?, ?, 4326),
                        1
                    ) <= ?
                    """,
                    (
                        table_name,
                        lng,
                        lat,
                        radius_deg,
                        lng,
                        lat,
                        radius_meters,
                    ),
                )
                return cursor.fetchone()[0]
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Spatial count failed for %s: %s", facility_type, e)
            return 0

    def point_in_polygons(
        self, lat: float, lng: float, facility_type: str
    ) -> List[FacilityRecord]:
        """
        Return all polygon features from facilities_{facility_type} that
        contain the given point.
        """
        if not self.is_available():
            return []
        table_name = f"facilities_{facility_type}"
        try:
            conn = _connect()
            try:
                # R-tree pre-filter: polygons whose MBR contains the point.
                # Use point as search_frame; SpatiaLite returns geometries
                # whose envelope intersects the search_frame envelope.
                cursor = conn.execute(
                    f"""
                    SELECT
                        name,
                        Y(ST_Centroid(geometry)) as lat,
                        X(ST_Centroid(geometry)) as lng,
                        metadata_json
                    FROM {table_name}
                    WHERE ROWID IN (
                        SELECT ROWID FROM SpatialIndex
                        WHERE f_table_name = ?
                        AND f_geometry_column = 'geometry'
                        AND search_frame = MakePoint(?, ?, 4326)
                    )
                    AND ST_Contains(geometry, MakePoint(?, ?, 4326))
                    """,
                    (table_name, lng, lat, lng, lat),
                )
                results = []
                for row in cursor:
                    name, rlat, rlng, meta_json = row
                    metadata = json.loads(meta_json) if meta_json else {}
                    results.append(
                        FacilityRecord(
                            facility_type=facility_type,
                            name=name or "Unknown",
                            lat=rlat,
                            lng=rlng,
                            distance_meters=0.0,
                            distance_feet=0.0,
                            metadata=metadata,
                        )
                    )
                return results
            finally:
                conn.close()
        except Exception as e:
            logger.warning(
                "Point-in-polygon query failed for %s: %s", facility_type, e
            )
            return []

    def nearest_line(
        self,
        lat: float,
        lng: float,
        facility_type: str,
        max_radius_meters: float = 5000,
    ) -> Optional[FacilityRecord]:
        """Return the closest line feature within max_radius_meters."""
        results = self.lines_within(
            lat, lng, max_radius_meters, facility_type
        )
        return results[0] if results else None

    def lines_within(
        self,
        lat: float,
        lng: float,
        radius_meters: float,
        facility_type: str,
    ) -> List[FacilityRecord]:
        """Return all line features within radius_meters of the given point."""
        if not self.is_available():
            return []
        table_name = f"facilities_{facility_type}"
        try:
            conn = _connect()
            try:
                radius_deg = radius_meters / 80000.0
                # For lines: use centroid for lat/lng; ST_Distance gives
                # distance from point to line.
                cursor = conn.execute(
                    f"""
                    SELECT
                        name,
                        Y(ST_Centroid(geometry)) as lat,
                        X(ST_Centroid(geometry)) as lng,
                        ST_Distance(
                            geometry,
                            MakePoint(?, ?, 4326),
                            1
                        ) as distance_m,
                        metadata_json
                    FROM {table_name}
                    WHERE ROWID IN (
                        SELECT ROWID FROM SpatialIndex
                        WHERE f_table_name = ?
                        AND f_geometry_column = 'geometry'
                        AND search_frame = BuildCircleMbr(?, ?, ?, 4326)
                    )
                    AND ST_Distance(
                        geometry,
                        MakePoint(?, ?, 4326),
                        1
                    ) <= ?
                    ORDER BY distance_m ASC
                    """,
                    (
                        lng,
                        lat,
                        table_name,
                        lng,
                        lat,
                        radius_deg,
                        lng,
                        lat,
                        radius_meters,
                    ),
                )
                results = []
                for row in cursor:
                    name, rlat, rlng, dist_m, meta_json = row
                    metadata = json.loads(meta_json) if meta_json else {}
                    results.append(
                        FacilityRecord(
                            facility_type=facility_type,
                            name=name or "Unknown",
                            lat=rlat,
                            lng=rlng,
                            distance_meters=dist_m,
                            distance_feet=dist_m * 3.28084,
                            metadata=metadata,
                        )
                    )
                return results
            finally:
                conn.close()
        except Exception as e:
            logger.warning(
                "Lines-within query failed for %s: %s", facility_type, e
            )
            return []


def init_spatial_db():
    """
    Initialize the SpatiaLite database with metadata table.
    Called by ingestion scripts, not by the web app.
    """
    db_path = _spatial_db_path()
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = _connect()
    try:
        # Initialize SpatiaLite metadata tables
        conn.execute("SELECT InitSpatialMetaData(1)")

        # Registry table: tracks which datasets have been ingested
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_registry (
                facility_type TEXT PRIMARY KEY,
                source_url TEXT,
                ingested_at TEXT,
                record_count INTEGER,
                notes TEXT
            )
        """
        )
        conn.commit()
    finally:
        conn.close()


def create_facility_table(
    facility_type: str,
    extra_columns: str = "",
    geometry_type: str = "POINT",
):
    """
    Create a facility table with standard schema + optional extra columns.
    Called by ingestion scripts.

    Standard schema:
    - name TEXT
    - geometry (SRID 4326) — POINT, POLYGON, LINESTRING, MULTILINESTRING, or MULTIPOLYGON
    - metadata_json TEXT (JSON blob for type-specific fields)
    - Plus any extra_columns

    Drops existing table first (idempotent).
    """
    allowed = ("POINT", "POLYGON", "LINESTRING", "MULTILINESTRING", "MULTIPOLYGON")
    if geometry_type not in allowed:
        raise ValueError(
            f"geometry_type must be one of {allowed}, got {geometry_type!r}"
        )
    table_name = f"facilities_{facility_type}"
    conn = _connect()
    try:
        # Try to clean up existing spatial metadata first
        try:
            conn.execute(
                f"SELECT DisableSpatialIndex('{table_name}', 'geometry')"
            )
        except Exception:
            pass
        try:
            conn.execute(
                f"SELECT DiscardGeometryColumn('{table_name}', 'geometry')"
            )
        except Exception:
            pass
        conn.execute(f"DROP TABLE IF EXISTS idx_{table_name}_geometry")
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")

        # Create table
        extra = f", {extra_columns}" if extra_columns else ""
        conn.execute(
            f"""
            CREATE TABLE {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                metadata_json TEXT
                {extra}
            )
        """
        )

        # Add geometry column + spatial index
        conn.execute(
            f"SELECT AddGeometryColumn('{table_name}', 'geometry', 4326, "
            f"'{geometry_type}', 'XY')"
        )
        conn.execute(f"SELECT CreateSpatialIndex('{table_name}', 'geometry')")
        conn.commit()
    finally:
        conn.close()
