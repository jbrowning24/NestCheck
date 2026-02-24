# Implementation Plan: NES-124 — Proximity Flag Pills in Verdict Card

**Progress:** 100% · **Status:** Complete
**Last updated:** 2026-02-20

## TLDR
Add compact proximity-flag pills to the verdict card so users see safety concerns (gas station, highway, high-volume road, rail corridor) immediately next to the overall score. Pills render only when there are non-CLEAR safety checks. The Proximity & Environment section remains unchanged.

## Scope
**In scope:**
- Add a `verdict-proximity-flags` container inside the verdict card (after dimension summaries)
- Render pills for SAFETY checks where `result_type != "CLEAR"` (CONFIRMED_ISSUE, VERIFICATION_NEEDED)
- Add CSS for `.verdict-proximity-flags` and `.verdict-proximity-pill` with severity-based colors

**Out of scope:**
- Modifying the Proximity & Environment section (lines 406–484)
- Changing existing CSS classes
- Changes to `property_evaluator.py` or `app.py`
- JavaScript

## Key Decisions
| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Filter to `result_type != "CLEAR"` | Only surface concerns; CLEAR items add noise |
| 2 | Use `proximity_band \| lower` for CSS class | `presented_checks` stores band as "VERY_CLOSE"/"NOTABLE"/"NEUTRAL"; CSS uses `.proximity-very_close` etc. |
| 3 | Reuse existing design tokens | Pills use same `--color-danger-*`, `--color-warning-*`, `--color-surface-subtle` as `.proximity-item` for visual consistency |

## Assumptions
- `result.presented_checks` is always present (guaranteed by NES-80 backfill for old snapshots)
- `proximity_band` may be `None` for lifestyle checks; we filter by `category == "SAFETY"` so only safety checks (which have bands) are shown

## Tasks

- [x] 🟩 **1. Add verdict proximity flags block to template** · _[S]_
  Insert the pill container after the dimension summaries block and before the verdict card closing `</div>`.
  - [x] 🟩 1.1 In `templates/_result_sections.html`, after line 56 (after `{% endif %}` that closes dimension-list) and before line 57 (verdict card closing `</div>`), add a Jinja block that:
    - Sets a variable for safety concerns: `{% set safety_concerns = result.presented_checks | selectattr('category', 'equalto', 'SAFETY') | selectattr('result_type', 'ne', 'CLEAR') | list %}`
    - Wraps content in `{% if safety_concerns %}` so the container renders only when the list is non-empty
    - Renders `<div class="verdict-proximity-flags">` containing a loop over `safety_concerns`
    - Each item: `<span class="verdict-proximity-pill proximity-{{ pc.proximity_band | lower }}">⚠ {{ pc.headline }}</span>`
  - [x] 🟩 1.2 Ensure `proximity_band` is lowercased for CSS class (e.g. `VERY_CLOSE` → `proximity-very_close`)

- [x] 🟩 **2. Add CSS for verdict proximity pills** · _[S]_
  Add new styles in `static/css/report.css` without modifying existing `.proximity-*` rules.
  - [x] 🟩 2.1 Add `.verdict-proximity-flags`: `display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px;`
  - [x] 🟩 2.2 Add `.verdict-proximity-pill`: `display: inline-flex; align-items: center; font-size: 0.78rem; padding: 4px 10px; border-radius: 12px; font-weight: 500;`
  - [x] 🟩 2.3 Add `.verdict-proximity-pill.proximity-very_close`: `background-color: var(--color-danger-bg); color: var(--color-danger-text);` (or `--color-danger-text-dark` for contrast)
  - [x] 🟩 2.4 Add `.verdict-proximity-pill.proximity-notable`: `background-color: var(--color-warning-surface); color: var(--color-warning-text);`
  - [x] 🟩 2.5 Add `.verdict-proximity-pill.proximity-neutral`: `background-color: var(--color-surface-subtle); color: var(--color-text-dim);` (fallback for edge cases)

## Verification
- [ ] **0 flags:** Evaluate an address with all proximity checks CLEAR (e.g. residential Park Slope). Verdict card shows score, band, dimension summaries; no pills, no empty container.
- [ ] **1 flag:** Evaluate an address with one CONFIRMED_ISSUE (e.g. highway-adjacent Bronx address). One pill appears below dimension summaries with appropriate severity color.
- [ ] **3 flags:** Evaluate an address with multiple proximity concerns. Multiple pills wrap in a row with 6px gap.
- [ ] Proximity & Environment section unchanged: full cards with explanations still render in section 6.

## Status Report Format (post-implementation)
- **Files changed:** `templates/_result_sections.html`, `static/css/report.css`
- **Blocks modified:** Verdict card (insert after dimension-list, before verdict-card `</div>`); new CSS block in report.css
- **Jinja filter logic:** `selectattr('category', 'equalto', 'SAFETY')` filters to safety checks; `selectattr('result_type', 'ne', 'CLEAR')` excludes passed checks; `| list` materializes for `{% if %}` and loop
- **Screenshot-equivalent:** 0 flags = no pills; 1 flag = single pill below dimensions; 3 flags = three pills in a flex row, wrapping on narrow viewports
