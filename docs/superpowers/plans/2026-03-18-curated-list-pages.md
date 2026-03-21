# Curated List Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build config-driven curated list pages at `/lists/<slug>` that aggregate existing evaluation snapshots into SEO-friendly collections with editorial commentary.

**Architecture:** JSON config files in `data/lists/` define each list (title, intro, entries with snapshot_id + narrative, related lists). A single Flask route loads the config, hydrates each entry's snapshot through the existing migration/backfill pipeline, and renders a Jinja template that reuses `_eval_snippet.html` for each entry. JSON-LD `ItemList` schema and sitemap integration provide SEO value.

**Tech Stack:** Flask, Jinja2, stdlib `json`, existing SQLite snapshot storage.

**Linear:** NES-293

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `app.py` | Modify | Extract `_prepare_snapshot_for_display()` helper, add `/lists/<slug>` route, extend sitemap |
| `templates/list.html` | Create | List page template extending `_base.html` |
| `templates/_eval_snippet.html` | Modify | Add optional `snippet_link` for CTA target |
| `static/css/list.css` | Create | List page + eval snippet styles |
| `data/lists/_example.json` | Create | Example config file documenting the schema |
| `tests/test_curated_lists.py` | Create | Tests for config loading, route, snapshot hydration |

---

## Task 1: Extract `_prepare_snapshot_for_display()` helper

Deduplicate the migration/backfill pipeline that's currently copy-pasted across `view_snapshot()` (lines 3239-3313), `export_snapshot_json()` (lines 3336-3345), and `export_snapshot_csv()` (lines 3369-3378). The new list route needs this same pipeline.

**Files:**
- Modify: `app.py:3239-3313` (view_snapshot), `app.py:3336-3345` (export_json), `app.py:3369-3378` (export_csv)
- Create: `tests/test_curated_lists.py`

- [ ] **Step 1: Write test for the helper**

```python
# tests/test_curated_lists.py
"""Tests for curated list pages and supporting helpers."""

import json
import pytest
from app import _prepare_snapshot_for_display


def _make_minimal_result():
    """Build a minimal result dict matching snapshot structure."""
    return {
        "address": "123 Test St, Testville, NY 10000",
        "coordinates": {"lat": 41.0, "lng": -73.7},
        "tier1_checks": [],
        "tier2_scores": [],
        "dimension_summaries": [],
        "neighborhood_places": {
            "coffee": [{"name": "Bean Co", "walk_time_min": 5, "rating": 4.5}],
            "grocery": [],
            "fitness": [],
        },
        "final_score": 72,
        "passed_tier1": True,
        "score_band": {"label": "Strong", "css_class": "band-strong"},
        "verdict": "Strong",
    }


class TestPrepareSnapshotForDisplay:
    def test_adds_presented_checks_when_missing(self):
        result = _make_minimal_result()
        assert "presented_checks" not in result
        _prepare_snapshot_for_display(result)
        assert "presented_checks" in result

    def test_idempotent(self):
        """Running the pipeline twice produces identical output."""
        result = _make_minimal_result()
        _prepare_snapshot_for_display(result)
        first_pass = json.dumps(result, sort_keys=True, default=str)

        _prepare_snapshot_for_display(result)
        second_pass = json.dumps(result, sort_keys=True, default=str)

        assert first_pass == second_pass

    def test_adds_neighborhood_summary(self):
        result = _make_minimal_result()
        _prepare_snapshot_for_display(result)
        assert "neighborhood_summary" in result
        assert result["neighborhood_summary"]["coffee_count"] == 1

    def test_adds_show_numeric_score(self):
        result = _make_minimal_result()
        _prepare_snapshot_for_display(result)
        assert "show_numeric_score" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_curated_lists.py::TestPrepareSnapshotForDisplay -v`
Expected: `ImportError` — `_prepare_snapshot_for_display` does not exist yet.

- [ ] **Step 3: Extract the helper function**

Add this function to `app.py` near the other migration helpers (around line 2070, after `_compute_show_numeric_score`):

```python
def _prepare_snapshot_for_display(result):
    """Run all view-layer migrations, backfills, and display-time derivations.

    Mutates *result* in-place. Caller should shallow-copy first if the
    stored snapshot dict must not be modified.

    Covers: presented_checks backfill, structured_summary backfill,
    suppression (NES-196), hazard_tier (NES-241), dimension name migration
    (NES-210), confidence tier migration, dimension band backfill,
    green_escape count, neighborhood_summary, show_numeric_score,
    summary_narrative, walkability summary, and coverage metadata.
    """
    # Backfill presented_checks for old snapshots
    if "presented_checks" not in result:
        result["presented_checks"] = present_checks(
            result.get("tier1_checks", [])
        )

    # Backfill structured_summary for old snapshots
    if "structured_summary" not in result:
        result["structured_summary"] = generate_structured_summary(
            result.get("presented_checks", [])
        )

    # NES-196: Suppress UNKNOWN spatial checks at presentation layer
    filtered_checks, _ = suppress_unknown_safety_checks(
        result.get("presented_checks", [])
    )
    result["presented_checks"] = filtered_checks

    # NES-241: Backfill hazard_tier (rebuild dicts to avoid mutating stored refs)
    result["presented_checks"] = [
        {**pc, "hazard_tier": 2 if pc.get("name") in _TIER_2_CHECKS else 1}
        if "hazard_tier" not in pc else pc
        for pc in result.get("presented_checks", [])
    ]

    # NES-210: Migrate legacy dimension names and confidence tiers
    _migrate_dimension_names(result)
    _migrate_confidence_tiers(result)
    _backfill_dimension_bands(result)

    # Backfill total green space count (shallow-copy nested dict)
    _ge = result.get("green_escape") or {}
    if _ge and "total_green_space_count" not in _ge:
        _ge = dict(_ge)
        _ge["total_green_space_count"] = len(
            _ge.get("nearby_green_spaces", [])
        )
        result["green_escape"] = _ge

    # Backfill neighborhood summary
    if "neighborhood_summary" not in result:
        _np = result.get("neighborhood_places") or {}
        result["neighborhood_summary"] = {
            "coffee_count": len(_np.get("coffee", [])),
            "grocery_count": len(_np.get("grocery", [])),
            "fitness_count": len(_np.get("fitness", [])),
            "parks_count": len(_np.get("parks", [])),
        }

    # Phase B2: Backfill show_numeric_score
    if "show_numeric_score" not in result:
        result["show_numeric_score"] = _compute_show_numeric_score(
            result.get("dimension_summaries", [])
        )

    # NES-239: Backfill summary_narrative
    if "summary_narrative" not in result:
        result["summary_narrative"] = generate_report_narrative(result)

    # NES-249: Walkability summary (display-time only)
    result["walkability_summary"] = _build_walkability_summary(result)

    # NES-288: Coverage metadata (always recompute)
    _add_coverage_metadata(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_curated_lists.py::TestPrepareSnapshotForDisplay -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Refactor `view_snapshot()` to use the helper**

Replace lines 3239-3313 of `view_snapshot()` with:

```python
    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)
```

The shallow copy (`{**snapshot["result"]}`) is critical — preserves the stored snapshot dict.

- [ ] **Step 6: Refactor `export_snapshot_json()` to use the helper**

Replace lines 3336-3345 with:

```python
    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)
    if not g.is_builder:
        result = {k: v for k, v in result.items() if k != "_trace"}
```

Note: This expands the export pipeline to include presented_checks backfill, suppression, hazard_tier, etc. that it previously skipped. This is acceptable because exports should be consistent with the view — an export missing fields that the view shows is a bug, not a feature. The additional fields (walkability_summary, coverage metadata) are harmless in JSON export and useful for consumers.

- [ ] **Step 7: Refactor `export_snapshot_csv()` to use the helper**

Replace lines 3369-3378 with:

```python
    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)
```

Note: Same expansion as JSON export. The CSV writer already selects specific columns, so additional fields in the result dict don't affect CSV output.

- [ ] **Step 8: Run full test suite to verify no regressions**

Run: `pytest tests/ -x -q`
Expected: All existing tests pass.

- [ ] **Step 9: Commit**

```bash
git add app.py tests/test_curated_lists.py
git commit -m "refactor: extract _prepare_snapshot_for_display() from view_snapshot

Deduplicates migration/backfill pipeline across view_snapshot(),
export_snapshot_json(), and export_snapshot_csv(). Enables reuse
by the upcoming /lists/<slug> route.

NES-293"
```

---

## Task 2: Config loader and route

Build the config loading function and Flask route for `/lists/<slug>`.

**Files:**
- Modify: `app.py`
- Create: `data/lists/` directory
- Modify: `tests/test_curated_lists.py`

- [ ] **Step 1: Create the `data/lists/` directory**

```bash
mkdir -p data/lists
```

- [ ] **Step 2: Write tests for config loading**

Append to `tests/test_curated_lists.py`:

```python
import os
import tempfile
from app import _load_list_config, _get_all_list_slugs


class TestLoadListConfig:
    def test_returns_none_for_missing_slug(self):
        assert _load_list_config("nonexistent-slug-xyz") is None

    def test_loads_valid_config(self, tmp_path):
        config = {
            "slug": "test-list",
            "title": "Test List",
            "meta_description": "A test list.",
            "intro": "This is a test.",
            "entries": [
                {"snapshot_id": "abc123", "narrative": "Great spot."}
            ],
        }
        config_file = tmp_path / "test-list.json"
        config_file.write_text(json.dumps(config))

        result = _load_list_config("test-list", config_dir=str(tmp_path))
        assert result is not None
        assert result["title"] == "Test List"
        assert len(result["entries"]) == 1

    def test_returns_none_for_invalid_json(self, tmp_path):
        config_file = tmp_path / "bad.json"
        config_file.write_text("{not valid json")
        assert _load_list_config("bad", config_dir=str(tmp_path)) is None

    def test_slug_rejects_path_traversal(self):
        """Slug must not allow directory traversal."""
        assert _load_list_config("../etc/passwd") is None
        assert _load_list_config("foo/../../bar") is None


class TestGetAllListSlugs:
    def test_returns_slugs_from_json_files(self, tmp_path):
        (tmp_path / "alpha.json").write_text('{"slug": "alpha", "title": "A"}')
        (tmp_path / "beta.json").write_text('{"slug": "beta", "title": "B"}')
        (tmp_path / "_example.json").write_text('{"slug": "_example"}')
        slugs = _get_all_list_slugs(config_dir=str(tmp_path))
        assert "alpha" in slugs
        assert "beta" in slugs

    def test_skips_underscore_prefixed_files(self, tmp_path):
        (tmp_path / "_example.json").write_text('{"slug": "_example"}')
        slugs = _get_all_list_slugs(config_dir=str(tmp_path))
        assert "_example" not in slugs
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_curated_lists.py::TestLoadListConfig -v`
Expected: `ImportError` — functions don't exist yet.

- [ ] **Step 4: Implement config loading functions**

Add to `app.py` near the top of the routes section (after imports, before routes):

```python
import re

# ---------------------------------------------------------------------------
# Curated list pages (NES-293)
# ---------------------------------------------------------------------------

_LISTS_DIR = os.path.join(os.path.dirname(__file__), "data", "lists")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _load_list_config(slug, config_dir=None):
    """Load a curated list config by slug. Returns dict or None."""
    if not slug or not _SLUG_RE.fullmatch(slug):
        return None
    config_dir = config_dir or _LISTS_DIR
    path = os.path.join(config_dir, f"{slug}.json")
    try:
        with open(path) as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _get_all_list_slugs(config_dir=None):
    """Return list of slugs from all published config files (excludes _-prefixed)."""
    config_dir = config_dir or _LISTS_DIR
    slugs = []
    try:
        for fname in os.listdir(config_dir):
            if fname.endswith(".json") and not fname.startswith("_"):
                slugs.append(fname[:-5])  # strip .json
    except OSError:
        pass
    return slugs
```

- [ ] **Step 5: Run config loading tests**

Run: `pytest tests/test_curated_lists.py::TestLoadListConfig tests/test_curated_lists.py::TestGetAllListSlugs -v`
Expected: All PASS.

- [ ] **Step 6: Write test for the route**

Append to `tests/test_curated_lists.py`:

```python
from models import save_snapshot


def _create_test_snapshot():
    """Insert a minimal snapshot into the DB and return its auto-generated ID."""
    result = _make_minimal_result()
    snapshot_id = save_snapshot(
        address_input=result["address"],
        address_norm=result["address"],
        result_dict=result,
    )
    return snapshot_id


class TestListRoute:
    def test_404_for_missing_slug(self, client):
        resp = client.get("/lists/nonexistent-slug")
        assert resp.status_code == 404

    def test_200_for_valid_list(self, client, tmp_path, monkeypatch):
        sid = _create_test_snapshot()
        config = {
            "slug": "test-walkable",
            "title": "Test Walkable List",
            "meta_description": "Test description.",
            "intro": "An intro paragraph.",
            "entries": [
                {"snapshot_id": sid, "narrative": "A nice place."}
            ],
        }
        (tmp_path / "test-walkable.json").write_text(json.dumps(config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))

        resp = client.get("/lists/test-walkable")
        assert resp.status_code == 200
        assert b"Test Walkable List" in resp.data

    def test_json_ld_item_list(self, client, tmp_path, monkeypatch):
        sid = _create_test_snapshot()
        config = {
            "slug": "ld-test",
            "title": "JSON-LD Test",
            "meta_description": "Test desc.",
            "intro": "Intro.",
            "entries": [{"snapshot_id": sid, "narrative": "Note."}],
        }
        (tmp_path / "ld-test.json").write_text(json.dumps(config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))

        resp = client.get("/lists/ld-test")
        assert b'"@type": "ItemList"' in resp.data
        assert b'"numberOfItems": 1' in resp.data
        assert bytes(f'/s/{sid}', "utf-8") in resp.data

    def test_og_tags_from_config(self, client, tmp_path, monkeypatch):
        sid = _create_test_snapshot()
        config = {
            "slug": "og-test",
            "title": "OG Test Title",
            "meta_description": "OG test desc.",
            "intro": "Intro.",
            "entries": [{"snapshot_id": sid, "narrative": "N."}],
        }
        (tmp_path / "og-test.json").write_text(json.dumps(config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))

        resp = client.get("/lists/og-test")
        assert b'og:title" content="OG Test Title"' in resp.data
        assert b'og:description" content="OG test desc."' in resp.data

    def test_related_lists_rendered(self, client, tmp_path, monkeypatch):
        sid = _create_test_snapshot()
        main_config = {
            "slug": "main-list",
            "title": "Main List",
            "meta_description": "Main.",
            "intro": "Intro.",
            "entries": [{"snapshot_id": sid, "narrative": "N."}],
            "related_lists": ["related-list"],
        }
        related_config = {
            "slug": "related-list",
            "title": "The Related List",
            "meta_description": "Related.",
            "intro": "Intro.",
            "entries": [],
        }
        (tmp_path / "main-list.json").write_text(json.dumps(main_config))
        (tmp_path / "related-list.json").write_text(json.dumps(related_config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))

        resp = client.get("/lists/main-list")
        assert b"The Related List" in resp.data
        assert b"/lists/related-list" in resp.data

    def test_skips_missing_snapshots(self, client, tmp_path, monkeypatch):
        config = {
            "slug": "sparse-list",
            "title": "Sparse List",
            "meta_description": "Some missing.",
            "intro": "Intro.",
            "entries": [
                {"snapshot_id": "does-not-exist", "narrative": "Gone."}
            ],
        }
        (tmp_path / "sparse-list.json").write_text(json.dumps(config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))

        resp = client.get("/lists/sparse-list")
        assert resp.status_code == 200
        # Page renders but entry is skipped — no crash
        assert b"does-not-exist" not in resp.data
```

- [ ] **Step 7: Run route tests to verify they fail**

Run: `pytest tests/test_curated_lists.py::TestListRoute -v`
Expected: FAIL — route doesn't exist, template doesn't exist.

- [ ] **Step 8: Implement the route**

Add to `app.py` in the routes section:

```python
@app.route("/lists/<slug>")
def view_list(slug):
    """Serve a curated list page from JSON config."""
    config = _load_list_config(slug)
    if not config:
        abort(404)

    # Hydrate each entry with its snapshot data
    hydrated_entries = []
    for entry in config.get("entries", []):
        snapshot = get_snapshot(entry.get("snapshot_id"))
        if not snapshot:
            logger.warning("List %s: snapshot %s not found, skipping",
                           slug, entry.get("snapshot_id"))
            continue
        result = {**snapshot["result"]}
        _prepare_snapshot_for_display(result)
        hydrated_entries.append({
            "snapshot_id": entry["snapshot_id"],
            "narrative": entry.get("narrative", ""),
            "result": result,
        })

    # Resolve related list titles for cross-linking
    related_lists = []
    for related_slug in config.get("related_lists", []):
        related_config = _load_list_config(related_slug)
        if related_config:
            related_lists.append({
                "slug": related_slug,
                "title": related_config["title"],
            })

    return render_template(
        "list.html",
        config=config,
        entries=hydrated_entries,
        related_lists=related_lists,
    )
```

- [ ] **Step 9: Create the template**

Create `templates/list.html`:

```jinja
{% extends "_base.html" %}

{% block title %}{{ config.title }} — NestCheck{% endblock %}

{% block meta_description %}
<meta name="description" content="{{ config.meta_description }}">
{% endblock %}

{% block og_tags %}
<meta property="og:title" content="{{ config.title }}">
<meta property="og:description" content="{{ config.meta_description }}">
<meta property="og:type" content="website">
<meta property="og:url" content="{{ request.url.split('?')[0] }}">
{% endblock %}

{% block json_ld %}
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "name": "{{ config.title | e }}",
  "description": "{{ config.meta_description | e }}",
  "numberOfItems": {{ entries | length }},
  "itemListElement": [
    {% for entry in entries %}
    {
      "@type": "ListItem",
      "position": {{ loop.index }},
      "url": "{{ request.host_url.rstrip('/') }}/s/{{ entry.snapshot_id }}"
    }{% if not loop.last %},{% endif %}
    {% endfor %}
  ]
}
</script>
{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/list.css') }}">
{% endblock %}

{% block content %}
<div class="list-page">

  {# ── Header ── #}
  <header class="list-header">
    <h1 class="list-title">{{ config.title }}</h1>
    <p class="list-intro">{{ config.intro }}</p>
  </header>

  {# ── Entries ── #}
  <div class="list-entries">
    {% for entry in entries %}
    <div class="list-entry">
      <div class="list-entry-rank">{{ loop.index }}</div>
      <div class="list-entry-content">
        {% set preview_result = entry.result %}
        {% set snippet_link = "/s/" ~ entry.snapshot_id %}
        {% include '_eval_snippet.html' %}
        {% if entry.narrative %}
        <div class="list-entry-narrative">
          {{ entry.narrative }}
        </div>
        {% endif %}
      </div>
    </div>
    {% endfor %}
  </div>

  {# ── Related Lists ── #}
  {% if related_lists %}
  <div class="list-related">
    <h2 class="list-related-heading">Related Lists</h2>
    <ul class="list-related-links">
      {% for rl in related_lists %}
      <li><a href="/lists/{{ rl.slug }}">{{ rl.title }}</a></li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

  {# ── CTA ── #}
  <div class="list-cta">
    <a href="/" class="list-cta-button">
      {{ config.cta_text | default("Evaluate your own address →") }}
    </a>
  </div>

</div>
{% endblock %}
```

- [ ] **Step 10: Run route tests**

Run: `pytest tests/test_curated_lists.py::TestListRoute -v`
Expected: All PASS.

- [ ] **Step 11: Commit**

```bash
git add app.py templates/list.html data/lists/ tests/test_curated_lists.py
git commit -m "feat: add /lists/<slug> route for curated list pages

Config-driven curated lists loaded from data/lists/<slug>.json.
Hydrates snapshots through _prepare_snapshot_for_display(), renders
eval snippet cards with editorial narratives. JSON-LD ItemList schema.

NES-293"
```

---

## Task 3: Eval snippet adaptation for list context

The eval snippet CTA currently points to `#evaluate` (landing page anchor). In list context, it should link to the full evaluation page.

**Files:**
- Modify: `templates/_eval_snippet.html`

- [ ] **Step 1: Update the snippet CTA to use `snippet_link` when available**

In `templates/_eval_snippet.html`, replace the CTA section (lines 92-94):

```jinja
  <div class="eval-snippet-cta">
    <a href="{{ snippet_link | default('#evaluate') }}">
      {% if snippet_link %}View full evaluation &rarr;{% else %}Run your own evaluation &rarr;{% endif %}
    </a>
  </div>
```

- [ ] **Step 2: Verify the landing page still works**

The landing page sets no `snippet_link` variable, so the default `#evaluate` applies unchanged.

Run: `pytest tests/ -x -q` to verify no regressions.

- [ ] **Step 3: Commit**

```bash
git add templates/_eval_snippet.html
git commit -m "feat: add snippet_link variable to eval snippet CTA

When snippet_link is set (e.g., in list pages), the CTA links to
the full evaluation. Falls back to #evaluate for the landing page.

NES-293"
```

---

## Task 4: Eval snippet and list page CSS

The eval snippet has HTML classes but no CSS yet. Create styles for both the snippet component and the list page layout.

**Files:**
- Create: `static/css/list.css`

- [ ] **Step 1: Create `static/css/list.css`**

```css
/* list.css — Curated list pages + eval snippet component
 *
 * Covers both the list-page layout and the eval-snippet component
 * (used here and on the landing page).
 */

/* ── List Page Layout ── */

.list-page {
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-xl) var(--space-base);
}

.list-header {
  margin-bottom: var(--space-xl);
}

.list-title {
  font-size: var(--type-l1-size);
  font-weight: var(--type-l1-weight);
  line-height: var(--type-l1-leading);
  color: var(--type-l1-color);
  margin: 0 0 var(--space-sm) 0;
}

.list-intro {
  font-size: var(--font-size-body);
  color: var(--color-text-secondary);
  line-height: 1.6;
  margin: 0;
}

/* ── Entry ── */

.list-entry {
  display: flex;
  gap: var(--space-base);
  margin-bottom: var(--space-xl);
  padding-bottom: var(--space-xl);
  border-bottom: 1px solid var(--color-border-light);
}

.list-entry:last-child {
  border-bottom: none;
}

.list-entry-rank {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--color-bg-surface-alt);
  color: var(--color-text-secondary);
  font-weight: var(--font-weight-semibold);
  font-size: var(--font-size-small);
}

.list-entry-content {
  flex: 1;
  min-width: 0;
}

.list-entry-narrative {
  margin-top: var(--space-sm);
  font-size: var(--font-size-body);
  color: var(--color-text-secondary);
  line-height: 1.6;
  font-style: italic;
}

/* ── Related Lists ── */

.list-related {
  margin-top: var(--space-2xl);
  padding-top: var(--space-xl);
  border-top: 1px solid var(--color-border-light);
}

.list-related-heading {
  font-size: var(--type-l3-size);
  font-weight: var(--type-l3-weight);
  color: var(--type-l3-color);
  margin: 0 0 var(--space-sm) 0;
}

.list-related-links {
  list-style: none;
  padding: 0;
  margin: 0;
}

.list-related-links li {
  margin-bottom: var(--space-xs);
}

.list-related-links a {
  color: var(--color-link);
  text-decoration: none;
}

.list-related-links a:hover {
  text-decoration: underline;
}

/* ── CTA ── */

.list-cta {
  text-align: center;
  margin-top: var(--space-2xl);
  padding: var(--space-xl) 0;
}

.list-cta-button {
  display: inline-block;
  padding: var(--space-sm) var(--space-xl);
  background: var(--color-brand);
  color: var(--color-text-inverse);
  border-radius: var(--radius-md);
  text-decoration: none;
  font-weight: var(--font-weight-semibold);
  transition: opacity 0.15s ease;
}

.list-cta-button:hover {
  opacity: 0.9;
}

/* ── Eval Snippet Component ── */

.eval-snippet {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.eval-snippet-label {
  font-size: var(--type-l5-size, 11px);
  font-weight: var(--type-l5-weight, 600);
  text-transform: uppercase;
  letter-spacing: var(--type-l5-tracking, 0.05em);
  color: var(--color-text-faint);
  padding: var(--space-sm) var(--space-base) 0;
}

.eval-snippet-card {
  padding: var(--space-base);
}

.eval-snippet-address {
  font-size: var(--type-l3-size, 18px);
  font-weight: var(--type-l3-weight, 600);
  color: var(--color-text-primary);
  margin-bottom: var(--space-sm);
}

/* ── Snippet: Health Proximity ── */

.snippet-proximity {
  margin-bottom: var(--space-sm);
}

.snippet-section-label {
  font-size: var(--type-l5-size, 11px);
  font-weight: var(--type-l5-weight, 600);
  text-transform: uppercase;
  letter-spacing: var(--type-l5-tracking, 0.05em);
  color: var(--color-text-faint);
  margin-bottom: var(--space-xs);
}

.snippet-proximity-item {
  padding: var(--space-xs) 0;
}

.snippet-proximity-headline {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-medium);
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.snippet-proximity-icon {
  flex-shrink: 0;
  width: 18px;
  text-align: center;
  font-size: 14px;
}

.snippet-proximity-icon--clear { color: var(--color-health-pass); }
.snippet-proximity-icon--issue { color: var(--color-health-fail); }
.snippet-proximity-icon--warning { color: var(--color-health-caution); }
.snippet-proximity-icon--unverified { color: var(--color-text-faint); }

.snippet-proximity-detail {
  font-size: var(--font-size-small);
  color: var(--color-text-secondary);
  margin-left: calc(18px + var(--space-xs));
}

/* ── Snippet: Nearby Places ── */

.snippet-places {
  margin-bottom: var(--space-sm);
}

.snippet-places-grid {
  display: flex;
  gap: var(--space-sm);
}

.snippet-place {
  display: flex;
  align-items: flex-start;
  gap: var(--space-xs);
  flex: 1;
  min-width: 0;
}

.snippet-place-icon {
  flex-shrink: 0;
  font-size: 16px;
}

.snippet-place-name {
  font-size: var(--font-size-small);
  font-weight: var(--font-weight-medium);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.snippet-place-meta {
  font-size: var(--font-size-small);
  color: var(--color-text-secondary);
  display: flex;
  gap: var(--space-xs);
}

.snippet-place-rating {
  color: var(--color-text-tertiary);
}

/* ── Snippet: Assessment ── */

.snippet-assessment {
  padding-top: var(--space-xs);
  border-top: 1px solid var(--color-border-light);
}

.snippet-assessment-label {
  font-size: var(--font-size-small);
  font-weight: var(--font-weight-semibold);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* ── Snippet: CTA ── */

.eval-snippet-cta {
  padding: var(--space-xs) var(--space-base) var(--space-sm);
  text-align: right;
}

.eval-snippet-cta a {
  font-size: var(--font-size-small);
  color: var(--color-link);
  text-decoration: none;
}

.eval-snippet-cta a:hover {
  text-decoration: underline;
}

/* ── Mobile ── */

@media (max-width: 640px) {
  .list-entry {
    flex-direction: column;
    gap: var(--space-xs);
  }

  .list-entry-rank {
    width: 28px;
    height: 28px;
    font-size: 12px;
  }

  .snippet-places-grid {
    flex-direction: column;
  }
}
```

- [ ] **Step 2: Manually test the snippet rendering**

Visit a list page locally (requires a config file with a valid snapshot_id). Verify:
- Snippet card renders with border, proper spacing
- Health icons use correct colors
- Places grid is horizontal on desktop, stacked on mobile
- CTA links to the evaluation page

- [ ] **Step 3: Commit**

```bash
git add static/css/list.css
git commit -m "feat: add CSS for list pages and eval snippet component

Styles the list page layout (header, entries, related links, CTA)
and the eval-snippet component (health proximity, nearby places,
assessment badge). Responsive at 640px breakpoint.

NES-293"
```

---

## Task 5: Sitemap integration

Add published list pages to the dynamic sitemap.

**Files:**
- Modify: `app.py` (sitemap_xml route, lines 4203-4248)
- Modify: `tests/test_curated_lists.py`

- [ ] **Step 1: Write test for list pages in sitemap**

Append to `tests/test_curated_lists.py`:

```python
class TestSitemap:
    def test_list_pages_in_sitemap(self, client, tmp_path, monkeypatch):
        config = {
            "slug": "sitemap-test",
            "title": "Sitemap Test List",
            "meta_description": "For sitemap test.",
            "intro": "Intro.",
            "entries": [],
        }
        (tmp_path / "sitemap-test.json").write_text(json.dumps(config))
        monkeypatch.setattr("app._LISTS_DIR", str(tmp_path))

        resp = client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert b"/lists/sitemap-test" in resp.data
        assert b"<priority>0.7</priority>" in resp.data
        assert b"<changefreq>monthly</changefreq>" in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_curated_lists.py::TestSitemap -v`
Expected: FAIL — sitemap doesn't include list pages yet.

- [ ] **Step 3: Add list pages to sitemap**

In `app.py`, in the `sitemap_xml()` function, after the static pages loop (line 4229) and before the snapshots loop (line 4231), add:

```python
    # Curated list pages
    for list_slug in _get_all_list_slugs():
        loc = f"{base}/lists/{_html_escape(list_slug)}"
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append("    <changefreq>monthly</changefreq>")
        lines.append("    <priority>0.7</priority>")
        lines.append("  </url>")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_curated_lists.py::TestSitemap -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_curated_lists.py
git commit -m "feat: add curated list pages to sitemap.xml

List pages get priority 0.7 and monthly changefreq — higher than
individual evaluations (0.5) since lists are actively promoted content.

NES-293"
```

---

## Task 6: Example config file

Create an example/template config file for editorial use.

**Files:**
- Create: `data/lists/_example.json`

- [ ] **Step 1: Create the example config**

```json
{
  "slug": "_example",
  "title": "Best Walkable Neighborhoods in Westchester County",
  "meta_description": "NestCheck's evaluation of the most walkable addresses in Westchester County, scored by proximity to grocery, coffee, fitness, and transit.",
  "intro": "We evaluated dozens of Westchester addresses for everyday walkability — how easily you can reach grocery stores, coffee shops, fitness options, and transit on foot. These addresses scored highest.",
  "target_keyword": "walkable neighborhoods westchester county",
  "entries": [
    {
      "snapshot_id": "REPLACE_WITH_REAL_SNAPSHOT_ID",
      "narrative": "This address scores well on walkability, but the nearest grocery store is a 27-minute walk — a provisioning gap common in lower-density Westchester towns."
    }
  ],
  "related_lists": [],
  "cta_text": "Evaluate your own address →"
}
```

Note: Files prefixed with `_` are excluded from sitemap and `_get_all_list_slugs()`.

- [ ] **Step 2: Commit**

```bash
git add data/lists/_example.json
git commit -m "docs: add example config for curated list pages

Template JSON for editorial use when creating new list pages.
Underscore prefix excludes it from sitemap and slug discovery.

NES-293"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass.

- [ ] **Step 2: Run the curated list tests specifically**

Run: `pytest tests/test_curated_lists.py -v`
Expected: All tests pass with clear names.

- [ ] **Step 3: Manual smoke test**

1. Create a test config at `data/lists/test-walkable.json` with a real snapshot_id from the database
2. Visit `http://localhost:5000/lists/test-walkable`
3. Verify: title renders, eval snippets load, CTA links work, related lists render (if configured)
4. Visit `http://localhost:5000/sitemap.xml` — verify the list page appears
5. View page source — verify JSON-LD `ItemList` is valid
6. Remove the test config file after verification

- [ ] **Step 4: Final commit if any cleanup needed**

---

## Deferred: OG Images for List Pages

**Not in scope for this implementation.** List pages use the static fallback OG image inherited from `_base.html`. A fast-follow ticket should:

1. Extend `og_image.py` with a `generate_list_og_image(title)` function
2. Generate on first request (lazy) and cache to filesystem or DB
3. Serve from `/og/list-<slug>.png`
4. Update `list.html` OG tags to point to the generated image

---

## CLAUDE.md Updates

After all tasks complete, add these entries to the project CLAUDE.md:

**Coding Standards section:**
```
- **Curated list config files live in `data/lists/`**: One JSON file per list, slug matches filename. Files prefixed with `_` (e.g., `_example.json`) are excluded from sitemap and slug discovery. Config is loaded at request time via `_load_list_config()` — no caching (editorial content, infrequent access).
- **`_prepare_snapshot_for_display()` is the canonical migration pipeline**: All snapshot deserialization paths (view, export JSON, export CSV, list pages) must use this helper. When adding new backfill/migration logic, add it to this function — not inline in route handlers.
```

**Decision Log:**
```
| 2026-03 | Curated list pages (NES-293) | Config-driven (JSON files in `data/lists/`), not database-driven. Editorial control at 3-5 lists doesn't justify a CMS. `_prepare_snapshot_for_display()` extracted to deduplicate migration pipeline across 4 deserialization paths. OG images deferred to fast-follow — static fallback sufficient for launch |
```
