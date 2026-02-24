# Deduplicate API calls across evaluation pipeline (~162 → ~85-90)

## TL;DR

Full API audit revealed **~162 typical HTTP requests per evaluation** (not 500+ as previously estimated). Seven concrete deduplication/batching fixes can cut this nearly in half to **~85-90 calls** with zero feature loss. This is the successor to the batching work in `evaluation-runtime-performance.md` (which reduced 572 → ~162).

## Current state

- Evaluation makes ~162 external HTTP requests per address (typical), up to ~259 worst case.
- Breakdown by service: ~112 Google Maps, ~22 Overpass, 3 Walk Score, ~25 website fetches.
- Multiple modules independently search for overlapping data (parks, transit, provisioning, third places).
- Walk Score is called 3 times for data available in 1 call.
- `find_primary_transit()` and `determine_major_hub()` each run twice (urban_access stage + Tier 2 scoring).
- Overpass park enrichment fires 1 POST per park (15–50 sequential calls to a rate-limited public API).

## Expected outcome

- **~85-90 calls per eval** (from ~162) — nearly 50% reduction.
- No feature loss or scoring changes.
- Reduced risk of Overpass rate-limit bans (from ~22 calls to ~4).
- Faster wall-clock time (fewer sequential HTTP round-trips).

## Fix plan — ordered by effort

| # | Fix | Calls saved | Effort | Files |
|---|-----|-------------|--------|-------|
| 1 | **Deduplicate Walk Score (3→1)** — `get_walk_scores()` already returns walk + transit + bike. Remove `get_bike_score()` and `get_transit_score()` calls; extract their data from the single response. | 2 | Trivial | `property_evaluator.py` |
| 2 | **Cache `find_primary_transit()` result** — Called in `get_urban_access_profile()` (line ~1875) and again in `score_transit_access()` (line ~2572). Pass the result from the first call into the second. | 5–6 | Easy | `property_evaluator.py` |
| 3 | **Cache `determine_major_hub()` result** — Same pattern: called in `get_urban_access_profile()` (line ~1877) and re-called in `score_transit_access()` (line ~2581). Pass result downstream. | 1–3 | Easy | `property_evaluator.py` |
| 4 | **Merge Overpass road checks (2→1)** — `check_highways()` and `check_high_volume_roads()` both call `overpass.get_nearby_roads()` with the same 200m radius and overlapping Overpass queries. Fetch once, filter twice. | 1–2 | Easy | `property_evaluator.py` |
| 5 | **Batch Overpass park enrichment (N→1)** — `enrich_from_osm()` in `green_space.py` fires 1 POST per park. Overpass supports `(around:...)` with union queries. Batch all parks into a single query, then partition results by proximity. | ~49 (15–49) | Medium | `green_space.py` |
| 6 | **Reuse neighborhood snapshot downstream** — `get_neighborhood_snapshot()` searches for grocery_store, supermarket, cafe, bakery, park, school — the same types that `score_third_place_access()`, `score_provisioning_access()`, and green_spaces stages search independently. Pass results down to avoid re-fetching. | ~10 | Medium | `property_evaluator.py` |
| 7 | **Reuse `green_spaces` results in `green_escape`** — Both `evaluate_green_spaces()` (7 Places Nearby + DM) and `evaluate_green_escape()` (4–8 Places Nearby + 7–14 Text Search + DM) search for overlapping park data. Feed the first stage's results into the second to avoid redundant discovery. | ~8-9 | Medium | `property_evaluator.py`, `green_space.py` |

**Total savings: ~77 calls (162 → ~85)**

## Additional findings from audit

### Rate limiting risks
- **Overpass (OSM)**: Public API recommends max 1 req/s. Current eval fires 17–52 calls back-to-back with no backoff or retry-on-429. Fix #5 addresses this directly.
- **Google Maps**: No retry-on-429 logic. Concurrent evaluations could hit per-second QPS limits.
- **Walk Score**: Free tier is 5,000 calls/day. At 3 calls/eval → 1,667 evals/day ceiling. Fix #1 raises that to 5,000 evals/day.

### Error handling gaps
- `green_space.py` `_overpass_query()` (line ~447): catches all exceptions, returns empty data, no logging.
- Many `places_nearby`/`text_search` calls wrapped in bare `except Exception: continue` — errors silently swallowed.
- `fetch_website_text()` (line ~1430): silently swallows all exceptions on school website scraping.

### No hardcoded API keys
Both `GOOGLE_MAPS_API_KEY` and `WALKSCORE_API_KEY` are loaded from env vars. No secrets in source.

## Relevant files

- `property_evaluator.py` — orchestration, Google Maps client, Walk Score calls, Tier 1/2 scoring, neighborhood snapshot
- `green_space.py` — green escape engine, Overpass enrichment, park discovery
- `urban_access.py` — UrbanAccessEngine (hub reachability, geocode caching)
- `nc_trace.py` — API call tracing (use to verify before/after counts)

## Type / priority / effort

| Label    | Value |
|----------|-------|
| Type     | **improvement** (performance, cost) |
| Priority | **high** (API cost + Overpass rate-limit risk) |
| Effort   | **medium** (7 discrete fixes, most easy/trivial, 3 medium) |

## Notes / risks

- Fixes 1–4 are safe, isolated changes with no cross-module impact.
- Fixes 5–7 touch data flow between modules — test with `nc_trace` to verify call counts match expected.
- Overpass batching (#5) may need careful query construction to avoid timeouts on large union queries (>50 parks in a 5km radius). Consider chunking into groups of 10–15 parks per query.
- The `schools` stage (~25–45 Place Details + ~20–40 website fetches) is expensive but not redundant — those calls serve unique per-school filtering logic. Optimization there is a separate effort (parallelism, not deduplication).

---

## Discovery source

Full API audit performed across all modules. Call counts verified by tracing code paths in `evaluate_property()` through each stage. See conversation for detailed per-stage breakdown tables.
