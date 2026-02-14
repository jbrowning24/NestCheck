# NES-46a: Shared Section Hierarchy + Neighborhood Place Cards

**Overall Progress:** `100%`

## TLDR
Establish a consistent visual hierarchy pattern across all report sections (h2 → insight callout → key metric → supporting data) and upgrade the Your Neighborhood place cards with elevation, hover effects, and better internal hierarchy. CSS-only changes in `report.css`; no template restructuring needed.

## Critical Decisions
- **Insight callout style**: Left accent bar using `--color-primary` + subtle `--color-surface-subtle` background — visually distinct from proximity items (which use status-colored left borders)
- **Place card elevation**: Use existing `--shadow-card` token + hover lift via `transform: translateY` — no new shadow tokens needed
- **No template changes**: Current HTML structure in `_result_sections.html` already has the right hierarchy; this is purely a CSS visual weight adjustment
- **Hover on touch**: Hover lift is a progressive enhancement — touch devices see the elevated resting state only

## Tasks:

- [x] 🟩 **Step 1: Restyle `.section-insight` as a callout**
  - [x] 🟩 Add `--color-primary` left border (3px), `--color-surface-subtle` background, padding, and border-radius
  - [x] 🟩 Differentiate from proximity items: use `--radius-sm` corners on all sides (proximity uses square top-left/bottom-left)
  - [x] 🟩 Verify all 3 sections that use insights render correctly (Your Neighborhood, Getting Around, Parks)

- [x] 🟩 **Step 2: Upgrade `.place-card` visual treatment**
  - [x] 🟩 Add `box-shadow: var(--shadow-card)` for resting elevation
  - [x] 🟩 Add hover state: `translateY(-2px)` + `var(--shadow-elevated)` with `var(--transition-fast)`
  - [x] 🟩 Increase padding from `14px` to `16px` for more breathing room
  - [x] 🟩 Strengthen internal hierarchy: bump `.place-name` font-size slightly, ensure rating and walk-time have distinct visual weight

- [x] 🟩 **Step 3: Responsive adjustments**
  - [x] 🟩 Update 768px breakpoint: card padding already stepped down (16→12px) by existing rule
  - [x] 🟩 Update 640px breakpoint: tighten callout padding (10px 14px → 8px 12px)
  - [x] 🟩 Confirm horizontal scroll behavior unchanged (no layout changes to `.place-cards`)
  - [x] 🟩 Add print reset: strip place-card shadows

- [x] 🟩 **Step 4: Visual verification**
  - [x] 🟩 App imports cleanly, no syntax errors
  - [x] 🟩 Template conditionals already gate insights — old snapshots unaffected
  - [ ] 🟥 Manual browser test: verify callout + card styling on a live snapshot (user)
