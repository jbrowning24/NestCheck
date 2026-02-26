# Template Drift Audit: index.html vs snapshot.html

## Architecture Overview

Both templates extend `_base.html` and render evaluation results. The result-rendering
logic itself was already extracted into `_result_sections.html` (shared partial). The
remaining duplication is in page scaffolding, metadata, and JavaScript.

```
index.html
  ├── Landing page (unique to index)
  ├── Loading overlay (unique to index)
  ├── Error handling UI (unique to index)
  ├── {% include '_result_sections.html' %}    ← SHARED
  └── <script> block (partially duplicated)

snapshot.html
  ├── Builder diagnostic (similar to index)
  ├── {% include '_result_sections.html' %}    ← SHARED
  ├── {% include '_report_rail.html' %}        ← unique to snapshot
  └── <script> block (partially duplicated)
```

---

## 1. Jinja2 Sections in index.html That Render Results

| # | Section | Lines | Description |
|---|---------|-------|-------------|
| 1 | `{% block meta_description %}` | 21–27 | OG meta with result data |
| 2 | `{% block og_tags %}` | 29–39 | Open Graph tags |
| 3 | Builder diagnostic | 183–194 | `<details>` with JSON dump |
| 4 | `{% include '_result_sections.html' %}` | 197 | Shared result partial |
| 5 | `copyShareLink()` JS | 587–615 | Share link logic |
| 6 | `nativeShare()` JS | 617–639 | Web Share API logic |
| 7 | `toggleSection()` JS | 649–661 | Collapsible section toggle |
| 8 | Keyboard support JS | 663–672 | Enter/Space for toggles |

---

## 2. Corresponding Sections in snapshot.html

| index.html Section | snapshot.html Location | Status |
|--------------------|----------------------|--------|
| `{% block meta_description %}` (L21–27) | L10–16 | **Different** — snapshot adds `is_preview` branch |
| `{% block og_tags %}` (L29–39) | L18–33 | **Different** — see details below |
| Builder diagnostic (L183–194) | L44–57 | **Different** — see details below |
| `_result_sections.html` include (L197) | L61 | **Identical** — same partial, same variable |
| `copyShareLink()` (L587–615) | L77–103 | **Different** — URL construction differs |
| `nativeShare()` (L617–639) | L105–126 | **Different** — variable interpolation differs |
| `toggleSection()` (L649–661) | L136–148 | **Identical** (13 lines) |
| Keyboard support (L663–672) | L151–159 | **Identical** (9 lines) |

---

## 3. Differences Flagged

### 3a. OG Tags — Different Variable Names / Logic

**index.html (L29–39):**
- Uses `{% if result %}` guard
- `og:type` = `"website"`
- `og:url` = `{{ request.host_url }}`
- No OG image tag

**snapshot.html (L18–33):**
- Uses `{% if is_preview %}` branch (3-way: preview / full / fallback)
- `og:type` = `"article"`
- `og:url` = `{{ request.url }}`
- Adds `og:image` pointing to `static/images/og-default.png` (full reports only)

**Verdict:** Intentional divergence. Different contexts require different OG metadata.

### 3b. Builder Diagnostic — Different Data Shape

**index.html (L183–194):**
```jinja2
"snapshot_id": snapshot_id or none,
"snapshot_url": (request.host_url ~ 's/' ~ snapshot_id) if snapshot_id else none,
```

**snapshot.html (L44–57):**
```jinja2
"snapshot_id": snapshot_id,
"snapshot_url": request.url,
"created_at": snapshot.created_at,
"view_count": snapshot.view_count,
```

**Verdict:** Intentional — snapshot page has richer context available (created_at, view_count).

### 3c. `copyShareLink()` — Different URL Construction

**index.html (L587–615):**
```javascript
var snapshotId = '{{ snapshot_id or "" }}';
if (!snapshotId) return;
var url = window.location.origin + '/s/' + snapshotId;
```

**snapshot.html (L77–103):**
```javascript
var url = window.location.href;
```

Event tracking payload also differs:
- index.html: `snapshot_id: snapshotId` (variable)
- snapshot.html: `snapshot_id: '{{ snapshot_id }}'` (template literal)

**Verdict:** Functional divergence. Index must construct the URL (it's not on `/s/` path);
snapshot can use `window.location.href` directly. The core clipboard + feedback + tracking
logic (~20 lines) is identical and extractable.

### 3d. `nativeShare()` — Different Variable Interpolation

**index.html (L617–639):**
```javascript
var snapshotId = '{{ snapshot_id or "" }}';
if (!snapshotId) return;
var url = window.location.origin + '/s/' + snapshotId;
title: {{ (result.address if result else '') | tojson }},
text: {{ ((result.verdict ~ ' · Score: ' ~ result.final_score ~ '/100') if result else '') | tojson }},
```

**snapshot.html (L105–126):**
```javascript
// No guard — snapshot_id always exists on this page
title: {{ result.address | tojson }},
text: {{ (result.verdict ~ ' · Score: ' ~ result.final_score ~ '/100') | tojson }},
url: window.location.href
```

**Verdict:** Index has a `result` guard (may not have result on landing page). Snapshot
doesn't need it. The share/tracking logic body is identical.

### 3e. CSS Includes — Different Stylesheets

**index.html:** `report.css` + `index.css`
**snapshot.html:** `report.css` + `snapshot.css`

**Verdict:** Intentional. Each page has unique layout concerns.

### 3f. Sections Present in One But Not the Other

| Section | index.html | snapshot.html |
|---------|-----------|---------------|
| Loading overlay | Yes (L50–63) | No |
| Landing page / hero / form | Yes (L65–167) | No |
| Async job polling JS | Yes (L220–571) | No |
| Google Places autocomplete JS | Yes (L675–706) | No |
| Stripe checkout JS | Yes (L440–492) | No |
| Email gate UI | Yes (L121–125) | No |
| Persona selector | Yes (L98–119) | No |
| `_report_rail.html` sidebar | No | Yes (L63–65) |
| Preview checkout JS (NES-132) | No | Yes (L162–193) |
| Payment pending polling (NES-132) | No | Yes (L197–226) |
| `section-nav.js` include | No | Yes (L229) |
| `{% block nav_links %}` | "Dashboard" only | "Evaluate an address" + "Dashboard" |

### 3g. JavaScript Present in One But Not the Other

| Function/Block | index.html | snapshot.html |
|----------------|-----------|---------------|
| `STAGE_DISPLAY` / `startPolling` / `submitEvaluation` | ~350 lines | absent |
| `showFreeTierExhausted` / `startCheckout` | ~80 lines | absent |
| Persona pill toggle | ~12 lines | absent |
| Places autocomplete | ~25 lines | absent |
| Preview unlock checkout (NES-132) | absent | ~30 lines |
| Payment pending poll (NES-132) | absent | ~25 lines |

---

## 4. Lines Functionally Identical Between the Two Files

| Code Block | Lines |
|-----------|-------|
| `_result_sections.html` (shared include) | 900 |
| `toggleSection()` function | 13 |
| Keyboard support for collapsible toggles | 9 |
| `copyShareLink()` core logic (clipboard + feedback + tracking) | ~20 |
| `nativeShare()` core logic (share + tracking) | ~18 |
| `csrfToken()` helper | 3 |
| `neighborhood-map.js` script include | 1 |

**Total functionally identical: ~964 lines** (dominated by the shared `_result_sections.html` partial,
which was already extracted).

Of the remaining inline JS, **~63 lines** are functionally identical between the two files.

---

## 5. Recommendations for Extraction

### Already Extracted (Good)
- `_result_sections.html` — all result rendering (900 lines). Well done.
- `_macros.html` — `fmt_time`, `data_row`, `score_ring` helpers.
- `_report_rail.html` — snapshot sidebar.
- `_eval_snippet.html` — condensed preview card.

### Recommended Extractions

| Priority | Partial Name | Content | Lines Saved | Notes |
|----------|-------------|---------|-------------|-------|
| **High** | `_share_scripts.html` | `csrfToken()`, `copyShareLink()`, `nativeShare()`, `toggleSection()`, keyboard handler | ~63 | Both files duplicate these 5 functions nearly identically. Extract with template vars for URL/snapshot_id differences. |
| **Medium** | `_builder_diagnostic.html` | Builder diagnostic `<details>` block | ~12 | Minor differences (snapshot has `created_at`/`view_count`). Could accept a `diagnostic_data` dict parameter. |
| **Low** | `_og_tags.html` | Meta description + OG tags | ~15 | Significant branching differences (preview/full/landing). Extraction possible but would trade readable inline logic for parameterized complexity. |

### Not Worth Extracting

| Section | Reason |
|---------|--------|
| Loading overlay | Only used by index.html |
| Async polling / Stripe JS | Only used by index.html |
| Preview checkout JS | Only used by snapshot.html |
| Landing page hero | Only used by index.html |

---

## Summary

The most impactful drift has already been resolved: `_result_sections.html` consolidates
~900 lines of result rendering logic. The remaining duplication is **~63 lines of JavaScript**
(`csrfToken`, `copyShareLink`, `nativeShare`, `toggleSection`, keyboard handler) that could
be extracted into a `_share_scripts.html` partial or a shared `.js` file. All other differences
between the two templates are intentional page-level concerns (landing page, loading overlay,
sidebar nav).
