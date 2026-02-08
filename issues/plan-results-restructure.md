# Results Page Restructure — Neighborhood Guide Layout

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** 2026-02-08

## TLDR
Extract shared result rendering into a single partial (`_result_sections.html`), reorder sections to read like a neighborhood guide instead of a technical audit, always show the score, remove listing-quality checks and jargon from the score breakdown, and drop sections that will return in later phases.

## Critical Decisions
- **Single partial, conditional rendering:** Use `{% if is_snapshot %}` inside `_result_sections.html` to handle snapshot-vs-index differences (collapsible toggles, share bar position, CTA banner) rather than two separate templates.
- **Always show score:** `show_score = True` unconditionally. The `score-failed` CSS class and red Concerns section are removed. Verdict text still signals proximity concerns via suffix.
- **Cost score removed from Tier 2:** Drops from 6 scored categories (max 60) to 5 (max 50). `tier2_max` is computed dynamically, so normalization to 100 auto-adjusts. Old snapshots that still have a "Cost" row in `tier2_scores` will still render — they just won't appear in new evaluations.
- **Backward compatibility:** Old snapshots render safely because all new section keys use `{% if ... is defined %}` / `| default(...)` guards, and old keys (`tier1_checks`, `green_escape`, etc.) are still read.

## Tasks:

- [x] 🟩 **Step 1: Create `templates/_result_sections.html` partial**
  - [x] 🟩 Extract all result rendering from `index.html` (lines 739-1283) into the new partial
  - [x] 🟩 Extract parallel result rendering from `snapshot.html` (lines 585-1090) — merge the two into one file using `{% if is_snapshot %}` for: collapsible toggles, share bar at top vs bottom, CTA banner, snapshot metadata
  - [x] 🟩 In `index.html`, replace extracted block with `{% set is_snapshot = false %}{% include '_result_sections.html' %}`
  - [x] 🟩 In `snapshot.html`, replace extracted block with `{% set is_snapshot = true %}{% include '_result_sections.html' %}`
  - [x] 🟩 Verify: partial expects `result`, `show_score`, `snapshot_id`, `is_snapshot`

- [x] 🟩 **Step 2: Reorder sections in `_result_sections.html`**
  - [x] 🟩 Section 1: Verdict card (unchanged)
  - [x] 🟩 Section 2: Neighborhood map placeholder div (`id="neighborhood-map"`)
  - [x] 🟩 Section 3: "Your Neighborhood" placeholder div
  - [x] 🟩 Section 4: Rename "Urban Access" → "Getting Around" (content identical)
  - [x] 🟩 Section 5: Rename "Green Escape" → "Parks & Green Space" (content identical)
  - [x] 🟩 Section 6: Rename "Health & Safety Checks" → "Proximity & Environment"; remove LIFESTYLE checks subsection (the W/D, central air, sqft, bedrooms, cost listing detail rows)
  - [x] 🟩 Section 7: Rename "Score Breakdown" → "How We Score"; make collapsed by default (`collapsible-body collapsed`)
  - [x] 🟩 Remove "Family & Schooling" section entirely
  - [x] 🟩 Remove "What's Missing / Needs Verification" section entirely
  - [x] 🟩 Remove "Health & Safety Concerns" conditional red-bordered section entirely

- [x] 🟩 **Step 3: Always show score — `app.py` changes**
  - [x] 🟩 In `result_to_dict()`: change `show_score` from `not any(c["blocks_scoring"] ...)` to `True`
  - [x] 🟩 In `generate_verdict()`: when `not passed_tier1`, use the same score-based verdict strings but append " — has proximity concerns" if any CONFIRMED_ISSUE checks exist in presented_checks

- [x] 🟩 **Step 4: Rename jargon in score breakdown — `property_evaluator.py` changes**
  - [x] 🟩 `"Primary Green Escape"` → `"Parks & Green Space"` (all occurrences in `score_park_access`)
  - [x] 🟩 `"Third Place"` → `"Coffee & Social Spots"` (all occurrences in `score_third_place_access`)
  - [x] 🟩 `"Provisioning"` → `"Daily Essentials"` (all occurrences in `score_provisioning_access`)
  - [x] 🟩 `"Fitness access"` → `"Fitness & Recreation"` (all occurrences in `score_fitness_access`)
  - [x] 🟩 `"Urban access"` → `"Getting Around"` (all occurrences in `score_transit_access`)
  - [x] 🟩 Remove `score_cost()` call from `evaluate_property()` (line 2842) — do NOT delete the function, just remove the `result.tier2_scores.append(score_cost(...))` line
  - [x] 🟩 Update the score legend in `_result_sections.html` to match new names, remove "Cost / Affordability" row, change description from "Six daily-life factors" to "Five daily-life factors"

- [x] 🟩 **Step 5: Backward compatibility guards**
  - [x] 🟩 Wrap new section references with `{% if result.X is defined %}` guards
  - [x] 🟩 Use `| default('')` for any keys that old snapshots may not have
  - [x] 🟩 Keep old-snapshot fallback paths for `tier1_checks` in "Proximity & Environment" section
