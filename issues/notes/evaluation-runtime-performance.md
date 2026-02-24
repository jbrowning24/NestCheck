# Performance: Reduce evaluation runtime (~11.5 min / 572 API calls)

## TL;DR

Evaluation completes end-to-end (snapshot created, results shown) but takes **~686 seconds (~11.5 min)** and **572 API calls**. That runtime is not viable for users. Goal: bring runtime down to an acceptable level through batching, caching, parallelism, or fewer calls—without changing correctness.

## Current state

- Full evaluation runs to completion; snapshot and results are correct.
- **Runtime:** ~686 seconds (~11.5 min).
- **API volume:** 572 calls (Google Maps, Overpass, Walk Score, etc.).
- Async queue (see `issues/async-evaluation-queue-PLAN.md`) avoids client timeouts but does not reduce server-side work.

## Expected outcome

- **Ideal:** Under 30 seconds
- **Acceptable for launch:** Under 2 minutes
- **Dealbreaker:** 10+ minutes (current state)

Fewer and/or faster API calls where possible (batching, caching, parallel requests, eliminating redundant calls).

## Initial hunches / attack plan

### Quick wins (do first)
1. **Parallelize `walking_time` calls** — 65+ sequential calls at ~80ms each = ~5s serial latency. Use `concurrent.futures` or `asyncio`.
2. **Batch with Distance Matrix API** — Google Maps Distance Matrix handles multiple origins/destinations per call. Replace 65 individual calls with 1-2 batched calls.

### Medium effort
3. **Reduce scope** — Do we need walking time to 65 green spaces? Filter to top 10 closest by straight-line distance first, then fetch walking times only for those.
4. **Batch Overpass queries** — 40+ individual `osm_enrich_query` calls at 1-5s each. Combine into fewer, larger queries.

### Larger refactors
5. **Caching layer** — Nearby addresses share many green spaces / roads / POIs. Redis or in-memory LRU could help. Adds infra complexity.

**Recommendation:** Tackle #1 and #2 first. Could cut 5+ minutes alone. Reassess after.

---

## Implementation progress

**Overall: 100%** (all steps done + peer review fixes applied)

| Step | Status | Notes |
|------|--------|--------|
| 1. Batch Distance Matrix (walking_times_batch) | 🟩 Done | Added to GoogleMapsClient; chunks of 25 destinations |
| 2. Use batch in green_space find_green_spaces | 🟩 Done | Replace N calls with ceil(N/25) calls; fallback for mocks |
| 3. Reduce scope (top N by straight-line) | 🟩 Done | Sort by straight-line distance, cap at MAX_PLACES_FOR_WALK_TIMES (50) in green_space |
| 4. Parallelize / batch elsewhere | 🟩 Done | _walking_times_batch helper; neighborhood, childcare, schools, transit, green_spaces, third place, provisioning, fitness all use batch |
| 5. Peer review fixes | 🟩 Done | See below |

### Peer review fixes (step 5)

| Fix | Status | Details |
|-----|--------|---------|
| Filter cached 9999 walk times | 🟩 Done | `green_space.py:367` — cache-hit path now filters `walk_time == 9999` same as batch/fallback paths |
| Batch response length guard | 🟩 Done | `green_space.py:377` — if `walking_times_batch` returns wrong count, treat all as 9999 |
| Test: cached 9999 regression | 🟩 Done | `test_green_space.py:TestBatchWalkTimeBehavior.test_cached_9999_filtered_on_second_call` |
| Test: batch length mismatch | 🟩 Done | `test_green_space.py:TestBatchWalkTimeBehavior.test_batch_response_length_mismatch_treated_as_failure` |

**Tests: 44/44 passing** (29 green_space + 15 transit_access)

## Relevant files

- `property_evaluator.py` – evaluation stages, API clients (Maps, Overpass, Walk Score), request logic
- `worker.py` – invokes evaluator; may be touchpoint for parallelism/batching
- `nc_trace.py` – `record_api_call`; useful for measuring before/after

## Type / priority / effort

| Label   | Value   |
|--------|---------|
| Type   | **improvement** (performance) |
| Priority | **high** (blocks viable UX) |
| Effort | **large** (investigation + batching/caching/parallelism work) |

## Notes / risks

- This is a **performance optimization project**, not a bug fix. Behavior is correct; only latency and API volume need improvement.
- Possible levers: parallelize independent stages/calls, cache repeated or stable data, batch similar requests, reduce Overpass/Maps call count per property.
- Changing call patterns may affect rate limits or costs (Maps/Overpass); validate after changes.

---

## Linear

**Add to Linear:** [Open in Linear (linear.new)](https://linear.new?title=Performance%3A+Reduce+evaluation+runtime+%28~11.5+min+%2F+572+API+calls%29&description=**Type:**+improvement+%7C+**Priority:**+high+%7C+**Effort:**+large%0A%0A**TL;DR**%0AEvaluation+completes+end-to-end+but+takes+~686s+%28~11.5+min%29+and+572+API+calls.+Runtime+is+not+viable+for+users.+Goal%3A+reduce+runtime+via+batching%2C+caching%2C+parallelism%2C+fewer+calls.%0A%0A**Current+state**%0A-Full+evaluation+runs+to+completion%3B+snapshot+and+results+correct.%0A-Runtime+~686s.+API+volume+572+calls.+Async+queue+avoids+client+timeouts+but+does+not+reduce+server-side+work.%0A%0A**Expected**%0A-Runtime+reduced+to+viable+UX+%28target+TBD%2C+e.g.+under+2+min%29.%0A-Fewer+or+faster+API+calls+where+possible.%0A%0A**Relevant+files**%0A-property_evaluator.py%2C+worker.py%2C+nc_trace.py%0A%0A**Notes**%0A-Performance+optimization+project%2C+not+bug+fix.+Levers%3A+parallelize%2C+cache%2C+batch.+Validate+rate+limits+and+costs+after+changes.&priority=high)

---

## Discovery prompt (for /explore phase)

Audit performance bottlenecks in the property evaluation pipeline. Focus on `green_escape` stage (~10 min, 190+ API calls).

**Questions to answer:**

1. **`green_space.py`** (if exists) or relevant module:
   - Entry point for green_escape evaluation?
   - How are green spaces discovered? (API, radius, filters)
   - Walking times: one call per space or batched?
   - Sequential vs parallel?
   - Overpass query count and why?

2. **`property_evaluator.py`:**
   - How does green_escape get invoked?
   - Any caching layer?
   - Configurable params (radius, max results) to reduce calls?

3. **API utilities:**
   - Where are Google Maps calls made?
   - Where are Overpass calls made?
   - Any batching logic (Distance Matrix) already?

**Return structured summary:**
```
## Entry Points
- green_escape stage entry: [file:function]

## API Call Patterns
- Walking time calls: [sequential/parallel], [count], [file:function]
- Overpass calls: [sequential/parallel], [count], [file:function]

## Current Bottlenecks
1. [description] - [file:line]

## Quick Wins
- [suggestion]

## Larger Refactors
- [suggestion]

## Relevant Config/Constants
- [variable]: [value] - [file:line]
```
