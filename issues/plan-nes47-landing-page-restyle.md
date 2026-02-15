# NES-47: Landing Page & Input Form Restyle

**Overall Progress:** `100%`

## TLDR
Premium visual redesign of the landing page — the product's front door. Full-width white hero band with refined typography hierarchy, form area as clear focal point with amplified elevation and prominent CTA, why-block as a styled callout, feature cards with elevation + hover-lift, and a determinate progress bar in the loading overlay mapped to real backend stages. All CSS flipped to mobile-first. All hardcoded values migrated to tokens.

## Critical Decisions
- **White band, not navy wash** — hero + form sit on a full-width `--color-surface` band, body `--color-bg` provides the tonal break below
- **Mobile-first CSS** — rewrite index.css with base styles for mobile, `min-width` media queries scaling up
- **Determinate progress bar** — map `STAGE_DISPLAY` keys to approximate percentages using real backend stage data
- **Fold "who it's for" into why-block** — remove the floating one-liner, consolidate explanatory copy
- **Footer out of scope** — no changes to footer styling

## Files
- `static/css/index.css` — full rewrite (mobile-first, tokenized, new sections)
- `templates/index.html` — HTML structure changes (hero band wrapper, why-block callout, progress bar markup, remove who-its-for)

## Tasks

- [x] 🟩 **Step 1: Hero band & typography hierarchy**
  - [x] 🟩 Wrap hero + form + why-block in a full-width `.landing-hero-band` div with `background: var(--color-surface)` and bottom border/shadow for tonal break
  - [x] 🟩 Refine hero h1/tagline spacing and sizing using tokens (`--font-size-2xl`, `--font-weight-extrabold`, `--letter-spacing-tight`)
  - [x] 🟩 Increase vertical breathing room between hero → tagline → form (generous `margin`/`padding` via space tokens)

- [x] 🟩 **Step 2: Form area as focal point**
  - [x] 🟩 Increase search-section max-width to 680px, add more vertical padding around it
  - [x] 🟩 Amplify CTA button — larger padding (`--space-16` / `--space-32`), bold weight, subtle hover lift (`translateY(-1px)` + shadow transition)
  - [x] 🟩 Ensure focus-within border treatment remains clear and smooth
  - [x] 🟩 Tokenize all hardcoded px values (input padding, button padding, gap, border-width)

- [x] 🟩 **Step 3: Why-block as styled callout**
  - [x] 🟩 Absorb "who it's for" copy into why-block paragraph text; remove `.who-its-for` element from HTML and CSS
  - [x] 🟩 Style why-block as a visually distinct section — `--color-surface-subtle` background, `border-radius`, padding, border treatment

- [x] 🟩 **Step 4: Feature cards — elevation & hover-lift**
  - [x] 🟩 Add `box-shadow: var(--shadow-card)` at rest, `var(--shadow-elevated)` + `translateY(-2px)` on hover (matching NES-46a place cards)
  - [x] 🟩 Add `transition` for shadow and transform
  - [x] 🟩 Tokenize all hardcoded values (padding, gap, font sizes, margin)

- [x] 🟩 **Step 5: Loading overlay — determinate progress bar**
  - [x] 🟩 Add progress bar HTML to loading overlay (track div + fill div)
  - [x] 🟩 Create stage-to-percentage mapping in JS (geocode 5% → saving 97%)
  - [x] 🟩 Update `startPolling` and `submitEvaluation` to drive fill width via `setProgress()`
  - [x] 🟩 Style progress bar — 200px wide, 6px tall, rounded track, primary-color fill, 0.4s width transition
  - [x] 🟩 Polish overlay typography using tokens (loading-text, loading-sub sizing/weight/color)

- [x] 🟩 **Step 6: Mobile-first CSS rewrite**
  - [x] 🟩 Rewrite index.css base styles as mobile defaults (column layout, full-width button, `--font-size-xl-2` hero)
  - [x] 🟩 Add `min-width: 641px` breakpoint for tablet+ (row search-box, `--font-size-2xl-2` hero, 2-col features)
  - [x] 🟩 Add `min-width: 1025px` breakpoint for desktop (`--font-size-2xl` hero, 3-col features)
  - [x] 🟩 Migrate all remaining hardcoded values to design tokens

- [x] 🟩 **Step 7: Verify & clean up**
  - [x] 🟩 Delete dead CSS (`.who-its-for` rule)
  - [x] 🟩 Verify error banner still renders correctly within the new hero band layout
  - [x] 🟩 Confirm result-page variant (`.search-section--result`) is unaffected (outside hero band)
  - [x] 🟩 Confirm print media query still works
