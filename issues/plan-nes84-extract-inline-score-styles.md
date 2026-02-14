# NES-84: Extract Inline Score Colors to Semantic CSS Classes

**Overall Progress:** `100%`

## TLDR
Extract the single remaining inline score-driven `style=` attribute in `_result_sections.html` into semantic CSS classes, and add the missing `.score-failed` CSS rule that's already referenced in the template but has no definition.

## Critical Decisions
- **New class names `score-good` / `score-moderate` / `score-poor`** — mirrors the existing `badge-pass` / `badge-borderline` / `badge-fail` naming convention but scoped to text color only (not background + color like badges). Clean semantic intent.
- **`.score-failed` gets border + muted background** — it's applied to `.verdict-card` when the score gate fails. A subtle fail treatment (tinted background, fail-colored left border) signals the failed state without overwhelming, consistent with how `.proximity-very_close` handles danger styling.
- **No cleanup of unused `.badge-great` / `.badge-ok` / `.badge-painful`** — out of scope for this ticket.

## Tasks:

- [x] 🟩 **Step 1: Add semantic score classes to `base.css`**
  - [x] 🟩 After the `.badge-painful` rule (line 153), add `.score-good`, `.score-moderate`, `.score-poor` classes using existing design tokens
  - [x] 🟩 Add `.score-failed` rule with fail-themed styling for the verdict card

- [x] 🟩 **Step 2: Replace inline style in `_result_sections.html`**
  - [x] 🟩 Replace `style="color: ..."` at line 231 with `class="{% if ... %}score-good{% elif ... %}score-moderate{% else %}score-poor{% endif %}"`
  - [x] 🟩 Preserve thresholds (7 and 5), display text, and all surrounding markup exactly as-is

- [x] 🟩 **Step 3: Verify**
  - [x] 🟩 Confirm no other inline styles were modified (index.html lines 65, 69, 116 untouched)
  - [x] 🟩 Confirm no other template files were changed
  - [x] 🟩 Produce status report with exact CSS rules added and lines changed
