# NES-326: Scoring Key Card Below Verdict

**Date:** 2026-03-26
**Ticket:** [NES-326](https://linear.app/nestcheck/issue/NES-326/scoring-key-card-below-verdict-band-decoder-ring)
**PRD Reference:** `docs/prd-report-design-system.md` Section 4.10

---

## Problem

Users see a composite score (e.g., "77 — Strong Daily Fit") with no immediate context for what the number means. The only band explanation lives in the "How We Score" methodology section at the bottom of the report. Users must scroll past the entire report to understand the scoring system.

Additionally, the existing band table at `_result_sections.html:1199-1205` hardcodes ranges and labels in HTML, creating a maintenance risk where the template and `scoring_config.py` can drift out of sync.

## Solution

A standalone scoring key card placed directly below the verdict card (Tier 1), before Tier 2 content. It serves as a "decoder ring" that builds instant comprehension. The implementation uses a reusable Jinja2 macro driven by `SCORING_MODEL.score_bands` data, eliminating hardcoded values.

---

## Design

### Data Wiring

**Helper function:** `_build_score_bands_context()` — module-level pure function in `app.py`.

- Reads `SCORING_MODEL.score_bands` (tuple of `ScoreBand` objects, ordered descending by threshold: 85, 70, 55, 40, 0)
- Returns a list of dicts: `{threshold, upper_bound, label, css_class, description}`
- `upper_bound` computation: bands are iterated in descending threshold order. For band at index `i`, `upper_bound = bands[i-1].threshold - 1` when `i > 0`, or `100` when `i == 0`
- `description` is editorial content keyed by `css_class` (see Band Descriptions table below)

**Delivery mechanism:** Jinja2 context processor (`@app.context_processor`) that injects `score_bands` globally into all templates. This is static config, not per-evaluation data — it doesn't belong in snapshot JSON or individual route handlers. A context processor avoids wiring `score_bands` into every `render_template` call that includes `_result_sections.html` (view_snapshot, index, city pages, etc.).

**Rationale (CTO):** Band definitions are static config. No changes to `result_to_dict()`, exports, or compare routes.

### Macro: `scoring_key(bands, current_band_class)`

**File:** `templates/_macros.html`

**Parameters:**
- `bands` — list of band dicts from `_build_score_bands_context()`
- `current_band_class` (optional, default `None`) — the user's current band CSS class. When provided, highlights the matching row.

**Structure:** Five rows, one per band. Each row contains:
- Colored dot: 10px circle (reuses existing `.band-dot` class) using 5-band tokens (`--band-exceptional`, `--band-strong`, `--band-moderate`, `--band-limited`, `--band-poor`)
- Band label: `--type-detail`, `--weight-medium`, `--color-text-primary`
- Score range: `--type-detail`, `--weight-normal`, `--color-text-secondary`, `font-family: var(--font-mono)`
- Description: `--type-detail`, `--weight-normal`, `--color-text-muted`

**Current band highlight (CDO):** `.scoring-key__row--active` adds `font-weight: var(--font-weight-semibold)` on the label only, plus a 2px left border in the band color. No background fill (per anti-pattern §1.3 "color as wallpaper").

**Footer link:** "How we score" in `--color-accent`, followed by a 12px arrow SVG in `--color-text-tertiary` transitioning to `--color-accent` on hover. Follows drill-down affordance pattern (PRD §4.13). Links to `#how-we-score` anchor.

### Band Descriptions

Short one-line descriptions for each band (used in the scoring key only, not stored in `ScoreBand`):

| Band | Description |
|------|-------------|
| Exceptional Daily Fit | Excellent across nearly all dimensions |
| Strong Daily Fit | Good daily fit with minor gaps |
| Moderate — Some Trade-offs | Mixed — some strengths, some limitations |
| Limited — Car Likely Needed | Significant gaps in daily livability |
| Significant Gaps | Major limitations across most dimensions |

These are defined in `_build_score_bands_context()`, keyed by `css_class`, and included in each band dict as the `description` field. Editorial content, not scoring logic — but co-located with the other band display data for testability.

### CSS (`.scoring-key` in `report.css`)

**Container:**
```css
.scoring-key {
  background: var(--color-surface-alt);
  border-top: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-8); /* 32px — Tier 1 to Tier 2 gap */
}
```

**Rows:**
```css
.scoring-key__row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-1) 0;
  font-size: var(--type-detail);
}
```

**Dot:** Reuses existing `.band-dot` class (10px circle, defined in `report.css` with 5-band color variants).

**Label:** `.scoring-key__label` — `font-weight: var(--font-weight-medium)`, `color: var(--color-text-primary)`.

**Range:** `.scoring-key__range` — `font-family: var(--font-mono)`, `color: var(--color-text-secondary)`, `min-width: 48px`.

**Description:** `.scoring-key__desc` — `color: var(--color-text-muted)`.

**Active row:**
```css
.scoring-key__row--active {
  border-left: 2px solid; /* inherits band color */
  padding-left: var(--space-2);
}
.scoring-key__row--active .scoring-key__label {
  font-weight: var(--font-weight-semibold);
}
```

**Footer link:**
```css
.scoring-key__link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  margin-top: var(--space-2);
  font-size: var(--type-detail);
  color: var(--color-accent);
  text-decoration: none;
}
.scoring-key__link svg {
  color: var(--color-text-tertiary);
  transition: color var(--transition-fast);
}
.scoring-key__link:hover svg {
  color: var(--color-accent);
}
```

**Responsive (mobile, max-width: 640px):**
```css
.scoring-key__row {
  flex-wrap: wrap;
}
.scoring-key__desc {
  width: 100%;
  padding-left: 20px; /* dot width + gap alignment */
}
```

### Template Placement (`_result_sections.html`)

**New placement:** Insert `{{ scoring_key(score_bands, band_class) }}` after the verdict badge and preview banner blocks (after the `{% endif %}` closing the `is_preview` block around line 80), guarded by `{% if not is_preview and show_score %}`. Inside the `report-tier--verdict` section, before Tier 2 content.

**Macro import:** Add `scoring_key` to the existing `{% from "_macros.html" import ... %}` statement at line 14 of `_result_sections.html`.

**Existing "How We Score" replacement:** Replace the hardcoded `.band-table` div inside the `#how-we-score` section with `{{ scoring_key(score_bands) }}` (no `current_band_class` — methodology section doesn't highlight the user's band).

---

## What's NOT Changing

- `scoring_config.py` — no changes to band names, ranges, or thresholds
- `result_to_dict()` — no new fields in snapshot JSON
- Compare/export routes — no changes needed
- Existing `.band-dot` CSS (10px circles) — reused as-is
- Existing `.band-table` / `.band-row` CSS — left in place as legacy (the "How We Score" section call uses the new macro, but old CSS doesn't need removal in this ticket)

## Files Changed

| File | Change |
|------|--------|
| `app.py` | Add `_build_score_bands_context()` helper; register as `@app.context_processor` to inject `score_bands` globally |
| `templates/_macros.html` | Add `scoring_key(bands, current_band_class)` macro |
| `templates/_result_sections.html` | Insert scoring key below verdict; replace hardcoded band table in "How We Score" |
| `static/css/report.css` | Add `.scoring-key` component styles |

## Testing

- Playwright: verify `.scoring-key` renders below verdict with 5 rows
- Playwright: verify active row matches the snapshot's band
- Playwright: verify "How we score" link points to `#how-we-score`
- Playwright: mobile viewport — verify rows stack correctly
- Visual QA: verify dot colors match verdict card band color
