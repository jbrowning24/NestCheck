# NES-326: Scoring Key Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a data-driven scoring key card below the verdict that decodes score bands, replacing the hardcoded band table.

**Architecture:** A `_build_score_bands_context()` helper in `app.py` reads `SCORING_MODEL.score_bands` and returns display-ready band dicts. Injected globally via `app.jinja_env.globals`. A `scoring_key()` macro in `_macros.html` renders the card. Used in two places: below verdict (with active-band highlight) and in the "How We Score" section (replacing the hardcoded table).

**Tech Stack:** Python/Flask, Jinja2 macros, CSS custom properties from `tokens.css`

**Spec:** `docs/superpowers/specs/2026-03-26-nes-326-scoring-key-card-design.md`

---

### Task 1: Data Helper — `_build_score_bands_context()`

**Files:**
- Modify: `app.py` (add helper + global injection, near line 191 where `oauth_enabled` is set)
- Modify: `app.py` line 34 (add `SCORING_MODEL` to import)
- Test: `tests/test_scoring_key.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_scoring_key.py`:

```python
"""Tests for the scoring key context builder."""
from app import _build_score_bands_context


def test_build_score_bands_context_returns_five_bands():
    bands = _build_score_bands_context()
    assert len(bands) == 5


def test_build_score_bands_context_band_structure():
    bands = _build_score_bands_context()
    for band in bands:
        assert "threshold" in band
        assert "upper_bound" in band
        assert "label" in band
        assert "css_class" in band
        assert "description" in band


def test_build_score_bands_context_upper_bounds():
    bands = _build_score_bands_context()
    # First band (highest threshold) has upper_bound 100
    assert bands[0]["upper_bound"] == 100
    assert bands[0]["threshold"] == 85
    # Each subsequent band's upper_bound = previous band's threshold - 1
    for i in range(1, len(bands)):
        assert bands[i]["upper_bound"] == bands[i - 1]["threshold"] - 1


def test_build_score_bands_context_ranges_no_gaps_no_overlaps():
    bands = _build_score_bands_context()
    for i in range(len(bands) - 1):
        assert bands[i]["threshold"] == bands[i + 1]["upper_bound"] + 1


def test_build_score_bands_context_last_band_starts_at_zero():
    bands = _build_score_bands_context()
    assert bands[-1]["threshold"] == 0


def test_build_score_bands_context_descriptions_not_empty():
    bands = _build_score_bands_context()
    for band in bands:
        assert len(band["description"]) > 0


def test_build_score_bands_context_exact_thresholds():
    bands = _build_score_bands_context()
    thresholds = [b["threshold"] for b in bands]
    assert thresholds == [85, 70, 55, 40, 0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_scoring_key.py -v`
Expected: FAIL with `ImportError: cannot import name '_build_score_bands_context'`

- [ ] **Step 3: Add `SCORING_MODEL` to the import block in `app.py`**

In `app.py` line 34, add `SCORING_MODEL` to the `from scoring_config import (...)` block:

```python
from scoring_config import (
    SCORING_MODEL,
    TIER2_NAME_TO_DIMENSION,
    HEALTH_CHECK_CITATIONS,
    CONFIDENCE_VERIFIED, CONFIDENCE_ESTIMATED, CONFIDENCE_SPARSE, CONFIDENCE_NOT_SCORED,
    _LEGACY_CONFIDENCE_MAP,
    WALK_DRIVE_BOTH_THRESHOLD, WALK_DRIVE_ONLY_THRESHOLD,
)
```

- [ ] **Step 4: Write `_build_score_bands_context()` in `app.py`**

Add after the `app.jinja_env.globals["oauth_enabled"] = _oauth_enabled` line (around line 191):

```python
# ---------------------------------------------------------------------------
# Scoring key context — static band definitions for template rendering
# ---------------------------------------------------------------------------
_BAND_DESCRIPTIONS = {
    "band-exceptional": "Excellent across nearly all dimensions",
    "band-strong": "Good daily fit with minor gaps",
    "band-moderate": "Mixed — some strengths, some limitations",
    "band-limited": "Significant gaps in daily livability",
    "band-poor": "Major limitations across most dimensions",
}


def _build_score_bands_context():
    """Build display-ready band dicts from SCORING_MODEL.score_bands.

    Returns a list of dicts ordered descending by threshold (highest first).
    Each dict has: threshold, upper_bound, label, css_class, description.
    """
    raw = SCORING_MODEL.score_bands  # tuple of ScoreBand, descending
    bands = []
    for i, sb in enumerate(raw):
        bands.append({
            "threshold": sb.threshold,
            "upper_bound": 100 if i == 0 else raw[i - 1].threshold - 1,
            "label": sb.label,
            "css_class": sb.css_class,
            "description": _BAND_DESCRIPTIONS.get(sb.css_class, ""),
        })
    return bands


app.jinja_env.globals["score_bands"] = _build_score_bands_context()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_scoring_key.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py tests/test_scoring_key.py
git commit -m "feat(NES-326): add _build_score_bands_context helper + tests"
```

---

### Task 2: Jinja2 Macro — `scoring_key()`

**Files:**
- Modify: `templates/_macros.html` (append macro after line 334)

- [ ] **Step 1: Add the `scoring_key` macro to `_macros.html`**

Append at the end of the file (after the `a_an` macro):

```jinja2


{# ── scoring_key ─────────────────────────────────────────────────────
   Compact band reference card — "decoder ring" for score bands.
   Renders below verdict (with active highlight) and in How We Score.

   Args:
     bands:              List of band dicts from _build_score_bands_context().
     current_band_class: CSS class of the user's band (optional). Highlights
                         the matching row with a left border + semibold label.
     show_link:          Show "How we score" footer link (default True).
                         Set False when rendering inside the How We Score section.
#}
{% macro scoring_key(bands, current_band_class=None, show_link=True) %}
<div class="scoring-key">
  {% for band in bands %}
  <div class="scoring-key__row{% if current_band_class and band.css_class == current_band_class %} scoring-key__row--active{% endif %}">
    <span class="band-dot {{ band.css_class }}"></span>
    <span class="scoring-key__label">{{ band.label }}</span>
    <span class="scoring-key__range">{{ band.threshold }}–{{ band.upper_bound }}</span>
    <span class="scoring-key__desc">{{ band.description }}</span>
  </div>
  {% endfor %}
  {% if show_link %}
  <a href="#how-we-score" class="scoring-key__link">
    How we score
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      <path d="M4.5 2.5L8.5 6L4.5 9.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
  </a>
  {% endif %}
</div>
{% endmacro %}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add templates/_macros.html
git commit -m "feat(NES-326): add scoring_key macro to _macros.html"
```

---

### Task 3: CSS — `.scoring-key` Component Styles

**Files:**
- Modify: `static/css/report.css` (add after the `.band-label` rule, around line 1632)

- [ ] **Step 1: Add `.scoring-key` CSS rules to `report.css`**

Insert after the existing `.band-label` rule (after line ~1631):

```css
/* ── Scoring Key Card (NES-326) ─────────────────────────────────────── */
.scoring-key {
  background: var(--color-surface-alt);
  border-top: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-8);
}

.scoring-key__row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-1) 0;
  font-size: var(--type-detail);
}

.scoring-key__row--active {
  border-left: 2px solid;
  padding-left: var(--space-2);
}

.scoring-key__row--active .scoring-key__label {
  font-weight: var(--font-weight-semibold);
}

.scoring-key__label {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.scoring-key__range {
  font-family: var(--font-mono);
  color: var(--color-text-secondary);
  min-width: 48px;
}

.scoring-key__desc {
  color: var(--color-text-muted);
}

.scoring-key__link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  margin-top: var(--space-2);
  font-size: var(--type-detail);
  color: var(--color-accent);
  text-decoration: none;
}

.scoring-key__link svg {
  color: var(--color-text-tertiary);
  transition: color var(--transition-fast);
}

.scoring-key__link:hover svg {
  color: var(--color-accent);
}

/* Mobile: stack description on second line */
@media (max-width: 640px) {
  .scoring-key__row {
    flex-wrap: wrap;
  }
  .scoring-key__desc {
    width: 100%;
    padding-left: 22px; /* 10px dot + 12px gap */
  }
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add static/css/report.css
git commit -m "feat(NES-326): add .scoring-key CSS component"
```

---

### Task 4: Template Wiring — Insert Scoring Key + Replace Hardcoded Table

**Files:**
- Modify: `templates/_result_sections.html` line 14 (add macro import)
- Modify: `templates/_result_sections.html` after line 80 (insert scoring key below verdict)
- Modify: `templates/_result_sections.html` lines 1199-1205 (replace hardcoded band table)

- [ ] **Step 1: Add `scoring_key` to the macro import at line 14**

Change:
```jinja2
{% from "_macros.html" import fmt_time, data_row, score_ring, verdict_badge, school_card, health_check_icon, confidence_badge, coverage_badge, annotation, access_mode_annotation %}
```

To:
```jinja2
{% from "_macros.html" import fmt_time, data_row, score_ring, verdict_badge, school_card, health_check_icon, confidence_badge, coverage_badge, annotation, access_mode_annotation, scoring_key %}
```

- [ ] **Step 2: Insert scoring key card below verdict (after line 80)**

After the `{% endif %}` that closes the `{% if is_preview %}` block (line 80), add:

```jinja2

        {# ── SCORING KEY (NES-326 §4.10) ── #}
        {% if not is_preview and show_score %}
        {{ scoring_key(score_bands, band_class) }}
        {% endif %}
```

- [ ] **Step 3: Replace hardcoded band table in "How We Score" section**

Replace the hardcoded `.band-table` div (lines 1199-1205):

```html
          <div class="band-table">
            <div class="band-row"><span class="band-dot band-exceptional"></span><span class="band-range">85–100</span><span class="band-label">Exceptional Daily Fit</span></div>
            <div class="band-row"><span class="band-dot band-strong"></span><span class="band-range">70–84</span><span class="band-label">Strong Daily Fit</span></div>
            <div class="band-row"><span class="band-dot band-moderate"></span><span class="band-range">55–69</span><span class="band-label">Moderate — Some Trade-offs</span></div>
            <div class="band-row"><span class="band-dot band-limited"></span><span class="band-range">40–54</span><span class="band-label">Limited — Car Likely Needed</span></div>
            <div class="band-row"><span class="band-dot band-poor"></span><span class="band-range">0–39</span><span class="band-label">Significant Gaps</span></div>
          </div>
```

With:

```jinja2
          {{ scoring_key(score_bands, show_link=False) }}
```

- [ ] **Step 4: Run the app locally and verify rendering**

Run: `cd /Users/jeremybrowning/NestCheck && python app.py`
Navigate to an existing snapshot URL. Verify:
- Scoring key card appears below the verdict badge
- Five rows with colored dots, labels, ranges, descriptions
- The user's current band row has a left border + bold label
- "How we score" link at bottom
- Scrolling to "HOW WE SCORE" section shows the same card (no active highlight)
- Card does NOT appear on preview/health-only reports

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add templates/_result_sections.html
git commit -m "feat(NES-326): wire scoring key into verdict + How We Score section"
```

---

### Task 5: Playwright Tests

**Files:**
- Create: `tests/playwright/test_scoring_key.py`
- Reference: `tests/fixtures/eval_result_healthy.json` (existing fixture, band-strong)

Uses the existing `healthy_report_url` fixture from `tests/playwright/conftest.py`, which saves the `eval_result_healthy.json` fixture (score 74, band-strong) as a snapshot.

- [ ] **Step 1: Write Playwright tests**

Create `tests/playwright/test_scoring_key.py`:

```python
"""Playwright tests for the scoring key card (NES-326)."""


def test_scoring_key_renders_below_verdict(page, healthy_report_url):
    """Scoring key card appears below verdict with 5 band rows."""
    page.goto(healthy_report_url)
    page.wait_for_load_state("networkidle")

    card = page.locator(".scoring-key").first
    assert card.is_visible()

    rows = card.locator(".scoring-key__row")
    assert rows.count() == 5


def test_scoring_key_active_row_matches_band(page, healthy_report_url):
    """The active row's band-dot class matches the verdict band (band-strong)."""
    page.goto(healthy_report_url)
    page.wait_for_load_state("networkidle")

    active_row = page.locator(".scoring-key__row--active").first
    assert active_row.is_visible()

    # The healthy fixture has score 74 = band-strong
    dot = active_row.locator(".band-dot")
    dot_classes = dot.get_attribute("class")
    assert "band-strong" in dot_classes


def test_scoring_key_has_how_we_score_link(page, healthy_report_url):
    """Footer link points to #how-we-score anchor."""
    page.goto(healthy_report_url)
    page.wait_for_load_state("networkidle")

    link = page.locator(".scoring-key__link").first
    assert link.is_visible()
    assert link.get_attribute("href") == "#how-we-score"
    assert "How we score" in link.inner_text()


def test_scoring_key_in_methodology_section(page, healthy_report_url):
    """How We Score section also uses the scoring key (no active row)."""
    page.goto(healthy_report_url)
    page.wait_for_load_state("networkidle")

    methodology = page.locator("#how-we-score")
    methodology_key = methodology.locator(".scoring-key")
    assert methodology_key.is_visible()

    # No active row in the methodology section
    active_rows = methodology_key.locator(".scoring-key__row--active")
    assert active_rows.count() == 0


def test_scoring_key_each_row_has_range_and_description(page, healthy_report_url):
    """Each row shows a range (e.g., '85-100') and a description."""
    page.goto(healthy_report_url)
    page.wait_for_load_state("networkidle")

    rows = page.locator(".scoring-key").first.locator(".scoring-key__row")
    for i in range(rows.count()):
        row = rows.nth(i)
        assert row.locator(".scoring-key__range").inner_text().strip() != ""
        assert row.locator(".scoring-key__desc").inner_text().strip() != ""
```

- [ ] **Step 2: Run Playwright tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/playwright/test_scoring_key.py -v`
Expected: All tests PASS (requires local Flask server — the Playwright conftest starts one)

- [ ] **Step 3: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add tests/playwright/test_scoring_key.py
git commit -m "test(NES-326): add Playwright tests for scoring key card"
```

---

### Task 6: CI Gate Update

**Files:**
- Modify: `.github/workflows/ci.yml` line 31 (add `tests/test_scoring_key.py` to explicit file list)
- Modify: `Makefile` line 27 (add `tests/test_scoring_key.py` to explicit file list)

Both CI and Makefile use explicit file lists (not globs), so the new test file must be added to both.

- [ ] **Step 1: Add `tests/test_scoring_key.py` to CI**

In `.github/workflows/ci.yml` line 31, change:

```yaml
        run: python -m pytest tests/test_scoring_regression.py tests/test_scoring_config.py tests/test_overflow.py tests/test_schema_migration.py -v --tb=short
```

To:

```yaml
        run: python -m pytest tests/test_scoring_regression.py tests/test_scoring_config.py tests/test_overflow.py tests/test_schema_migration.py tests/test_scoring_key.py -v --tb=short
```

- [ ] **Step 2: Add `tests/test_scoring_key.py` to Makefile**

In `Makefile` line 27, change:

```makefile
	python3 -m pytest tests/test_scoring_regression.py tests/test_scoring_config.py tests/test_overflow.py tests/test_schema_migration.py -v --tb=short
```

To:

```makefile
	python3 -m pytest tests/test_scoring_regression.py tests/test_scoring_config.py tests/test_overflow.py tests/test_schema_migration.py tests/test_scoring_key.py -v --tb=short
```

- [ ] **Step 3: Run the full scoring test suite**

Run: `cd /Users/jeremybrowning/NestCheck && make test-scoring`
Expected: All scoring tests PASS including the new ones

- [ ] **Step 4: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add .github/workflows/ci.yml Makefile
git commit -m "ci(NES-326): add scoring key tests to CI gate"
```
