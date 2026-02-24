# NES-43: Design Tokens — Colors, Spacing, Type Scale

**Overall Progress:** `100%`

## TLDR
Extract existing CSS custom properties from `base.css` into a dedicated `tokens.css` file, and add new spacing, typography, and transition tokens based on actual codebase usage. No visual changes — tokens are just made available for subsequent restyle phases.

## Critical Decisions
- **File split:** Move all existing `:root` tokens from `base.css` → `tokens.css` (single source of truth)
- **Text colors:** Migrate all 12 variants as-is — defer rationalization to a later phase
- **Spacing tokens:** Named by px equivalent (e.g. `--space-8`) with values in actual use, not a theoretical clean grid
- **Font size units:** `rem` (modern best practice) — conversion from existing `em`/`px` happens when tokens are adopted, not now
- **Dark mode:** Light-only. No stubs.
- **Builder dashboard:** Out of scope (self-contained dark theme)

## Reference: Current State
- `base.css` lines 7–95: `:root` block with ~45 color tokens, 1 font token, 3 radius tokens, 2 shadow tokens
- `_base.html` line 14: loads `base.css` for all pages
- No spacing, font-size, font-weight, line-height, or transition tokens exist yet

## Tasks

- [x] 🟩 **Step 1: Create `static/css/tokens.css` with existing tokens**
  - [x] 🟩 Create `tokens.css` containing the full `:root` block currently in `base.css` lines 7–95
  - [x] 🟩 Organize into clearly commented sections: Brand, Backgrounds, Text, Borders, Status, Accent, Interactive, Overlay, Typography, Radius, Shadows

- [x] 🟩 **Step 2: Add spacing tokens**
  - [x] 🟩 Define `--space-{n}` tokens for each px value actually in use across CSS files:
    - `2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 30, 32, 36, 40, 60`
  - [x] 🟩 Values stay in `px` (spacing in rem is fragile when root font-size varies)

- [x] 🟩 **Step 3: Add typography tokens**
  - [x] 🟩 Define `--font-size-*` scale in `rem`, covering all sizes in use:
    - Display: `3rem, 2.6rem, 2.3rem, 2.2rem, 2rem` (score-number, hero h1, pricing h1)
    - Heading: `1.5rem, 1.35rem, 1.15rem, 1.1rem, 1.05rem, 1.02rem` (ws-value, logo, section h2, subheadings)
    - Body: `1rem, 0.95rem, 0.92rem, 0.9rem, 0.88rem` (base, nav links, card text, detail text)
    - Small: `0.85rem, 0.82rem, 0.8rem, 0.78rem, 0.75rem, 0.72rem` (captions, labels, fine print)
    - Pixel-based: `--font-size-input: 16px` (prevents iOS zoom), `--font-size-button: 15px`, `--font-size-cookie: 14px`
  - [x] 🟩 Define `--font-weight-*` tokens: `medium (500), semibold (600), bold (700), extrabold (800)`
  - [x] 🟩 Define `--line-height-*` tokens: `none (1), tight (1.3), normal (1.5), relaxed (1.6), loose (1.7)`
  - [x] 🟩 Define `--letter-spacing-*` tokens: `tight (-0.02em), wide (0.03em), wider (0.04em)`

- [x] 🟩 **Step 4: Add transition tokens**
  - [x] 🟩 Define `--transition-fast: 0.2s ease` (covers all current hardcoded transitions)

- [x] 🟩 **Step 5: Wire up `tokens.css` in templates**
  - [x] 🟩 Add `<link rel="stylesheet" href="tokens.css">` in `_base.html` **before** the existing `base.css` link
  - [x] 🟩 Remove the `:root { ... }` block from `base.css`, update header comment to point to `tokens.css`

- [x] 🟩 **Step 6: Verify zero visual change**
  - [x] 🟩 Confirm all 53 existing `var()` references resolve to tokens in `tokens.css`
  - [x] 🟩 Smoke test: index (200), pricing (200), 404 (404) — all load `tokens.css` before `base.css`
  - [x] 🟩 No orphaned `var()` references, no residual `:root` block in `base.css`
