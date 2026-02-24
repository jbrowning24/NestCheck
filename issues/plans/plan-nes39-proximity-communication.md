# NES-39: Proximity & Environment — Show and Prove

**Overall Progress:** `100%`

## TLDR

Make the existing 3 proximity checks (gas station, highway, high-traffic road) communicate better. Add a synthesized insight paragraph at the top of the section, put icons on the proximity cards, and give users a satellite link when we can't verify something — so "Unverified" becomes actionable instead of a dead end. No new checks, no layout overhaul.

## Critical Decisions

- **Synthesis lives in Python, not the template** — `_proximity_synthesis()` in `property_evaluator.py` takes `presented_checks` and returns a plain sentence. Added to `generate_insights()` under a `proximity` key. Old snapshots get it for free via the backfill at `app.py:1274`.
- **Satellite link is template-only** — Built from `result.coordinates` already in template context. No Python changes needed. Renders as a small linked line below the explanation, only for `VERIFICATION_NEEDED` items.
- **Unicode icons, not SVG** — Reuse `✓ ✗ ?` from the backward-compat path. Color them to match the band (green/amber/red) via CSS.
- **Six synthesis permutations** — Handled explicitly, not concatenated. The insight reads like a sentence a friend would say.

## Tasks

- [x] 🟩 **Phase 1: Synthesis logic (Python)**
  - [x] 🟩 Add `proximity_synthesis(presented_checks) -> str` to `property_evaluator.py`
    - Takes the list of SAFETY-category presented checks
    - Returns a plain-English paragraph based on the combination of result types
    - Six explicit branches:
      1. 3 CLEAR → "No environmental concerns detected near this address."
      2. 2 CLEAR + 1 VERIFICATION_NEEDED → names the unverified check
      3. 1 CLEAR + 2 VERIFICATION_NEEDED → names both unverified checks
      4. 3 VERIFICATION_NEEDED → all unverified message
      5. 1+ CONFIRMED_ISSUE (no VERIFICATION_NEEDED) → names specific concerns + notes clears
      6. CONFIRMED_ISSUE + VERIFICATION_NEEDED mix → names concerns + notes unverified items
  - [x] 🟩 Add `proximity` key to `generate_insights()` in `app.py`
    - Call `proximity_synthesis()` with the `presented_checks` from `result_dict`
    - Follows same pattern as `_insight_neighborhood()`, `_insight_parks()`, etc.

- [x] 🟩 **Phase 2: Template & CSS updates**
  - [x] 🟩 Add synthesis insight to section 6 in `_result_sections.html`
    - `<p class="section-insight">{{ result.insights.proximity }}</p>` below the `<h2>`, guarded by `{% if result.insights... %}`
    - Same pattern as sections 3, 4, 5
  - [x] 🟩 Add Unicode icons to proximity-band cards in `_result_sections.html`
    - `✓` for CLEAR, `✗` for CONFIRMED_ISSUE, `?` for VERIFICATION_NEEDED
    - Inline with `.proximity-name`, before the headline text
    - Wrap in `<span>` with a class for color styling
  - [x] 🟩 Add icon color classes to `report.css`
    - `.proximity-icon-clear { color: var(--color-pass-text); }`
    - `.proximity-icon-issue { color: var(--color-fail-text); }`
    - `.proximity-icon-unverified { color: var(--color-warning-text); }`
  - [x] 🟩 Add satellite link for VERIFICATION_NEEDED items in `_result_sections.html`
    - Small linked line below `.proximity-detail`: "View satellite imagery →"
    - URL: `https://www.google.com/maps/@{{ result.coordinates.lat }},{{ result.coordinates.lng }},18z/data=!3m1!1e1`
    - `target="_blank" rel="noopener"`
    - Only renders when `pc.result_type == 'VERIFICATION_NEEDED'` and `result.coordinates` exists
    - Minimal CSS for the link (muted color, small font, subtle)

- [x] 🟩 **Phase 3: Verification**
  - [x] 🟩 Test all six synthesis permutations by reviewing real evaluations or crafting test data
  - [x] 🟩 Verify imports, template parsing, and backward-compat paths preserved
  - [x] 🟩 End-to-end test: Tier1Check → present_checks → proximity_synthesis
  - [x] 🟩 Update UNKNOWN explanation text — removed redundant "Check Google Maps" now that satellite link is in template
