# Phase 2 Refinements: Proximity Band Presentation

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** 2026-02-09

## TLDR
The Phase 2 proximity-band infrastructure is already in place (committed in `c196735`). This plan covers the remaining delta between the current implementation and the spec: updating thresholds, making explanations band-aware with factual tone, updating CSS to spec colors, and aligning template logic.

## Critical Decisions
- **Decision 1:** `distance_ft` already on `Tier1Check` — no dataclass changes needed. Gas station populates it; highway/high-volume road don't (Overpass radius query). This is unchanged.
- **Decision 2:** `_proximity_explanation()` must accept `band` parameter to generate different text per VERY_CLOSE/NOTABLE/NEUTRAL. Current version generates one explanation per check regardless of band.
- **Decision 3:** Highway/high-volume road checks lack `distance_ft`, so their explanations use road names (from `check.details`) instead of `[X] ft` distance. The spec's `[X] ft` templates apply only to gas station checks.
- **Decision 4:** CSS moves from green/yellow/orange palette to gray/amber/red per spec — neutral becomes visually quiet (gray) rather than positive (green).

## Tasks:

- [x] 🟩 **Step 1: Update `PROXIMITY_THRESHOLDS` to spec values**
  - [x] 🟩 Change Gas station `very_close` from 300 → 200 (keep `notable` at 500)
  - [x] 🟩 Change Highway `very_close` from 300 → 500, `notable` from 500 → 1000
  - [x] 🟩 Change High-volume road `very_close` from 300 → 200 (keep `notable` at 500)

- [x] 🟩 **Step 2: Rewrite `_proximity_explanation()` to be band-aware**
  - [x] 🟩 Add `band: str` parameter to function signature
  - [x] 🟩 Gas station VERY_CLOSE: "This address is [X] ft from a gas station. At this distance, fuel odor may be noticeable and studies have measured elevated benzene levels."
  - [x] 🟩 Gas station NOTABLE: "A gas station is [X] ft from this address. At this distance, air quality impact is typically minimal but may be detectable in certain wind conditions."
  - [x] 🟩 Gas station NEUTRAL (PASS): "Nearest gas station is [X] ft away — outside the typical impact zone."
  - [x] 🟩 Highway VERY_CLOSE: "A highway is [X] ft from this address. At this distance, road noise and particulate matter (PM2.5) levels are typically elevated." (use road names when no distance_ft)
  - [x] 🟩 Highway NOTABLE: "A highway is [X] ft from this address. Some road noise may be audible, especially during peak traffic hours."
  - [x] 🟩 Highway NEUTRAL (PASS): "Nearest highway is [X] ft away — outside the typical noise and air quality impact zone."
  - [x] 🟩 High-volume road: same pattern as highway with road-specific wording
  - [x] 🟩 UNKNOWN: "We could not automatically verify [factor] proximity. Check Google Maps satellite view to assess this yourself."
  - [x] 🟩 Update call site in `present_checks()` to pass `band` argument

- [x] 🟩 **Step 3: Generate explanation for PASS/NEUTRAL gas station checks**
  - [x] 🟩 Currently `_proximity_explanation()` returns empty string for PASS. Spec wants "Nearest gas station is [X] ft away — outside the typical impact zone." when distance is available
  - [x] 🟩 Template already hides explanation for CLEAR items, so this only surfaces if template logic changes (see Step 5)

- [x] 🟩 **Step 4: Update CSS to spec colors and sizing**
  - [x] 🟩 In `index.html`: `.proximity-neutral` → `background: #f8f9fa; border-left: 3px solid #e2e8f0;` (gray, not green)
  - [x] 🟩 In `index.html`: `.proximity-notable` → `background: #fffbeb; border-left: 3px solid #f59e0b;` (amber)
  - [x] 🟩 In `index.html`: `.proximity-very_close` → `background: #fef2f2; border-left: 3px solid #ef4444;` (red, not orange)
  - [x] 🟩 In `index.html`: `.proximity-item` → `padding: 12px 16px; border-radius: 8px; margin-bottom: 8px;` (border-left base color removed — each band sets its own)
  - [x] 🟩 In `index.html`: `.proximity-name` → `color: #1e293b;`
  - [x] 🟩 In `index.html`: `.proximity-detail` → `color: #64748b; font-size: 0.9em; line-height: 1.5;`
  - [x] 🟩 Mirror all CSS changes in `snapshot.html`

- [x] 🟩 **Step 5: Align template detail display logic with spec**
  - [x] 🟩 Current: `{% if pc.result_type != "CLEAR" and pc.explanation %}` — hides detail for all CLEAR items
  - [x] 🟩 Spec: `{% if pc.proximity_band != 'NEUTRAL' or pc.result_type != 'CLEAR' %}` — shows detail for non-NEUTRAL bands even if CLEAR
  - [x] 🟩 Update `_result_sections.html` to match spec condition

- [x] 🟩 **Step 6: Verify backward compatibility and no evaluation logic changes**
  - [x] 🟩 Old snapshots without `proximity_band` still fall through to legacy rendering (already handled)
  - [x] 🟩 Confirm check functions, scoring, and API calls are untouched
