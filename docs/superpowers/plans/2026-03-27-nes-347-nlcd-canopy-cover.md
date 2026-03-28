# NES-347: NLCD Tree Canopy Cover — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tree canopy cover from MRLC's NLCD WMS endpoint as a quantitative signal replacing the keyword-based nature-feel subscore in green space scoring.

**Architecture:** Standalone `canopy.py` module queries MRLC WMS with 25-point grid sampling within a 500m buffer. Results cached in `nestcheck.db` (90-day TTL). Canopy % fed to `apply_piecewise()` for smooth 0-2 scoring, replacing the keyword-based `_score_nature_feel()` when available.

**Tech Stack:** Python, requests, concurrent.futures (ThreadPoolExecutor), WMS 1.1.1

**Spec:** `docs/superpowers/specs/2026-03-27-nes-347-nlcd-canopy-cover-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `canopy.py` | **New.** Standalone module: WMS query, grid sampling, caching via models.py helpers |
| `scoring_config.py` | Add `CANOPY_NATURE_FEEL_KNOTS`, bump model version |
| `green_space.py` | Accept `canopy_pct` param, canopy-first scoring path in nature-feel |
| `property_evaluator.py` | New `_staged("canopy")` stage, `canopy_cover` field on `EvaluationResult` |
| `models.py` | `canopy_cache` table + `get/set_canopy_cache()` helpers |
| `app.py` | Merge canopy data into `green_escape` dict in `result_to_dict()` |
| `coverage_config.py` | Add `NLCD_CANOPY` source metadata |
| `templates/_result_sections.html` | Display canopy % and low-canopy annotation |
| `tests/test_canopy.py` | **New.** Unit tests for canopy module + scoring integration |
| `tests/conftest.py` | Add `canopy_cache` to `_fresh_db` cleanup |
| `tests/test_schema_migration.py` | Add `canopy_cache` to `_OLDEST_SCHEMA` |
| `.github/workflows/ci.yml` | Add `tests/test_canopy.py` to scoring-tests |
| `Makefile` | Add `tests/test_canopy.py` to test-scoring |
| `scripts/ingest_nlcd.py` | **Delete.** Dead code (uses defunct EJScreen proxy) |

---

### Task 1: Cache Infrastructure (models.py)

**Files:**
- Modify: `models.py` — add `canopy_cache` table to `init_db()`, add `get/set_canopy_cache()`
- Modify: `tests/conftest.py` — add `"canopy_cache"` to `_fresh_db` cleanup
- Modify: `tests/test_schema_migration.py` — add `canopy_cache` to `_OLDEST_SCHEMA`

- [ ] **Step 1: Add `canopy_cache` table to `init_db()` in `models.py`**

Find the `weather_cache` CREATE TABLE block in `init_db()` and add `canopy_cache` immediately after:

```python
    CREATE TABLE IF NOT EXISTS canopy_cache (
        cache_key     TEXT PRIMARY KEY,
        data_json     TEXT NOT NULL,
        created_at    TEXT NOT NULL DEFAULT (datetime('now'))
    );
```

- [ ] **Step 2: Add `get_canopy_cache()` and `set_canopy_cache()` to `models.py`**

Add after the census cache section (around line 1700). Follow the exact weather/census cache pattern:

```python
# ---------------------------------------------------------------------------
# Canopy cache (90-day TTL)
# ---------------------------------------------------------------------------

_CANOPY_CACHE_TTL_DAYS = 90


def get_canopy_cache(cache_key: str) -> Optional[str]:
    """Look up cached canopy data by rounded-coordinate key.

    Returns the raw JSON string if found and younger than TTL, else None.
    Cache errors are swallowed so they never break an evaluation.
    """
    try:
        conn = _get_db()
        try:
            row = conn.execute(
                """SELECT data_json, created_at FROM canopy_cache
                   WHERE cache_key = ?""",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            if not _check_cache_ttl(row["created_at"], _CANOPY_CACHE_TTL_DAYS):
                return None
            return row["data_json"]
        finally:
            conn.close()
    except Exception:
        logger.warning("Canopy cache lookup failed", exc_info=True)
        return None


def set_canopy_cache(cache_key: str, data_json: str) -> None:
    """Store canopy data in the persistent cache.

    Cache errors are swallowed so they never break an evaluation.
    """
    try:
        conn = _get_db()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO canopy_cache
                   (cache_key, data_json, created_at)
                   VALUES (?, ?, datetime('now'))""",
                (cache_key, data_json),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.warning("Canopy cache write failed", exc_info=True)
```

- [ ] **Step 3: Add `"canopy_cache"` to `_fresh_db` cleanup in `tests/conftest.py`**

In the `for table in (...)` tuple (line ~41), add `"canopy_cache"`:

```python
    for table in ("events", "snapshots", "payments", "free_tier_usage", "users", "evaluation_jobs", "feedback", "subscriptions", "canopy_cache"):
```

- [ ] **Step 4: Add `canopy_cache` CREATE TABLE to `_OLDEST_SCHEMA` in `tests/test_schema_migration.py`**

Add after the `weather_cache` CREATE TABLE in the `_OLDEST_SCHEMA` string:

```sql
    CREATE TABLE IF NOT EXISTS canopy_cache (
        cache_key     TEXT PRIMARY KEY,
        data_json     TEXT NOT NULL,
        created_at    TEXT
    );
```

- [ ] **Step 5: Run schema migration test**

Run: `python -m pytest tests/test_schema_migration.py -v --tb=short`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add models.py tests/conftest.py tests/test_schema_migration.py
git commit -m "feat(NES-347): add canopy_cache table and get/set helpers"
```

---

### Task 2: Scoring Config (scoring_config.py)

**Files:**
- Modify: `scoring_config.py` — add `CANOPY_NATURE_FEEL_KNOTS`, bump version

- [ ] **Step 1: Add `CANOPY_NATURE_FEEL_KNOTS` to `scoring_config.py`**

Add after the existing knot definitions (e.g., after `_FITNESS_DRIVE_KNOTS`):

```python
# ---------------------------------------------------------------------------
# Canopy cover → nature-feel subscore (0–2)
# Replaces keyword-based _score_nature_feel when NLCD data is available.
# ---------------------------------------------------------------------------

CANOPY_NATURE_FEEL_KNOTS = (
    PiecewiseKnot(5, 0.0),     # < 5% = barren/paved
    PiecewiseKnot(15, 0.5),    # sparse canopy
    PiecewiseKnot(25, 1.0),    # moderate urban canopy
    PiecewiseKnot(40, 1.5),    # well-treed neighborhood
    PiecewiseKnot(55, 2.0),    # heavily treed — subscore max
)
```

- [ ] **Step 2: Bump `SCORING_MODEL.version` to next minor**

Read the current version in `SCORING_MODEL = ScoringModel(version="...")` and bump to next minor (e.g., `1.6.0` → `1.7.0`). Don't assume the current value — read it first.

- [ ] **Step 3: Run scoring config tests**

Run: `python -m pytest tests/test_scoring_config.py -v --tb=short`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add scoring_config.py
git commit -m "feat(NES-347): add CANOPY_NATURE_FEEL_KNOTS, bump model to 1.7.0"
```

---

### Task 3: Canopy Module (canopy.py)

**Files:**
- Create: `canopy.py`
- Create: `tests/test_canopy.py`

- [ ] **Step 1: Write failing tests in `tests/test_canopy.py`**

```python
"""Tests for canopy.py — NLCD tree canopy cover module."""

import json
import math
import pytest
from unittest.mock import patch, MagicMock

from scoring_config import CANOPY_NATURE_FEEL_KNOTS, apply_piecewise


# ---------------------------------------------------------------------------
# Piecewise scoring tests (no mocking needed)
# ---------------------------------------------------------------------------

class TestCanopyPiecewiseScoring:
    """Test apply_piecewise with CANOPY_NATURE_FEEL_KNOTS."""

    def test_below_first_knot(self):
        """< 5% canopy should return 0.0."""
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 0) == 0.0
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 3) == 0.0

    def test_at_knot_boundaries(self):
        """Exact knot values should return exact scores."""
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 5) == 0.0
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 15) == 0.5
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 25) == 1.0
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 40) == 1.5
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 55) == 2.0

    def test_interpolation(self):
        """Midpoints between knots should interpolate linearly."""
        # Midpoint of (5, 0.0) and (15, 0.5) is (10, 0.25)
        assert abs(apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 10) - 0.25) < 0.01

    def test_above_last_knot(self):
        """Above 55% should clamp at 2.0."""
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 80) == 2.0
        assert apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, 100) == 2.0

    def test_monotonicity(self):
        """Score should increase monotonically with canopy %."""
        prev = -1.0
        for pct in range(0, 101, 5):
            score = apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, pct)
            assert score >= prev, f"Non-monotonic at {pct}%: {score} < {prev}"
            prev = score


# ---------------------------------------------------------------------------
# Grid generation tests
# ---------------------------------------------------------------------------

class TestGridGeneration:
    """Test _generate_sample_grid geometry."""

    def test_grid_count(self):
        from canopy import _generate_sample_grid
        points = _generate_sample_grid(40.78, -73.97, 500)
        # Should produce ~21-25 points (5x5 grid pruned to circle)
        assert 15 <= len(points) <= 30

    def test_points_within_buffer(self):
        from canopy import _generate_sample_grid
        lat, lng = 40.78, -73.97
        buffer_m = 500
        points = _generate_sample_grid(lat, lng, buffer_m)
        for plat, plng in points:
            # Haversine distance check (approximate)
            dlat = math.radians(plat - lat)
            dlng = math.radians(plng - lng)
            a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(plat)) * math.sin(dlng / 2) ** 2
            dist_m = 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            assert dist_m <= buffer_m * 1.1, f"Point ({plat}, {plng}) is {dist_m:.0f}m from center"

    def test_latitude_correction(self):
        """Grid should be wider in longitude at higher latitudes."""
        from canopy import _generate_sample_grid
        equator_pts = _generate_sample_grid(0.0, -73.97, 500)
        high_lat_pts = _generate_sample_grid(60.0, -73.97, 500)
        # At 60N, lng range should be ~2x the equator lng range
        eq_lngs = [p[1] for p in equator_pts]
        hi_lngs = [p[1] for p in high_lat_pts]
        eq_range = max(eq_lngs) - min(eq_lngs)
        hi_range = max(hi_lngs) - min(hi_lngs)
        assert hi_range > eq_range * 1.5


# ---------------------------------------------------------------------------
# WMS query + caching tests (mocked)
# ---------------------------------------------------------------------------

class TestGetCanopyCover:
    """Test get_canopy_cover with mocked WMS responses."""

    def _mock_wms_response(self, canopy_pct):
        """Create a mock response matching MRLC WMS GetFeatureInfo JSON."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"PALETTE_INDEX": canopy_pct},
            }],
        }
        return resp

    @patch("canopy.requests.get")
    @patch("canopy.get_canopy_cache", return_value=None)
    @patch("canopy.set_canopy_cache")
    def test_basic_query(self, mock_set, mock_get_cache, mock_requests_get):
        from canopy import get_canopy_cover
        mock_requests_get.return_value = self._mock_wms_response(42)

        result = get_canopy_cover(40.78, -73.97)

        assert result is not None
        assert result.canopy_pct == 42.0
        assert result.sample_count > 0
        assert result.buffer_m == 500
        assert result.source == "nlcd_2021"
        assert mock_set.called  # Should cache the result

    @patch("canopy.get_canopy_cache")
    def test_cache_hit(self, mock_get_cache):
        from canopy import get_canopy_cover
        mock_get_cache.return_value = json.dumps({
            "canopy_pct": 35.5,
            "sample_count": 25,
            "buffer_m": 500,
            "source": "nlcd_2021",
        })

        result = get_canopy_cover(40.78, -73.97)

        assert result is not None
        assert result.canopy_pct == 35.5

    @patch("canopy.requests.get", side_effect=Exception("Connection refused"))
    @patch("canopy.get_canopy_cache", return_value=None)
    def test_endpoint_failure_returns_none(self, mock_get_cache, mock_requests_get):
        from canopy import get_canopy_cover
        result = get_canopy_cover(40.78, -73.97)
        assert result is None

    @patch("canopy.requests.get")
    @patch("canopy.get_canopy_cache", return_value=None)
    @patch("canopy.set_canopy_cache")
    def test_mixed_valid_invalid_samples(self, mock_set, mock_get_cache, mock_requests_get):
        """Some sample points may return no features — should average valid ones."""
        from canopy import get_canopy_cover

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:
                # Return empty features for every 3rd call
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {"type": "FeatureCollection", "features": []}
                return resp
            return self._mock_wms_response(30)

        mock_requests_get.side_effect = side_effect

        result = get_canopy_cover(40.78, -73.97)
        assert result is not None
        assert result.canopy_pct == 30.0  # Only valid samples averaged
        assert result.sample_count < 25  # Some were invalid
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_canopy.py -v --tb=short`
Expected: FAIL (canopy module doesn't exist yet, piecewise tests should pass since they only use scoring_config)

- [ ] **Step 3: Create `canopy.py`**

```python
"""
NLCD Tree Canopy Cover — address-level vegetation analysis.

Queries MRLC's WMS endpoint for NLCD 30m tree canopy data within a
configurable buffer around an address. Returns mean canopy percentage.

Data source: USGS NLCD Tree Canopy Cover (2021), served via MRLC GeoServer.
Resolution: 30m pixels, CONUS coverage, no API key required.

Standalone module — no Flask or evaluation pipeline dependencies.
"""

import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Cache helpers — imported from models.py at module level.
# If models.py is unavailable (e.g., standalone testing), cache is a no-op.
try:
    from models import get_canopy_cache, set_canopy_cache
except ImportError:
    def get_canopy_cache(cache_key):
        return None

    def set_canopy_cache(cache_key, data_json):
        pass


# MRLC WMS endpoint for NLCD Tree Canopy Cover
_WMS_BASE_URL = (
    "https://www.mrlc.gov/geoserver/mrlc_display"
    "/nlcd_tcc_conus_2021_v2021-4/wms"
)

_WMS_TIMEOUT = 15  # seconds per request
_THREAD_WORKERS = 5
_REQUEST_RETRIES = 1


@dataclass
class CanopyCoverResult:
    """Result of a canopy cover analysis within a buffer around an address."""
    canopy_pct: float       # Mean canopy % (0-100) across valid sample points
    sample_count: int       # Number of valid samples obtained
    buffer_m: int           # Buffer radius used
    source: str             # Data source identifier


def _generate_sample_grid(
    lat: float, lng: float, buffer_m: int,
) -> List[Tuple[float, float]]:
    """Generate a grid of sample points within a circular buffer.

    Returns ~21-25 points in a 5x5 grid, pruned to the buffer circle.
    Uses latitude-corrected longitude spacing.
    """
    # Convert buffer to degrees
    lat_step = buffer_m / 111320.0  # meters per degree latitude
    lng_step = buffer_m / (111320.0 * math.cos(math.radians(lat)))

    points = []
    for i in range(-2, 3):
        for j in range(-2, 3):
            plat = lat + i * lat_step / 2.0
            plng = lng + j * lng_step / 2.0
            # Check if point is within the buffer circle
            dlat_m = (plat - lat) * 111320.0
            dlng_m = (plng - lng) * 111320.0 * math.cos(math.radians(lat))
            dist_m = math.sqrt(dlat_m ** 2 + dlng_m ** 2)
            if dist_m <= buffer_m:
                points.append((plat, plng))
    return points


def _query_wms_canopy(lat: float, lng: float) -> Optional[int]:
    """Query MRLC WMS for canopy % at a single point.

    Returns canopy percentage (0-100) or None on failure.
    """
    # Small bbox centered on the point (WMS 1.1.1: x=lng, y=lat)
    delta = 0.001
    params = {
        "service": "WMS",
        "version": "1.1.1",
        "request": "GetFeatureInfo",
        "layers": "nlcd_tcc_conus_2021_v2021-4",
        "query_layers": "nlcd_tcc_conus_2021_v2021-4",
        "info_format": "application/json",
        "srs": "EPSG:4326",
        "bbox": f"{lng - delta},{lat - delta},{lng + delta},{lat + delta}",
        "width": "3",
        "height": "3",
        "x": "1",
        "y": "1",
    }

    for attempt in range(_REQUEST_RETRIES + 1):
        try:
            resp = requests.get(_WMS_BASE_URL, params=params, timeout=_WMS_TIMEOUT)
            if resp.status_code != 200:
                if attempt < _REQUEST_RETRIES:
                    continue
                return None
            data = resp.json()
            features = data.get("features", [])
            if not features:
                return None
            props = features[0].get("properties", {})
            value = props.get("PALETTE_INDEX")
            if value is not None and 0 <= value <= 100:
                return int(value)
            return None
        except Exception:
            if attempt < _REQUEST_RETRIES:
                continue
            return None
    return None


def get_canopy_cover(
    lat: float, lng: float, buffer_m: int = 500,
) -> Optional[CanopyCoverResult]:
    """Query NLCD tree canopy cover within a buffer around coordinates.

    1. Check canopy_cache → return if fresh
    2. Generate ~25 sample points in a grid within buffer
    3. Query MRLC WMS GetFeatureInfo for each point (parallel)
    4. Compute mean canopy %, cache result, return

    Returns None on endpoint failure or if no valid samples obtained.
    Never raises — all errors are logged and swallowed.
    """
    cache_key = f"canopy:{lat:.4f},{lng:.4f}"

    # Check cache
    try:
        cached = get_canopy_cache(cache_key)
        if cached:
            data = json.loads(cached)
            return CanopyCoverResult(
                canopy_pct=data["canopy_pct"],
                sample_count=data["sample_count"],
                buffer_m=data["buffer_m"],
                source=data["source"],
            )
    except Exception:
        logger.warning("Canopy cache parse failed", exc_info=True)

    # Generate sample grid
    points = _generate_sample_grid(lat, lng, buffer_m)
    if not points:
        return None

    # Query WMS in parallel
    valid_values = []
    try:
        with ThreadPoolExecutor(max_workers=_THREAD_WORKERS) as executor:
            futures = {
                executor.submit(_query_wms_canopy, plat, plng): (plat, plng)
                for plat, plng in points
            }
            for future in as_completed(futures):
                try:
                    value = future.result()
                    if value is not None:
                        valid_values.append(value)
                except Exception:
                    pass
    except Exception:
        logger.warning("Canopy WMS query failed", exc_info=True)
        return None

    if not valid_values:
        logger.info("No valid canopy samples obtained for %.4f, %.4f", lat, lng)
        return None

    mean_pct = round(sum(valid_values) / len(valid_values), 1)

    result = CanopyCoverResult(
        canopy_pct=mean_pct,
        sample_count=len(valid_values),
        buffer_m=buffer_m,
        source="nlcd_2021",
    )

    # Cache the result
    try:
        set_canopy_cache(cache_key, json.dumps({
            "canopy_pct": result.canopy_pct,
            "sample_count": result.sample_count,
            "buffer_m": result.buffer_m,
            "source": result.source,
        }))
    except Exception:
        logger.warning("Canopy cache write failed", exc_info=True)

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_canopy.py -v --tb=short`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add canopy.py tests/test_canopy.py
git commit -m "feat(NES-347): add canopy.py module with WMS query and tests"
```

---

### Task 4: Green Space Scoring Integration (green_space.py)

**Files:**
- Modify: `green_space.py` — add `canopy_pct` param to `evaluate_green_escape()`, `score_green_space()`, `compute_park_score()`

- [ ] **Step 1: Update imports in `green_space.py`**

Change the existing import line:
```python
from scoring_config import WALK_DRIVE_BOTH_THRESHOLD
```
To:
```python
from scoring_config import WALK_DRIVE_BOTH_THRESHOLD, CANOPY_NATURE_FEEL_KNOTS, apply_piecewise
```

- [ ] **Step 2: Add `canopy_pct` parameter to `compute_park_score()`**

Add `canopy_pct: Optional[float] = None` to the function signature (after `osm_nature_tags`). Replace the nature-feel scoring line:

```python
    # Nature feel: use canopy data if available, else keyword heuristics
    if canopy_pct is not None:
        nf_score = apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, canopy_pct)
    else:
        nf_score, _ = _score_nature_feel(osm_data, name, types)
```

- [ ] **Step 3: Add `canopy_pct` parameter to `score_green_space()`**

Add `canopy_pct: Optional[float] = None` to the signature (after `osm_data`). Replace the nature-feel scoring:

```python
    # Nature feel: use canopy data if available, else keyword heuristics
    if canopy_pct is not None:
        nf_score = apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, canopy_pct)
        nf_reason = f"{canopy_pct:.0f}% tree canopy within 500m (NLCD)"
    else:
        nf_score, nf_reason = _score_nature_feel(osm_data, name, types)
```

- [ ] **Step 4: Add `canopy_pct` parameter to `evaluate_green_escape()`**

Add `canopy_pct: Optional[float] = None` to the signature (after `enable_osm`). Thread it through to every `score_green_space()` call inside the function. Find the call to `score_green_space()` and add `canopy_pct=canopy_pct`:

```python
    result = score_green_space(place, lat, lng, osm_data=osm_data, canopy_pct=canopy_pct)
```

Do this for ALL calls to `score_green_space()` within `evaluate_green_escape()`. Grep for `score_green_space(` in the function body.

- [ ] **Step 5: Run existing green space tests**

Run: `python -m pytest tests/test_green_space.py -v --tb=short 2>/dev/null; python -m pytest test_green_space.py -v --tb=short`
Expected: PASS (new params are optional, default None → existing behavior unchanged)

- [ ] **Step 6: Commit**

```bash
git add green_space.py
git commit -m "feat(NES-347): add canopy_pct param to green space scoring functions"
```

---

### Task 5: Evaluation Pipeline Integration (property_evaluator.py)

**Files:**
- Modify: `property_evaluator.py` — add `canopy_cover` field, new stage, pass to green escape

- [ ] **Step 1: Add `canopy_cover` field to `EvaluationResult` dataclass**

After the `bike_metadata` field (around line 411):

```python
    canopy_cover: Optional[dict] = None  # CanopyCoverResult as dict
```

- [ ] **Step 2: Add canopy stage in `evaluate_property()`**

Find the `green_escape` stage block (around line 6013-6017). Add the canopy stage BEFORE it:

```python
    canopy_pct = None
    try:
        from canopy import get_canopy_cover
        _canopy_result = _staged("canopy", get_canopy_cover, lat, lng)
        if _canopy_result:
            canopy_pct = _canopy_result.canopy_pct
            result.canopy_cover = {
                "canopy_pct": _canopy_result.canopy_pct,
                "sample_count": _canopy_result.sample_count,
                "buffer_m": _canopy_result.buffer_m,
                "source": _canopy_result.source,
            }
    except Exception:
        pass
```

- [ ] **Step 3: Pass `canopy_pct` to `evaluate_green_escape()` call**

Change the existing call (around line 6014):
```python
        result.green_escape_evaluation = _staged(
            "green_escape", evaluate_green_escape, maps, lat, lng)
```
To:
```python
        result.green_escape_evaluation = _staged(
            "green_escape", evaluate_green_escape, maps, lat, lng,
            canopy_pct=canopy_pct)
```

- [ ] **Step 4: Add `canopy` stage to frontend `STAGE_DISPLAY` in `templates/index.html`**

Find the `STAGE_DISPLAY` object (around line 499 in `index.html`). Add the canopy entry between `green_spaces` and `green_escape`:

```javascript
      canopy:               { text: 'Checking tree canopy cover...',          pct: 57 },
```

- [ ] **Step 5: Run a quick smoke check**

Run: `python -c "from property_evaluator import EvaluationResult; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add property_evaluator.py templates/index.html
git commit -m "feat(NES-347): add canopy stage to evaluation pipeline"
```

---

### Task 6: Serialization (app.py)

**Files:**
- Modify: `app.py` — merge canopy data into `green_escape` dict in `result_to_dict()`

- [ ] **Step 1: Add canopy data to `result_to_dict()`**

The result dict is built in a variable called `output` (line ~2340 in `app.py`). The `green_escape` key is set on line ~2382:

```python
        "green_escape": _serialize_green_escape(result.green_escape_evaluation),
```

Extract the serialization to a local variable BEFORE the `output = {` dict, then merge canopy data:

```python
    _ge = _serialize_green_escape(result.green_escape_evaluation)
    if _ge and result.canopy_cover:
        _ge["canopy_cover"] = result.canopy_cover
```

Then in the `output = {` dict, replace:
```python
        "green_escape": _serialize_green_escape(result.green_escape_evaluation),
```
With:
```python
        "green_escape": _ge,
```

**Note:** `result.canopy_cover` is already a dict (stored as dict on `EvaluationResult`, not a dataclass). This is an intentional deviation from the spec — it avoids coupling `property_evaluator.py` to the `canopy` module import.

- [ ] **Step 2: Verify serialization works**

Run: `python -c "from app import app; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(NES-347): serialize canopy data in green_escape dict"
```

---

### Task 7: Template Display (_result_sections.html)

**Files:**
- Modify: `templates/_result_sections.html` — add canopy display

- [ ] **Step 1: Add canopy cover display in the green space section**

Find the green escape section (around line 787, after the messages loop). Add canopy display before the park highlight:

```html
          {%- if result.green_escape and result.green_escape.canopy_cover -%}
            {% set _canopy = result.green_escape.canopy_cover %}
            <div class="data-row">
              <span class="data-row__label">Tree canopy cover</span>
              <span class="data-row__value">{{ "%.0f"|format(_canopy.canopy_pct) }}% within {{ _canopy.buffer_m }}m</span>
            </div>
            {%- if _canopy.canopy_pct < 15 -%}
            <div class="callout callout--caution">
              Limited tree cover may mean less shade and higher summer temperatures
            </div>
            {%- endif -%}
          {%- endif -%}
```

- [ ] **Step 2: Commit**

```bash
git add templates/_result_sections.html
git commit -m "feat(NES-347): display canopy cover in green space section"
```

---

### Task 8: Coverage Config (coverage_config.py)

**Files:**
- Modify: `coverage_config.py` — add NLCD_CANOPY source

- [ ] **Step 1: Read `coverage_config.py` to find `_SOURCE_METADATA` dict and `SOURCE_DISPLAY_LIST`**

Identify where `green_space` dimension sources are defined and add the new source following the existing pattern.

- [ ] **Step 2: Add `NLCD_CANOPY` to `_SOURCE_METADATA`**

Add to the `_SOURCE_METADATA` dict following the existing pattern (read the file to get exact field names):

```python
    "NLCD_CANOPY": {
        "description": "NLCD Tree Canopy Cover",
        "table": None,
        "dimension": "green_space",
        "source_url": "https://www.mrlc.gov/geoserver/mrlc_display/nlcd_tcc_conus_2021_v2021-4/wms",
        "state_filter": None,
    },
```

- [ ] **Step 3: Add to `SOURCE_DISPLAY_LIST`**

Add an entry for NLCD_CANOPY in the display list, grouped with other green_space sources.

- [ ] **Step 4: Add to per-state manifests as `active`**

For all 8 states in `COVERAGE_MANIFEST`, add `NLCD_CANOPY: "active"` under the appropriate dimension section.

- [ ] **Step 5: Commit**

```bash
git add coverage_config.py
git commit -m "feat(NES-347): add NLCD_CANOPY to coverage config"
```

---

### Task 9: CI Configuration

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `Makefile`

- [ ] **Step 1: Add `tests/test_canopy.py` to CI scoring-tests**

In `.github/workflows/ci.yml`, find the pytest command (line ~31):
```
python -m pytest tests/test_scoring_regression.py tests/test_scoring_config.py tests/test_overflow.py tests/test_schema_migration.py tests/test_scoring_key.py -v --tb=short
```
Add `tests/test_canopy.py` to the list.

- [ ] **Step 2: Add to Makefile `test-scoring` target**

In `Makefile`, find the `test-scoring` target (line ~27) and add `tests/test_canopy.py` to the pytest command.

- [ ] **Step 3: Run full scoring test suite**

Run: `make test-scoring`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml Makefile
git commit -m "ci(NES-347): add canopy tests to scoring gate"
```

---

### Task 10: Ground Truth + Cleanup

**Files:**
- Create: `scripts/generate_ground_truth_canopy.py`
- Create: `scripts/validate_ground_truth_canopy.py`
- Modify: `scripts/validate_all_ground_truth.py` — add canopy label
- Delete: `scripts/ingest_nlcd.py`

- [ ] **Step 1: Create `scripts/generate_ground_truth_canopy.py`**

Follow the Tier 2 single-curve pattern from `generate_ground_truth_coffee.py`. Test `apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, ...)` with synthetic canopy values:

```python
#!/usr/bin/env python3
"""Generate ground truth test cases for canopy nature-feel scoring."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_config import CANOPY_NATURE_FEEL_KNOTS, apply_piecewise

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "ground_truth", "canopy.json",
)


def generate():
    cases = []

    # Knot boundary tests
    for knot in CANOPY_NATURE_FEEL_KNOTS:
        cases.append({
            "type": "knot_boundary",
            "canopy_pct": knot.x,
            "expected_score": knot.y,
        })

    # Interpolation midpoints
    for i in range(len(CANOPY_NATURE_FEEL_KNOTS) - 1):
        k1 = CANOPY_NATURE_FEEL_KNOTS[i]
        k2 = CANOPY_NATURE_FEEL_KNOTS[i + 1]
        mid_x = (k1.x + k2.x) / 2
        mid_y = (k1.y + k2.y) / 2
        cases.append({
            "type": "interpolation",
            "canopy_pct": mid_x,
            "expected_score": round(mid_y, 4),
        })

    # Below first knot (clamped)
    cases.append({
        "type": "clamping_low",
        "canopy_pct": 0,
        "expected_score": 0.0,
    })

    # Above last knot (clamped)
    cases.append({
        "type": "clamping_high",
        "canopy_pct": 100,
        "expected_score": 2.0,
    })

    # Monotonicity: every 5%
    prev_score = -1
    for pct in range(0, 101, 5):
        score = apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, pct)
        cases.append({
            "type": "monotonicity",
            "canopy_pct": pct,
            "expected_score": round(score, 4),
        })

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump({"dimension": "canopy", "cases": cases}, f, indent=2)
    print(f"Generated {len(cases)} test cases → {OUTPUT_PATH}")


if __name__ == "__main__":
    generate()
```

- [ ] **Step 2: Create `scripts/validate_ground_truth_canopy.py`**

```python
#!/usr/bin/env python3
"""Validate canopy nature-feel scoring against ground truth."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring_config import CANOPY_NATURE_FEEL_KNOTS, apply_piecewise

GROUND_TRUTH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "ground_truth", "canopy.json",
)
TOLERANCE = 0.01


def validate():
    with open(GROUND_TRUTH_PATH) as f:
        data = json.load(f)

    matches = 0
    mismatches = 0

    for case in data["cases"]:
        actual = apply_piecewise(CANOPY_NATURE_FEEL_KNOTS, case["canopy_pct"])
        expected = case["expected_score"]
        if abs(actual - expected) <= TOLERANCE:
            matches += 1
        else:
            mismatches += 1
            print(
                f"MISMATCH [{case['type']}] canopy={case['canopy_pct']}%: "
                f"expected={expected}, actual={round(actual, 4)}"
            )

    print(f"\nMatches: {matches}")
    print(f"Mismatches: {mismatches}")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    sys.exit(validate())
```

- [ ] **Step 3: Generate ground truth data**

Run: `python scripts/generate_ground_truth_canopy.py`
Expected: Creates `data/ground_truth/canopy.json`

- [ ] **Step 4: Validate ground truth**

Run: `python scripts/validate_ground_truth_canopy.py`
Expected: All matches, 0 mismatches

- [ ] **Step 5: Add canopy to `_DIMENSION_LABELS` in `scripts/validate_all_ground_truth.py`**

Find the `_DIMENSION_LABELS` dict and add:
```python
    "canopy": "Canopy Nature Feel",
```

- [ ] **Step 6: Delete `scripts/ingest_nlcd.py`**

```bash
rm scripts/ingest_nlcd.py
```

- [ ] **Step 7: Commit**

```bash
git add scripts/generate_ground_truth_canopy.py scripts/validate_ground_truth_canopy.py data/ground_truth/canopy.json scripts/validate_all_ground_truth.py
git rm scripts/ingest_nlcd.py
git commit -m "feat(NES-347): add canopy ground truth, remove dead ingest_nlcd.py"
```

---

### Task 11: End-to-End Verification

- [ ] **Step 1: Run full scoring test suite**

Run: `make test-scoring`
Expected: ALL PASS

- [ ] **Step 2: Run ground truth validation**

Run: `python scripts/validate_all_ground_truth.py`
Expected: canopy dimension shows all matches

- [ ] **Step 3: Test a live canopy query (manual, optional)**

Run: `python -c "from canopy import get_canopy_cover; r = get_canopy_cover(40.7785, -73.9685); print(f'Canopy: {r.canopy_pct}%' if r else 'Failed')"`
Expected: Should return a canopy percentage (likely 40-60% for Central Park Ramble area). May take 3-5 seconds.

- [ ] **Step 4: Verify app imports cleanly**

Run: `python -c "from app import app; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix(NES-347): end-to-end verification fixes"
```
