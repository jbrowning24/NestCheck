# NES-34: Fix Duplicate Grocery Reference in Neighborhood Insight

**Overall Progress:** `100%`

## TLDR
`_insight_neighborhood()` in `app.py` can mention the same dimension (e.g. "grocery") in both the lead sentence and the "others" sentence. Fix the primary bug in the "one standout, rest middling" branch, add defensive filtering to all other branches that pick a lead + others, and add unit tests covering every branch.

## Critical Decisions
- **Keep phrasing simple:** When 2+ dims are strong, list all non-lead dims with the existing "reasonable but not as close" wording. No second copy variant for this edge case.
- **Defensive filtering everywhere:** Apply lead-exclusion filtering to all branches, not just the broken one, so future classification changes can't reintroduce copy collisions.
- **New test file:** No test infrastructure exists. Create `tests/test_insights.py` from scratch.

## Tasks

- [x] 🟩 **Step 1: Fix the primary bug — "one standout, rest middling" branch**
  - [x] 🟩 Build `rest` from `strong[1:] + middling` instead of just `middling`
  - [x] 🟩 Build `other_clause` from `rest`
  - [x] 🟩 Simplified from overcomplicated two-path structure to single clean path

- [x] 🟩 **Step 2: Defensive filtering on remaining branches**
  - [x] 🟩 **"All strong":** Already uses `strong[1:]` — verified, no change needed
  - [x] 🟩 **"All weak":** No lead/others pattern — verified, no change needed
  - [x] 🟩 **"Mixed: strong and weak":** Added `other_weak = [d for d in weak if d is not lead]` defensive filter
  - [x] 🟩 **"No strong, middling + weak":** Added `other_weak = [d for d in weak if d is not ok]` with `None` guard (no fallback to unfiltered list)
  - [x] 🟩 **"All middling":** No lead/others pattern — verified, no change needed

- [x] 🟩 **Step 3: Add unit tests — `tests/test_insights.py`**
  - [x] 🟩 Created `tests/` dir, `tests/__init__.py`, and `tests/test_insights.py`
  - [x] 🟩 Built `_build_inputs()` helper for synthetic neighborhood/tier2 dicts (4 dims incl. parks)
  - [x] 🟩 18 tests across 8 test classes — all passing
  - [x] 🟩 Run tests, confirmed all 18 pass

- [x] 🟩 **Step 4: Peer review fixes**
  - [x] 🟩 Added parks dimension to `_build_inputs()` helper — tests now match 4-dim production code
  - [x] 🟩 Fixed defensive filter fallback in "no strong, middling + weak" branch — `None` guard instead of `weak[0]`
  - [x] 🟩 Tightened vacuous assertion in `TestAllStrong::test_no_duplicate_labels` — structural split on em-dash
  - [x] 🟩 Tightened imprecise assertion in `TestNoStrongMiddlingAndWeak::test_ok_and_weakness_mentioned` — assert grocery directly
  - [x] 🟩 Removed unused `import pytest`

## Files Changed
| File | Action |
|------|--------|
| `app.py` | Edited `_insight_neighborhood()` — 3 defensive filter changes |
| `tests/__init__.py` | Created (empty package init) |
| `tests/test_insights.py` | Created (18 tests, 4-dim coverage) |

## Status Report
- **Files changed:** `app.py`, `tests/__init__.py`, `tests/test_insights.py`
- **Functions modified:** `_insight_neighborhood()` in `app.py`
- **Branches patched:**
  - "Strong dims with rest middling" — primary fix: `rest = strong[1:] + middling`
  - "Mixed: strong and weak" — defensive filter on `weak` excluding `lead`
  - "No strong, middling + weak" — defensive filter on `weak` excluding `ok`, with `None` guard
- **Tests added (18 total):**
  | Test | Branch |
  |------|--------|
  | `TestAllStrong::test_output_mentions_lead_and_others` | All strong (4 dims) |
  | `TestAllStrong::test_no_duplicate_labels` | All strong (4 dims) |
  | `TestAllWeakWithPlaces::test_driving_phrasing` | All weak (4 dims, with places) |
  | `TestAllWeakNoPlaces::test_didnt_find_phrasing` | All weak (4 dims, no places) |
  | `TestOneStandoutRestMiddling::test_lead_appears_once` | 1 strong + 3 middling |
  | `TestOneStandoutRestMiddling::test_other_dims_present` | 1 strong + 3 middling |
  | `TestOneStandoutRestMiddling::test_lead_place_name_in_output` | 1 strong + 3 middling |
  | `TestTwoStrongRestMiddling::test_no_dropped_dims` | 2 strong + 2 middling |
  | `TestTwoStrongRestMiddling::test_lead_not_in_others` | 2 strong + 2 middling |
  | `TestMixedStrongAndWeak::test_strength_and_weakness_mentioned` | Strong + weak |
  | `TestMixedStrongAndWeak::test_no_duplicate_dim_in_both_sentences` | Strong + weak |
  | `TestMixedStrongAndWeak::test_weak_with_no_places` | Strong + weak (no places) |
  | `TestNoStrongMiddlingAndWeak::test_ok_and_weakness_mentioned` | Middling + weak |
  | `TestNoStrongMiddlingAndWeak::test_weak_no_places` | Middling + weak (no places) |
  | `TestAllMiddling::test_generic_phrasing` | All middling (4 dims) |
  | `TestAllMiddling::test_mentions_all_labels` | All middling (4 dims) |
  | `TestEdgeCases::test_empty_neighborhood_returns_none` | Empty input |
  | `TestEdgeCases::test_none_neighborhood_returns_none` | None input |
- **What was NOT tested:** Integration with real evaluation data / live API responses. Tests use synthetic dicts only.
