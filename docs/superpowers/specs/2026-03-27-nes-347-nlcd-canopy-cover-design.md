# NES-347: NLCD Tree Canopy Cover

**Linear:** [NES-347](https://linear.app/nestcheck/issue/NES-347)
**Date:** 2026-03-27
**Status:** Design

## Summary

Add tree canopy cover as a quantitative signal to the green space Nature Feel subscore. Uses MRLC's free public WMS endpoint to query NLCD 30m canopy data at evaluation time — no bulk ingest, no raster dependencies, no new scoring dimension.

## Problem

Green space scoring currently uses 4 subscores: walk time (0-3), size/loop (0-3), quality (0-2), and nature feel (0-2). Nature feel relies entirely on keyword heuristics — OSM tags ("forest", "wetland") and park name patterns ("woods", "preserve"). This misses the actual vegetation environment around the address: tree-lined streets, shade coverage, urban canopy. The PRD positions green space *quality* as a Tier One differentiator and lists NLCD tree canopy as a Phase 1 data source.

## Data Source

**MRLC WMS endpoint** (verified working, free, no auth):
```
https://www.mrlc.gov/geoserver/mrlc_display/nlcd_tcc_conus_2021_v2021-4/wms
```

- WMS 1.1.1 `GetFeatureInfo` returns `PALETTE_INDEX` (0-100 = canopy %)
- 30m resolution, CONUS coverage, EPSG:5070 native CRS (GeoServer reprojects to EPSG:4326 on request)
- CORS open (`access-control-allow-origin: *`), no API key
- Updates every 2-3 years (current vintage: 2021)

**Validation:** Central Park Ramble = 54%, North Woods = 63%, Catskills forest = 84%, Great Lawn (open grass) = 0%. Values are plausible.

## Architecture

### New module: `canopy.py`

Standalone module (follows `green_space.py` / `overflow.py` pattern). Dependencies: `requests` only (no Flask, no DB client). Cache interaction via `models.py` helpers.

```python
@dataclass
class CanopyCoverResult:
    canopy_pct: float       # Mean canopy % (0-100) across sample points
    sample_count: int       # Number of valid samples obtained
    buffer_m: int           # Buffer radius used (default 500)
    source: str             # "nlcd_2021"

def get_canopy_cover(lat: float, lng: float, buffer_m: int = 500) -> Optional[CanopyCoverResult]:
    """Query NLCD tree canopy cover within a buffer around coordinates.

    1. Check canopy_cache in nestcheck.db → return if fresh
    2. Generate ~25 sample points in a grid within buffer
    3. Query MRLC WMS GetFeatureInfo for each point (ThreadPoolExecutor)
    4. Compute mean canopy %, cache result, return

    Returns None on endpoint failure (never raises).
    """
```

**Sample grid:** ~25 points in a 5x5 grid within the buffer radius. Grid spacing calculated with latitude correction: `lat_step = buffer_m / 111320` for latitude degrees, `lng_step = buffer_m / (111320 * cos(radians(lat)))` for longitude degrees. At ~41N (Westchester), this gives ~200m spacing per step. Points outside the buffer circle are pruned.

**Concurrency:** Use `ThreadPoolExecutor(max_workers=5)` to parallelize the 25 WMS requests. Each request is a lightweight HTTP GET returning a single integer. Expected wall time: 3-5 seconds uncached.

**WMS request format (WMS 1.1.1 to avoid axis order confusion):**
```
?service=WMS&version=1.1.1&request=GetFeatureInfo
&layers=nlcd_tcc_conus_2021_v2021-4
&query_layers=nlcd_tcc_conus_2021_v2021-4
&info_format=application/json
&srs=EPSG:4326
&bbox={lng-0.001},{lat-0.001},{lng+0.001},{lat+0.001}
&width=3&height=3&x=1&y=1
```

The tiny bbox (0.001 deg ≈ 80-110m) centers a 3x3 pixel window on the target point. GetFeatureInfo returns the center pixel value. Each of the 25 grid points gets its own request.

### Cache: `canopy_cache` table in `nestcheck.db`

Follows the weather/census cache pattern in `models.py`:

```python
_CANOPY_CACHE_TTL_DAYS = 90

def get_canopy_cache(cache_key: str) -> Optional[str]: ...
def set_canopy_cache(cache_key: str, data_json: str) -> None: ...
```

**Cache key:** `canopy:{lat:.4f},{lng:.4f}` (4 decimal places = ~11m precision). Close enough for same-address re-evals, won't conflate neighboring addresses.

**Table schema** (added to `init_db()`):
```sql
CREATE TABLE IF NOT EXISTS canopy_cache (
    cache_key TEXT PRIMARY KEY,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
```

## Scoring Integration

### Clean separation: canopy path vs. keyword fallback

When canopy data is available, it replaces the keyword-based nature-feel score entirely (no double-counting). When unavailable, the existing `_score_nature_feel()` runs unchanged.

**In `green_space.py`:**
```python
# In score_green_space() and compute_park_score():
if canopy_pct is not None:
    nf_score = apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, canopy_pct)
    nf_reason = f"{canopy_pct:.0f}% tree canopy within 500m (NLCD)"
else:
    nf_score, nf_reason = _score_nature_feel(osm_data, name, types)
```

**Import addition in `green_space.py`:**
```python
from scoring_config import WALK_DRIVE_BOTH_THRESHOLD, CANOPY_NATURE_FEEL_KNOTS, apply_piecewise
```

### Piecewise scoring curve (in `scoring_config.py`)

```python
CANOPY_NATURE_FEEL_KNOTS = (
    PiecewiseKnot(5, 0.0),     # < 5% = barren/paved
    PiecewiseKnot(15, 0.5),    # sparse canopy
    PiecewiseKnot(25, 1.0),    # moderate urban canopy
    PiecewiseKnot(40, 1.5),    # well-treed neighborhood
    PiecewiseKnot(55, 2.0),    # heavily treed — subscore max
)
```

Smooth interpolation via `apply_piecewise()`. Output range 0.0-2.0, matching existing nature-feel max. No change to the 10-point park scoring model.

**Scoring model version bump:** `SCORING_MODEL.version` bumped from current to next minor (e.g., `1.6.0` → `1.7.0`).

### Confidence

- Canopy data available: `verified` (30m national coverage)
- Keyword fallback: retains existing confidence classification

### Affected functions

| Function | Module | Change |
|---|---|---|
| `evaluate_green_escape()` | `green_space.py` | New optional `canopy_pct` param, passed through to each `score_green_space()` call |
| `score_green_space()` | `green_space.py` | New optional `canopy_pct` param, canopy-first scoring path |
| `compute_park_score()` | `green_space.py` | New optional `canopy_pct` param (pure function, for ground truth) |
| `_score_nature_feel()` | `green_space.py` | Unchanged (fallback path) |

The canopy value is an area-level metric (address buffer), not per-park. It threads from `evaluate_property()` → `evaluate_green_escape(canopy_pct=...)` → each `score_green_space(canopy_pct=...)` call. The same canopy value applies to all parks.

## Evaluation Pipeline Integration

### `property_evaluator.py`

New stage in `evaluate_property()` using the existing `_staged()` wrapper pattern:

```python
# Add field to EvaluationResult dataclass:
canopy_cover: Optional[CanopyCoverResult] = None

# In evaluate_property(), new stage (runs sequentially with other stages):
try:
    canopy_result = _staged("canopy", get_canopy_cover, lat, lng)
except Exception:
    canopy_result = None
    logger.warning("Canopy cover lookup failed", exc_info=True)
```

**Note:** This adds 3-5 seconds to uncached evaluations (sequential, not parallel — matching the current architecture). The `ThreadPoolExecutor` inside `get_canopy_cover()` parallelizes the 25 WMS requests internally, but the stage itself blocks.

Result passed to `evaluate_green_escape()`:
```python
evaluate_green_escape(maps, lat, lng, canopy_pct=canopy_result.canopy_pct if canopy_result else None)
```

### `result_to_dict()` in `app.py`

Canopy data merged into the `green_escape` serialized dict after `_serialize_green_escape()` returns:

```python
ge = _serialize_green_escape(result.green_escape_evaluation)
if ge and result.canopy_cover:
    ge["canopy_cover"] = {
        "canopy_pct": result.canopy_cover.canopy_pct,
        "sample_count": result.canopy_cover.sample_count,
        "buffer_m": result.canopy_cover.buffer_m,
        "source": result.canopy_cover.source,
    }
```

Output in snapshot JSON:
```json
{
  "green_escape": {
    "canopy_cover": {
      "canopy_pct": 42.3,
      "sample_count": 25,
      "buffer_m": 500,
      "source": "nlcd_2021"
    },
    ...existing fields...
  }
}
```

Old snapshots without this field: template guards with `{% if %}`, no migration needed.

## Template Output

### Green space section in `_result_sections.html`

New line in green space detail area:
```
Tree canopy cover: 42% within 500m
```

Low-canopy annotation when < 15%:
```
Limited tree cover may mean less shade and higher summer temperatures
```

Uses existing `.callout--caution` component for the annotation. Data accessed via `result.green_escape.canopy_cover`.

## Coverage Config

New source in `coverage_config.py` using the existing `_SOURCE_METADATA` dict pattern:

```python
"NLCD_CANOPY": {
    "description": "NLCD Tree Canopy Cover",
    "table": None,  # Live WMS query, not bulk ingest
    "dimension": "green_space",
    "source_url": "https://www.mrlc.gov/geoserver/mrlc_display/nlcd_tcc_conus_2021_v2021-4/wms",
    "state_filter": None,  # CONUS-wide via live API
},
```

Added to `SOURCE_DISPLAY_LIST` and per-state manifests as `active` for all 8 states. Source added in the same commit as `canopy.py` (per CLAUDE.md: don't declare sources without their implementation).

## Testing

### Ground truth (Tier 2 pattern)

`scripts/generate_ground_truth_canopy.py`:
- Tests `apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, ...)` with synthetic canopy values
- Types: knot boundary, interpolation, monotonicity, clamping, floor
- No spatial.db or API calls needed

`scripts/validate_ground_truth_canopy.py`:
- Validates against `data/ground_truth/canopy.json`
- Added to `_DIMENSION_LABELS` in `validate_all_ground_truth.py`

### Unit tests

`tests/test_canopy.py`:
- `get_canopy_cover()` with mocked WMS responses
- Cache hit/miss paths
- Grid point generation within buffer (verify lat correction)
- Graceful failure (endpoint down → returns None)
- `apply_piecewise` with `CANOPY_NATURE_FEEL_KNOTS` edge cases

### CI

Add `tests/test_canopy.py` to `scoring-tests` job in `.github/workflows/ci.yml` and `Makefile` `test-scoring` target.

## Files Changed

| File | Change |
|---|---|
| `canopy.py` | **New** — standalone canopy query module with `CanopyCoverResult` dataclass |
| `scoring_config.py` | Add `CANOPY_NATURE_FEEL_KNOTS` (PiecewiseKnot tuple), bump `SCORING_MODEL.version` |
| `green_space.py` | Add `canopy_pct` param to `evaluate_green_escape()`, `score_green_space()`, `compute_park_score()`; canopy-first scoring path; update imports from `scoring_config` |
| `property_evaluator.py` | Add `canopy_cover: Optional[CanopyCoverResult]` field to `EvaluationResult`; add `_staged("canopy")` call; pass `canopy_pct` to `evaluate_green_escape()` |
| `models.py` | Add `canopy_cache` table to `init_db()` + `get_canopy_cache()` / `set_canopy_cache()` |
| `app.py` | Merge canopy data into `green_escape` dict in `result_to_dict()` after `_serialize_green_escape()` |
| `coverage_config.py` | Add `NLCD_CANOPY` source to `_SOURCE_METADATA`, `SOURCE_DISPLAY_LIST`, per-state manifests |
| `templates/_result_sections.html` | Display canopy % + low-canopy annotation |
| `tests/conftest.py` | Add `"canopy_cache"` to `_fresh_db` fixture table cleanup list |
| `tests/test_schema_migration.py` | Add `canopy_cache` CREATE TABLE to `_OLDEST_SCHEMA` |
| `scripts/generate_ground_truth_canopy.py` | **New** — ground truth generator |
| `scripts/validate_ground_truth_canopy.py` | **New** — ground truth validator |
| `scripts/validate_all_ground_truth.py` | Add `canopy` to `_DIMENSION_LABELS` |
| `tests/test_canopy.py` | **New** — unit tests |
| `.github/workflows/ci.yml` | Add test file to scoring-tests |
| `Makefile` | Add test file to test-scoring |
| `scripts/ingest_nlcd.py` | **Delete** — dead code, never wired in |

## Out of Scope

- Sentinel-2 NDVI (Phase 3)
- Multiple buffer radii (just 500m)
- Park-specific canopy analysis (address buffer only)
- Rasterio/GDAL dependencies
- Bulk ingest into spatial.db
- New scoring dimension (augments existing nature-feel)
- Seasonal composites
- Parallel stage execution (canopy runs sequentially like all other stages)
