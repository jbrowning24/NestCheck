# Three Quick Fixes — NES-19, NES-20, NES-21

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** 2026-02-10

## TLDR
Remove the builder debug block from both templates, format walk/drive times >=60 min as "X hr Y min", and remove collapsible accordion behavior from result sections (except "How We Score").

## Critical Decisions
- **Time formatting via Jinja2 macro** — A `{% macro fmt_time(minutes, mode) %}` in `_result_sections.html` is self-contained and requires no changes to `app.py`. All 6 time-display locations are in this one file.
- **Collapsible removal is template-only** — Sections 3-6 use collapsible wrappers only when `is_snapshot` is true. Removing those conditionals makes all content permanently visible. CSS and JS for `toggleSection()` are kept because "How We Score" (section 7) still needs them.
- **Debug block: remove HTML + CSS, keep print rule reference harmless** — The `.builder-debug` reference in `@media print` is a no-op once the HTML is removed, but cleaning it up avoids confusion.

## Tasks

- [x] 🟩 **Step 1: Remove builder debug blocks (NES-19)**
  - [x] 🟩 `index.html`: Remove debug HTML block (lines 827-843) and `.builder-debug` CSS (lines 594-615), clean `.builder-debug` from `@media print` rule (line 727)
  - [x] 🟩 `snapshot.html`: Remove debug HTML block (lines 648-664) and `.builder-debug` CSS (lines 505-526), clean `.builder-debug` from `@media print` rule (line 614)
  - [x] 🟩 Verify: no remaining references to `builder-debug` class, `tier2_raw`, `tier2_normalized`, `snapshot_id:` display in either template (the error diagnostic block in index.html lines 772-777 is separate — it shows "Builder diagnostic" for error details and should remain)

- [x] 🟩 **Step 2: Format walk/drive times as hours + minutes (NES-20)**
  - [x] 🟩 Add a Jinja2 macro `fmt_time(minutes, mode)` at the top of `_result_sections.html` that outputs `X hr Y min mode` when minutes >= 60, otherwise `X min mode`
  - [x] 🟩 Replace all 6 time-display locations in `_result_sections.html`:
    1. Line 112: neighborhood place cards — `{{ place.walk_time_min }} min walk`
    2. Line 154: primary transit walk time — `{{ pt.walk_time_min }} min walk`
    3. Line 156: primary transit drive time — `{{ pt.drive_time_min }} min drive`
    4. Line 172: transit access fallback walk — `{{ result.transit_access.walk_minutes }} min walk`
    5. Line 248: best daily park time — conditional walk/drive
    6. Line 311: nearby green spaces time — conditional walk/drive
  - [x] 🟩 Verify: no remaining raw `}} min walk` or `}} min drive` patterns in `_result_sections.html` (except inside the macro definition itself)

- [x] 🟩 **Step 3: Remove collapsible cards from result sections (NES-21)**
  - [x] 🟩 In `_result_sections.html`, flatten sections 3-6 by removing the `{% if is_snapshot %}` collapsible-toggle/collapsible-body wrappers and their closing tags — replace with plain `<h2>` headings (matching the non-snapshot branch that already exists):
    1. Section 3 "Your Neighborhood" (lines 68-76, closing line 120)
    2. Section 4 "Getting Around" (lines 130-138, closing line 220)
    3. Section 5 "Parks & Green Space" (lines 225-233, closing line 317)
    4. Section 6 "Proximity & Environment" (lines 322-330, closing line 381)
  - [x] 🟩 Leave section 7 "How We Score" (lines 385-413) collapsible — it's reference material
  - [x] 🟩 Keep CSS for `.collapsible-toggle`, `.collapse-icon`, `.collapsible-body` in both templates (still needed by "How We Score")
  - [x] 🟩 Keep `toggleSection()` JS in both templates (still needed by "How We Score")

- [x] 🟩 **Step 4: Verification**
  - [x] 🟩 Search templates for any remaining `builder-debug` HTML (should only exist in index.html error diagnostic block, which is separate)
  - [x] 🟩 Search `_result_sections.html` for `}} min walk` or `}} min drive` outside the macro — should find none
  - [x] 🟩 Search `_result_sections.html` for `collapsible-toggle` — should only appear in "How We Score" section
  - [x] 🟩 Confirm `toggleSection` JS references in both templates don't reference removed elements
