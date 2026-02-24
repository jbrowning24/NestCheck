# Expand Your Neighborhood Insight to All Four Categories (NES-37)

**Overall Progress:** `85%` · **Status:** Commit 2 code complete — needs verification
**Last updated:** 2026-02-12
**Depends on:** NES-34 (fixed in commit 1 of this branch)

## TLDR
The `_insight_neighborhood()` insight covers only coffee/grocery/fitness. Add parks as a 4th dimension so the top-of-section paragraph synthesizes all four categories the user sees in the place cards. Also fix the NES-34 duplicate-label bug and harden all branch copy to generate from the `dims` dict instead of hardcoded strings. Two commits, one branch, single file change (`app.py`).

## Critical Decisions
- **Option A chosen** — single richer paragraph at top, no per-category micro-insights
- **Parks data from `neighborhood_places["parks"]`** — consistent with coffee/grocery/fitness; save `green_escape` richness for the dedicated Parks section
- **Keep `_insight_parks()` as-is** — neighborhood paragraph is orientation, dedicated section goes deeper
- **NES-34 fix first** — separate commit, same branch

## Commit 1 — NES-34: Harden `_insight_neighborhood()` copy generation

### What's wrong
Two branches in `_insight_neighborhood()` use hardcoded dimension lists instead of generating from `dims`:

| Branch | Lines | Problem |
|---|---|---|
| All weak | 398-409 | Hardcoded `"grocery stores, cafés, or fitness options"` and `"grocery, coffee, and fitness"` |
| All middling | 464-469 | Hardcoded `"daily errands"` prose with no dim names — acceptable today but won't scale to 4 dims |

Additionally, the "one standout, rest middling" branch (434-443) silently drops any 2nd strong dim — if 2 dims score ≥ 7 and 1 is middling, only the top strong dim and the middling dim are mentioned.

### Tasks

- [x] 🟩 **1a: Fix "all weak" branch — generate dim names from `dims` dict**
  - Replaced hardcoded strings with `_join_labels()` using "or" for nothing-found, "and" for found-but-far
  - Keep the "nothing found" vs "found but far" distinction

- [x] 🟩 **1b: Fix "one standout" branch — handle 2+ strong dims**
  - Added multi-strong path: mentions additional strong dims as "also close by", then middling as "reasonable but not as close"
  - Single-strong path unchanged, now uses `_join_labels()` for middling list

- [x] 🟩 **1c: Fix "all middling" branch — generate from dims**
  - Replaced static prose with `_join_labels()` so it adapts to any number of dims

- [x] 🟩 **1d: Audit remaining branches**
  - "All strong": updated to `len(dims)` + `_join_labels()` (was using `" and ".join`)
  - "Mixed": already dynamic — no changes needed
  - "No strong + middling/weak": already dynamic — no changes needed

- [x] 🟩 **1e: `_join_labels()` helper added** (line 337-347)
  - Oxford comma for 3+ items, plain conjunction for 2, passthrough for 1
  - Configurable conjunction ("and" default, "or" for the nothing-found variant)

## Commit 2 — NES-37: Add parks as 4th dimension

### What changes

- [x] 🟩 **2a: Add parks to the `dims` dict (lines 379-384)**
  - Added `"parks"` key: `label` = `"parks"`, `label_plural` = `"parks and green spaces"`
  - `places` from `neighborhood.get("parks")`, `score` from `tier2["Parks & Green Space"]`

- [x] 🟩 **2b: Update all branch thresholds that assume 3 dimensions** *(done in commit 1)*
  - `len(strong) == 3` → `len(strong) == len(dims)`
  - `len(weak) == 3` → `len(weak) == len(dims)`
  - `len(middling) == 3` → `len(middling) == len(dims)`

- [x] 🟩 **2c: Review and adjust copy for natural 4-dim phrasing**
  - All 6 branches traced with 4 dims — all produce natural English
  - Oxford comma in `_join_labels()` correctly handles "parks and green spaces" without double-and
  - No changes needed to any branch logic or `_join_labels()`

- [x] 🟩 **2d: Verify `generate_insights()` — no change needed**
  - `neighborhood` dict already includes `"parks"` key, passed through unchanged
  - `_insight_parks()` untouched — continues to use `green_escape` for the dedicated section

- [x] 🟩 **2e: Write a natural-English join helper** *(done in commit 1)*
  - `_join_labels(items, conjunction="and")` — Oxford comma for 3+, plain conjunction for 2

## Verification

- [x] 🟩 **3a: Trace through all 6 branches with 4 dims**
  - All strong: 1 lead + 3 others with Oxford comma ✓
  - All weak (nothing found): 4 labels joined with "or" ✓
  - All weak (found but far): 4 labels joined with "and" ✓
  - Mixed: lead + worst contrast, extra strong mentioned ✓
  - Strong + middling: lead + rest as "reasonable but not as close" ✓
  - All middling: 4 labels in generic prose ✓

- [ ] 🟥 **3b: Test with a real snapshot**
  - Load an existing snapshot via `/s/{id}` and confirm the insight now mentions parks where relevant

## Files Changed
- `app.py` — `_insight_neighborhood()` function only (lines ~337-471)

## Out of Scope
- No template changes (Option A = single paragraph in existing slot)
- No changes to `_insight_parks()` or `_insight_getting_around()`
- No new API calls
- No changes to `property_evaluator.py`
