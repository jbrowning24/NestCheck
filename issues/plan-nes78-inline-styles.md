# NES-78: Extract Inline Styles to CSS Classes

**Overall Progress:** `100%`

## TLDR
Remove all 7 inline `style=` attributes from `_result_sections.html` by extracting them to named CSS classes in `report.css`. One data-driven instance (dimension bar width) migrates to a CSS custom property pattern; the rest become static classes.

## Critical Decisions
- **Dimension bar width:** Use `style="--fill: X%"` + `width: var(--fill)` in CSS — keeps data-driven value out of presentation rules
- **Road noise sub-elements:** Flat component names (`.road-noise-detail`, `.road-noise-toggle`, etc.) — these are card-specific, not reusable modifiers
- **Library count footnote:** New `.section-footnote` class — semantic name describing its role (faint summary line below a list)
- **Collapsible toggle redundancy:** Line 508 sets `cursor:pointer` inline but `.collapsible-toggle` already declares it — just drop the duplicate

## Tasks

- [x] 🟩 **Step 1: Add new CSS classes to report.css**
  - [x] 🟩 Add `width: var(--fill)` to `.dimension-bar-fill`
  - [x] 🟩 Add `.section-footnote` (margin-top: 8px + text-faint-sm sizing)
  - [x] 🟩 Add `.road-noise-detail` (margin-top:2px, font-size:0.85em, opacity:0.85)
  - [x] 🟩 Add `.road-noise-toggle` (margin-top:6px — cursor already inherited from `.collapsible-toggle`)
  - [x] 🟩 Add `.road-noise-label` (font-size:0.82em, opacity:0.7 — used by both collapse icon and "About the estimate" span)
  - [x] 🟩 Add `.road-noise-methodology` (font-size:0.8em, opacity:0.65, margin-top:4px)

- [x] 🟩 **Step 2: Update template — dimension bar (line 51)**
  - [x] 🟩 Change `style="width: X%"` → `style="--fill: X%"`

- [x] 🟩 **Step 3: Update template — library footnote (line 431)**
  - [x] 🟩 Replace `class="text-faint-sm" style="margin-top: 8px;"` → `class="section-footnote"`

- [x] 🟩 **Step 4: Update template — road noise card (lines 505-512)**
  - [x] 🟩 Line 505: Replace `class="proximity-detail" style="..."` → `class="proximity-detail road-noise-detail"`
  - [x] 🟩 Line 508: Replace `style="margin-top:6px; cursor:pointer;"` → `class="road-noise-toggle"` (add to existing class attr)
  - [x] 🟩 Line 509: Replace `style="font-size:0.82em; opacity:0.7;"` → `class="road-noise-label"` (add to existing class attr)
  - [x] 🟩 Line 510: Replace `style="font-size:0.82em; opacity:0.7;"` → `class="road-noise-label"`
  - [x] 🟩 Line 512: Replace `style="font-size:0.8em; opacity:0.65; margin-top:4px;"` → `class="road-noise-methodology"` (add to existing class attr)

- [x] 🟩 **Step 5: Verify zero inline styles remain**
  - [x] 🟩 Grep `_result_sections.html` for `style=` — only the dimension bar `style="--fill:` should remain
