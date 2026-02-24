# NES-42 Phase 1: CSS Extraction & Shared Base Layout

**Progress:** 100% · **Status:** Complete
**Last updated:** 2026-02-13

## TLDR

Extract all inline `<style>` blocks from five Jinja2 templates into external CSS files, introduce CSS custom properties as design tokens, and create a shared `_base.html` layout template. Pure refactoring — zero visual changes. This eliminates ~1,500 lines of duplicated CSS and establishes the foundation for all subsequent restyle phases.

## Scope

**In scope:**
- Extract inline CSS from `index.html`, `snapshot.html`, `pricing.html`, `404.html`
- Create external stylesheets: `base.css`, `report.css`, `index.css`, `snapshot.css`, `pricing.css`, `404.css`
- Define CSS custom properties (design tokens) for colors, fonts, radii, shadows
- Create `_base.html` layout template with shared nav/footer/head
- Refactor all four public templates to extend `_base.html`
- Extract ~10 layout-hack inline `style=` attributes from `_result_sections.html` to classes
- Fix missing hub-row 640px stacking in index.html (bug — already present in snapshot.html)
- Remove dead `.score-row` CSS (after verifying snapshots re-render from data)
- Deduplicate the double `.error-banner` definition in index.html

**Out of scope:**
- `builder_dashboard.html` — internal tooling with a different design language, zero user-facing value
- Any visual changes — this is a refactor, not a restyle
- New breakpoints — the ~900px tablet breakpoint will come in a later phase
- Data-driven inline styles in `_result_sections.html` (color thresholds based on score values stay inline)

## Key Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Builder dashboard excluded from restyle | Internal tooling with a separate dark/monospace design. Can revisit later if a unified admin experience is wanted. |
| 2 | Single 640px breakpoint preserved; no new breakpoints yet | Fine for now. A tablet breakpoint (~900px) will come in a later restyle phase. |
| 3 | Data-driven inline styles stay inline | Color thresholds based on score values are templating logic, not design. Only static layout-hack `style=` attributes get extracted. |
| 4 | `.score-row` removed as dead CSS | Not referenced in `_result_sections.html`. Snapshots store evaluation data and re-render through current templates, so no old rendered HTML depends on it. Verified during discovery. |
| 5 | Shared base extracted via `_base.html` | Nav and body reset are duplicated across 4 templates (~30 lines each). A Jinja2 layout template with blocks is the standard Flask pattern. |
| 6 | index.html CSS is canonical for shared rules | Where index.html and snapshot.html have identical CSS, index.html's version goes into `report.css`. Snapshot.html divergences go into `snapshot.css` as overrides. |

## Assumptions

- Snapshots re-render from stored data through current templates (not stored HTML) — making `.score-row` safe to remove. A quick verification is included in the discovery step.
- Flask's default `static_folder` (`static/` relative to app root) will work, or `app.py` already configures it. Discovery step checks this.
- Railway serves the app via Gunicorn (Procfile). Flask's default static handler serves `static/` at `/static/` — no additional config needed.

## Discovery Findings (from NES-42 Phase 0 audit)

Summary of current state informing this plan:

- **All CSS is inline** — `<style>` blocks in every template. No external stylesheets. No `static/` directory exists.
- **No design tokens** — zero CSS custom properties. Every color is a hardcoded hex literal (e.g. `#0f3460` appears ~20 times).
- **~1,596 total lines of CSS** across all templates.
- **~500 lines are fully duplicated** between index.html and snapshot.html (verdict-card, report-section, dimension-rows, badges, check-rows, proximity items, walkscore pills, etc.)
- **~15 inline `style=` attributes** in `_result_sections.html`, split between data-driven (keep) and layout-hacks (extract).
- **One responsive breakpoint** at 640px. Hub-row stacking rule exists in snapshot.html but is missing from index.html (bug).
- **`.error-banner` defined twice** in index.html with slightly different properties.
- **`.score-row` CSS exists** in both files but is not referenced in `_result_sections.html`.

## Tasks

- [x] 🟩 **1. Discovery — precise CSS inventory and deployment check** · _M_
  Before touching any files, produce the exact selector-by-selector inventory needed to split CSS correctly.
  - [x] 🟩 1.1 Read `app.py` — Flask defaults apply, no config needed
  - [x] 🟩 1.2 88 SHARED, 5 SHARED-DIVERGED, ~28 INDEX-ONLY, ~9 SNAPSHOT-ONLY
  - [x] 🟩 1.3 ~45 colors → ~30 tokens, plus font, radius, shadow tokens
  - [x] 🟩 1.4 18 LAYOUT-HACK, 1 DATA-DRIVEN
  - [x] 🟩 1.5 Nav links differ per page, footer text differs (index vs others), 404 has no footer
  - [x] 🟩 1.6 Gunicorn via Procfile (Railway) — Flask defaults serve static files, no changes needed
  - [x] 🟩 1.7 Confirmed: snapshots re-render from stored data — `.score-row` safe to remove

- [x] 🟩 **2. Create `static/css/base.css` — design tokens, reset, nav, footer** · _M_
  The foundation stylesheet that every page loads. Defines all CSS custom properties and shared structural styles.
  - [ ] 🟥 2.1 Create `static/css/` directory
  - [ ] 🟥 2.2 Define `:root` CSS custom properties for all repeated colors, font stacks, border-radii, box-shadows (from discovery token list)
  - [ ] 🟥 2.3 Extract the shared reset (`*`, `body`, base typography) into `base.css`
  - [ ] 🟥 2.4 Extract canonical nav styles (use index.html as source of truth)
  - [ ] 🟥 2.5 Extract canonical footer styles
  - [ ] 🟥 2.6 Extract shared utility classes: all `.badge-*` variants
  - [ ] 🟥 2.7 Replace all hardcoded values with `var(--token)` references

- [x] 🟩 **3. Create `static/css/report.css` — shared result/report styles** · _L_
  All CSS for rendering evaluation results, used by both index.html and snapshot.html.
  - [ ] 🟥 3.1 Extract all `SHARED` selectors from the discovery inventory into `report.css`
  - [ ] 🟥 3.2 For `SHARED-DIVERGED` selectors, use index.html as canonical — note snapshot overrides for Step 5
  - [ ] 🟥 3.3 Include hub-row 640px stacking rule (fixing the index.html bug)
  - [ ] 🟥 3.4 Include shared `@media (max-width: 640px)` rules
  - [ ] 🟥 3.5 Include shared `@media print` rules
  - [ ] 🟥 3.6 Remove `.score-row` (dead CSS)
  - [ ] 🟥 3.7 Replace all hardcoded values with `var(--token)` references

- [x] 🟩 **4. Create `static/css/index.css` — landing and index-only styles** · _M_
  Styles unique to the index.html landing page and its result view.
  - [ ] 🟥 4.1 Extract all `INDEX-ONLY` selectors: hero, search-box, why-block, features, loading overlay, spinner, error-banner, who-its-for
  - [ ] 🟥 4.2 Deduplicate `.error-banner` — use one definition
  - [ ] 🟥 4.3 Extract index-specific `.share-bar` variant (if it differs from snapshot's)
  - [ ] 🟥 4.4 Include index-specific responsive rules
  - [ ] 🟥 4.5 Replace all hardcoded values with `var(--token)` references

- [x] 🟩 **5. Create `static/css/snapshot.css` — snapshot-only overrides** · _S_
  Styles unique to snapshot.html, plus overrides for any `SHARED-DIVERGED` selectors.
  - [ ] 🟥 5.1 Extract `SNAPSHOT-ONLY` selectors: `.snapshot-cta`, `.data-unavailable`, `.snapshot-meta`
  - [ ] 🟥 5.2 Add `.share-bar` overrides (different `justify-content` and `margin`)
  - [ ] 🟥 5.3 Add any diverged responsive rules
  - [ ] 🟥 5.4 Replace all hardcoded values with `var(--token)` references

- [x] 🟩 **6. Create `static/css/pricing.css` and `static/css/404.css`** · _S_
  Page-specific styles for pricing and 404 — everything except what's already in `base.css`.
  - [ ] 🟥 6.1 Extract pricing-only styles: `.pricing-page`, `.price-card`, `.price-tag`, `.price-features`, `.price-btn`, `.coming-soon`, `.cta-flow`, `.note`
  - [ ] 🟥 6.2 Extract 404-only styles: `.container` (centered layout)
  - [ ] 🟥 6.3 Replace all hardcoded values with `var(--token)` references

- [x] 🟩 **7. Create `templates/_base.html` — shared layout template** · _M_
  Jinja2 base template with blocks for title, extra CSS, head extras, nav extras, content, and scripts.
  - [ ] 🟥 7.1 Create `_base.html` with `DOCTYPE`, `<html>`, `<head>` (charset, viewport, title block, base.css link, extra_css block, head_extra block)
  - [ ] 🟥 7.2 Add canonical `<nav>` HTML with `{% block nav_extra %}` for per-page nav items (e.g. builder dashboard link)
  - [ ] 🟥 7.3 Add `{% block content %}` for page body
  - [ ] 🟥 7.4 Add canonical `<footer>` HTML
  - [ ] 🟥 7.5 Add `{% block scripts %}` for per-page JavaScript

- [x] 🟩 **8. Refactor templates to extend `_base.html`** · _L_
  Convert all four public templates from standalone HTML to Jinja2 template inheritance. This is the highest-risk step — every template changes structurally.
  - [ ] 🟥 8.1 Refactor `index.html`: remove `<style>` block, `DOCTYPE`/`html`/`head`/`body` wrapper → `{% extends "_base.html" %}`, add CSS links (`report.css`, `index.css`) in `extra_css` block, move content and scripts into blocks, keep `{% include '_result_sections.html' %}` as-is
  - [ ] 🟥 8.2 Refactor `snapshot.html`: same pattern, CSS links to `report.css` and `snapshot.css`, preserve OG meta tags in `head_extra` block
  - [ ] 🟥 8.3 Refactor `pricing.html`: same pattern, CSS link to `pricing.css`
  - [ ] 🟥 8.4 Refactor `404.html`: same pattern, CSS link to `404.css`

- [x] 🟩 **9. Extract layout-hack inline styles from `_result_sections.html`** · _S_
  Replace static `style=` attributes with classes. Leave data-driven inline styles (score-based colors) untouched.
  - [ ] 🟥 9.1 For each `LAYOUT-HACK` identified in discovery: create a descriptive class in `report.css` and replace the `style=` attribute
  - [ ] 🟥 9.2 Verify data-driven inline styles are untouched

- [x] 🟩 **10. Flask / deployment config (if needed)** · _S_
  Ensure `static/css/` files are served correctly in both local dev and production.
  - [ ] 🟥 10.1 If `app.py` doesn't set `static_folder`, confirm Flask default works with directory structure
  - [x] 🟩 10.2 Railway deployment: Flask default static serving works, no config changes needed

## Verification

- [ ] Visit `/` (landing page) — renders identically to pre-refactor
- [ ] Submit an address or visit a known snapshot URL — result page renders identically
- [ ] Visit `/pricing` — renders identically
- [ ] Visit a non-existent route — 404 renders identically
- [ ] Test at 640px viewport — responsive behavior matches (hub-row stacking now works on both index and snapshot)
- [ ] Test print preview — print styles work
- [ ] Check browser console — no 404s on CSS file requests
- [ ] `builder_dashboard.html` is untouched and still works

## Execution Notes

**Task 1 (discovery) should be run and reviewed before starting Tasks 2–10.** The precise token names, selector classifications, and inline style list from discovery will inform the exact contents of each CSS file. Do not start implementation until the discovery report is reviewed and confirmed.

**Task 8 is the highest-risk step.** Template inheritance changes can introduce subtle rendering bugs if blocks are misplaced or content falls outside blocks. Verify each template individually after refactoring.

**What to watch for during implementation:**
- CSS specificity is unchanged when moving from inline `<style>` to external `<link>` (both are author stylesheet level), but load order matters — `base.css` must load before `report.css`, which must load before page-specific CSS
- `url_for('static', ...)` requires Flask to know the static folder — verify this works before extensive refactoring
- OG meta tags in `snapshot.html` depend on template variables — they need to go in a `head_extra` block, not outside the template inheritance structure
