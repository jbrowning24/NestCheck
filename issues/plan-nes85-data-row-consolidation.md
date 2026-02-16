# NES-85: Consolidate Data List/Row Patterns

**Overall Progress:** `100%`

## TLDR
Three patterns (`.place-item`, `.hub-row`, `.dimension-row`) share the same visual shape — label + detail + right-aligned value — but use different HTML structures and CSS. We consolidate them into a single `data_row` Jinja macro in a new `_macros.html` partial, backed by a unified `.data-row` CSS component with semantic modifiers.

## Critical Decisions
- **Macro location:** New `templates/_macros.html` file. `fmt_time` moves there too — single home for shared template utilities.
- **Macro API:** Uses `{% call(slot) %}` block for custom right-side content (e.g., dimension progress bar). Simple cases (just a text value) work without `{% call %}`.
- **CSS naming:** Semantic modifiers — `.data-row--place`, `.data-row--hub`, `.data-row--dimension`. Purpose won't change even if styling does.
- **Accessibility lines:** Stay outside the macro as separate markup. They follow the row, they aren't part of it.
- **Backward compatibility:** Old snapshots must render identically. The macro handles missing/optional fields via Jinja defaults.

## Files Touched
- `templates/_macros.html` — **new file**: `data_row` macro + `fmt_time` (moved from `_result_sections.html`)
- `templates/_result_sections.html` — replace `.place-item`, `.hub-row`, `.dimension-row` HTML with macro calls; add `{% from %}` import
- `static/css/report.css` — add `.data-row` component; remove `.place-item`, `.hub-row`, `.dimension-row` CSS blocks; update responsive breakpoints

## Tasks

- [x] 🟩 **Step 1: Create `_macros.html` with `data_row` macro**
  - [x] 🟩 Create `templates/_macros.html` with `fmt_time` (moved from `_result_sections.html` line 7) and the `data_row` macro. Macro params: `name` (required), `detail` (optional), `value` (optional right-side text), `variant` (place/hub/dimension). Supports `{% call(slot) %}` for custom right content.
  - [x] 🟩 In `_result_sections.html`, replace the inline `fmt_time` definition with `{% from "_macros.html" import data_row, fmt_time %}`
  - [ ] 🟥 **Verify:** Load any report — all travel times render correctly. No visual change.

- [x] 🟩 **Step 2: Add `.data-row` CSS component**
  - [x] 🟩 Add `.data-row` base class + `__info`, `__name`, `__detail`, `__right`, `__value` children + three variant modifiers (`--place`, `--hub`, `--dimension`) + `--no-border` modifier. Insert after "Collapsible Sections" block, before "Place Items".
  - [x] 🟩 Add responsive overrides in existing media query blocks: 768px (dimension gap/name-width), 640px (dimension wrap, hub column stack)
  - [ ] 🟥 **Verify:** CSS added but not yet used — no visual changes.

- [x] 🟩 **Step 3: Migrate `.dimension-row` → `data_row` macro**
  - [x] 🟩 Replace `.dimension-row` HTML (lines 44-54) with `{% call(slot) data_row(..., variant="dimension") %}`. Caller block renders `.dimension-indicator` with score + bar.
  - [ ] 🟥 **Verify:** Load a report with scores. Compare verdict card at desktop, 768px, 640px — padding, alignment, font sizes, progress bars must match exactly.

- [x] 🟩 **Step 4: Migrate `.hub-row` → `data_row` macro**
  - [x] 🟩 4a — Primary transit rail (lines 170-185): `{% call %}` for walk + optional drive time. Accessibility lines remain as separate markup below.
  - [x] 🟩 4b — Bus fallback (lines 213-226): simple `value=` param, no call block needed.
  - [x] 🟩 4c — Emergency services loop (lines 390-401): name + type label + drive time.
  - [x] 🟩 4d — Libraries loop (lines 419-428): name + "Public Library" + estimated walk time.
  - [ ] 🟥 **Verify:** Check transit (name, mode, frequency, walk/drive times), emergency (fire/police + drive times), libraries (names + walk times). Test phone width — rows should stack vertically.

- [x] 🟩 **Step 5: Migrate `.place-item` → `data_row` macro**
  - [x] 🟩 5a — Best daily park highlight (lines 292-307): `{% call %}` for compound right content (travel time + daily value score). Uses `.data-row--no-border` inside `.park-highlight`.
  - [x] 🟩 5b — Nearby green spaces loop (lines 348-371): name param accepts safe HTML (contains inline badge). Detail has rating + score. Right side is travel time only.
  - [ ] 🟥 **Verify:** Check best park (name, rating, reviews, type, travel time, daily value, subscore grid below). Check nearby spaces (names with distance badges, meta, travel times). All breakpoints.

- [x] 🟩 **Step 6: Remove old CSS + cleanup**
  - [x] 🟩 Remove `.place-item` block: `.place-item`, `:last-child`, `.place-name`, `.place-meta`, `.place-time`, `.place-item--no-border`
  - [x] 🟩 Remove `.hub-row` block: `.hub-row`, `:last-child`, `.hub-info`, `.hub-name`, `.hub-detail`, `.hub-right`, `.hub-time`
  - [x] 🟩 Remove `.dimension-row` layout classes: `.dimension-row`, `.dimension-name`, `.dimension-summary` (keep `.dimension-indicator`, `.dimension-score`, `.dimension-bar`, `.dimension-bar-fill` — progress bar component, not row layout)
  - [x] 🟩 Update responsive breakpoints: replace old class references (`.dimension-row`, `.dimension-name`, `.hub-row`, `.hub-right`, etc.) with `.data-row--dimension` and `.data-row--hub` equivalents
  - [x] 🟩 Grep codebase for all removed class names — confirm zero references outside `issues/` docs
  - [ ] 🟥 **Verify:** Load multiple reports (parks, transit, emergency services). Full visual comparison at desktop, tablet, phone. No broken styles, no layout shifts.

## Pattern Inventory (Post-Consolidation)

| Pattern | Purpose | Status |
|---------|---------|--------|
| `.data-row` (3 variants) | Label + detail + right-aligned value | Reusable macro |
| `.place-card` | Horizontal scroll cards (neighborhood) | Section-specific |
| `.proximity-item` | Status items with severity bands | Section-specific |
| `.band-row` | Static score legend | Section-specific |
| `.subscore-card` | Grid cards (park quality) | Section-specific |
| `.walkscore-pill` | Score pills (Walk/Transit/Bike) | Section-specific |

Down from 9 active patterns to 6 (3 consolidated into 1).
