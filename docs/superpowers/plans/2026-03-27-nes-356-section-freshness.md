# NES-356: Section Freshness Captions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render data-source freshness captions below report section headings so users know how current each section's underlying data is.

**Architecture:** Freshness data is static config (changes only when `startup_ingest.py` runs, not per-evaluation). Build a `build_section_freshness()` function in `coverage_config.py` that reads from `get_dataset_registry()` and the Census ACS vintage. Register the result as a Jinja global (`app.jinja_env.globals["section_freshness"]`), following the `score_bands` precedent (NES-326). Template renders `<span class="section-freshness">` below annotated section headings with a `--stale` modifier when data is >24 months old.

**Tech Stack:** Python (coverage_config.py), Jinja2 (_result_sections.html), CSS (report.css)

**Sections to annotate:** Health & Environment (Tier 1), EPA Environmental Profile (Tier 2 / EJScreen), Area Context (Census), Parks & Green Space
**Sections to skip:** Getting Around, Neighborhood venues (real-time API data)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `coverage_config.py` | Modify (~line 580) | New `build_section_freshness()` function |
| `app.py` | Modify (~line 225) | Register freshness dict as Jinja global |
| `templates/_result_sections.html` | Modify (lines 206, 781, 1010, 1145) | Freshness `<span>` below each annotated `<h2>` |
| `static/css/report.css` | Modify (~line 2570) | `.section-freshness` and `.section-freshness--stale` styles |
| `tests/test_coverage_config.py` | Modify | Tests for `build_section_freshness()` |

---

### Task 1: `build_section_freshness()` in `coverage_config.py`

**Files:**
- Modify: `coverage_config.py:572-601` (after `get_source_last_refreshed()`, before `SECTION_DIMENSION_MAP`)
- Test: `tests/test_coverage_config.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_coverage_config.py`:

```python
from coverage_config import build_section_freshness

# --- Section freshness tests ---

def test_build_section_freshness_returns_expected_keys():
    """Freshness dict contains exactly the 4 annotated sections."""
    freshness = build_section_freshness()
    assert set(freshness.keys()) == {"health_tier1", "health_tier2", "census", "parks"}


def test_build_section_freshness_structure():
    """Each entry has source, date, and stale fields."""
    freshness = build_section_freshness()
    for key, entry in freshness.items():
        assert "source" in entry, f"{key} missing 'source'"
        assert "date" in entry, f"{key} missing 'date'"
        assert "stale" in entry, f"{key} missing 'stale'"
        assert isinstance(entry["stale"], bool), f"{key} stale is not bool"


def test_build_section_freshness_census_from_acs_base():
    """Census entry derives its date from the _ACS_BASE vintage year."""
    from unittest.mock import patch
    import types
    fake_census = types.ModuleType("census")
    fake_census._ACS_BASE = "https://api.census.gov/data/2022/acs/acs5"
    with patch.dict("sys.modules", {"census": fake_census}):
        freshness = build_section_freshness()
    census = freshness["census"]
    assert census["source"] == "Census ACS 5-Year"
    assert census["date"] == "2022"


def test_build_section_freshness_stale_threshold():
    """Entries with ingested_at > 24 months ago are marked stale."""
    from unittest.mock import patch
    from datetime import datetime, timezone, timedelta

    old_date = (datetime.now(timezone.utc) - timedelta(days=800)).strftime("%Y-%m-%d")
    fake_registry = {
        "sems": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "ejscreen": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "tri": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "ust": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "hpms": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "hifld": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "fra": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
        "fema_nfhl": {"ingested_at": old_date, "source_url": "", "record_count": 1, "notes": ""},
    }
    with patch("coverage_config.get_dataset_registry", return_value=fake_registry):
        freshness = build_section_freshness()
    assert freshness["health_tier1"]["stale"] is True
    assert freshness["health_tier2"]["stale"] is True


def test_build_section_freshness_not_stale_when_recent():
    """Entries with recent ingested_at are not stale."""
    from unittest.mock import patch
    from datetime import datetime, timezone

    recent_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fake_registry = {
        "ejscreen": {"ingested_at": recent_date, "source_url": "", "record_count": 1, "notes": ""},
    }
    with patch("coverage_config.get_dataset_registry", return_value=fake_registry):
        freshness = build_section_freshness()
    assert freshness["health_tier2"]["stale"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_coverage_config.py::test_build_section_freshness_returns_expected_keys -v`
Expected: FAIL with `ImportError: cannot import name 'build_section_freshness'`

- [ ] **Step 3: Implement `build_section_freshness()`**

Add to `coverage_config.py` after `get_source_last_refreshed()` (around line 580), before the `SECTION_DIMENSION_MAP` block:

```python
# =============================================================================
# Section freshness captions (NES-356)
# =============================================================================

# Staleness threshold: data older than this is flagged with caution styling.
_FRESHNESS_STALE_MONTHS = 24

# Maps section keys to the dataset_registry facility_type keys whose
# ingested_at dates determine that section's freshness.
_SECTION_FRESHNESS_SOURCES = {
    "health_tier1": {
        "label": "Federal environmental databases",
        "registry_keys": ["sems", "ejscreen", "tri", "ust", "hpms", "hifld", "fra", "fema_nfhl"],
    },
    "health_tier2": {
        "label": "EPA EJScreen",
        "registry_keys": ["ejscreen"],
    },
    "parks": {
        "label": "ParkServe",
        "registry_keys": ["parkserve"],  # not yet ingested — entry will be absent
    },
}


def _parse_freshness_date(date_str: str) -> Optional[datetime]:
    """Parse an ingested_at string into a datetime. Returns None on failure."""
    from datetime import datetime, timezone
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _format_freshness_date(dt: "datetime") -> str:
    """Format a datetime as 'March 2025' for display."""
    return dt.strftime("%B %Y")


def _is_stale(dt: "datetime") -> bool:
    """Return True if dt is more than _FRESHNESS_STALE_MONTHS ago."""
    from datetime import datetime, timezone
    age_days = (datetime.now(timezone.utc) - dt).days
    return age_days > _FRESHNESS_STALE_MONTHS * 30


def build_section_freshness() -> Dict[str, dict]:
    """Build freshness metadata for annotated report sections.

    Returns {section_key: {"source": str, "date": str, "stale": bool}}.
    Always includes all 4 keys. Sections with no registry data get
    a fallback date string and stale=False.
    """
    from datetime import datetime, timezone
    import re

    registry = get_dataset_registry()

    result = {}

    # --- Spatial.db-backed sections ---
    for section_key, config in _SECTION_FRESHNESS_SOURCES.items():
        oldest_dt = None
        for rkey in config["registry_keys"]:
            entry = registry.get(rkey)
            if not entry or not entry.get("ingested_at"):
                continue
            dt = _parse_freshness_date(entry["ingested_at"])
            if dt and (oldest_dt is None or dt < oldest_dt):
                oldest_dt = dt

        if oldest_dt:
            result[section_key] = {
                "source": config["label"],
                "date": _format_freshness_date(oldest_dt),
                "stale": _is_stale(oldest_dt),
            }
        else:
            result[section_key] = {
                "source": config["label"],
                "date": "",
                "stale": False,
            }

    # --- Census ACS (live API, vintage pinned in census.py) ---
    try:
        from census import _ACS_BASE
        match = re.search(r"/(\d{4})/", _ACS_BASE)
        acs_year = match.group(1) if match else "Unknown"
    except ImportError:
        acs_year = "Unknown"

    result["census"] = {
        "source": "Census ACS 5-Year",
        "date": acs_year,
        "stale": False,  # ACS vintage is intentionally pinned
    }

    return result
```

- [ ] **Step 4: Run all freshness tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_coverage_config.py -k "section_freshness" -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add coverage_config.py tests/test_coverage_config.py
git commit -m "feat(NES-356): add build_section_freshness() to coverage_config"
```

---

### Task 2: Register freshness as Jinja global in `app.py`

**Files:**
- Modify: `app.py:225` (after `score_bands` global registration)

- [ ] **Step 1: Add the Jinja global registration**

After the `app.jinja_env.globals["score_bands"]` line (~line 225), add:

```python
# ---------------------------------------------------------------------------
# Section freshness captions — static config (NES-356)
# ---------------------------------------------------------------------------
# Freshness data depends on dataset_registry which lives in spatial.db.
# At module-load time spatial.db may not exist yet (startup_ingest runs
# later). Compute lazily on first access via a Jinja global function.
def _get_section_freshness():
    if not hasattr(_get_section_freshness, "_cache"):
        from coverage_config import build_section_freshness
        _get_section_freshness._cache = build_section_freshness()
    return _get_section_freshness._cache

app.jinja_env.globals["section_freshness"] = _get_section_freshness
```

> **Note:** We use a lazy wrapper because `spatial.db` (and therefore `dataset_registry`) may not exist at module load time — `startup_ingest.py` populates it later. The cache ensures we only call `build_section_freshness()` once.

- [ ] **Step 2: Verify app starts without error**

Run: `cd /Users/jeremybrowning/NestCheck && python -c "from app import app; print('OK')"`
Expected: Prints `OK` without error

- [ ] **Step 3: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py
git commit -m "feat(NES-356): register section_freshness as Jinja global"
```

---

### Task 3: CSS for freshness captions in `report.css`

**Files:**
- Modify: `static/css/report.css` (~line 2086, after the section header group spacing block ending at line 2085)

- [ ] **Step 1: Add CSS rules**

Insert after the section header group spacing block (after line 2085, before the `.section-title--collapsible` rule at line 2087):

```css
/* ── Section freshness caption (NES-356) ── */
.section-freshness {
  font-size: var(--type-caption);
  color: var(--color-text-tertiary);
  display: block;
  margin-top: var(--space-1);
  margin-bottom: var(--space-2);
}
.section-freshness--stale {
  color: var(--color-health-caution);
}
```

These tokens are already defined:
- `--type-caption`: `0.7rem` (~11px) in `tokens.css:176`
- `--color-text-tertiary`: alias for `--color-text-faint` in `tokens.css:47`
- `--color-health-caution`: alias for `--color-warning` in `tokens.css:94`
- `--space-1`: `4px` in `tokens.css:296`
- `--space-2`: `8px` in `tokens.css:297`

No print stylesheet changes needed — freshness captions are static text (not interactive), so they remain visible by default. The print block only hides interactive/nav elements.

- [ ] **Step 2: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add static/css/report.css
git commit -m "feat(NES-356): add .section-freshness CSS"
```

---

### Task 4: Render freshness captions in `_result_sections.html`

**Files:**
- Modify: `templates/_result_sections.html` (lines 206, 781, 1010, 1145)

The template accesses `section_freshness` as a callable Jinja global (returns a dict). Each section gets a `<span>` below its `<h2>`.

- [ ] **Step 1: Add a Jinja helper at template top for the freshness dict**

Near the top of `_result_sections.html` (around line 5, after existing `{% set %}` blocks), add:

```jinja2
{# Section freshness data (NES-356) — callable global, invoke once #}
{% set _sf = section_freshness() %}
```

- [ ] **Step 2: Health & Environment (Tier 1) — after line 206**

After the closing `</h2>` on line 206, add:

```jinja2
          {% if _sf.get('health_tier1') and _sf.health_tier1.date %}
          <span class="section-freshness{% if _sf.health_tier1.stale %} section-freshness--stale{% endif %}" aria-label="Data source: {{ _sf.health_tier1.source }}, last updated {{ _sf.health_tier1.date }}.">
            Data from {{ _sf.health_tier1.source }}, last updated {{ _sf.health_tier1.date }}
          </span>
          {% endif %}
```

- [ ] **Step 3: Parks & Green Space — after line 781**

After the closing `</h2>` on line 781, add:

```jinja2
          {% if _sf.get('parks') and _sf.parks.date %}
          <span class="section-freshness{% if _sf.parks.stale %} section-freshness--stale{% endif %}" aria-label="Data source: {{ _sf.parks.source }}, last updated {{ _sf.parks.date }}.">
            Data from {{ _sf.parks.source }}, last updated {{ _sf.parks.date }}
          </span>
          {% endif %}
```

- [ ] **Step 4: Area Context (Census) — after line 1018**

After the `<h2>` at line 1018 (`ABOUT {{ demo.place_name|upper }}`), inside the existing `{% if result.demographics %}` guard, add:

```jinja2
          {% if _sf.get('census') and _sf.census.date %}
          <span class="section-freshness" aria-label="Data source: {{ _sf.census.source }}, {{ _sf.census.date }} vintage.">
            Data from {{ _sf.census.source }}, {{ _sf.census.date }} vintage
          </span>
          {% endif %}
```

Note: Census freshness shows "vintage" instead of "last updated" since ACS data is vintage-pinned. Placed inside the demographics guard (line 1015) so it only renders when census data exists.

- [ ] **Step 5: EPA Environmental Profile (Tier 2 / EJScreen) — after line 1145**

After the closing `</h2>` on line 1145, before the existing `<p class="area-context-note">`, add:

```jinja2
          {% if _sf.get('health_tier2') and _sf.health_tier2.date %}
          <span class="section-freshness{% if _sf.health_tier2.stale %} section-freshness--stale{% endif %}" aria-label="Data source: {{ _sf.health_tier2.source }}, last updated {{ _sf.health_tier2.date }}.">
            Data from {{ _sf.health_tier2.source }}, last updated {{ _sf.health_tier2.date }}
          </span>
          {% endif %}
```

- [ ] **Step 6: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add templates/_result_sections.html
git commit -m "feat(NES-356): render freshness captions in report sections"
```

---

### Task 5: Verify end-to-end and update smoke test

**Files:**
- Modify: `smoke_test.py:37` (add freshness marker to `SNAPSHOT_REQUIRED_MARKERS` — optional, see note)

- [ ] **Step 1: Manual verification**

Start the dev server and load an existing snapshot page. Verify:
1. Freshness captions appear below Health & Environment and EPA Environmental Profile headings
2. Census caption shows "Data from Census ACS 5-Year, 2022 vintage" below Area Context
3. Parks caption appears only if ParkServe data is in the registry (likely absent — caption correctly hidden)
4. `aria-label` attributes are present on each `<span>`
5. Stale styling (caution color) appears if data is >24 months old

Run: `cd /Users/jeremybrowning/NestCheck && python -c "from app import app; f = app.jinja_env.globals['section_freshness'](); print(f)"`
Expected: Dict with 4 keys, each having `source`, `date`, `stale` fields

- [ ] **Step 2: Run existing test suites to verify no regressions**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_coverage_config.py tests/test_scoring_config.py -v`
Expected: All tests PASS

- [ ] **Step 3: Smoke test marker (skip if freshness is data-dependent)**

The freshness caption is only rendered when registry data exists, so it's NOT a reliable smoke test marker (it may be absent on a fresh deployment). **Do not add to `SNAPSHOT_REQUIRED_MARKERS`** — the existing markers (verdict-card, dimension-score, how-we-score) are sufficient.

- [ ] **Step 4: Final commit if any adjustments were needed**

If adjustments were made, stage only the changed files:
```bash
cd /Users/jeremybrowning/NestCheck
git add coverage_config.py app.py templates/_result_sections.html static/css/report.css
git commit -m "fix(NES-356): address adjustments from verification"
```
