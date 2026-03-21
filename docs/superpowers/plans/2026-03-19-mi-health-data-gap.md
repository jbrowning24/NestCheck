# Michigan Health Data Gap Fix (NES-297) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Michigan evaluations use all 8 federal health data sources by fixing the startup_ingest.py state-detection logic that skips ingestion when any state's data exists.

**Architecture:** Option A — detect missing states per source, re-ingest all TARGET_STATES when any are missing (since 5 of 7 ingest scripts use DROP TABLE + CREATE). One small metadata addition to FRA's ingest script (add `stateab` field) to enable generic state detection. HPMS already supports incremental; HIFLD is national and done. Update coverage_config.py manifest after ingestion.

**Tech Stack:** Python, SQLite, ArcGIS REST APIs, json_extract()

**Linear:** NES-297

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `startup_ingest.py` | Modify (lines 119-146, 224-314) | Add generic `_missing_states()` function; replace `_table_has_data()` with per-state checks for 6 sources |
| `scripts/ingest_fra.py` | Modify (line ~211-219) | Add `"stateab"` to metadata_json so state detection works |
| `coverage_config.py` | Modify (lines 333-350) | Update MI manifest from `intended`/`planned` to `active` after successful ingestion |

**Not touched:** The 5 DROP TABLE ingest scripts (TRI, EJScreen, School Districts, NCES, HPMS ingest logic). We re-run them as-is with full TARGET_STATES.

---

## Context for Implementers

### Root Cause
`startup_ingest.py` uses `_table_has_data(db_path, "facilities_X")` to decide whether to skip ingestion. This checks total row count — if NY/NJ/CT data exists, it returns True and skips ingestion even though MI has 0 rows. UST already has a fix (`_ust_missing_states()`). The other 6 sources need the same treatment.

### Source Detection Strategies
- **TRI, EJScreen:** `json_extract(metadata_json, '$.state')` returns 2-letter codes (e.g., `'MI'`)
- **HPMS:** `json_extract(metadata_json, '$.state')` returns 2-letter codes
- **FRA:** Currently has NO state field in metadata_json. Task 1 adds `"stateab"` so it works with the generic checker. Gets tested immediately since Option A re-ingests all states.
- **School Districts:** `SUBSTR(json_extract(metadata_json, '$.geoid'), 1, 2)` returns FIPS codes (e.g., `'26'` for MI)
- **NCES:** `SUBSTR(json_extract(metadata_json, '$.leaid'), 1, 2)` returns FIPS codes (e.g., `'26'` for MI). Also: startup_ingest already iterates per-state (line 428-430), just blocked by `_table_has_data()` wrapping the whole loop.
- **HIFLD:** National ingest, no state filter. If table has data, MI lines are already there. No change needed.

### What "Re-ingest All States" Means
For DROP TABLE sources, calling `ingest(states=["NY","NJ","CT","MI",...])` drops the table and re-fetches all states from scratch. This is a one-time cost (~5-15 min per source on first deploy). Acceptable for MI onboarding; follow-up ticket converts to incremental.

---

## Task 1: Add `stateab` to FRA metadata_json

**Files:**
- Modify: `scripts/ingest_fra.py:211-219`

This is the prerequisite for the generic missing-states checker to work on FRA.

- [ ] **Step 1: Add stateab to FRA metadata dict**

In `scripts/ingest_fra.py`, find the metadata dict construction (around line 211):

```python
                metadata = {
                    "owner": owner,
                    "owner2": attrs.get("RROWNER2", ""),
                    "net": net,
                    "passenger": attrs.get("PASSNGR", ""),
                    "stracnet": attrs.get("STRACNET", ""),
                    "miles": attrs.get("MILES"),
                    "km": attrs.get("KM"),
                }
```

Add one line after `"km"`:

```python
                    "stateab": attrs.get("STATEAB", ""),
```

- [ ] **Step 2: Verify the STATEAB field exists in FRA data**

We confirmed via curl that FRA returns `STATEAB` in feature attributes. The attrs dict comes from `feature.get("attributes", {})` which includes all outFields. No schema change needed.

- [ ] **Step 3: Commit**

```bash
git add scripts/ingest_fra.py
git commit -m "feat(ingest): add stateab to FRA metadata_json for state detection (NES-297)"
```

---

## Task 2: Add generic `_missing_states()` to startup_ingest.py

**Files:**
- Modify: `startup_ingest.py:119-146`

Replace the UST-specific `_ust_missing_states()` with a generic function that handles all detection strategies, then make `_ust_missing_states()` delegate to it.

- [ ] **Step 1: Write `_missing_states()` function**

Add after `_table_has_data()` (after line 116), before the existing `_ust_missing_states()`:

```python
def _missing_states(
    db_path: str,
    table_name: str,
    state_expr: str,
    expected: dict[str, str],
) -> list[str]:
    """Return TARGET_STATES codes that have 0 rows in the given table.

    Args:
        db_path: Path to spatial.db.
        table_name: Table to check (e.g., "facilities_tri").
        state_expr: SQL expression that extracts the state identifier from a row.
            Examples:
            - "json_extract(metadata_json, '$.state')"  (returns 2-letter code)
            - "SUBSTR(json_extract(metadata_json, '$.geoid'), 1, 2)"  (returns FIPS)
        expected: Mapping of TARGET_STATES code → value that state_expr produces.
            e.g., {"NY": "NY", "MI": "MI"} for 2-letter, or {"NY": "36", "MI": "26"} for FIPS.

    Returns list of TARGET_STATES codes (e.g., ["MI", "CA"]) that are missing.
    On any error, returns all codes from expected (safe: triggers full re-ingest).
    """
    try:
        _validate_table_name(table_name)
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            if not cursor.fetchone():
                return list(expected.keys())

            cursor = conn.execute(
                f"SELECT DISTINCT {state_expr} FROM {table_name}"
            )
            present = {row[0] for row in cursor.fetchall()}
            return [
                code for code, val in expected.items()
                if val not in present
            ]
        finally:
            conn.close()
    except Exception:
        return list(expected.keys())
```

- [ ] **Step 2: Rewrite `_ust_missing_states()` to delegate**

Replace the body of `_ust_missing_states()` (lines 119-146) with:

```python
def _ust_missing_states(db_path: str) -> list[str]:
    """Return target state codes that have 0 UST rows in spatial.db.

    UST stores state as full name in json_extract(metadata_json, '$.state').
    Returns e.g. ['NJ', 'CT', 'MI'] for states without data.
    On any error (table missing, DB missing), returns all target states.
    """
    return _missing_states(
        db_path,
        "facilities_ust",
        "json_extract(metadata_json, '$.state')",
        {code: info["full_name"] for code, info in TARGET_STATES.items()},
    )
```

- [ ] **Step 3: Add convenience builders for the two key formats**

Add right after `_missing_states()`:

```python
def _missing_states_abbr(db_path: str, table_name: str) -> list[str]:
    """Missing states for tables where metadata $.state is 2-letter code."""
    return _missing_states(
        db_path, table_name,
        "json_extract(metadata_json, '$.state')",
        {code: code for code in TARGET_STATES},
    )


def _missing_states_fips(db_path: str, table_name: str, json_field: str) -> list[str]:
    """Missing states for tables where a metadata field has FIPS prefix."""
    return _missing_states(
        db_path, table_name,
        f"SUBSTR(json_extract(metadata_json, '$.{json_field}'), 1, 2)",
        {code: info["fips"] for code, info in TARGET_STATES.items()},
    )
```

- [ ] **Step 4: Commit**

```bash
git add startup_ingest.py
git commit -m "feat(ingest): add generic _missing_states() for multi-state detection (NES-297)"
```

---

## Task 3: Replace `_table_has_data()` checks with per-state detection

**Files:**
- Modify: `startup_ingest.py:224-314`

For each of the 6 affected sources, replace the `_table_has_data()` → skip pattern with the missing-states pattern. Group A (TRI, EJScreen, HPMS) use 2-letter abbreviation detection. Group B (FRA) uses stateab in metadata. Group C (School Districts, NCES) use FIPS prefix detection. HPMS is special — it's already incremental, so we only re-ingest missing states.

- [ ] **Step 1: Fix EJScreen block (lines 232-238)**

Replace:
```python
    # --- EJScreen (EPA environmental justice block groups, NY+CT+NJ) ---
    has_data, count = _table_has_data(db_path, "facilities_ejscreen")
    if has_data:
        logger.info("Dataset ejscreen: present (%d records), skipping", count)
    else:
        logger.info("Dataset ejscreen: missing or empty, starting ingestion...")
        _run_ingest("ejscreen", _ingest_ejscreen)
```

With:
```python
    # --- EJScreen (EPA environmental justice block groups) ---
    ejscreen_missing = _missing_states_abbr(db_path, "facilities_ejscreen")
    if ejscreen_missing:
        has_data, count = _table_has_data(db_path, "facilities_ejscreen")
        logger.info(
            "Dataset ejscreen: missing states %s (%d existing records), re-ingesting all states...",
            ejscreen_missing, count,
        )
        _run_ingest("ejscreen", _ingest_ejscreen)
    else:
        has_data, count = _table_has_data(db_path, "facilities_ejscreen")
        logger.info("Dataset ejscreen: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)
```

- [ ] **Step 2: Fix TRI block (lines 240-246)**

Replace with same pattern:
```python
    # --- TRI (EPA Toxic Release Inventory) ---
    tri_missing = _missing_states_abbr(db_path, "facilities_tri")
    if tri_missing:
        has_data, count = _table_has_data(db_path, "facilities_tri")
        logger.info(
            "Dataset tri: missing states %s (%d existing records), re-ingesting all states...",
            tri_missing, count,
        )
        _run_ingest("tri", _ingest_tri)
    else:
        has_data, count = _table_has_data(db_path, "facilities_tri")
        logger.info("Dataset tri: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)
```

- [ ] **Step 3: Fix HPMS block (lines 224-230)**

HPMS is already incremental (per-state DELETE + INSERT, no DROP TABLE). Only re-ingest missing states, not all. Replace:
```python
    # --- HPMS (high-traffic roads, tri-state) ---
    has_data, count = _table_has_data(db_path, "facilities_hpms")
    if has_data:
        logger.info("Dataset hpms: present (%d records), skipping", count)
    else:
        logger.info("Dataset hpms: missing or empty, starting ingestion...")
        _run_ingest("hpms", _ingest_hpms)
```

With:
```python
    # --- HPMS (high-traffic roads, per-state incremental) ---
    hpms_missing = _missing_states_abbr(db_path, "facilities_hpms")
    if hpms_missing:
        has_data, count = _table_has_data(db_path, "facilities_hpms")
        logger.info(
            "Dataset hpms: missing states %s (%d existing records), ingesting missing states...",
            hpms_missing, count,
        )
        _run_ingest("hpms", lambda: _ingest_hpms_states(hpms_missing))
    else:
        has_data, count = _table_has_data(db_path, "facilities_hpms")
        logger.info("Dataset hpms: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)
```

Then add a new wrapper function near the other `_ingest_*` functions:

```python
def _ingest_hpms_states(states: list[str]):
    """Ingest HPMS for specific states only (incremental — HPMS supports per-state DELETE+INSERT)."""
    from scripts.ingest_hpms import ingest as do_ingest
    do_ingest(states_filter=states)
```

Note: The existing `_ingest_hpms()` passes `states_filter=list(TARGET_STATES.keys())`. The new wrapper passes only missing states. This works because HPMS uses `CREATE TABLE IF NOT EXISTS` + per-state `DELETE FROM ... WHERE` + `INSERT`, not DROP TABLE.

- [ ] **Step 4: Fix FRA block (lines 273-279)**

FRA will have `stateab` in metadata after Task 1. Use a custom `_missing_states()` call:
```python
    # --- FRA (rail network lines, state-filtered via STATEAB) ---
    fra_missing = _missing_states(
        db_path, "facilities_fra",
        "json_extract(metadata_json, '$.stateab')",
        {code: code for code in TARGET_STATES},
    )
    if fra_missing:
        has_data, count = _table_has_data(db_path, "facilities_fra")
        logger.info(
            "Dataset fra: missing states %s (%d existing records), re-ingesting all states...",
            fra_missing, count,
        )
        _run_ingest("fra", _ingest_fra)
    else:
        has_data, count = _table_has_data(db_path, "facilities_fra")
        logger.info("Dataset fra: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)
```

**Edge case:** On first deploy after this change, FRA's existing rows won't have `stateab` in metadata_json. `json_extract` returns NULL for missing keys, which won't match any expected value → `fra_missing` returns all states → triggers full re-ingest. This is exactly correct behavior: the re-ingest populates the new field.

- [ ] **Step 5: Fix School Districts block (lines 281-287)**

```python
    # --- School Districts (TIGER unified school district boundaries) ---
    sd_missing = _missing_states_fips(db_path, "facilities_school_districts", "geoid")
    if sd_missing:
        has_data, count = _table_has_data(db_path, "facilities_school_districts")
        logger.info(
            "Dataset school_districts: missing states %s (%d existing records), re-ingesting all states...",
            sd_missing, count,
        )
        _run_ingest("school_districts", _ingest_school_districts)
    else:
        has_data, count = _table_has_data(db_path, "facilities_school_districts")
        logger.info("Dataset school_districts: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)
```

- [ ] **Step 6: Fix NCES block (lines 308-314)**

NCES is called per-state via `startup_ingest.py` lines 422-430. The `_table_has_data()` wrapping the whole loop is the problem. Replace:
```python
    # --- NCES Public Schools (2022-23, tri-state) ---
    has_data, count = _table_has_data(db_path, "facilities_nces_schools")
    if has_data:
        logger.info("Dataset nces_schools: present (%d records), skipping", count)
    else:
        logger.info("Dataset nces_schools: missing or empty, starting ingestion...")
        _run_ingest("nces_schools", _ingest_nces_schools)
```

With:
```python
    # --- NCES Public Schools (2022-23) ---
    nces_missing = _missing_states_fips(db_path, "facilities_nces_schools", "leaid")
    if nces_missing:
        has_data, count = _table_has_data(db_path, "facilities_nces_schools")
        logger.info(
            "Dataset nces_schools: missing states %s (%d existing records), re-ingesting all states...",
            nces_missing, count,
        )
        _run_ingest("nces_schools", _ingest_nces_schools)
    else:
        has_data, count = _table_has_data(db_path, "facilities_nces_schools")
        logger.info("Dataset nces_schools: present for all %d states (%d records), skipping",
                     len(TARGET_STATES), count)
```

Note: `_ingest_nces_schools()` already iterates over all TARGET_STATES (line 428). The first call creates the table; subsequent calls use `_skip_table_create=True`. Since `create_facility_table` does DROP+CREATE, the first state's call wipes existing data — but since we're re-ingesting all states, this is fine.

- [ ] **Step 7: Update stale comments**

Update the inline comments that still say "NY+CT+NJ" or "tri-state" to reflect multi-state scope:
- Line 232: `"NY+CT+NJ"` → remove state list from comment (already handled by TARGET_STATES)
- Line 240: same
- Line 281: same
- Line 308: same

- [ ] **Step 8: Commit**

```bash
git add startup_ingest.py
git commit -m "fix(ingest): per-state detection for EJScreen/TRI/HPMS/FRA/SchoolDistricts/NCES (NES-297)

Replaces _table_has_data() checks with _missing_states() for 6 sources.
When any state is missing, re-ingests all states (Option A — DROP TABLE
scripts can't do incremental). HPMS uses incremental path since it
supports per-state DELETE+INSERT.

This fixes the root cause of the MI health data gap: tri-state data
existing caused _table_has_data() to return True, skipping MI ingestion."
```

---

## Task 4: Update coverage_config.py manifest for MI

**Files:**
- Modify: `coverage_config.py:333-350`

After deploying and confirming data lands, update the manifest. Since we can't run the actual ingestion locally (it requires the production spatial.db), prepare the manifest update to deploy alongside the code change. The manifest should reflect what the code will produce, not what spatial.db contains right now.

- [ ] **Step 1: Update MI manifest entries**

Change these MI entries in `COVERAGE_MANIFEST`:
```python
        "EJSCREEN": "intended",     # targeted but 0 rows
```
to:
```python
        "EJSCREEN": "active",       # per-state detection re-ingests (NES-297)
```

```python
        "HPMS": "intended",         # targeted but 0 rows
```
to:
```python
        "HPMS": "active",           # per-state incremental ingest (NES-297)
```

```python
        "HIFLD": "planned",         # bbox doesn't cover MI
```
to:
```python
        "HIFLD": "active",          # national ingest covers MI (NES-285)
```

```python
        "FRA": "planned",           # bbox doesn't cover MI
```
to:
```python
        "FRA": "active",            # state-filtered via STATEAB (NES-297)
```

```python
        "SCHOOL_DISTRICTS": "intended",  # targeted but 0 rows
```
to:
```python
        "SCHOOL_DISTRICTS": "active",    # per-state detection re-ingests (NES-297)
```

```python
        "NCES_SCHOOLS": "intended",      # targeted but 0 rows
```
to:
```python
        "NCES_SCHOOLS": "active",        # per-state detection re-ingests (NES-297)
```

- [ ] **Step 2: Update the manifest datestamp comment**

Line 272: change `as of 2026-03-18` to `as of 2026-03-19`.

- [ ] **Step 3: Commit**

```bash
git add coverage_config.py
git commit -m "fix(coverage): update MI manifest to active for 6 health sources (NES-297)"
```

---

## Task 5: Verify locally (no spatial.db needed)

**Files:** None (read-only verification)

- [ ] **Step 1: Run CI scoring tests**

```bash
cd /Users/jeremybrowning/NestCheck && make test-scoring
```

Expected: PASS — no scoring logic changed.

- [ ] **Step 2: Verify startup_ingest.py imports cleanly**

```bash
cd /Users/jeremybrowning/NestCheck && python -c "from startup_ingest import _missing_states, _missing_states_abbr, _missing_states_fips, _ust_missing_states; print('All imports OK')"
```

Expected: `All imports OK`

- [ ] **Step 3: Verify ingest_fra.py imports cleanly**

```bash
cd /Users/jeremybrowning/NestCheck && python -c "from scripts.ingest_fra import ingest; print('FRA ingest OK')"
```

Expected: `FRA ingest OK`

- [ ] **Step 4: Verify `_missing_states()` returns all states when table doesn't exist**

```bash
cd /Users/jeremybrowning/NestCheck && python -c "
from startup_ingest import _missing_states_abbr, TARGET_STATES
result = _missing_states_abbr('/nonexistent/path.db', 'facilities_tri')
assert set(result) == set(TARGET_STATES.keys()), f'Expected all states, got {result}'
print(f'Correctly returns all {len(result)} states for missing DB')
"
```

Expected: `Correctly returns all 8 states for missing DB`

- [ ] **Step 5: Verify `_ust_missing_states()` still works via delegation**

```bash
cd /Users/jeremybrowning/NestCheck && python -c "
from startup_ingest import _ust_missing_states
result = _ust_missing_states('/nonexistent/path.db')
assert len(result) == 8, f'Expected 8 states, got {len(result)}'
print(f'UST delegation OK: {result}')
"
```

Expected: `UST delegation OK: ['NY', 'NJ', 'CT', 'MI', 'CA', 'TX', 'FL', 'IL']`

---

## Task 6: CLAUDE.md update

**Files:**
- Modify: `NestCheck/.claude/CLAUDE.md`

- [ ] **Step 1: Add pattern to Spatial Ingest section**

Add after the existing `_ust_missing_states` documentation:

```
- **Per-state missing detection is required for all multi-state tables** (NES-297): When adding a new state to `TARGET_STATES`, all state-filtered ingest paths must detect the new state's absence and trigger re-ingestion. Use `_missing_states_abbr()` for tables with 2-letter `$.state` in metadata, `_missing_states_fips()` for FIPS-prefix tables, or the generic `_missing_states()` with a custom SQL expression. HPMS is the only incremental source (re-ingests only missing states); all others re-ingest all states due to DROP TABLE. Follow-up: convert DROP TABLE scripts to incremental (per-state DELETE + INSERT) for efficient expansion.
```

- [ ] **Step 2: Update Decision Log**

Add entry:
```
| 2026-03 | Per-state missing detection for all ingest sources (NES-297) | `_table_has_data()` was skipping ingestion when tri-state data existed, leaving MI with 0 rows in 6/8 federal sources. Generic `_missing_states()` + convenience wrappers replace it. Option A (re-ingest all states) chosen over Option B (incremental) for speed — re-fetch cost is negligible at current scale. FRA got `stateab` in metadata to enable detection. |
```

- [ ] **Step 3: Commit**

```bash
git add .claude/CLAUDE.md
git commit -m "docs: add per-state missing detection pattern to CLAUDE.md (NES-297)"
```
