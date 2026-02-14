# NES-79: Tablet Breakpoint Strategy

**Overall Progress:** `100%`

## TLDR
Add tablet breakpoints (768px, 1024px) to the existing responsive design. Currently only a single 640px mobile breakpoint exists — the layout jumps straight from desktop to phone with nothing in between. This adds deliberate intermediate steps so tablet users get optimized layouts.

## Critical Decisions
- **Desktop-first approach preserved** — existing styles are desktop-first with `max-width` overrides; we continue that pattern rather than rewriting to mobile-first
- **No CSS custom properties for breakpoints** — CSS custom properties can't be used in `@media` queries; instead, document the breakpoint scale as a comment block in `base.css` alongside design tokens
- **Two new breakpoints only** — `768px` (small tablet) and `1024px` (large tablet); keeps the system simple with three total tiers
- **Surgical per-component rules** — only add media queries where a component genuinely benefits at tablet width; no blanket rewrites

## Breakpoint Scale

| Token | Value | Target |
|-------|-------|--------|
| `--bp-mobile` | 640px | Phone (existing) |
| `--bp-tablet` | 768px | Small tablet / iPad portrait |
| `--bp-desktop` | 1024px | Large tablet / small desktop |

## Tasks:

- [x] 🟩 **Step 1: Document breakpoint strategy in base.css**
  - [x] 🟩 Add a `/* === Breakpoints === */` comment block in `base.css` design tokens section documenting the three breakpoints (640, 768, 1024) as the canonical reference

- [x] 🟩 **Step 2: Add tablet rules to report.css**
  - [x] 🟩 `@media (max-width: 1024px)`: Reduce `.report-section` padding slightly, adjust `.verdict-card` padding for tablet
  - [x] 🟩 `@media (max-width: 768px)`: `.subscore-grid` → 3-column grid, `.dimension-row` tighten gap/spacing, `.place-card` width adjustment
  - [x] 🟩 Verify existing 640px rules still cascade correctly with new breakpoints above them

- [x] 🟩 **Step 3: Add tablet rules to index.css**
  - [x] 🟩 `@media (max-width: 1024px)`: `.hero h1` intermediate font-size (2.3em)
  - [x] 🟩 `@media (max-width: 768px)`: `.features` grid explicit 2-column layout for small tablet

- [x] 🟩 **Step 4: Add tablet rules to snapshot.css**
  - [x] 🟩 `@media (max-width: 768px)`: `.share-bar` tighten gap and button sizing before 640px column-stack

- [x] 🟩 **Step 5: Add tablet rules to pricing.css**
  - [x] 🟩 Reviewed — no changes needed. Single-column centered layout works well at all tablet widths.

- [ ] 🟥 **Step 6: Visual QA across breakpoints**
  - [ ] 🟥 Test report page at 1024px, 768px, 640px widths in browser devtools
  - [ ] 🟥 Test landing page at all three breakpoints
  - [ ] 🟥 Test snapshot/share page at all three breakpoints
  - [ ] 🟥 Confirm no regressions at existing 640px mobile breakpoint
