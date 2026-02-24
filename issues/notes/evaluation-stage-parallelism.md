# Parallelize independent evaluation stages (~60-90s → ~25-35s)

## TL;DR

All 7 dedup fixes from `api-call-deduplication.md` are implemented (call count down from ~162 to ~120 typical). The bottleneck is now **wall-clock time**: every evaluation stage runs strictly sequentially even when there are no data dependencies between them. At ~120 HTTP calls in series, typical evaluations take **60–90 seconds**. Parallelizing independent stages can cut this roughly in half.

## Current state

- All stages in `evaluate_property()` execute sequentially via `_timed_stage()`.
- No use of `concurrent.futures`, `asyncio`, or threading anywhere in the evaluation pipeline.
- Each stage blocks the next, even when the only shared dependency is `lat`/`lng` from geocoding.
- Typical wall-clock time: **60–90 seconds** (acceptable for launch, but not good UX).

### Stage dependency graph

```
geocode (must run first — all stages need lat/lng)
  │
  ├── walk_scores          (no further deps)
  ├── neighborhood ──────► score_third_place, score_provisioning
  ├── schools              (no further deps)
  ├── urban_access ──┬───► score_transit_access
  ├── transit_access ┘
  ├── green_escape ──────► score_park_access
  ├── tier1_checks         (no further deps)
  └── score_fitness        (no further deps)
      score_cost           (no API calls)
```

**Key insight:** After geocode completes, stages `walk_scores`, `neighborhood`, `schools`, `urban_access`, `transit_access`, `green_escape`, and `tier1_checks` can all run concurrently. Tier 2 scoring then runs as a second wave once its upstream dependencies resolve.

## Expected outcome

- **Target:** 25–35 seconds typical (down from 60–90s).
- **Mechanism:** Run independent stages concurrently using `concurrent.futures.ThreadPoolExecutor` (I/O-bound work — threads are appropriate).
- No feature loss or scoring changes.
- `nc_trace` stage timing still recorded accurately per-stage.

## Proposed approach

### Wave 1 — Concurrent enrichment (after geocode)

Run these stages in parallel:
- `walk_scores`
- `neighborhood`
- `schools`
- `urban_access`
- `transit_access`
- `green_escape`
- `tier1_checks` (Overpass roads + gas station check)

All depend only on `lat`/`lng`. Wall-clock time becomes the slowest stage (~15–25s for schools) instead of the sum of all stages (~45–60s).

### Wave 2 — Concurrent Tier 2 scoring (after Wave 1)

Run these in parallel once their inputs are ready:
- `score_park_access` (needs `green_escape_evaluation`)
- `score_third_place` (needs `neighborhood_snapshot.raw_places`)
- `score_provisioning` (needs `neighborhood_snapshot.raw_places`)
- `score_fitness` (independent)
- `score_transit_access` (needs `urban_access` + `transit_access`)
- `score_cost` (no API calls — instant)

### Implementation sketch

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def evaluate_property(listing, api_key, on_stage=None):
    maps = GoogleMapsClient(api_key)
    overpass = OverpassClient()
    lat, lng = _run_stage("geocode", maps.geocode, listing.address)
    result = EvaluationResult(listing=listing, lat=lat, lng=lng)

    # Wave 1: independent enrichment stages
    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = {
            pool.submit(_run_stage, "walk_scores", get_all_walk_scores, listing.address, lat, lng): "walk_scores",
            pool.submit(_run_stage, "neighborhood", get_neighborhood_snapshot, maps, lat, lng): "neighborhood",
            pool.submit(_run_stage, "schools", get_child_and_schooling_snapshot, maps, lat, lng): "schools",
            pool.submit(_run_stage, "urban_access", get_urban_access_profile, maps, lat, lng): "urban_access",
            pool.submit(_run_stage, "transit_access", evaluate_transit_access, maps, lat, lng): "transit_access",
            pool.submit(_run_stage, "green_escape", evaluate_green_escape, maps, lat, lng): "green_escape",
            pool.submit(_run_tier1, maps, overpass, lat, lng, listing): "tier1",
        }
        for future in as_completed(futures):
            # assign results to EvaluationResult...

    # Wave 2: Tier 2 scoring (parallel, using Wave 1 outputs)
    # ...
```

### Thread safety considerations

- `GoogleMapsClient` uses `requests.Session` internally — needs to be thread-safe or use one session per thread.
- `nc_trace` uses thread-local storage (`threading.local`) — each thread gets its own trace context. The parent trace must aggregate child-thread records after Wave 1 completes.
- `OverpassClient` uses `requests.Session` — same concern as Maps client.
- `green_space._cache` is a module-level dict — not thread-safe for concurrent writes. Needs a lock or switch to `threading.Lock`-protected access.
- `UrbanAccessEngine._cache` is a class-level dict — same concern.
- `on_stage` callback may need to be thread-safe if the consumer isn't expecting concurrent calls.

## Relevant files

- `property_evaluator.py` — `evaluate_property()` orchestration, `_timed_stage()`, all stage functions
- `green_space.py` — module-level `_cache` dict (thread safety)
- `urban_access.py` — `UrbanAccessEngine._cache` class-level dict (thread safety)
- `nc_trace.py` — thread-local trace context (needs cross-thread aggregation)
- `worker.py` — invokes `evaluate_property()`; may need adjustment for thread pool sizing

## Type / priority / effort

| Label    | Value |
|----------|-------|
| Type     | **improvement** (performance) |
| Priority | **medium** (UX improvement; current runtime is acceptable for launch) |
| Effort   | **medium** (thread pool orchestration + thread-safety audit for caches and tracing) |

## Notes / risks

- **Thread safety is the main risk.** The caches in `green_space.py` and `urban_access.py` use plain dicts. Concurrent writes from parallel stages could cause data corruption. Adding `threading.Lock` is straightforward but must be done before parallelizing.
- **`nc_trace` aggregation:** Each thread currently gets its own trace context via `threading.local`. API calls recorded in child threads won't appear in the parent trace unless explicitly merged. This needs a trace-aggregation step after each wave.
- **Google Maps API rate limits:** Running 7 stages concurrently means higher burst QPS against Google Maps. Monitor for 429s. The Maps client may need retry-on-429 logic.
- **Overpass rate limits:** The public Overpass API recommends max 1 req/s. If `tier1_checks` (roads) and `green_escape` (batch enrichment) fire Overpass queries simultaneously, that's 2+ concurrent requests. May need a shared Overpass rate limiter.
- **Worker thread pool sizing:** `worker.py` may already use threads for job processing. Nested thread pools (worker threads spawning evaluation thread pools) need careful sizing to avoid thread starvation.
- **Fallback:** If parallelism introduces instability, the sequential path should remain available as a feature flag (e.g., `PARALLEL_EVAL=false` env var).

---

## Discovery source

Identified during read-only audit of `evaluate_property()` in conversation. All 7 dedup fixes from `api-call-deduplication.md` confirmed as implemented. Zero parallelism confirmed — every stage blocks the next via synchronous `_timed_stage()` calls.
