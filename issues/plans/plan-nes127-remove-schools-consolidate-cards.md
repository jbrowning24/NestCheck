# Implementation Plan: NES-127 — Remove Schools Messaging and Consolidate Landing Page Cards

**Progress:** 100% · **Status:** Complete
**Last updated:** 2026-02-16

## TLDR
Remove all schools references from landing, base, and pricing templates (schools are feature-flagged off). Replace the overlapping "Family & Schools" and "Health & Safety" cards with "Proximity & Safety" and "Daily Errands" so the landing page accurately reflects live product capabilities.

## Scope
**In scope:**
- `templates/index.html` — cards, hero tagline, loading overlay, meta descriptions
- `templates/_base.html` — meta descriptions (fallback when child templates don't override)
- `templates/pricing.html` — features list, meta descriptions

**Out of scope:**
- `STAGE_DISPLAY` JS object and loading stage logic (schools stage already gated on ENABLE_SCHOOLS)
- Python files
- `templates/snapshot.html`
- Any card other than Family & Schools and Health & Safety

## Key Decisions
| # | Decision | Rationale |
|---|----------|------------|
| 1 | Replace two cards with two new cards (6 total) | Consolidate overlapping messaging; Proximity & Safety covers highway/gas/road/rail; Daily Errands covers grocery/pharmacy/essentials |
| 2 | Add emoji icons to new cards only | User-specified: 🛤️ for Proximity & Safety, 🛒 for Daily Errands; existing cards stay iconless for consistency with current design |
| 3 | Remove "schools" from all meta and copy | Product does not deliver schools when ENABLE_SCHOOLS=false; avoid overpromising |

## Assumptions
- `_base.html` meta blocks are overridden by `index.html` and `pricing.html` when those pages render; we still update `_base.html` for any pages that extend it without overriding (e.g. privacy, terms).
- Grammar after removing "schools": "walkability, parks, transit, and safety" (Oxford comma before "and" preserved where present).

## Tasks

- [x] 🟩 **1. Replace landing page feature cards** · _S_
  Replace Family & Schools and Health & Safety with Proximity & Safety and Daily Errands. Final grid: Green Escape, Urban Access, Proximity & Safety, Daily Errands, Daily Essentials, Final Score.
  - [x] 🟩 1.1 In `templates/index.html`, delete the two `<div class="feature-card">` blocks for "Family & Schools" (lines 123–126) and "Health & Safety" (lines 127–130)
  - [x] 🟩 1.2 Insert two new feature-card blocks in the same position (between Urban Access and Daily Essentials):
    - Proximity & Safety: `<h3>🛤️ Proximity &amp; Safety</h3>` + `<p>Distance from highways, gas stations, high-traffic roads, and rail corridors.</p>`
    - Daily Errands: `<h3>🛒 Daily Errands</h3>` + `<p>Walking distance to grocery stores, pharmacies, and everyday essentials.</p>`

- [x] 🟩 **2. Update hero tagline** · _S_
  Remove "schools" from the hero tagline so it matches live product capabilities.
  - [x] 🟩 2.1 In `templates/index.html` line 72, change the tagline from `walkability, green space, transit, schools, and daily-life quality` to `walkability, green space, transit, and daily-life quality`

- [x] 🟩 **3. Update loading overlay text** · _S_
  Remove "schools" from the static loading overlay subtitle.
  - [x] 🟩 3.1 In `templates/index.html` line 60, change `Checking parks, transit, schools, safety, and more.` to `Checking parks, transit, safety, and more.`

- [x] 🟩 **4. Update index.html meta descriptions** · _S_
  Remove "schools" from meta and og:description when on landing (no result).
  - [x] 🟩 4.1 Line 25: change `walkability, parks, transit, schools, and safety` to `walkability, parks, transit, and safety`
  - [x] 🟩 4.2 Line 35: same change for og:description

- [x] 🟩 **5. Update _base.html meta descriptions** · _S_
  Remove "schools" from fallback meta used by pages that don't override.
  - [x] 🟩 5.1 Line 7: change `walkability, parks, transit, schools, and safety` to `walkability, parks, transit, and safety`
  - [x] 🟩 5.2 Line 10: same change for og:description

- [x] 🟩 **6. Update pricing.html features and meta** · _S_
  Remove school/childcare from features list and meta.
  - [x] 🟩 6.1 Remove the `<li>School &amp; childcare proximity mapping</li>` line (line 44)
  - [x] 🟩 6.2 Line 5: change meta description from `walkability, parks, transit, schools, and safety` to `walkability, parks, transit, and safety`
  - [x] 🟩 6.3 Line 9: same change for og:description

## Verification
- [ ] Landing page shows 6 cards: Green Escape, Urban Access, Proximity & Safety (🛤️), Daily Errands (🛒), Daily Essentials, Final Score
- [ ] No occurrence of "schools" or "School & childcare" in index.html, _base.html, or pricing.html (except STAGE_DISPLAY)
- [ ] Hero tagline reads "walkability, green space, transit, and daily-life quality"
- [ ] Loading overlay subtitle reads "Checking parks, transit, safety, and more."
- [ ] Pricing features list has no school/childcare item; meta descriptions omit schools

---

## Status Report (post-execution)

Use this section to record what was changed. Fill in after execution.

### Files changed

**templates/index.html**
| Location | Removed | Added/Modified |
|---------|---------|-----------------|
| Lines 123–130 | Family & Schools card + Health & Safety card | Proximity & Safety card + Daily Errands card |
| Line 72 | `schools, and` in tagline | (removed) |
| Line 60 | `schools, ` in loading-sub | (removed) |
| Line 25 | `schools, and` in meta description | (removed) |
| Line 35 | `schools, and` in og:description | (removed) |

**Exact final text (index.html):**
- Line 60: `<div class="loading-sub">Checking parks, transit, safety, and more.</div>`
- Line 72: `<p class="tagline">Evaluate any U.S. address for walkability, green space, transit, and daily-life quality — instant results, shareable link.</p>`
- Line 25: `<meta name="description" content="Enter any address and get a detailed evaluation of walkability, parks, transit, and safety. Know before you move.">`
- Line 35: `<meta property="og:description" content="Enter any address and get a detailed evaluation of walkability, parks, transit, and safety.">`
- Cards (replace lines 123–130):
```html
  <div class="feature-card">
    <h3>🛤️ Proximity &amp; Safety</h3>
    <p>Distance from highways, gas stations, high-traffic roads, and rail corridors.</p>
  </div>
  <div class="feature-card">
    <h3>🛒 Daily Errands</h3>
    <p>Walking distance to grocery stores, pharmacies, and everyday essentials.</p>
  </div>
```

**templates/_base.html**
| Location | Removed | Added/Modified |
|---------|---------|-----------------|
| Line 7 | `schools, and` in meta description | (removed) |
| Line 10 | `schools, and` in og:description | (removed) |

**Exact final text (_base.html):**
- Line 7: `<meta name="description" content="NestCheck evaluates any address for walkability, parks, transit, and safety — so families can make confident moving decisions.">`
- Line 10: `<meta property="og:description" content="NestCheck evaluates any address for walkability, parks, transit, and safety — so families can make confident moving decisions.">`

**templates/pricing.html**
| Location | Removed | Added/Modified |
|---------|---------|-----------------|
| Line 44 | `<li>School &amp; childcare proximity mapping</li>` | (deleted) |
| Line 5 | `schools, and` in meta description | (removed) |
| Line 9 | `schools, and` in og:description | (removed) |

**Exact final text (pricing.html):**
- Line 5: `<meta name="description" content="NestCheck pricing — first evaluation free, then $9 each. Get detailed reports on walkability, parks, transit, and safety for any address.">`
- Line 9: `<meta property="og:description" content="NestCheck pricing — first evaluation free, then $9 each. Get detailed reports on walkability, parks, transit, and safety for any address.">`
- Features list: remove line 44 entirely. Remaining `<li>` order: Health & safety screening, Green escape & park quality, Transit/walkability/commute, Daily essentials, Final livability score, Shareable snapshot link, JSON & CSV export, Print-ready layout.

### Ambiguities / line number drift
- Line numbers may shift after edits. Use content search to locate if line numbers differ.
