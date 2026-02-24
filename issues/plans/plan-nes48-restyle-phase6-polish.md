# NES-48: [Restyle Phase 6] Polish — pricing, 404, loading, error states, empty states

**Overall Progress:** `100%`

## TLDR
Visual polish pass on every non-core-report surface. Restyle pricing page to match the new design language. Add branded 404/429/500 error pages with inline SVG icons. Upgrade the loading overlay from generic spinner to a branded, intentional experience. Add a retry button to the error banner for transient failures. Replace bare "no data" text with icon + styled message empty states throughout the report. Light token pass on builder dashboard. All styling via existing design tokens — no new dependencies.

## Critical Decisions
- **Inline SVG icons only** — hand-pick ~6 simple icons (empty parks, empty transit, empty fitness, map unavailable, general "no data" fallback, error page). No icon library dependency.
- **One error component** — single clean error banner style for all error types (user, payment, system). Differentiation comes from the retry button appearing only for transient/system failures.
- **Loading overlay: branded but achievable** — replace the generic border-spinner with a pulsing NestCheck-branded mark (house/pin SVG) + improved typography hierarchy. Keep the determinate progress bar and stage text (already good from NES-47). Don't over-engineer.
- **Error pages share one CSS file** — rename `404.css` → `error-page.css`, used by 404, 429, and new 500. All three share the same centered layout with distinct icon + heading + body + CTA.
- **Builder dashboard: tokens only** — swap hardcoded hex colors for CSS custom properties. No layout, structural, or feature changes. Keep it as a standalone page (no `_base.html` inheritance).
- **Cookie banner: out of scope**

## Files

| File | Change |
|---|---|
| `static/css/error-page.css` | New (renamed from 404.css). Shared styles for 404/429/500 pages with icon slot. |
| `static/css/pricing.css` | Restyle to match new design language. Migrate remaining hardcoded values to tokens. |
| `static/css/index.css` | Update loading overlay styles (branded spinner, improved hierarchy). Update error banner (retry button). |
| `static/css/report.css` | Update `.section-empty` and `.map-placeholder` for icon + text empty state pattern. |
| `templates/404.html` | Add inline SVG icon, improve copy, use error-page.css. |
| `templates/429.html` | Add inline SVG icon, improve copy, use error-page.css. |
| `templates/500.html` | New template. Inline SVG icon, friendly copy, CTA home link. |
| `templates/pricing.html` | Restyle markup — tighter spacing, better hierarchy, token alignment. |
| `templates/index.html` | Replace spinner with branded SVG. Add retry button to error banner JS. |
| `templates/_result_sections.html` | Add inline SVG icons to empty state messages (parks, transit, map). |
| `templates/builder_dashboard.html` | Swap hardcoded hex values for token references (import tokens.css). |
| `app.py` | Add 500 error handler (~3 lines). |

## Tasks

- [x] **Step 1: Error pages (404 / 429 / 500)**
  - [x] Rename `static/css/404.css` → `static/css/error-page.css`
  - [x] Restyle error-page.css: centered layout with icon slot (`.error-icon` div above heading), use tokens for all values (font sizes, colors, spacing, radius). Keep vertical centering approach.
  - [x] Update `templates/404.html`: add inline SVG icon (magnifying glass + question mark — "not found"), improve body copy, link to `error-page.css`
  - [x] Update `templates/429.html`: add inline SVG icon (clock/hourglass — "slow down"), improve body copy, link to `error-page.css`
  - [x] Create `templates/500.html`: add inline SVG icon (warning triangle — "something went wrong"), friendly body copy ("Something went wrong on our end. Please try again in a moment."), CTA link home
  - [x] Add `@app.errorhandler(500)` handler in `app.py` (render `500.html`, return 500)

- [x] **Step 2: Loading overlay upgrade**
  - [x] Replace the generic `.spinner` (border-spin circle) with a branded SVG mark — a simple house/location-pin outline that pulses. Keep it small (48-56px), uses `--color-primary`.
  - [x] CSS: replace `@keyframes spin` with `@keyframes pulse` (scale 0.95→1.05 + opacity 0.6→1, ~1.5s ease-in-out infinite)
  - [x] Tighten typography: loading-text stays semibold, loading-sub gets slightly larger. Add a subtle "This usually takes 30–60 seconds" note below the stage text after 10 seconds (JS timeout adds a `.loading-patience` element or unhides it).
  - [x] Keep the determinate progress bar exactly as-is (width, height, transition, color — all good from NES-47)

- [x] **Step 3: Error banner + retry button**
  - [x] Add a "Try again" button to the error banner markup (created by JS `showError` function in index.html)
  - [x] The retry button should: hide the error banner, re-enable the submit button, and focus the address input — letting the user re-submit without refreshing
  - [x] Style the retry button: secondary style (outline, `--color-primary` border, no fill), sits below the error message
  - [x] Only show the retry button for non-validation errors (the button appears on all showError calls from polling/network failures; the server-rendered `{% if error %}` banner in the template does NOT get a retry button since the user can just resubmit the form)

- [x] **Step 4: Empty states with icons**
  - [x] Create ~6 inline SVG icons (simple, consistent 24×24 stroke style, `--color-text-faintest` stroke, no fill):
    - `empty-parks`: tree outline
    - `empty-transit`: bus/train outline
    - `empty-fitness`: dumbbell outline
    - `empty-map`: map-pin with X or dashed outline
    - `empty-general`: circle with horizontal line (generic "nothing here")
    - (error pages get their own icons in Step 1)
  - [x] Update `.section-empty` in report.css: flex row layout, icon left + text right, padding, slightly larger text, remove italic
  - [x] Update `.map-placeholder` in report.css: add icon above text, centered, slightly larger
  - [x] Update `_result_sections.html`:
    - Parks empty state (line 279): add `empty-parks` SVG + text
    - Transit empty state (line 220): add `empty-transit` SVG + text
    - Map placeholder (line 73): add `empty-map` SVG + text
    - Neighborhood section: no empty state needed (entire section is hidden when empty)

- [x] **Step 5: Pricing page restyle**
  - [x] Migrate all remaining hardcoded values in pricing.css to tokens (font sizes, spacing, colors already partially tokenized)
  - [x] Tighten the price card: heading uses `--font-size-xl`, price-tag uses `--font-size-3xl`, feature list uses `--font-size-body-4`, CTA button matches the landing page CTA style (same padding, weight, hover-lift)
  - [x] Style "coming soon" cards: add a subtle left-border accent (`--color-primary`, 3px) to distinguish them from the main card
  - [x] Improve the note/footer area: cleaner spacing, use `--font-size-sm` token
  - [x] Ensure responsive behavior: card should breathe on mobile (full-width padding), center nicely on desktop

- [x] **Step 6: Builder dashboard token pass**
  - [x] Add `<link rel="stylesheet" href="tokens.css">` to the `<head>` (keep the existing `<style>` block but migrate color values)
  - [x] Replace hardcoded hex colors with token references:
    - `#0d1117` body bg → keep dark (this is an intentionally dark internal tool — use a local `--builder-bg` variable or keep hardcoded; it's not a public surface)
    - `#58a6ff` accent → `var(--color-primary)` or keep as-is since it's a dark-theme accent
    - `#8b949e` muted → keep for dark theme contrast
  - [x] Actually — keep the dark theme entirely. Only ensure font-family uses `--font-sans` from tokens instead of the hardcoded monospace stack. Everything else stays.

- [x] **Step 7: Visual QA**
  - [x] Verify all error pages render correctly (404, 429, 500)
  - [x] Verify loading overlay looks good during an actual evaluation
  - [x] Verify error banner + retry button works (trigger a failure)
  - [x] Verify empty states render with icons in the report
  - [x] Verify pricing page matches new design language
  - [x] Check mobile responsive on all changed pages
