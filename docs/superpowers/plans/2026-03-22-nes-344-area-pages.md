# NES-344: State Pages & Internal Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add state hub pages and wire internal linking across the snapshot→city→state hierarchy to build SEO topical authority.

**Architecture:** Lightweight state pages derive data from `COVERAGE_MANIFEST` + existing `get_cities_with_snapshots()`. Internal links wire snapshots→cities→states. No new DB queries or tables needed.

**Tech Stack:** Python/Flask routes, Jinja2 templates, CSS tokens, JSON-LD structured data

**Spec:** `docs/superpowers/specs/2026-03-22-nes-344-area-pages-design.md`

---

### Task 1: City → State Breadcrumb Link

**Files:**
- Modify: `app.py:3267-3271` (view_city breadcrumbs)

This is the simplest change — one line. Ship it first to wire the existing city pages into the hierarchy.

- [ ] **Step 1: Update breadcrumb URL in view_city()**

In `app.py`, change the state breadcrumb from `url: None` to the state page URL:

```python
# Line 3267-3271 — change the state breadcrumb entry
breadcrumbs = [
    {"name": "Home", "url": "/"},
    {"name": state_name, "url": f"/state/{state_upper.lower()}"},
    {"name": city_name, "url": None},
]
```

- [ ] **Step 2: Verify city.html template handles the change**

The template at `templates/city.html:50-56` already has `{% if bc.url %}` guards for both the visible breadcrumb link (line 50-53) and JSON-LD item URL (line 23-24). No template changes needed — confirm by reading those lines.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(NES-344): wire city breadcrumb to state page URL"
```

---

### Task 2: State Page Route & Template

**Files:**
- Modify: `app.py` (add view_state route, near view_city at line 3191)
- Create: `templates/state.html`
- Create: `static/css/state.css`

- [ ] **Step 0: Add module-level import for COVERAGE_MANIFEST**

At the top of `app.py`, near other coverage-related imports, add:

```python
from coverage_config import COVERAGE_MANIFEST
```

Verify this isn't already imported by grepping: `grep "from coverage_config import" app.py`

- [ ] **Step 1: Add view_state route to app.py**

Insert before `view_city()` (before line 3191):

```python
# ---------------------------------------------------------------------------
# State area pages (NES-344)
# ---------------------------------------------------------------------------

@app.route("/state/<state_slug>")
def view_state(state_slug):
    """State-level area page listing evaluated cities (NES-344)."""
    state_upper = state_slug.upper()
    state_name = _STATE_FULL_NAMES.get(state_upper)
    if not state_name:
        abort(404)

    # Cities with enough evaluations for their own page
    all_cities = get_cities_with_snapshots(min_count=3)
    state_cities = [c for c in all_cities if c["state_abbr"] == state_upper]
    for c in state_cities:
        c["slug"] = _city_slug(c["city"])

    # Coverage tier from manifest (module-level import at top of app.py)
    manifest = COVERAGE_MANIFEST.get(state_upper, {})
    has_education = manifest.get("STATE_EDUCATION") == "active"
    coverage_tier = "Full evaluation" if has_education else "Health check only"

    breadcrumbs = [
        {"name": "Home", "url": "/"},
        {"name": state_name, "url": None},
    ]

    return render_template(
        "state.html",
        state_name=state_name,
        state_abbr=state_upper,
        state_cities=state_cities,
        coverage_tier=coverage_tier,
        breadcrumbs=breadcrumbs,
    )
```

- [ ] **Step 2: Create state.html template**

Create `templates/state.html`:

```html
{% extends "_base.html" %}

{% block title %}{{ state_name }} Neighborhood Reports | NestCheck{% endblock %}

{% block meta_description %}Explore NestCheck property evaluations across {{ state_cities | length }} cities in {{ state_name }}. Health checks, walkability scores, and livability data.{% endblock %}

{% block json_ld %}
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "CollectionPage",
  "name": "{{ state_name }} Neighborhood Reports",
  "description": "NestCheck property evaluations in {{ state_name }}",
  "url": "{{ request.url.split('?')[0] }}",
  "mainEntity": {
    "@type": "AdministrativeArea",
    "name": "{{ state_name }}"{% if state_cities %},
    "containsPlace": [
      {% for city in state_cities %}
      {
        "@type": "City",
        "name": "{{ city.city | e }}",
        "url": "{{ request.host_url.rstrip('/') }}/city/{{ state_abbr | lower }}/{{ city.slug }}"
      }{% if not loop.last %},{% endif %}
      {% endfor %}
    ]
    {% endif %}
  },
  "breadcrumb": {
    "@type": "BreadcrumbList",
    "itemListElement": [
      {% for bc in breadcrumbs %}
      {
        "@type": "ListItem",
        "position": {{ loop.index }},
        "name": "{{ bc.name }}"{% if bc.url %},
        "item": "{{ request.host_url.rstrip('/') }}{{ bc.url }}"{% endif %}
      }{% if not loop.last %},{% endif %}
      {% endfor %}
    ]
  }
}
</script>
{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/state.css') }}">
{% endblock %}

{% block content %}
<div class="state-page">

  <nav class="state-breadcrumbs" aria-label="Breadcrumb">
    {% for bc in breadcrumbs %}
      {% if bc.url %}
        <a href="{{ bc.url }}">{{ bc.name }}</a>
      {% else %}
        <span>{{ bc.name }}</span>
      {% endif %}
      {% if not loop.last %}<span class="state-breadcrumb-sep">/</span>{% endif %}
    {% endfor %}
  </nav>

  <h1 class="state-heading">{{ state_name }}</h1>

  <div class="state-tier-pill">{{ coverage_tier }}</div>

  {% if state_cities %}
  <section class="state-cities">
    <h2 class="state-section-heading">Evaluated Cities</h2>
    <div class="state-city-list">
      {% for city in state_cities %}
      <a href="{{ url_for('view_city', state=state_abbr|lower, city_slug=city.slug) }}" class="state-city-card">
        <span class="state-city-name">{{ city.city }}</span>
        <span class="state-city-count">{{ city.snapshot_count }} evaluations</span>
      </a>
      {% endfor %}
    </div>
  </section>
  {% else %}
  <p class="state-no-cities">We're building evaluation coverage in {{ state_name }}. Check back soon.</p>
  {% endif %}

  <section class="state-cta">
    <a href="/" class="state-cta-button">Evaluate an address in {{ state_name }}</a>
  </section>

</div>
{% endblock %}
```

- [ ] **Step 3: Create state.css**

Create `static/css/state.css` — mirrors `city.css` patterns:

```css
/* State area page (NES-344) — page-scoped styles */

.state-page {
  max-width: 720px;
  margin: 0 auto;
  padding: var(--space-xl) var(--space-base);
}

.state-breadcrumbs {
  font-size: var(--type-l5-size, 11px);
  text-transform: uppercase;
  letter-spacing: var(--type-l5-tracking, 0.05em);
  color: var(--color-text-muted);
  margin-bottom: var(--space-sm);
}

.state-breadcrumbs a {
  color: var(--color-text-muted);
  text-decoration: none;
}

.state-breadcrumbs a:hover {
  text-decoration: underline;
}

.state-breadcrumb-sep {
  margin: 0 var(--space-xs);
}

.state-heading {
  font-size: var(--type-l1-size, 28px);
  font-weight: var(--type-l1-weight, 600);
  line-height: var(--type-l1-leading, 1.2);
  color: var(--color-text-primary);
  margin: 0 0 var(--space-sm) 0;
}

.state-tier-pill {
  display: inline-block;
  font-size: var(--type-l5-size, 11px);
  text-transform: uppercase;
  letter-spacing: var(--type-l5-tracking, 0.05em);
  padding: 2px 10px;
  border-radius: var(--radius-full, 999px);
  background: var(--color-surface-alt, #F1F5F9);
  color: var(--color-text-muted);
  margin-bottom: var(--space-lg);
}

.state-section-heading {
  font-size: var(--type-l2-size, 14px);
  font-weight: var(--type-l2-weight, 600);
  text-transform: uppercase;
  letter-spacing: var(--type-l2-tracking, 0.08em);
  color: var(--color-text-muted);
  margin: 0 0 var(--space-md) 0;
}

.state-city-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}

.state-city-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-md);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  text-decoration: none;
  color: var(--color-text-primary);
  transition: border-color 0.15s ease;
}

.state-city-card:hover {
  border-color: var(--color-border);
}

.state-city-name {
  font-size: 15px;
  font-weight: var(--font-weight-medium, 500);
}

.state-city-count {
  font-size: 13px;
  color: var(--color-text-muted);
}

.state-no-cities {
  color: var(--color-text-secondary);
  margin-bottom: var(--space-lg);
}

.state-cta {
  margin-top: var(--space-xl);
  text-align: center;
}

.state-cta-button {
  display: inline-block;
  padding: var(--space-sm) var(--space-lg);
  background: var(--color-brand);
  color: var(--color-text-inverse);
  text-decoration: none;
  border-radius: var(--radius-md);
  font-weight: var(--font-weight-semibold, 600);
  font-size: 15px;
}

.state-cta-button:hover {
  opacity: 0.9;
}

@media (max-width: 640px) {
  .state-page {
    padding: var(--space-md) var(--space-sm);
  }
}
```

- [ ] **Step 4: Manual test**

Run: `python -c "from app import app; app.test_client().get('/state/ny')"` — should return 200 for a state with data, 404 for unknown slugs.

- [ ] **Step 5: Commit**

```bash
git add app.py templates/state.html static/css/state.css
git commit -m "feat(NES-344): add state area page route and template"
```

---

### Task 3: Sitemap Integration for State Pages

**Files:**
- Modify: `app.py:4647-4659` (sitemap_xml, after city pages block)

- [ ] **Step 1: Add state pages to sitemap**

Insert after the city pages block (after line 4659) and before the snapshots loop (line 4661):

```python
    # State pages (NES-344) — only states with evaluated cities
    try:
        states_with_cities = {c["state_abbr"] for c in city_list}
        for st_abbr in sorted(states_with_cities):
            st_slug = _html_escape(st_abbr.lower())
            lines.append("  <url>")
            lines.append(f"    <loc>{base}/state/{st_slug}</loc>")
            lines.append("    <changefreq>weekly</changefreq>")
            lines.append("    <priority>0.6</priority>")
            lines.append("  </url>")
    except Exception:
        logger.warning("Failed to add state pages to sitemap")
```

Note: reuses `city_list` already fetched at line 4649 — no extra DB query.

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "feat(NES-344): add state pages to sitemap.xml"
```

---

### Task 4: Snapshot → City Page Internal Link

**Files:**
- Modify: `app.py:3586-3623` (view_snapshot)
- Modify: `templates/_result_sections.html:~1340` (after share bar)
- Modify: `static/css/report.css` (add .report-city-link style)

- [ ] **Step 1: Add city page URL lookup in view_snapshot()**

In `app.py`, after `_prepare_snapshot_for_display(result)` (line 3598) and before the feedback prompt block (line 3605), add:

```python
    # NES-344: city page link + breadcrumbs
    city_page_url = None
    city_name_for_link = None
    snap_city = snapshot.get("city")
    snap_state = snapshot.get("state_abbr")
    if snap_city and snap_state:
        _city_stats = get_city_stats(snap_state, snap_city)
        if _city_stats and _city_stats.get("eval_count", 0) >= 3:
            city_page_url = f"/city/{snap_state.lower()}/{_city_slug(snap_city)}"
            city_name_for_link = snap_city
            state_full = _STATE_FULL_NAMES.get(snap_state, snap_state)
            result["breadcrumbs"] = [
                {"name": state_full, "url": f"/state/{snap_state.lower()}"},
                {"name": snap_city, "url": city_page_url},
            ]
```

- [ ] **Step 2: Pass city_page_url and city_name to render_template**

Update the main GET render_template call at line 3616-3623:

```python
    return render_template(
        "snapshot.html",
        snapshot=snapshot,
        result=result,
        snapshot_id=snapshot_id,
        is_builder=g.is_builder,
        show_feedback_prompt=show_feedback_prompt,
        city_page_url=city_page_url,
        city_name_for_link=city_name_for_link,
    )
```

- [ ] **Step 3: Fix snapshot.html breadcrumb JSON-LD to use absolute URLs**

In `templates/snapshot.html:118`, the breadcrumb item URL is rendered as `{{ crumb.url }}` (relative). Change to absolute:

```html
          "item": "{{ request.host_url.rstrip('/') }}{{ crumb.url }}"
```

- [ ] **Step 4: Add city link to _result_sections.html**

After the share bar closing `</div>` (around line 1345, after the `{% endif %}` that closes the `{% if not is_preview and snapshot_id %}` block), add:

```html
    {# ── CITY PAGE LINK (NES-344) ── #}
    {% if city_page_url %}
    <div class="report-city-link-wrap">
      <a href="{{ city_page_url }}" class="report-city-link">
        More evaluations in {{ city_name_for_link }} →
      </a>
    </div>
    {% endif %}
```

- [ ] **Step 5: Add CSS for city link**

Append to `static/css/report.css`:

```css
/* NES-344: city page link on snapshot reports */
.report-city-link-wrap {
  text-align: center;
  margin: var(--space-md) 0;
}

.report-city-link {
  color: var(--color-text-muted);
  text-decoration: none;
  font-size: 14px;
}

.report-city-link:hover {
  text-decoration: underline;
  color: var(--color-text-primary);
}
```

- [ ] **Step 6: Commit**

```bash
git add app.py templates/snapshot.html templates/_result_sections.html static/css/report.css
git commit -m "feat(NES-344): add snapshot→city internal link and breadcrumbs"
```

---

### Task 5: City Page Health-Only Card Variant

**Files:**
- Modify: `templates/city.html:113-121` (address card loop)
- Modify: `static/css/city.css` (add health-only styles)

- [ ] **Step 1: Update city.html address card loop**

Replace lines 113-121 in `templates/city.html`:

```html
      {% for snap in snapshots %}
      <a href="{{ url_for('view_snapshot', snapshot_id=snap.snapshot_id) }}"
         class="city-address-card{% if not snap.tier1_passed %} city-address-card--health-only{% endif %}">
        <span class="city-address-text">{{ snap.address_norm }}</span>
        {% if snap.tier1_passed %}
        <span class="city-score-pill city-band--{{ snap.score_band|lower|replace(' ', '-') }}">
          {{ snap.final_score }}/100
        </span>
        {% else %}
        <span class="city-score-pill city-score-pill--health-only">Health check only</span>
        {% endif %}
      </a>
      {% endfor %}
```

- [ ] **Step 2: Add CSS for health-only variant**

Append to `static/css/city.css` (before the `@media` block at line 204):

```css
.city-address-card--health-only {
  opacity: 0.7;
}

.city-score-pill--health-only {
  background: var(--color-surface-alt, #F1F5F9);
  color: var(--color-text-muted);
}
```

- [ ] **Step 3: Commit**

```bash
git add templates/city.html static/css/city.css
git commit -m "feat(NES-344): visually distinguish health-only addresses on city pages"
```

---

### Task 6: Homepage Featured Cities

**Files:**
- Modify: `app.py:3286-3292` (index() function top) and `app.py:3536-3542` (GET render_template)
- Modify: `templates/index.html` (add cities section)
- Modify: `static/css/homepage.css` (add styles)

- [ ] **Step 1: Initialize featured_cities in index()**

At `app.py:3292` (after `request_id = getattr(g, "request_id", "unknown")`), add:

```python
    featured_cities = []
```

- [ ] **Step 2: Compute featured cities before the main GET return**

Before the final `return render_template(` at line 3536, add:

```python
    # NES-344: featured cities for homepage
    try:
        featured_cities = get_cities_with_snapshots(min_count=3)
        featured_cities.sort(key=lambda c: c["snapshot_count"], reverse=True)
        featured_cities = featured_cities[:5]
        for c in featured_cities:
            c["slug"] = _city_slug(c["city"])
    except Exception:
        logger.warning("Failed to load featured cities for homepage")
        featured_cities = []
```

- [ ] **Step 3: Add featured_cities to the main GET render_template call**

Add `featured_cities=featured_cities,` to the final `render_template("index.html", ...)` call at line 3536. The template will use `{% if featured_cities is defined and featured_cities %}` to guard the section, so the ~12 early-return render_template calls (POST errors, payment gates, etc.) that don't pass `featured_cities` will simply not show the section — which is the correct behavior since those are error/redirect paths.

- [ ] **Step 4: Add cities section to index.html**

Find an appropriate location near the bottom of the homepage content sections (after the existing coverage/data sections, before the closing content blocks). Add:

```html
    {% if featured_cities is defined and featured_cities %}
    <section class="hp-cities" id="evaluated-cities">
      <h2 class="hp-section-heading">Cities we've evaluated</h2>
      <div class="hp-cities-pills">
        {% for city in featured_cities %}
        <a href="/city/{{ city.state_abbr|lower }}/{{ city.slug }}" class="hp-city-pill">
          {{ city.city }}, {{ city.state_abbr }}
          <span class="hp-city-count">{{ city.snapshot_count }}</span>
        </a>
        {% endfor %}
      </div>
    </section>
    {% endif %}
```

- [ ] **Step 5: Add CSS for featured cities**

Append to `static/css/homepage.css`:

```css
/* NES-344: featured cities section */
.hp-cities {
  margin-top: var(--space-xl);
}

.hp-cities-pills {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
}

.hp-city-pill {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-xs) var(--space-md);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full, 999px);
  text-decoration: none;
  color: var(--color-text-primary);
  font-size: 14px;
  transition: border-color 0.15s ease;
}

.hp-city-pill:hover {
  border-color: var(--color-border);
}

.hp-city-count {
  font-size: 12px;
  color: var(--color-text-muted);
}
```

- [ ] **Step 6: Commit**

```bash
git add app.py templates/index.html static/css/homepage.css
git commit -m "feat(NES-344): add featured cities section to homepage"
```

---

### Task 7: Smoke Test & Verification

**Files:**
- Modify: `smoke_test.py` (if new markers needed)

- [ ] **Step 1: Manual verification checklist**

Run the dev server and verify:
1. `GET /state/ny` — renders state page with cities, breadcrumbs, JSON-LD
2. `GET /state/xx` — returns 404
3. `GET /city/ny/white-plains` — breadcrumb "New York" is now a link to `/state/ny`
4. `GET /s/<any-snapshot-id>` — "More evaluations in [City] →" link appears (if city has ≥3 snapshots)
5. `GET /s/<any-snapshot-id>` — view page source, check JSON-LD breadcrumbs have absolute URLs
6. `GET /sitemap.xml` — state pages appear with priority 0.6
7. `GET /` — "Cities we've evaluated" section appears with city pills
8. City page address cards show "Health check only" badge for non-Tier-1 snapshots

- [ ] **Step 2: Check smoke test markers**

Verify `smoke_test.py` LANDING_REQUIRED_MARKERS doesn't need updates. The new homepage section is guarded by `{% if featured_cities %}`, so it won't appear if no cities have ≥3 snapshots (which may be the case in a fresh test DB).

- [ ] **Step 3: Commit any smoke test updates**

```bash
git add smoke_test.py
git commit -m "chore(NES-344): update smoke test markers if needed"
```

---

### Task 8: CLAUDE.md Decision Log Update

**Files:**
- Modify: `NestCheck/.claude/CLAUDE.md` (Decision Log table)

- [ ] **Step 1: Add decision log entry**

Add to the Decision Log table:

```
| 2026-03 | State area pages + internal linking (NES-344) | State pages as lightweight link hubs (not data-rich). Internal linking wires snapshot→city→state hierarchy for SEO topical authority. City page breadcrumb now links to state page. Snapshot breadcrumbs extended to Home > State > City > Address when matching city page exists. Sitemap includes only states with ≥1 qualifying city. Homepage shows top 5 evaluated cities. City address cards show all snapshots with "Health check only" badge for non-Tier-1. CMO decisions: show all addresses (Option C), no pre-generated pages, state pages kept lean |
```

- [ ] **Step 2: Commit**

```bash
git add .claude/CLAUDE.md
git commit -m "docs(NES-344): add decision log entry for state pages and internal linking"
```
