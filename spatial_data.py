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
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Whitelist of valid facility types for SQL table name interpolation.
# Prevents SQL injection via facility_type parameter.
_VALID_FACILITY_TYPES = frozenset({
    "sems", "fema_nfhl", "hpms", "ejscreen", "tri", "ust",
    "hifld", "fra", "school_districts", "nces_schools",
})


def _validate_facility_type(facility_type: str) -> Optional[str]:
    """Validate facility_type against whitelist, return table name or None.

    Returns None for unknown types (graceful degradation in queries).
    Logs a warning so invalid types are visible in monitoring.
    """
    if facility_type not in _VALID_FACILITY_TYPES:
        logger.warning(
            "Unknown facility_type %r — must be one of %s",
            facility_type, sorted(_VALID_FACILITY_TYPES),
        )
        return None
    return f"facilities_{facility_type}"


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

    def has_nearby_data(
        self,
        lat: float,
        lng: float,
        facility_type: str,
        radius_km: float = 50.0,
    ) -> bool:
        """Check if any data exists within radius_km of the given point.

        Used to distinguish 'no hazard found' (PASS) from 'no data coverage'
        (UNKNOWN) for partial-coverage datasets like FEMA NFHL.
        """
        if not self.is_available():
            return False
        table_name = _validate_facility_type(facility_type)
        if table_name is None:
            return False
        radius_meters = radius_km * 1000.0
        try:
            conn = _connect()
            try:
                radius_deg = radius_meters / 80000.0
                cursor = conn.execute(
                    f"""
                    SELECT 1 FROM {table_name}
                    WHERE ROWID IN (
                        SELECT ROWID FROM SpatialIndex
                        WHERE f_table_name = ?
                        AND f_geometry_column = 'geometry'
                        AND search_frame = BuildCircleMbr(?, ?, ?, 4326)
                    )
                    LIMIT 1
                    """,
                    (table_name, lng, lat, radius_deg),
                )
                return cursor.fetchone() is not None
            finally:
                conn.close()
        except Exception as e:
            logger.warning(
                "has_nearby_data check failed for %s: %s", facility_type, e
            )
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
        table_name = _validate_facility_type(facility_type)
        if table_name is None:
            return []
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
        table_name = _validate_facility_type(facility_type)
        if table_name is None:
            return 0
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
        table_name = _validate_facility_type(facility_type)
        if table_name is None:
            return []
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
        table_name = _validate_facility_type(facility_type)
        if table_name is None:
            return []
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
    table_name = _validate_facility_type(facility_type)
    if table_name is None:
        raise ValueError(
            f"Invalid facility_type {facility_type!r}. "
            f"Must be one of: {sorted(_VALID_FACILITY_TYPES)}"
        )
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


# ---------------------------------------------------------------------------
# Venue Cache — write path (NES-290)
# ---------------------------------------------------------------------------

# Maps Google Places place_type to NestCheck category.
# Covers every places_nearby() call site in property_evaluator.py.
_PLACE_TYPE_TO_CATEGORY: Dict[str, str] = {
    # Coffee & Social
    "cafe": "coffee",
    "bakery": "coffee",
    "coffee_shop": "coffee",
    # Grocery
    "supermarket": "grocery",
    "grocery_store": "grocery",
    "grocery_or_supermarket": "grocery",
    # Fitness
    "gym": "fitness",
    # Parks & Green Space
    "park": "park",
    "playground": "park",
    "campground": "park",
    "natural_feature": "park",
    "trail": "park",
    "rv_park": "park",
    "tourist_attraction": "park",
    # Transit
    "train_station": "transit",
    "subway_station": "transit",
    "light_rail_station": "transit",
    "transit_station": "transit",
    "bus_station": "transit",
    # Schools & Childcare
    "school": "school",
    "primary_school": "school",
    "child_care": "childcare",
    "preschool": "childcare",
    # Safety checks
    "gas_station": "gas_station",
    # Hub search
    "locality": "locality",
}

# Substring rules for inferring category from text_search() queries.
# Checked in order — first match wins.
_TEXT_QUERY_CATEGORY_RULES = [
    ("supermarket", "grocery"),
    ("grocery", "grocery"),
    ("gym", "fitness"),
    ("fitness", "fitness"),
    ("coffee", "coffee"),
    ("cafe", "coffee"),
    ("school", "school"),
    ("daycare", "childcare"),
    ("preschool", "childcare"),
]


def _infer_text_search_category(query: str) -> str:
    """Infer NestCheck category from a text_search query string."""
    q = query.lower()
    for keyword, category in _TEXT_QUERY_CATEGORY_RULES:
        if keyword in q:
            return category
    return "other"


class VenueCache:
    """Write-through cache for Google Places venues in spatial.db.

    Phase 1 (NES-290): write-only. Upserts every venue returned by Google
    Places API as a side effect of normal evaluations. Never blocks or
    crashes evaluations — all writes are swallowed on error.
    """

    # Hardcoded constant — safe for SQL interpolation without the
    # _VALID_FACILITY_TYPES whitelist because it never comes from user input.
    # Not prefixed with "facilities_" because venues are a different entity.
    _TABLE = "venue_cache"

    def __init__(self):
        self._table_ready: bool = False

    def _ensure_table(self) -> bool:
        """Create venue_cache table if it doesn't exist.

        Returns True when the table is confirmed ready. Returns False on any
        error (SpatiaLite unavailable, DB path unwritable, etc.) — the caller
        should skip the write silently.
        """
        if self._table_ready:
            return True
        try:
            db_path = _spatial_db_path()
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

            conn = _connect()
            try:
                conn.execute("PRAGMA busy_timeout = 30000")

                row = conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name=?",
                    (self._TABLE,),
                ).fetchone()
                if row is not None:
                    self._table_ready = True
                    return True

                # Ensure SpatiaLite metadata exists (no-op if already init'd)
                try:
                    conn.execute("SELECT InitSpatialMetaData(1)")
                except Exception:
                    pass

                conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self._TABLE} (
                        place_id TEXT PRIMARY KEY,
                        name TEXT,
                        category TEXT,
                        latitude REAL,
                        longitude REAL,
                        rating REAL,
                        rating_count INTEGER,
                        price_level INTEGER,
                        business_status TEXT,
                        raw_response TEXT,
                        first_seen TEXT NOT NULL,
                        last_verified TEXT NOT NULL,
                        source_address TEXT
                    )
                    """
                )

                # SpatiaLite DDL is NOT idempotent — wrap each call so
                # concurrent first-time creation from multiple workers
                # doesn't fail when the second worker finds column/index
                # already exists.
                try:
                    conn.execute(
                        f"SELECT AddGeometryColumn('{self._TABLE}', "
                        f"'geometry', 4326, 'POINT', 'XY')"
                    )
                except Exception:
                    pass
                try:
                    conn.execute(
                        f"SELECT CreateSpatialIndex('{self._TABLE}', "
                        f"'geometry')"
                    )
                except Exception:
                    pass

                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{self._TABLE}_category "
                    f"ON {self._TABLE} (category)"
                )
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS "
                    f"idx_{self._TABLE}_last_verified "
                    f"ON {self._TABLE} (last_verified)"
                )

                conn.commit()
                self._table_ready = True
                logger.info("Created venue_cache table in spatial.db")
                return True
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Failed to ensure venue_cache table: %s", e)
            return False

    def upsert_venues(
        self,
        places: List[Dict],
        category: str,
        source_address: str,
    ) -> None:
        """Upsert a batch of Google Places results into venue_cache.

        New place_ids get a full INSERT with first_seen = now.
        Existing place_ids get last_verified, rating, business_status, etc.
        updated; first_seen, source_address, and category are preserved from
        the original INSERT.

        Swallows all errors — never impacts evaluation.
        """
        if not places:
            return
        if not self._ensure_table():
            return

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            conn = _connect()
            try:
                conn.execute("PRAGMA busy_timeout = 30000")

                for place in places:
                    try:
                        place_id = place.get("place_id")
                        if not place_id:
                            continue

                        loc = place.get("geometry", {}).get("location", {})
                        lat = loc.get("lat")
                        lng = loc.get("lng")
                        if lat is None or lng is None:
                            continue

                        conn.execute(
                            f"""
                            INSERT INTO {self._TABLE}
                                (place_id, name, category, latitude, longitude,
                                 rating, rating_count, price_level,
                                 business_status, raw_response,
                                 first_seen, last_verified, source_address,
                                 geometry)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                    MakePoint(?, ?, 4326))
                            ON CONFLICT(place_id) DO UPDATE SET
                                name = excluded.name,
                                latitude = excluded.latitude,
                                longitude = excluded.longitude,
                                rating = excluded.rating,
                                rating_count = excluded.rating_count,
                                price_level = excluded.price_level,
                                business_status = excluded.business_status,
                                raw_response = excluded.raw_response,
                                last_verified = excluded.last_verified,
                                geometry = excluded.geometry
                            """,
                            (
                                place_id,
                                place.get("name", ""),
                                category,
                                lat,
                                lng,
                                place.get("rating"),
                                place.get("user_ratings_total"),
                                place.get("price_level"),
                                place.get("business_status", "OPERATIONAL"),
                                json.dumps(place),
                                now,
                                now,
                                source_address,
                                lng,
                                lat,
                            ),
                        )
                    except Exception as e:
                        logger.debug(
                            "Venue cache upsert skipped for %s: %s",
                            place.get("place_id", "?"),
                            e,
                        )
                        continue

                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning("Venue cache batch upsert failed: %s", e)
