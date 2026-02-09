# Phase 2: Factual Distance-Based Presentation

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** 2026-02-08

## TLDR
Replace PASS/FAIL/UNKNOWN icon system for health & safety checks with a factual, proximity-band presentation. Items are shown as neutral distance facts with graduated visual emphasis (VERY_CLOSE / NOTABLE / NEUTRAL) instead of judgmental pass/fail verdicts.

## Critical Decisions
- **Decision 1:** Add `distance_ft: Optional[float] = None` to `Tier1Check` dataclass — gas stations already compute distance (`check.value`), so we populate it there. Highway and high-volume road checks DON'T compute distance (Overpass radius query only), so `distance_ft` stays `None` for those. This avoids modifying evaluation logic.
- **Decision 2:** When `distance_ft` is `None` on a FAIL result (highway/high-volume road), `_proximity_band()` returns `VERY_CLOSE` — conservative default since these are confirmed within the ~656 ft search radius. Headlines and explanations use road names instead of distance when `distance_ft` is unavailable.
- **Decision 3:** Explanation text is generated dynamically in `present_checks()` (not static `CHECK_EXPLANATIONS` dict) — distance and band determine the phrasing at runtime.
- **Decision 4:** Template backward compat — check for `proximity_band` key existence; old snapshots without it fall through to existing `tier1_checks` rendering.

## Tasks:

- [x] 🟩 **Step 1: Add `distance_ft` field to `Tier1Check` dataclass**
  - [x] 🟩 Add `distance_ft: Optional[float] = None` to `Tier1Check` at [property_evaluator.py:101](property_evaluator.py#L101)
  - [x] 🟩 In `check_gas_stations()` (~line 898-909): set `distance_ft=min_distance` on both PASS and FAIL returns (value already computed)
  - [x] 🟩 No changes to `check_highways()` or `check_high_volume_roads()` — they don't compute distance

- [x] 🟩 **Step 2: Add `PROXIMITY_THRESHOLDS` constant and `_proximity_band()` function**
  - [x] 🟩 Add `PROXIMITY_THRESHOLDS` dict at module level near existing constants (~line 182)
  - [x] 🟩 Add `_proximity_band(check: Tier1Check) -> str` function after `_classify_check()` (~line 213). Logic: if check not in thresholds → `"NEUTRAL"`; if UNKNOWN result → `"NOTABLE"`; if `distance_ft` available → compare against thresholds; if `distance_ft` is None + FAIL → `"VERY_CLOSE"`; if PASS → `"NEUTRAL"`

- [x] 🟩 **Step 3: Replace static explanations with dynamic `_proximity_explanation()` helper**
  - [x] 🟩 Add `_proximity_explanation(check: Tier1Check, band: str) -> str` function that generates distance-aware factual text using the templates from the task spec
  - [x] 🟩 For gas stations: use actual `distance_ft` value in `[X] ft` placeholder
  - [x] 🟩 For highway / high-volume road (no distance): use road names from `check.details` instead of distance
  - [x] 🟩 For UNKNOWN: use "We could not automatically verify [factor] proximity..." phrasing
  - [x] 🟩 Remove safety check entries from `CHECK_EXPLANATIONS` dict (keep lifestyle entries unchanged)

- [x] 🟩 **Step 4: Rewrite `_generate_headline()` for factual framing**
  - [x] 🟩 CLEAR → `"[Display Name] — Clear"`
  - [x] 🟩 CONFIRMED_ISSUE with distance → `"[Display Name] — [X] ft"`
  - [x] 🟩 CONFIRMED_ISSUE without distance (highway/road) → `"[Display Name] — Nearby"` (since no exact ft available)
  - [x] 🟩 VERIFICATION_NEEDED → `"[Display Name] — Unverified"`
  - [x] 🟩 Signature changes to accept `proximity_band` parameter (or compute it internally)

- [x] 🟩 **Step 5: Update `present_checks()` to wire everything together**
  - [x] 🟩 Add `"proximity_band"` key to each presented check dict
  - [x] 🟩 Call `_proximity_explanation()` instead of static `CHECK_EXPLANATIONS.get()` for SAFETY checks
  - [x] 🟩 Pass band to `_generate_headline()` for SAFETY checks
  - [x] 🟩 Remove `_ACTION_HINTS` lookups for SAFETY checks (explanations are now self-contained)

- [x] 🟩 **Step 6: Update template rendering in `_result_sections.html`**
  - [x] 🟩 Replace the SAFETY check loop (lines 269-284) with proximity-band styled `<div>` elements
  - [x] 🟩 Add CSS for `.proximity-item`, `.proximity-neutral`, `.proximity-notable`, `.proximity-very_close`, `.proximity-name`, `.proximity-detail`
  - [x] 🟩 CLEAR + NEUTRAL items: show headline only (single line)
  - [x] 🟩 Non-CLEAR items: show headline + explanation
  - [x] 🟩 Remove action hint rendering for SAFETY checks
  - [x] 🟩 Add backward compat: check `pc.proximity_band is defined` — old snapshots with `presented_checks` but no `proximity_band` fall back to current rendering; very old snapshots without `presented_checks` still use `tier1_checks` fallback

- [x] 🟩 **Step 7: Verify no evaluation logic changed**
  - [x] 🟩 Confirm `check_gas_stations`, `check_highways`, `check_high_volume_roads` internal logic untouched (only `distance_ft` field added to return values in gas stations)
  - [x] 🟩 Confirm score calculation unchanged
  - [x] 🟩 Confirm `_classify_check()` unchanged
  - [x] 🟩 Confirm `generate_structured_summary()` and `generate_verdict()` still work (they read `result_type` and `category`, not `proximity_band`)
