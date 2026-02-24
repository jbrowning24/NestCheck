# NES-73: Design Token Cleanup

**Goal:** Eliminate remaining hardcoded values in CSS and HTML templates so every color, radius, and shadow routes through `:root` tokens in `base.css`.

**Out of scope:** Builder dashboard, spacing/type scale tokens, `tokens.css` split, print-only values.

---

## Phase 1 — CSS hardcoded values + radius merge

| Step | Task | Status |
|------|------|--------|
| 1a | Add new tokens to `:root` in `base.css` | ✅ |
| 1b | Replace hardcoded hex values in `index.css` | ✅ |
| 1c | Replace hardcoded hex value in `report.css` | ✅ |
| 1d | Replace hardcoded hex + radius in `pricing.css` | ✅ |
| 1e | Merge `10px` border-radius → `var(--radius-lg)` across files | ✅ |

## Phase 2 — HTML inline style extraction

| Step | Task | Status |
|------|------|--------|
| 2a | Extract cookie banner inline styles to `.cookie-banner` in `base.css` | ✅ |
| 2b | Update `_base.html` to use `.cookie-banner` class | ✅ |
| 2c | Extract `index.html` inline styles to classes | ✅ |

## Verification

| Check | Status |
|-------|--------|
| Grep for remaining non-token hex values | ✅ |

---

**Overall progress: 100%**

### Remaining non-token values (intentionally deferred)

- `#93c5fd` — cookie banner link color (dark/inverted context, no matching light-theme token)
- `#ddd` × 2 — print-only border color in `report.css`
- Builder dashboard — self-contained dark theme, out of scope
