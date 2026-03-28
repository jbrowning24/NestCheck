# NES-321: Inline Terminology Explanations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace technical jargon in NestCheck reports with plain-language text and inline annotations so homebuyers understand every term on first read.

**Architecture:** Two-layer content changes (term elimination + inline annotations) plus a centralized `TERM_GLOSSARY` dict exposed as a Jinja global. Annotations use lightweight `<span>`/`<div>` elements styled with annotation tokens (not the `annotation()` macro, which uses `<div>` + 120-char truncation — unsuitable for the EJScreen indicator grid layout). All changes are presentation-only (no scoring, storage, or serialization changes).

**Tech Stack:** Python/Flask (app.py), Jinja2 templates

**Spec:** `docs/superpowers/specs/2026-03-28-nes-321-inline-terminology-explanations-design.md`

---

## File Map

| File | Responsibility | Change Type |
|---|---|---|
| `app.py` | `TERM_GLOSSARY` dict + Jinja global, cross-ref template rewrites, empty-state label rewrites | Modify |
| `templates/_result_sections.html` | EJScreen section rewrites, percentile annotations, school label rewrites, FRL annotation (once above school list) | Modify |
| `templates/index.html` | Homepage "EPA EJScreen 2.3" → plain language | Modify |

---

### Task 1: Add TERM_GLOSSARY dict and Jinja global in app.py

**Files:**
- Modify: `app.py:225` (after `score_bands` global)

- [ ] **Step 1: Add TERM_GLOSSARY dict and expose as Jinja global**

After the `app.jinja_env.globals["score_bands"]` line (~line 225), add:

```python
# NES-321: Plain-language glossary for technical terms in report templates.
# Static content — exposed as Jinja global following NES-326 score_bands pattern.
TERM_GLOSSARY = {
    "free_reduced_lunch": "Share of students from lower-income households",
    "chronic_absenteeism": "Students missing 10% or more of school days",
}
app.jinja_env.globals["term_glossary"] = TERM_GLOSSARY
```

- [ ] **Step 2: Verify app starts**

Run: `python -c "from app import app; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(NES-321): add TERM_GLOSSARY dict and Jinja global"
```

---

### Task 2: Rewrite cross-reference annotation templates in app.py

**Files:**
- Modify: `app.py:938-957` (`_EJSCREEN_CROSS_REFS`)

- [ ] **Step 1: Replace jargon in cross-ref templates**

Change the two template strings in `_EJSCREEN_CROSS_REFS`:

```python
_EJSCREEN_CROSS_REFS = [
    {
        "address_checks": ["Superfund (NPL)"],
        "ejscreen_field": "PNPL",
        "threshold": 80,
        "template": (
            "Address clear, but this area scores higher than {pct}% "
            "of U.S. neighborhoods for Superfund proximity."
        ),
    },
    {
        "address_checks": ["TRI facility", "ust_proximity"],
        "ejscreen_field": "PTSDF",
        "threshold": 80,
        "template": (
            "No nearby facilities found, but this area scores higher "
            "than {pct}% of U.S. neighborhoods for hazardous waste proximity."
        ),
    },
]
```

- [ ] **Step 2: Verify cross-ref templates are under 120 chars**

Both templates must be ≤120 characters when rendered (per spec Section 4.11). Check with max `pct=99`:
- Superfund: "Address clear, but this area scores higher than 99% of U.S. neighborhoods for Superfund proximity." = 97 chars ✓
- Hazardous waste: "No nearby facilities found, but this area scores higher than 99% of U.S. neighborhoods for hazardous waste proximity." = 118 chars ✓

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(NES-321): rewrite cross-ref annotations to plain language"
```

---

### Task 3: Rewrite EJScreen section in _result_sections.html

**Files:**
- Modify: `templates/_result_sections.html:1156-1200`

- [ ] **Step 1: Update EJScreen indicator labels (line 1156-1169)**

Replace the `ej_indicators` tuple list with plain-language labels:

```jinja2
          {% set ej_indicators = [
            ("PM25",   "Fine Particle Pollution (PM2.5)",  true),
            ("OZONE",  "Ozone",                            false),
            ("DSLPM",  "Diesel Particulate Matter",         true),
            ("CANCER", "Air Toxics Cancer Risk",            true),
            ("RESP",   "Air Toxics Respiratory Risk",       false),
            ("PTRAF",  "Traffic Proximity",                 false),
            ("PNPL",   "Superfund Proximity",               true),
            ("PRMP",   "RMP Facility Proximity",            false),
            ("PTSDF",  "Hazardous Waste Proximity",         true),
            ("UST",    "Underground Storage Tanks",         false),
            ("PWDIS",  "Wastewater Discharge Proximity",    false),
            ("LEAD",   "Lead Paint Risk",                   true),
          ] %}
```

Changes: `PM2.5 Particulate Matter` → `Fine Particle Pollution (PM2.5)`, `Air Toxics Respiratory HI` → `Air Toxics Respiratory Risk`, `Wastewater Discharge` → `Wastewater Discharge Proximity`, `Lead Paint (Pre-1960 Housing)` → `Lead Paint Risk`.

- [ ] **Step 2: Rewrite the area-context-note (line 1177)**

Replace:
```html
<p class="area-context-note">Census block group indicators from EPA EJScreen (national percentiles)</p>
```
With:
```html
<p class="area-context-note">Neighborhood-level environmental indicators from the EPA</p>
```

- [ ] **Step 3: Replace indicator div block with version including percentile annotations (lines 1194-1200)**

Replace the entire `<div class="ejscreen-indicator ...">` block with a version that includes a directional annotation span:

```jinja2
                  <div class="ejscreen-indicator {{ indicator_css }}">
                    <span class="ejscreen-indicator__label">{{ label }}</span>
                    <span class="ejscreen-indicator__value">{{ "%.0f"|format(pct) }}th</span>
                    {% if pct >= 80 %}
                      <span class="ejscreen-indicator__badge"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></span>
                    {% endif %}
                    <span class="ejscreen-indicator__annotation">
                      {%- if pct >= 80 -%}
                        Higher than {{ "%.0f"|format(pct) }}% of U.S. neighborhoods &mdash; elevated concern
                      {%- elif pct >= 50 -%}
                        Higher than {{ "%.0f"|format(pct) }}% of U.S. neighborhoods
                      {%- else -%}
                        Lower than {{ "%.0f"|format(100 - pct) }}% of U.S. neighborhoods
                      {%- endif -%}
                    </span>
                  </div>
```

- [ ] **Step 4: Rewrite source line (lines 1204-1209)**

Replace:
```html
            <div class="ejscreen-source">
              Source: <a href="https://www.epa.gov/ejscreen" target="_blank" rel="noopener">EPA EJScreen 2024</a>
              &bull; Block group {{ ej._block_group_id if ej._block_group_id else "N/A" }}
              &bull; {{ "%.0f"|format(ej._distance_m) if ej._distance_m else "?" }} m from address
            </div>
```
With:
```html
            <div class="ejscreen-source">
              <span title="Census block group {{ ej._block_group_id if ej._block_group_id else 'N/A' }}">Source: <a href="https://www.epa.gov/ejscreen" target="_blank" rel="noopener noreferrer">U.S. Environmental Protection Agency</a></span>
            </div>
```

Note: Added `noreferrer` to the `rel` attribute per CLAUDE.md rule.

- [ ] **Step 5: Add CSS for the annotation span**

Add to `static/css/report.css` (in the EJScreen indicator section):

```css
.ejscreen-indicator__annotation {
  display: block;
  width: 100%;
  font-size: var(--type-detail);
  color: var(--color-text-secondary);
  font-weight: var(--weight-normal);
  margin-top: var(--space-xs);
}
```

- [ ] **Step 6: Verify template renders without errors**

Run: `python -c "from app import app; client = app.test_client(); print(client.get('/').status_code)"`
Expected: `200`

- [ ] **Step 7: Commit**

```bash
git add templates/_result_sections.html static/css/report.css
git commit -m "feat(NES-321): rewrite EJScreen section with plain language and percentile annotations"
```

---

### Task 4: Rewrite school section labels in _result_sections.html

**Files:**
- Modify: `templates/_result_sections.html:1108,1120,1147`

- [ ] **Step 1: Replace "ELA proficiency" label (line 1108)**

Change:
```html
              <div class="stat-card__label">ELA proficiency</div>
```
To:
```html
              <div class="stat-card__label">Reading proficiency (ELA)</div>
```

- [ ] **Step 2: Add annotation below "Chronic absenteeism" label (line 1120)**

Change:
```html
              <div class="stat-card__label">Chronic absenteeism</div>
```
To:
```html
              <div class="stat-card__label">Chronic absenteeism</div>
              <div class="stat-card__annotation">{{ term_glossary.chronic_absenteeism }}</div>
```

- [ ] **Step 3: Replace "NCES 2022–23" in source line (line 1147)**

Change:
```html
              &middot; NCES 2022&ndash;23
```
To:
```html
              &middot; U.S. Dept. of Education 2022&ndash;23
```

- [ ] **Step 4: Add CSS for stat-card annotation**

Add to `static/css/report.css` (in the school district section):

```css
.stat-card__annotation {
  font-size: var(--type-detail);
  color: var(--color-text-secondary);
  font-weight: var(--weight-normal);
  margin-top: var(--space-xs);
}
```

- [ ] **Step 5: Commit**

```bash
git add templates/_result_sections.html static/css/report.css
git commit -m "feat(NES-321): rewrite school section labels to plain language"
```

---

### Task 5: Add FRL annotation once above school list (not per-card)

The FRL glossary annotation should render once above the school cards list, not on every individual school card (which would repeat it N times).

**Files:**
- Modify: `templates/_result_sections.html` (near line 1125, before the school cards loop)

- [ ] **Step 1: Add a single FRL annotation above the school list**

Before the `<div class="nearby-schools-list">` block (~line 1125), add:

```html
          <p class="stat-card__annotation">{{ term_glossary.free_reduced_lunch }}</p>
```

This reuses the `.stat-card__annotation` CSS from Task 4 Step 4.

- [ ] **Step 2: Commit**

```bash
git add templates/_result_sections.html
git commit -m "feat(NES-321): add FRL glossary annotation above school list"
```

---

### Task 6: Rewrite EJScreen empty-state label in app.py

**Files:**
- Modify: `app.py:889,894` (`_CHECK_SOURCE_GROUP` ejscreen entry)

- [ ] **Step 1: Replace "EPA EJScreen" in empty-state label and explanation**

Change:
```python
    "ejscreen": {
        "label": "EPA EJScreen environmental indicators",
        ...
        "explanation": "EPA EJScreen data not available for this area",
    },
```
To:
```python
    "ejscreen": {
        "label": "EPA environmental indicators",
        ...
        "explanation": "EPA environmental data not available for this area",
    },
```

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "feat(NES-321): rewrite EJScreen empty-state labels to plain language"
```

---

### Task 7: Rewrite homepage EJScreen reference in index.html

**Files:**
- Modify: `templates/index.html:277`

- [ ] **Step 1: Replace "EPA EJScreen 2.3" on homepage**

Find the `hp-source-detail` span containing "EPA EJScreen 2.3" and replace with "U.S. Environmental Protection Agency". Keep the rest of the text (e.g., "13 environmental indicators") as-is.

- [ ] **Step 2: Commit**

```bash
git add templates/index.html
git commit -m "feat(NES-321): rewrite homepage EJScreen reference to plain language"
```

---

### Task 8: Run tests and verify

- [ ] **Step 1: Run unit tests**

```bash
python -m pytest tests/ -x -q --ignore=tests/playwright/ --ignore=tests/test_zillow_graphql.py -k "not test_healthz_missing_key and not TestCoverageRoute and not test_dashboard_non_builder_404" 2>&1 | tail -10
```

Expected: All previously-passing tests still pass (1470+).

- [ ] **Step 2: Run Playwright browser tests**

```bash
python -m pytest tests/playwright/ -x -v 2>&1 | tail -50
```

Expected: All browser tests pass. Template changes should not break any existing assertions since we're only changing text content and adding annotation spans.

- [ ] **Step 3: Visual QA checklist**

Start the dev server and open a snapshot that has EJScreen data and school data:
- [ ] EJScreen section heading says "EPA ENVIRONMENTAL PROFILE" (no "EJScreen" in heading)
- [ ] Area context note says "Neighborhood-level environmental indicators from the EPA"
- [ ] Each EJScreen indicator row has a plain-language annotation beneath the percentile value
- [ ] Annotations use directional framing ("Higher than X%..." / "Lower than X%...")
- [ ] >= 80th percentile annotations include " — elevated concern"
- [ ] Source line says "U.S. Environmental Protection Agency" (no block group ID visible, but available on hover via title attribute)
- [ ] "ELA proficiency" now reads "Reading proficiency (ELA)"
- [ ] "Chronic absenteeism" has annotation: "Students missing 10% or more of school days"
- [ ] School source line says "U.S. Dept. of Education 2022–23" (not "NCES 2022–23")
- [ ] School cards show "free/reduced lunch" with annotation: "Share of students from lower-income households"
- [ ] All annotations render correctly on mobile (visible, not behind hover)

- [ ] **Step 4: Commit any fixes from QA**

```bash
git add -A && git commit -m "fix(NES-321): QA adjustments"
```
