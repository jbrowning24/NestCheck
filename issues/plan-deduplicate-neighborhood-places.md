# Deduplicate Neighborhood Places

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** 2026-02-09

## TLDR
Coffee, grocery, and fitness categories each search multiple Google Places types and `.extend()` the results together without deduplication. A place matching both types (e.g. a store tagged `supermarket` + `grocery_store`) appears twice in the card UI. Fix by deduplicating on `place_id`, matching the existing pattern used by green spaces and transit.

## Critical Decisions
- **Shared helper `_dedupe_by_place_id()`**: Avoids repeating the dedup logic in 4 locations. Simple first-wins approach (no type merging needed — scoring only cares about the place, not its full type list).
- **Dedup at collection point, not template**: Fixing upstream means scoring, walk-time batching, and display all benefit — no wasted Distance Matrix API calls on duplicates.
- **Dedup raw_places in snapshot too**: `get_neighborhood_snapshot()` stores raw results that feed into Tier 2 scoring via `pre_fetched_places`. Deduping there means the pre-fetched path is clean without needing a second dedup downstream.

## Tasks:

- [x] 🟩 **Step 1: Add `_dedupe_by_place_id()` helper**
  - [x] 🟩 Add a small private function in `property_evaluator.py` near the other helpers (around line ~2090). Signature: `_dedupe_by_place_id(places: List[Dict]) -> List[Dict]`. Uses a `seen` set on `place_id`, preserves order, returns first occurrence only.

- [x] 🟩 **Step 2: Dedup in `get_neighborhood_snapshot()`**
  - [x] 🟩 After `places.extend(...)` at line 1341, call `places = _dedupe_by_place_id(places)` before storing into `snapshot.raw_places[category]` (line 1344). This cleans the pre-fetched data that flows into Tier 2 scoring.

- [x] 🟩 **Step 3: Dedup in `score_third_place_access()` fallback path**
  - [x] 🟩 After `all_places.extend(...)` at line 2282, call `all_places = _dedupe_by_place_id(all_places)`. Only needed in the `else` branch (when `pre_fetched_places is None`) since the pre-fetched path is already deduped by Step 2.

- [x] 🟩 **Step 4: Dedup in `score_provisioning_access()` fallback path**
  - [x] 🟩 After `all_stores.extend(...)` at line 2556, call `all_stores = _dedupe_by_place_id(all_stores)`. Same reasoning as Step 3.

- [x] 🟩 **Step 5: Dedup in `score_fitness_access()`**
  - [x] 🟩 After `fitness_places.extend(yoga)` at line 2689, call `fitness_places = _dedupe_by_place_id(fitness_places)`. This function has no pre-fetched path so always needs its own dedup.

- [x] 🟩 **Step 6: Verify**
  - [x] 🟩 Syntax check passes, no linter errors, all 4 dedup call sites confirmed. Run a test evaluation to confirm no duplicate place names in the "Your Neighborhood" section.
