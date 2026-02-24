# Parallelize Independent Evaluation Stages

**Overall Progress:** `100%` · **Status:** Complete

## TLDR
Run the 6 independent data-collection stages (walk_scores, neighborhood, schools, urban_access, transit_access, green_escape) concurrently after geocode completes, using `concurrent.futures.ThreadPoolExecutor`. Tier 1 checks and Tier 2 scoring remain sequential. Target: ~25–35s wall-clock (down from 60–90s).

## Critical Decisions

- **ThreadPoolExecutor over asyncio**: All stages are I/O-bound HTTP calls. Threads are the right primitive — no need to rewrite call sites to async. Each stage already uses `requests.Session` which releases the GIL during I/O.
- **Batch A only (data collection)**: Tier 2 scoring stays sequential. Dependencies are tangled (score_park_access needs green_escape, score_third_place needs neighborhood, etc.). Parallelizing Tier 2 risks silent scoring bugs. Can revisit in a follow-up.
- **nc_trace is thread-local — must propagate explicitly**: `get_trace()` uses `threading.local()` (nc_trace.py:244). Child threads won't see the parent's TraceContext. Fix: call `set_trace(parent_ctx)` at the start of each thread worker. The TraceContext lists (`.api_calls`, `.stages`) will receive concurrent appends — Python list `.append()` is GIL-atomic, so this is safe without a lock.
- **Single combined on_stage call for parallel batch**: Fire `on_stage("analyzing")` once before the parallel batch. Individual stages don't call `on_stage` during parallel execution (they still call `_timed_stage` for trace recording). After the batch, resume sequential `on_stage` calls for tier1_checks and scoring stages.
- **green_space._cache needs a lock**: Module-level `_cache` dict in green_space.py gets concurrent reads/writes from parallel stages (green_escape + potentially neighborhood). Add a `threading.Lock` around `_cached_get`/`_cached_set`.
- **UrbanAccessEngine._cache needs a lock**: Class-level `_cache` dict gets concurrent reads/writes. Add a `threading.Lock` around cache access in `_get_duration`.
- **GoogleMapsClient.session is per-instance**: Each `GoogleMapsClient` created in `evaluate_property()` has its own `requests.Session`. `requests.Session` is **not** thread-safe. Fix: create a separate `GoogleMapsClient` per thread, or use `requests.get()` directly (no session reuse). Simplest: instantiate a new `GoogleMapsClient(api_key)` inside each thread's wrapper function.
- **OverpassClient.session is per-instance**: Same concern. green_space.py already creates a local `requests.Session()` per Overpass call (line 458), so it's already safe. The `OverpassClient` in property_evaluator.py is only used for tier1_checks (sequential) — no change needed.

## Tasks

- [x] 🟩 **Step 1: Add thread-safe caching to green_space.py**
  - [x] 🟩 Add a module-level `threading.Lock` (`_cache_lock`)
  - [x] 🟩 Wrap `_cached_get()` and `_cached_set()` with the lock

- [x] 🟩 **Step 2: Add thread-safe caching to urban_access.py**
  - [x] 🟩 Add a class-level `threading.Lock` to `UrbanAccessEngine`
  - [x] 🟩 Wrap `_cache` reads/writes in `_geocode_cached` and `_travel_time` with the lock

- [x] 🟩 **Step 3: Parallelize Batch A in evaluate_property()**
  - [x] 🟩 Add `from concurrent.futures import ThreadPoolExecutor, as_completed` import
  - [x] 🟩 Add `from nc_trace import get_trace, set_trace` import (set_trace needed for thread propagation)
  - [x] 🟩 Create `_threaded_stage` wrapper: propagates trace, creates fresh GoogleMapsClient, swaps maps arg, calls `_timed_stage`
  - [x] 🟩 Create `_timed_stage_in_thread` helper for stages without a maps client (walk_scores)
  - [x] 🟩 Replace 6 sequential try/except blocks with `ThreadPoolExecutor(max_workers=6)` block
  - [x] 🟩 Submit each stage as a future; map futures to stage names
  - [x] 🟩 Collect results via iteration; assign each to correct `result.*` field
  - [x] 🟩 Individual try/except per `future.result()` (graceful degradation preserved)
  - [x] 🟩 Fire `on_stage("analyzing")` once before the parallel batch

- [x] 🟩 **Step 4: Handle walk_scores result assignment**
  - [x] 🟩 Extracted `_assign_walk_scores()` helper for the multi-field unpacking

- [x] 🟩 **Step 5: Handle schools conditional (ENABLE_SCHOOLS)**
  - [x] 🟩 Schools future only submitted when `ENABLE_SCHOOLS` is True

- [x] 🟩 **Step 6: Verify nc_trace cross-thread recording**
  - [x] 🟩 `set_trace(parent_ctx)` in child threads → `get_trace()` returns shared TraceContext ✓
  - [x] 🟩 `trace.record_api_call()` and `trace.record_stage()` append to shared lists — GIL-atomic ✓
  - [x] 🟩 `_current_stage` race accepted: parallel threads overwrite the shared field, so per-stage API attribution in trace may drift. Total counts remain correct. Trace is debugging-only — acceptable trade-off per plan decision.

- [x] 🟩 **Step 7: Verify no changes to Tier 1, Tier 2, Tier 3**
  - [x] 🟩 Tier 1 checks remain sequential after the parallel batch (unchanged)
  - [x] 🟩 Tier 2 scoring remains sequential (unchanged)
  - [x] 🟩 Tier 3 bonuses remain sequential (unchanged)
  - [x] 🟩 No scoring logic or API patterns changed

- [x] 🟩 **Step 8: Test with existing test suite**
  - [x] 🟩 59/59 core tests pass (green_space, transit_access, urban_access) — zero regressions
  - [x] 🟩 All imports resolve correctly; locks instantiated as expected
  - [x] 🟩 Pre-existing failures (Flask not installed, hardcoded path) unrelated to changes
