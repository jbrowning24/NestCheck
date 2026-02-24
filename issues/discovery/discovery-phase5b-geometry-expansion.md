# Phase 5b Discovery: Geometry Expansion for SEMS, HPMS, HIFLD

## 1. spatial_data.py — Current State

### 1.1 Function Signatures

| Function | Signature | Docstring / Comment |
|----------|-----------|---------------------|
| `_spatial_db_path` | `_spatial_db_path() -> str` | Resolve spatial database path. Mirrors models.py DB_PATH logic. |
| `_connect` | `_connect() -> sqlite3.Connection` | Open a SpatiaLite-enabled connection. |
| `init_spatial_db` | `init_spatial_db()` | Initialize the SpatiaLite database with metadata table. Called by ingestion scripts, not by the web app. |
| `create_facility_table` | `create_facility_table(facility_type: str, extra_columns: str = "")` | Create a facility table with standard schema + optional extra columns. Called by ingestion scripts. |
| `_strip_html_tri_id` | (in ingest_tri.py) | Helper for TRI HTML stripping. |

### 1.2 FacilityRecord Dataclass

```python
@dataclass
class FacilityRecord:
    facility_type: str  # "ust", "tri", "sems", "hpms"
    name: str
    lat: float
    lng: float
    distance_meters: float
    distance_feet: float
    metadata: dict

    @property
    def distance_miles(self) -> float:
        return self.distance_meters / 1609.344
```

### 1.3 create_facility_table() — Full Implementation

```python
def create_facility_table(facility_type: str, extra_columns: str = ""):
    """
    Create a facility table with standard schema + optional extra columns.
    Called by ingestion scripts.

    Standard schema:
    - name TEXT
    - geometry POINT (SRID 4326)
    - metadata_json TEXT (JSON blob for type-specific fields)
    - Plus any extra_columns

    Drops existing table first (idempotent).
    """
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
            f"SELECT AddGeometryColumn('{table_name}', 'geometry', 4326, 'POINT', 'XY')"
        )
        conn.execute(f"SELECT CreateSpatialIndex('{table_name}', 'geometry')")
        conn.commit()
    finally:
        conn.close()
```

**Geometry type assumptions:** `AddGeometryColumn` is hardcoded to `'POINT'` and `'XY'`. No support for POLYGON or LINESTRING.

### 1.4 SpatialDataStore Class — Full Method List

| Method | Signature | Purpose |
|--------|-----------|---------|
| `__init__` | `__init__(self)` | Initialize; `_available` cached. |
| `is_available` | `is_available(self) -> bool` | Check if spatial DB exists and SpatiaLite loads. Result cached. |
| `find_facilities_within` | `find_facilities_within(self, lat, lng, radius_meters, facility_type) -> List[FacilityRecord]` | Find all facilities within radius of (lat, lng). Returns list sorted by distance ascending. |
| `nearest_facility` | `nearest_facility(self, lat, lng, facility_type, max_radius_meters=5000) -> Optional[FacilityRecord]` | Return single closest facility, or None. |
| `facility_count_within` | `facility_count_within(self, lat, lng, radius_meters, facility_type) -> int` | Count only — avoids hydrating full records. |

### 1.5 R-tree Spatial Index

- **Where created:** `create_facility_table()` calls `CreateSpatialIndex('{table_name}', 'geometry')` after adding the geometry column.
- **Where used:** Both `find_facilities_within` and `facility_count_within` use the same pattern:
  1. `radius_deg = radius_meters / 80000.0` (conservative overestimate for SRID 4326)
  2. Subquery: `SELECT ROWID FROM SpatialIndex WHERE f_table_name = ? AND f_geometry_column = 'geometry' AND search_frame = BuildCircleMbr(?, ?, ?, 4326)`
  3. Main query: `ST_Distance(geometry, MakePoint(?, ?, 4326), 1) <= ?` for exact filtering

**POINT assumptions:** `Y(geometry)` and `X(geometry)` are used to extract lat/lng from each row. This works only for POINT geometry. POLYGON and LINESTRING would need centroid or nearest-point extraction.

### 1.6 dataset_registry Schema

```sql
CREATE TABLE IF NOT EXISTS dataset_registry (
    facility_type TEXT PRIMARY KEY,
    source_url TEXT,
    ingested_at TEXT,
    record_count INTEGER,
    notes TEXT
)
```

### 1.7 TODO / Extensibility Hooks

- No TODO comments in the file.
- No explicit extensibility hooks for geometry type.
- `FacilityRecord` assumes `lat`/`lng` — for LINESTRING/POLYGON, `distance_meters` would be distance to nearest point on geometry, but `lat`/`lng` would need to be centroid or nearest point.

---

## 2. scripts/ingest_ust.py — UST Pattern

| Aspect | Implementation |
|--------|----------------|
| `create_facility_table` | `create_facility_table("ust")` — no extra columns |
| Geometry insertion | `INSERT ... VALUES (?, MakePoint(?, ?, 4326), ?)` — POINT from `geom.get("x")`, `geom.get("y")` |
| Pagination | `resultOffset` + `resultRecordCount` (PAGE_SIZE=2000). Stop when `exceededTransferLimit` is false and `len(features) < PAGE_SIZE`. |
| Edge cases | Skips records with null/invalid coords; validates bounds (-180..180, -90..90). |
| ArcGIS params | `returnGeometry=true`, `geometryType=esriGeometryPoint`, `outSR=4326` |

---

## 3. scripts/ingest_tri.py — Deviations from UST

| Aspect | Deviation |
|--------|------------|
| Source | ArcGIS primary; Envirofacts fallback at `data.epa.gov/efservice/tri.tri_facility` |
| Geometry | ArcGIS: `geom.get("x")`, `geom.get("y")`. Envirofacts: `LATITUDE83`/`LONGITUDE83` or `PREF_LATITUDE`/`PREF_LONGITUDE` from row dict (no geometry in response) |
| HTML stripping | `_strip_html_tri_id()` to remove `<a href=...>id</a>` from `TRI_FACILITY_ID` |
| Pagination | ArcGIS: same as UST. Envirofacts: 1-based row indexing `rows/{start}:{end}/JSON` |
| Stop condition | ArcGIS: `len(features) < PAGE_SIZE_ARCGIS`. Envirofacts: `len(rows) < PAGE_SIZE_ENVIROFACTS` or empty list |

---

## 4. property_evaluator.py — Spatial Data Usage

**Current state:** The evaluation pipeline does **not** use `SpatialDataStore` at all.

| Check | Current implementation | Future (per registry) |
|-------|-------------------------|------------------------|
| Gas station | `maps.places_nearby(lat, lng, "gas_station", radius_meters=500)` — Google Places API | Replace with UST spatial query |
| Highway | Overpass `get_nearby_roads()` | Upgrade with HPMS AADT |
| High-volume road | Overpass road classification | Upgrade with HPMS AADT |
| Rail corridor | Overpass | Supplement with FRA rail |

**Where new facility queries would be added:**

- Tier 1 checks: `evaluate_property()` around lines 4117–4140, where `check_gas_stations`, `check_highways`, `check_high_volume_roads`, `check_rail_corridor` run.
- New checks would be added as `result.tier1_checks.append(...)` for SEMS (Superfund), TRI (already ingested), HIFLD (transmission lines).
- Integration pattern: instantiate `SpatialDataStore()`, call `store.find_facilities_within()` or `store.nearest_facility()` with appropriate facility type and radius.

---

## 5. A. EPA SEMS (Superfund Sites)

### Two Data Sources

| Source | URL | Geometry | Purpose |
|--------|-----|----------|---------|
| **SEMS (FRS_INTERESTS layer 21)** | `https://gispub.epa.gov/arcgis/rest/services/OEI/FRS_INTERESTS/MapServer/21/query` | **POINT** | Site locations (lat/lng) |
| **Superfund Site Boundaries** | `https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/FAC_Superfund_Site_Boundaries_EPA_Public/FeatureServer/0/query` | **POLYGON** | EPA-defined remediation boundaries |

### Superfund Site Boundaries (Polygon) — Recommended for PRD

- **Working endpoint:** `https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/FAC_Superfund_Site_Boundaries_EPA_Public/FeatureServer/0/query`
- **Geometry type:** `esriGeometryPolygon`
- **Spatial reference:** WKID 4326 (WGS84)
- **Max record count:** 2000
- **Pagination:** `returnCountOnly=true`, `resultOffset`, `resultRecordCount` (same as UST/TRI)
- **Definition query:** `CLEARED_PUBLIC_RELEASE = 'Y'` (public releases only)

**Sample attributes:**

| Field | Type | Description |
|-------|------|-------------|
| OBJECTID | OID | |
| REGION_CODE | SmallInteger | EPA Region |
| EPA_PROGRAM | String | Superfund Remedial, Removal, etc. |
| EPA_ID | String (12) | Site ID |
| SITE_NAME | String (100) | Site name |
| SITE_FEATURE_CLASS | SmallInteger | Site Boundary, Operable Unit, etc. |
| NPL_STATUS_CODE | String (1) | F=Final NPL, P=Proposed, N=Not on NPL, etc. |
| FEDERAL_FACILITY_DETER_CODE | String (1) | Y/N/D |
| STREET_ADDR_TXT | String | Address |
| CITY_NAME | String | City |
| STATE_CODE | String (2) | State |
| ZIP_CODE | String | Zip |
| SITE_CONTACT_NAME | String | RPM |
| GIS_AREA | Double | Area |
| Shape__Area, Shape__Length | Double | |

**Record count:** Not probed (network blocked). Registry expects ~1,300 NPL + thousands non-NPL.

**PRD:** "Hard fail if within EPA-defined remediation boundary" — **polygons are available** via the Superfund Site Boundaries service. Use point-in-polygon (`ST_Contains` or `ST_Within`) for the property point, not centroid distance.

### SEMS (FRS_INTERESTS) — Points Only

- **Geometry type:** `esriGeometryPoint`
- **Max record count:** 5000
- **Fields:** REGISTRY_ID, PRIMARY_NAME, LATITUDE83, LONGITUDE83, CITY_NAME, STATE_CODE, POSTAL_CODE, PGM_SYS_ACRNM, etc.

**If polygons only:** Use Superfund Site Boundaries. If both are needed: polygons for "within boundary" and points for "nearest site" distance.

---

## 6. B. FHWA HPMS (Traffic Counts)

### Live ArcGIS FeatureServer — Available

- **Base URL pattern:** `https://geo.dot.gov/server/rest/services/Hosted/{State}_2018_PR/FeatureServer`
- **Example:** `https://geo.dot.gov/server/rest/services/Hosted/Massachusetts_2018_PR/FeatureServer`
- **Layer:** Layer 0 (e.g. `Massachusetts_PR_2018`)

**Geometry type:** `esriGeometryPolyline` (LINESTRING)

**Key attributes:**

| Field | Type | Description |
|-------|------|-------------|
| objectid | OID | |
| year_record | SmallInteger | Data year |
| state_code | SmallInteger | State FIPS |
| route_id | String | Route identifier |
| begin_point | Double | Beginning limit of segment |
| end_point | Double | End limit of segment |
| **aadt** | **Integer** | **Annual Average Daily Traffic** |
| aadt_combination | Integer | Combination truck AADT |
| aadt_single_unit | Integer | Single unit truck AADT |
| f_system | Integer | Functional classification |
| route_name | String (100) | Road name |
| route_number | Integer | Route number |
| through_lanes | Integer | etc. |

**AADT:** Yes — `aadt` field per segment.

**Spatial reference:** WKID 4326 (WGS84)

**Pagination:** `maxRecordCount=2000`

**Coverage:** One FeatureServer per state (52 total including DC and Puerto Rico). National ingest requires iterating over all state URLs.

**Shapefile alternative:** FHWA HPMS shapefiles are available at data.transportation.gov / NTAD. File size varies by state; registry estimates ~2GB raw, ~200MB filtered (AADT>50K only).

---

## 7. C. HIFLD Transmission Lines

### Live ArcGIS FeatureServer

- **Working endpoint:** `https://services2.arcgis.com/LYMgRMwHfrWWEg3s/arcgis/rest/services/HIFLD_US_Electric_Power_Transmission_Lines/FeatureServer/0?f=json`
- **Query URL:** `https://services2.arcgis.com/LYMgRMwHfrWWEg3s/arcgis/rest/services/HIFLD_US_Electric_Power_Transmission_Lines/FeatureServer/0/query`

**Geometry type:** `esriGeometryPolyline` (LINESTRING)

**Key attributes:**

| Field | Type | Description |
|-------|------|-------------|
| OBJECTID_1 | OID | |
| ID | String (80) | Line identifier |
| TYPE | String (80) | |
| STATUS | String (80) | |
| **VOLTAGE** | **Double** | **Voltage in kV** |
| **VOLT_CLASS** | String (80) | e.g. "100-161" |
| OWNER | String (80) | Operator |
| SUB_1, SUB_2 | String (80) | Substations |
| SOURCE, SOURCEDATE | String | |
| Shape__Length | Double | |

**Record count:** ~94,000 (per web search)

**Spatial reference:** WKID 102100 (Web Mercator) — **reproject to 4326 needed for SpatiaLite**

**Pagination:** `maxRecordCount=2000`, `supportsPagination=true`

**Coverage:** Continental US, Alaska, Hawaii.

---

## 8. Summary Table

| Dataset | Source | Geometry | Key Attributes | Record Count | Pagination |
|---------|--------|----------|----------------|--------------|------------|
| **EPA SEMS** | Superfund Site Boundaries (ArcGIS Online) | POLYGON | SITE_NAME, EPA_ID, NPL_STATUS_CODE, STATE_CODE | ~1,300+ | resultOffset/resultRecordCount, max 2000 |
| **EPA SEMS** | FRS_INTERESTS layer 21 (gispub.epa.gov) | POINT | PRIMARY_NAME, LATITUDE83, LONGITUDE83 | Thousands | resultOffset/resultRecordCount, max 5000 |
| **FHWA HPMS** | geo.dot.gov Hosted/{State}_2018_PR/FeatureServer | POLYLINE | aadt, route_id, route_name, f_system | Per state | resultOffset/resultRecordCount, max 2000 |
| **HIFLD** | services2.arcgis.com HIFLD_US_Electric_Power_Transmission_Lines | POLYLINE | VOLTAGE, VOLT_CLASS, OWNER | ~94K | resultOffset/resultRecordCount, max 2000 |

---

## 9. Implementation Implications

1. **spatial_data.py:** Extend `create_facility_table()` to accept geometry type (`POINT`, `POLYGON`, `LINESTRING`). `AddGeometryColumn` and `CreateSpatialIndex` support POLYGON and LINESTRING.

2. **SpatialDataStore queries:**
   - **POLYGON (SEMS):** Point-in-polygon query: `ST_Contains(geometry, MakePoint(?, ?, 4326))` or `ST_Within(MakePoint(...), geometry)`. No distance sort; return 0 or 1 (inside/outside).
   - **LINESTRING (HPMS, HIFLD):** Distance-to-line: `ST_Distance(geometry, MakePoint(?, ?, 4326), 1)`. R-tree `BuildCircleMbr` still works for pre-filtering. `Y(geometry)`/`X(geometry)` are invalid for lines — use `ST_ClosestPoint` or centroid for display.

3. **FacilityRecord:** For LINESTRING, `lat`/`lng` could be centroid or nearest point. For POLYGON, `lat`/`lng` could be centroid or nearest point on boundary.

4. **Ingestion:** SEMS polygons → WKT from ArcGIS paths; HPMS/HIFLD polylines → WKT from ArcGIS paths. HIFLD needs reprojection from 102100 to 4326 (or request `outSR=4326` in query).
