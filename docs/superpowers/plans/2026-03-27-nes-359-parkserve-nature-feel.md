# NES-359: ParkServe Nature Feel + Startup Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire ParkServe into startup ingest so data is reliably available on deploy, then use ParkServe `Park_Type` classification to improve the `_score_nature_feel()` subscore in green space scoring.

**Architecture:** Two sequenced parts. Part 1 converts `ingest_parkserve.py` from DROP TABLE to idempotent per-state DELETE+INSERT, wires it into `startup_ingest.py`, and registers the source in `coverage_config.py`. Part 2 adds an optional `parkserve_type` parameter to `_score_nature_feel()`, maps ParkServe `Park_Type` values to scores, and threads the data through both call sites. Ground truth tests are updated last.

**Tech Stack:** Python 3, SQLite/SpatiaLite, ArcGIS REST API

---

## Part 1: Wire ParkServe into Startup Ingest

### Task 1: Add `"parkserve"` to spatial_data.py whitelist

**Files:**
- Modify: `spatial_data.py:26-29` (`_VALID_FACILITY_TYPES`)

- [ ] **Step 1: Add parkserve to the whitelist**

In `spatial_data.py`, add `"parkserve"` to the `_VALID_FACILITY_TYPES` frozenset:

```python
_VALID_FACILITY_TYPES = frozenset({
    "sems", "fema_nfhl", "hpms", "ejscreen", "tri", "ust",
    "hifld", "fra", "school_districts", "nces_schools", "parkserve",
})
```

- [ ] **Step 2: Verify the whitelist validates correctly**

Run a quick Python check:
```bash
cd /Users/jeremybrowning/NestCheck && python -c "from spatial_data import _validate_facility_type; print(_validate_facility_type('parkserve'))"
```
Expected: `facilities_parkserve`

**Note:** Do NOT commit Task 1 separately. Per CLAUDE.md rule, `_VALID_FACILITY_TYPES` must be updated in the same commit as the ingest script changes. This will be committed together with Task 2.

---

### Task 2: Convert ingest_parkserve.py to idempotent per-state DELETE+INSERT

**Files:**
- Modify: `scripts/ingest_parkserve.py`

The current script calls `create_facility_table("parkserve", ...)` which does DROP TABLE — this destroys other states' data in multi-state mode. Convert to `CREATE TABLE IF NOT EXISTS` + per-state DELETE + INSERT following the `VenueCache._ensure_table()` pattern from `spatial_data.py`.

Also add a `states` parameter so `startup_ingest.py` can pass the full list from `TARGET_STATES`.

**Caution (from ticket):** Verify ParkServe `State` field format before writing the WHERE clause. The UST endpoint stores state names inconsistently (NES-294). Run `--discover` or `returnCountOnly` to confirm 2-letter codes.

- [ ] **Step 1: Verify ParkServe State field format**

Before changing any code, confirm the format by running:
```bash
cd /Users/jeremybrowning/NestCheck && python -c "
import requests, json
resp = requests.get(
    'https://server7.tplgis.org/arcgis7/rest/services/ParkServe/ParkServe_Shareable/MapServer/0/query',
    params={'where': \"State = 'NY'\", 'returnCountOnly': 'true', 'f': 'json'},
    timeout=60
)
print('NY count:', json.dumps(resp.json(), indent=2))
resp2 = requests.get(
    'https://server7.tplgis.org/arcgis7/rest/services/ParkServe/ParkServe_Shareable/MapServer/0/query',
    params={'where': \"State = 'New York'\", 'returnCountOnly': 'true', 'f': 'json'},
    timeout=60
)
print('New York count:', json.dumps(resp2.json(), indent=2))
"
```
Expected: `NY count` shows a positive count (confirming 2-letter codes). `New York count` shows 0 or an error. Document the verified format in a code comment.

If the opposite is true (full names, not abbreviations), adjust the `WHERE` clause format throughout — do NOT proceed with assumptions.

- [ ] **Step 2: Replace `create_facility_table` with idempotent table creation**

In `ingest_parkserve.py`, replace the `create_facility_table("parkserve", ...)` call with inline idempotent DDL. Replace the import of `create_facility_table` with just `init_spatial_db, _connect`.

Replace the current table creation block (around the line `create_facility_table("parkserve", geometry_type="MULTIPOLYGON")`) with:

```python
def _ensure_parkserve_table(conn):
    """Create facilities_parkserve if it doesn't exist (idempotent).

    Uses CREATE TABLE IF NOT EXISTS + SpatiaLite DDL wrapped in try/except,
    matching the VenueCache._ensure_table() pattern from spatial_data.py.
    Does NOT use create_facility_table() which does DROP TABLE.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facilities_parkserve (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # SpatiaLite geometry column — fails if already exists, that's OK
    try:
        conn.execute(
            "SELECT AddGeometryColumn('facilities_parkserve', 'geometry', 4326, 'MULTIPOLYGON', 'XY')"
        )
    except Exception:
        pass  # Column already exists
    # Spatial index — fails if already exists, that's OK
    try:
        conn.execute(
            "SELECT CreateSpatialIndex('facilities_parkserve', 'geometry')"
        )
    except Exception:
        pass  # Index already exists
    conn.commit()
```

- [ ] **Step 3: Add `states` parameter and per-state DELETE+INSERT logic**

Update the `ingest()` function signature to accept a `states` list:

```python
def ingest(
    limit_pages: int = 0,
    state: str = "",
    states: list[str] | None = None,
    discover: bool = False,
):
```

After discover mode and before the ingestion loop, replace the existing `where` construction and table creation with:

```python
    # Build state list: --state flag (single), states param (multi), or all
    if states:
        state_list = [s.upper() for s in states]
    elif state:
        st = state.upper()
        if not (len(st) == 2 and st.isalpha()):
            raise ValueError(f"Invalid state abbreviation: {state!r} (expected 2-letter code, e.g. NY)")
        state_list = [st]
    else:
        state_list = []  # No filter = ingest all

    logger.info("Starting ParkServe park polygon ingestion")
    if state_list:
        logger.info("  States: %s", state_list)
    if limit_pages:
        logger.info("  LIMIT: %d pages (%d records)", limit_pages, limit_pages * PAGE_SIZE)

    init_spatial_db()
    conn = _connect()
    _ensure_parkserve_table(conn)
    logger.info("Ensured facilities_parkserve table exists")

    total_inserted = 0
    total_skipped = 0

    # Ingest per-state for idempotency (DELETE old state rows, then INSERT)
    targets = state_list if state_list else [""]  # empty string = no WHERE filter
    for st in targets:
        if st:
            where = f"State = '{st}'"
            # Delete existing rows for this state before re-inserting
            # ParkServe State field uses 2-letter codes (verified via returnCountOnly)
            conn.execute(
                "DELETE FROM facilities_parkserve WHERE json_extract(metadata_json, '$.state') = ?",
                (st,),
            )
            conn.commit()
            logger.info("  Cleared existing %s rows, re-ingesting...", st)
        else:
            where = "1=1"
```

Then the existing pagination loop continues unchanged (using `where`). At the end of each state's loop iteration, commit and log. Wrap the per-state loop around the existing `while True` fetch loop.

- [ ] **Step 4: Update the import line**

Change:
```python
from spatial_data import init_spatial_db, create_facility_table, _connect
```
To:
```python
from spatial_data import init_spatial_db, _connect
```

- [ ] **Step 5: Update the `__main__` block to pass `states` from CLI**

Add a `--states` argument:
```python
parser.add_argument(
    "--states", type=str, default="",
    help="Comma-separated state abbreviations (e.g., NY,NJ,CT). Overrides --state.",
)
```

And in the `else` (non-discover) branch:
```python
states_list = [s.strip() for s in args.states.split(",") if s.strip()] if args.states else None
ingest(limit_pages=args.limit, state=args.state, states=states_list)
```

- [ ] **Step 6: Test the idempotent ingest locally with one state**

```bash
cd /Users/jeremybrowning/NestCheck && python scripts/ingest_parkserve.py --state NY --limit 2
```
Expected: Creates table, inserts ~2000 records for NY. Run again:
```bash
python scripts/ingest_parkserve.py --state NY --limit 2
```
Expected: Deletes old NY rows, re-inserts ~2000 — no table recreation, no loss of other states' data.

- [ ] **Step 7: Commit**

```bash
git add spatial_data.py scripts/ingest_parkserve.py
git commit -m "feat(NES-359): convert ingest_parkserve to idempotent per-state DELETE+INSERT

Replaces create_facility_table() (DROP TABLE) with CREATE TABLE IF NOT EXISTS
+ SpatiaLite DDL. Adds states param for startup_ingest.py integration.
Per-state DELETE+INSERT preserves other states' data during incremental ingest.
Adds 'parkserve' to _VALID_FACILITY_TYPES (same commit per CLAUDE.md rule)."
```

---

### Task 3: Wire ParkServe into startup_ingest.py

**Files:**
- Modify: `startup_ingest.py`

Follow the exact pattern used by EJScreen (lines 209-215): check `_missing_states_abbr()`, ingest all states if any are missing (ParkServe's `create_facility_table` was the old pattern — now idempotent, but since all states share the same endpoint pagination, re-ingesting all is simpler than per-state incremental).

- [ ] **Step 1: Add lazy-import wrapper**

After the `_ingest_fra()` wrapper and before `_ingest_school_districts()` (find by searching for `def _ingest_fra` and `def _ingest_school_districts`), add:

```python
def _ingest_parkserve():
    from scripts.ingest_parkserve import ingest as do_ingest
    do_ingest(states=list(TARGET_STATES.keys()))
```

- [ ] **Step 2: Add ParkServe check block to `_check_and_ingest_all()`**

After the FRA block and before the School Districts block (find by searching for `# --- FRA` and `# --- School Districts`), add:

```python
    # --- ParkServe (Trust for Public Land park polygons, per-state) ---
    parkserve_missing = _missing_states_abbr(db_path, "facilities_parkserve")
    if parkserve_missing:
        has_data, count = _table_has_data(db_path, "facilities_parkserve")
        logger.info(
            "Dataset parkserve: missing states %s (%d existing records), re-ingesting all states...",
            parkserve_missing, count,
        )
        _run_ingest("parkserve", _ingest_parkserve)
    else:
        has_data, count = _table_has_data(db_path, "facilities_parkserve")
        logger.info("Dataset parkserve: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)
```

- [ ] **Step 3: Update module docstring**

Add "ParkServe" to the dataset list in the docstring (line 4):

```python
Called during gunicorn post_fork to ensure spatial datasets (SEMS, FEMA, HPMS,
EJScreen, TRI, UST, HIFLD, FRA, ParkServe, School Districts, NYSED, NCES) are populated before
```

- [ ] **Step 4: Commit**

```bash
git add startup_ingest.py
git commit -m "feat(NES-359): wire ParkServe into startup ingest

Uses _missing_states_abbr() pattern — only ingests when states are missing.
ParkServe ingest runs after FRA, before School Districts."
```

---

### Task 4: Register ParkServe in coverage_config.py

**Files:**
- Modify: `coverage_config.py`

Four places to update: `_SOURCE_METADATA`, `SOURCE_DISPLAY_LIST`, `_SOURCE_TO_REGISTRY_KEY`, per-state manifests. Plus `SECTION_DIMENSION_MAP` to include ParkServe under parks.

- [ ] **Step 1: Add to `_SOURCE_METADATA`**

After the `GOOGLE_PLACES_PARKS` entry (line 215) and before `GOOGLE_TRANSIT` (line 216), add:

```python
    "PARKSERVE": {
        "description": "Trust for Public Land ParkServe Parks",
        "table": "facilities_parkserve",
        "dimension": "green_space",
        "source_url": "https://www.tpl.org/parkserve",
        "state_filter": "json_extract(metadata_json, '$.state')",
        "state_key_format": "abbr",  # 2-letter code (verified: "NY" not "New York")
        "notes": "Park polygon boundaries from TPL covering 14,000+ U.S. cities.",
    },
```

- [ ] **Step 2: Add to `SOURCE_DISPLAY_LIST`**

After the `GOOGLE_PLACES_PARKS` entry (line 85) — keep dimension groups together:

```python
    {"key": "PARKSERVE", "name": "Park Classifications (TPL)", "dimension": "Parks", "source_org": "TPL"},
```

- [ ] **Step 3: Add to `_SOURCE_TO_REGISTRY_KEY`**

After line 565 (`GOOGLE_PLACES_PARKS`):

```python
    "PARKSERVE": "parkserve",
```

- [ ] **Step 4: Update `SECTION_DIMENSION_MAP`**

The `parks` entry at line 592 already has a comment about adding ParkServe. Update it:

```python
    "parks": ["green_space"],       # Park scoring uses Google Places (live) +
                                    # ParkServe (spatial.db). PARKSERVE source is
                                    # registered in green_space dimension.
```

No change to the list value — ParkServe is part of the `green_space` dimension, which is already referenced. The coverage tier rollup will pick up ParkServe through `_SOURCE_METADATA` dimension mapping.

- [ ] **Step 5: Add ParkServe to all 8 state manifests**

Add `"PARKSERVE": "active",` to each state's manifest entry. For each state (NY, NJ, CT, MI, CA, TX, FL, IL), add after the `FEMA_NFHL` line, before `GOOGLE_PLACES_PARKS`:

```python
        "PARKSERVE": "active",          # TPL ParkServe park polygons
```

- [ ] **Step 6: Verify manifest sync whitelist picks up the new table**

The `_SYNC_VALID_TABLES` and `_SYNC_VALID_FILTERS` are derived dynamically from `_SOURCE_METADATA` (lines 680-690), so no manual update needed. Verify:

```bash
cd /Users/jeremybrowning/NestCheck && python -c "
from coverage_config import _SYNC_VALID_TABLES, _SYNC_VALID_FILTERS
print('parkserve table in whitelist:', 'facilities_parkserve' in _SYNC_VALID_TABLES)
print('parkserve filter in whitelist:', \"json_extract(metadata_json, '$.state')\" in _SYNC_VALID_FILTERS)
"
```
Expected: Both `True`.

- [ ] **Step 7: Commit**

```bash
git add coverage_config.py
git commit -m "feat(NES-359): register ParkServe in coverage manifest

Adds PARKSERVE to _SOURCE_METADATA, SOURCE_DISPLAY_LIST,
_SOURCE_TO_REGISTRY_KEY, and all 8 state manifest entries as active.
Dimension: green_space. State filter: 2-letter code in metadata_json."
```

---

### Task 5: Verify Part 1 — smoke test ParkServe availability

**Files:** None (verification only)

- [ ] **Step 1: Run make smoke-test**

```bash
cd /Users/jeremybrowning/NestCheck && make smoke-test
```
Expected: PASS (ParkServe in startup ingest doesn't break existing pipeline).

- [ ] **Step 2: Verify ParkServe discovery returns results locally**

```bash
cd /Users/jeremybrowning/NestCheck && python -c "
from green_space import _discover_parkserve_parks
results = _discover_parkserve_parks(40.7829, -73.9654, 2000)
print(f'Found {len(results)} ParkServe parks near Central Park')
for p in results[:3]:
    print(f'  {p[\"name\"]}: type={p.get(\"_parkserve_type\")}, acres={p.get(\"_parkserve_acres\")}')
"
```
Expected: At least 1 result with `_parkserve_type` populated (e.g., "Community Park", "Regional Park").

If `_discover_parkserve_parks` returns `[]`, the ParkServe data isn't in spatial.db yet. Run:
```bash
python scripts/ingest_parkserve.py --state NY --limit 5
```
Then re-run the discovery check.

---

## Part 2: Improve nature_feel with ParkServe Type Classification

### Task 6: Add `parkserve_type` parameter to `_score_nature_feel()`

**Files:**
- Modify: `green_space.py:1301-1354` (`_score_nature_feel`)

- [ ] **Step 1: Add the ParkServe type-to-score mapping**

Above `_score_nature_feel()` (before line 1301), add the mapping constant:

```python
# ParkServe Park_Type → nature_feel score mapping (NES-359).
# Values from Trust for Public Land classification. "Can only help, never hurt"
# pattern: max(parkserve_score, existing_keyword_score).
_PARKSERVE_TYPE_NATURE_SCORES: Dict[str, Tuple[float, str]] = {
    # Authoritative nature classification
    "Nature Preserve": (1.5, "Nature preserve (ParkServe)"),
    "Nature Area": (1.5, "Nature area (ParkServe)"),
    # Trail/corridor — good nature feel, less immersive
    "Greenway": (1.0, "Greenway (ParkServe)"),
    "Trail": (1.0, "Trail (ParkServe)"),
    "Linear Park": (1.0, "Linear park (ParkServe)"),
    # Large parks with likely natural areas
    "Regional Park": (1.0, "Regional park (ParkServe)"),
    "State Park": (1.0, "State park (ParkServe)"),
    # May have trees but primarily built amenities
    "Community Park": (0.3, "Community park (ParkServe)"),
    # Too small for meaningful nature feel
    "Pocket Park": (0.0, ""),
    "Mini Park": (0.0, ""),
}


def _parkserve_type_score(parkserve_type: Optional[str]) -> Tuple[float, str]:
    """Look up nature_feel score for a ParkServe Park_Type value.

    Uses substring matching: Park_Type "Regional Park and Open Space" matches
    "Regional Park". Checks longer keys first to avoid partial matches.
    Returns (0.0, "") if no match.
    """
    if not parkserve_type:
        return 0.0, ""
    # Check longest keys first to avoid "Park" matching before "Regional Park"
    for key in sorted(_PARKSERVE_TYPE_NATURE_SCORES, key=len, reverse=True):
        if key.lower() in parkserve_type.lower():
            return _PARKSERVE_TYPE_NATURE_SCORES[key]
    return 0.0, ""
```

- [ ] **Step 2: Update `_score_nature_feel()` signature and body**

Change the function signature from:
```python
def _score_nature_feel(osm_data: Dict[str, Any], name: str, types: List[str]) -> Tuple[float, str]:
```
To:
```python
def _score_nature_feel(
    osm_data: Dict[str, Any],
    name: str,
    types: List[str],
    parkserve_type: Optional[str] = None,
) -> Tuple[float, str]:
```

At the end of the function, before the final `return`, add the ParkServe integration using `max()` pattern (can only help, never hurt):

Replace:
```python
    if not parts:
        parts.append("no nature indicators found")

    return min(2.0, round(score, 1)), "; ".join(parts)
```

With:
```python
    # ParkServe type classification — can only help, never hurt (NES-359)
    ps_score, ps_reason = _parkserve_type_score(parkserve_type)
    if ps_score > score:
        score = ps_score
        parts = [ps_reason] if ps_reason else parts
    elif ps_score > 0 and ps_reason and ps_score == score:
        # Same score but ParkServe provides a more authoritative reason
        parts.append(ps_reason)

    if not parts:
        parts.append("no nature indicators found")

    return min(2.0, round(score, 1)), "; ".join(parts)
```

- [ ] **Step 3: Commit**

```bash
git add green_space.py
git commit -m "feat(NES-359): add parkserve_type to _score_nature_feel()

Maps ParkServe Park_Type values to nature_feel scores using substring
matching. Integration rule: max(parkserve_score, keyword_score) — ParkServe
can only help, never hurt. Replaces keyword guessing with authoritative
TPL classification where available."
```

---

### Task 7: Thread `parkserve_type` through both call sites

**Files:**
- Modify: `green_space.py:1403` (in `compute_park_score`)
- Modify: `green_space.py:1442` (in `score_green_space`)

- [ ] **Step 1: Add `parkserve_type` parameter to `compute_park_score()`**

Update the function signature at line 1357 — add after `park_acres`:

```python
def compute_park_score(
    walk_time_min: int,
    rating: Optional[float] = None,
    reviews: int = 0,
    name: str = "",
    types: Optional[List[str]] = None,
    park_acres: Optional[float] = None,
    parkserve_type: Optional[str] = None,  # NEW (NES-359)
    osm_area_sqm: Optional[float] = None,
    osm_path_count: int = 0,
    osm_has_trail: bool = False,
    osm_nature_tags: Optional[List[str]] = None,
) -> float:
```

- [ ] **Step 2: Pass `parkserve_type` to `_score_nature_feel()` in `compute_park_score()`**

Change line 1403 from:
```python
    nf_score, _ = _score_nature_feel(osm_data, name, types)
```
To:
```python
    nf_score, _ = _score_nature_feel(osm_data, name, types, parkserve_type=parkserve_type)
```

- [ ] **Step 3: Pass `parkserve_type` to `_score_nature_feel()` in `score_green_space()`**

At line 1442, the park dict's `_parkserve_type` is available. Change from:
```python
    nf_score, nf_reason = _score_nature_feel(osm_data, name, types)
```
To:
```python
    parkserve_type = place.get("_parkserve_type")
    nf_score, nf_reason = _score_nature_feel(osm_data, name, types, parkserve_type=parkserve_type)
```

Note: `parkserve_acres` is already extracted at line 1436. Add `parkserve_type` extraction right after it (before or after line 1436).

- [ ] **Step 4: Verify no import needed**

`_parkserve_type_score` and `_PARKSERVE_TYPE_NATURE_SCORES` are defined in the same file (`green_space.py`). `Optional` is already imported from `typing`. No new imports needed.

- [ ] **Step 5: Commit**

```bash
git add green_space.py
git commit -m "feat(NES-359): thread parkserve_type through both scoring call sites

compute_park_score() gains parkserve_type param for ground truth testing.
score_green_space() extracts _parkserve_type from the park dict.
Both pass to _score_nature_feel() which uses the max() integration rule."
```

---

### Task 8: Bump SCORING_MODEL version

**Files:**
- Modify: `scoring_config.py` (version line)

- [ ] **Step 1: Bump version to 1.6.1**

Find the `version=` line in the `ScoringModel` instantiation and change from current version to `"1.6.1"`:

```python
version="1.6.1",
```

- [ ] **Step 2: Commit**

```bash
git add scoring_config.py
git commit -m "feat(NES-359): bump SCORING_MODEL to 1.6.1

ParkServe type classification changes nature_feel subscore output for parks
with ParkServe data — scoring behavior change requires version bump."
```

---

## Part 3: Ground Truth Updates

### Task 9: Add ParkServe type test cases to ground truth generator

**Files:**
- Modify: `scripts/generate_ground_truth_parks.py`

Add ParkServe type cases to `_generate_nature_feel_tests()` and threading through composites.

- [ ] **Step 1: Update `_compute_nature_feel_score` mirror function**

The mirror at line 156 currently calls `_score_nature_feel(osm_data, name, types)`. Update to accept and pass `parkserve_type`:

```python
def _compute_nature_feel_score(osm_data, name, types, parkserve_type=None):
    """Mirror of _score_nature_feel, returns score only."""
    if _IMPORTS_OK:
        score, _ = _score_nature_feel(osm_data, name, types, parkserve_type=parkserve_type)
        return score
    raise RuntimeError("Cannot compute nature_feel without imports")
```

- [ ] **Step 2: Add ParkServe type test cases to `_generate_nature_feel_tests()`**

Extend the `nature_tests` list in `_generate_nature_feel_tests()` (around line 386) with ParkServe type cases:

```python
        # ParkServe type classification (NES-359)
        ([], "Some Nature Area", [], "parkserve Nature Preserve, no other signals",
         "Nature Preserve"),
        ([], "City Park", [], "parkserve Community Park, no other signals",
         "Community Park"),
        ([], "Mini Green", [], "parkserve Mini Park (too small)",
         "Mini Park"),
        ([], "Regional Open Space", [], "parkserve Regional Park",
         "Regional Park"),
        ([], "River Trail", [], "parkserve Greenway",
         "Greenway"),
        (["forest"], "Forest Park", [], "parkserve Nature Preserve + OSM forest tag",
         "Nature Preserve"),
        (["forest", "water"], "Lake Nature Preserve", [],
         "parkserve Community Park vs strong OSM (OSM wins at 1.5)",
         "Community Park"),
        ([], "Trail Path", [], "parkserve Trail vs trail name keyword",
         "Trail"),
```

Update the tuple unpacking in the loop to handle the optional 5th element (parkserve_type):

```python
    for i, test_data in enumerate(nature_tests, 1):
        if len(test_data) == 5:
            tags, name, types, desc, ps_type = test_data
        else:
            tags, name, types, desc = test_data
            ps_type = None

        osm_data = {"enriched": len(tags) > 0, "area_sqm": None,
                     "path_count": 0, "has_trail": False,
                     "nature_tags": tags}
        score = _compute_nature_feel_score(osm_data, name, types, parkserve_type=ps_type)
        inputs = {
            "osm_nature_tags": tags,
            "name": name,
            "types": types,
        }
        if ps_type is not None:
            inputs["parkserve_type"] = ps_type
        cases.append({
            "id": f"gt-parks-nf-{i:02d}",
            "test_type": "nature_feel",
            "description": desc,
            "inputs": inputs,
            "expected": {"nature_feel_score": score},
        })
```

- [ ] **Step 3: Add composite test cases with parkserve_type**

In `_generate_composite_tests()`, add at least one test case that includes `parkserve_type`:

```python
        (
            {"walk_time_min": 8, "rating": 4.2, "reviews": 150,
             "name": "Riverside Park", "park_acres": 15.0,
             "parkserve_type": "Nature Preserve",
             "osm_path_count": 3, "osm_nature_tags": []},
            "ParkServe Nature Preserve boosts nature_feel",
        ),
        (
            {"walk_time_min": 12, "rating": 3.8, "reviews": 50,
             "name": "Town Square", "parkserve_type": "Pocket Park"},
            "ParkServe Pocket Park — no nature_feel boost",
        ),
```

Update the composite score mirror to pass `parkserve_type` to `compute_park_score`:

The composite mirror already uses `compute_park_score(**kwargs)`. Since `parkserve_type` is now a parameter of `compute_park_score`, it will be passed through automatically from the kwargs dict. No change needed to the mirror — just include `parkserve_type` in the test case `inputs` dict and it flows through.

- [ ] **Step 4: Regenerate ground truth file**

```bash
cd /Users/jeremybrowning/NestCheck && python scripts/generate_ground_truth_parks.py --seed 42
```
Expected: Writes to `data/ground_truth/parks.json` with updated cases.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_ground_truth_parks.py data/ground_truth/parks.json
git commit -m "feat(NES-359): add ParkServe type test cases to parks ground truth

Adds 8 nature_feel tests with parkserve_type + 2 composite tests.
Exercises all 5 ParkServe type tiers and the max() integration rule."
```

---

### Task 10: Update ground truth validator to pass `parkserve_type`

**Files:**
- Modify: `scripts/validate_ground_truth_parks.py`

- [ ] **Step 1: Update `_validate_nature_feel()` to pass `parkserve_type`**

Change lines 148-150 from:
```python
    actual, _ = _score_nature_feel(
        osm_data, inp.get("name", ""), inp.get("types", [])
    )
```
To:
```python
    actual, _ = _score_nature_feel(
        osm_data, inp.get("name", ""), inp.get("types", []),
        parkserve_type=inp.get("parkserve_type"),
    )
```

- [ ] **Step 2: Update `_validate_composite()` to pass `parkserve_type`**

In the kwargs dict (line 163-174), add:
```python
        "parkserve_type": inp.get("parkserve_type"),
```

And in the nature_feel subscore check within composite validation (lines 230-232), update:
```python
        nf_actual, _ = _score_nature_feel(
            nf_osm, inp.get("name", ""), inp.get("types", []),
            parkserve_type=inp.get("parkserve_type"),
        )
```

- [ ] **Step 3: Run validation**

```bash
cd /Users/jeremybrowning/NestCheck && python scripts/validate_ground_truth_parks.py
```
Expected: All tests MATCH, 0 mismatches.

- [ ] **Step 4: Commit**

```bash
git add scripts/validate_ground_truth_parks.py
git commit -m "feat(NES-359): update parks validator to pass parkserve_type

Threads parkserve_type from ground truth inputs to _score_nature_feel()
in both standalone nature_feel and composite validation paths."
```

---

### Task 11: Run full test suite and validate

**Files:** None (verification only)

- [ ] **Step 1: Run scoring tests**

```bash
cd /Users/jeremybrowning/NestCheck && make test-scoring
```
Expected: All PASS.

- [ ] **Step 2: Run full ground truth validation**

```bash
cd /Users/jeremybrowning/NestCheck && make validate
```
Expected: All dimensions PASS, 0 mismatches.

- [ ] **Step 3: Run smoke test**

```bash
cd /Users/jeremybrowning/NestCheck && make smoke-test
```
Expected: PASS.

- [ ] **Step 4: Verify a ParkServe-attributed nature_feel rationale appears**

```bash
cd /Users/jeremybrowning/NestCheck && python -c "
from green_space import _score_nature_feel
# Simulate a park with ParkServe Nature Preserve type, no OSM data
osm = {'enriched': False, 'area_sqm': None, 'path_count': 0, 'has_trail': False, 'nature_tags': []}
score, reason = _score_nature_feel(osm, 'Some Park', [], parkserve_type='Nature Preserve')
print(f'Score: {score}, Reason: {reason}')
assert 'ParkServe' in reason, f'Expected ParkServe attribution, got: {reason}'
assert score == 1.5, f'Expected 1.5, got: {score}'
print('PASS: ParkServe attribution works')
"
```

- [ ] **Step 5: Final commit if any fixes were needed**

Only if previous steps revealed issues that needed fixing.
