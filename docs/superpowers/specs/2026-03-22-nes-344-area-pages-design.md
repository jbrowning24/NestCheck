# NES-344: Hyper-local SEO — State Pages & Internal Linking

## Context

City pages exist at `/city/<state>/<city-slug>` (NES-352). The remaining scope for NES-344 is:

1. State pages as lightweight link hubs
2. Internal linking across the snapshot→city→state hierarchy
3. City page card update to show all addresses (CMO guidance)
4. Sitemap integration for state pages

Neighborhood pages are deferred (Phase 2, per ticket). Pre-generated pages for cities without evaluations are explicitly rejected (CMO: thin content risk).

## Design

### 1. State Pages

**Route:** `GET /state/<state-slug>` — slug is lowercase state abbreviation (`ny`, `nj`, `ct`, `mi`)

**Route handler (`app.py`):**

```python
@app.route("/state/<state_slug>")
def view_state(state_slug):
    state_upper = state_slug.upper()
    state_name = _STATE_FULL_NAMES.get(state_upper)
    if not state_name:
        abort(404)

    # Cities with enough evaluations for their own page
    all_cities = get_cities_with_snapshots(min_count=3)
    state_cities = [c for c in all_cities if c["state_abbr"] == state_upper]

    # Coverage tier from manifest
    from coverage_config import COVERAGE_MANIFEST
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

**404 behavior:** Unknown state slug → 404. Known state with zero qualifying cities → renders page with coverage tier and CTA but no city list. This is intentional — the state is a valid coverage area.

**Template (`templates/state.html`):**

```
Breadcrumbs: Home > [State Name]
H1: [State Name]
Coverage tier pill: "Full evaluation" or "Health check only"
City list: cards with city name + evaluation count, linking to /city/<state>/<slug>
CTA: "Evaluate an address in [State]"
```

**SEO elements:**
- `<title>`: `"[State] Neighborhood Reports | NestCheck"`
- `<meta name="description">`: `"Explore NestCheck property evaluations across N cities in [State]. Health checks, walkability scores, and livability data."`
- JSON-LD: `State` schema with `BreadcrumbList` + `containsPlace` array of city page URLs
- Canonical URL via existing `_base.html` pattern

**CSS:** `static/css/state.css` — lightweight, follows `city.css` patterns. Token references for spacing/typography, minimal custom styling.

### 2. Internal Linking

#### 2a. Snapshot → City Page

In `view_snapshot()`, after `_prepare_snapshot_for_display(result)`:

```python
# City page link (NES-344)
city_page_url = None
snap_city = snapshot.get("city")
snap_state = snapshot.get("state_abbr")
if snap_city and snap_state:
    city_stats = get_city_stats(snap_state, snap_city)
    if city_stats and city_stats.get("eval_count", 0) >= 3:
        city_page_url = f"/city/{snap_state.lower()}/{_city_slug(snap_city)}"
```

Pass `city_page_url` and `snap_city` to `render_template()`. Template renders:

```html
{% if city_page_url %}
<a href="{{ city_page_url }}" class="report-city-link">
  More evaluations in {{ city_name }} →
</a>
{% endif %}
```

Placed in the report template near the share/export bar area — visible but not intrusive.

**Performance:** `get_city_stats()` is a single SQL aggregate query. No `result_json` loading. Acceptable cost per page view.

#### 2b. City → State Breadcrumb

In `view_city()`, change:

```python
# Before
{"name": state_name, "url": None},

# After
{"name": state_name, "url": f"/state/{state_upper.lower()}"},
```

This wires both the visible breadcrumb link and the JSON-LD `BreadcrumbList` item URL.

#### 2c. Homepage → Featured Cities

Add a "Cities we've evaluated" section on the homepage, below existing content sections. Data from `get_cities_with_snapshots(min_count=3)`, limited to 5, sorted by snapshot count (descending — most-evaluated cities first).

Rendered as a compact row of pill-links:

```html
<section class="hp-cities">
  <h2>Cities we've evaluated</h2>
  <div class="hp-cities-pills">
    {% for city in featured_cities %}
    <a href="/city/{{ city.state_abbr|lower }}/{{ city.slug }}" class="hp-city-pill">
      {{ city.city }}, {{ city.state_abbr }}
      <span class="hp-city-count">{{ city.snapshot_count }}</span>
    </a>
    {% endfor %}
  </div>
</section>
```

In the `index()` route handler, add:

```python
featured_cities = get_cities_with_snapshots(min_count=3)
featured_cities.sort(key=lambda c: c["snapshot_count"], reverse=True)
featured_cities = featured_cities[:5]
for c in featured_cities:
    c["slug"] = _city_slug(c["city"])
```

Only computed on GET, not POST.

#### 2d. Snapshot Breadcrumbs

When a matching city page exists, extend the snapshot's JSON-LD breadcrumbs from:

```
Home > [Address]
```

to:

```
Home > [State] > [City] > [Address]
```

Pass `breadcrumbs` list to `render_template()` in `view_snapshot()` when `city_page_url` is set:

```python
if city_page_url:
    result["breadcrumbs"] = [
        {"name": state_name, "url": f"/state/{snap_state.lower()}"},
        {"name": snap_city, "url": city_page_url},
    ]
```

The existing `snapshot.html` JSON-LD block already handles the optional `result.breadcrumbs` list (lines 113-122).

### 3. City Page Address Card Update

Show all non-preview snapshots on city pages. Visually distinguish addresses that didn't pass Tier 1 health checks.

**Template change in `city.html`:**

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

**CSS (`city.css`):**

```css
.city-address-card--health-only {
  opacity: 0.7;
}
.city-score-pill--health-only {
  background: var(--color-bg-alt);
  color: var(--color-text-muted);
}
```

Note: `opacity` on the entire card is acceptable here because it's a single-purpose link element with no nested interactive children — the CMO-recommended "gray out" pattern.

**No Python changes needed** — `get_city_snapshots()` already returns all non-preview snapshots with `passed_tier1`. The route handler already sets `snap["tier1_passed"] = bool(snap["passed_tier1"])`.

### 4. Sitemap Integration

Add state pages to `sitemap_xml()` after the city pages block:

```python
# State pages (NES-344)
for st_abbr in _STATE_FULL_NAMES:
    st_slug = st_abbr.lower()
    lines.append("  <url>")
    lines.append(f"    <loc>{base}/state/{st_slug}</loc>")
    lines.append("    <changefreq>weekly</changefreq>")
    lines.append("    <priority>0.6</priority>")
    lines.append("  </url>")
```

Priority 0.6 (same as city pages). All states in `_STATE_FULL_NAMES` get sitemap entries regardless of snapshot count — state pages render for all coverage states.

### State Slug Helper

Reuse the pattern from city slugs. State slugs are simply the lowercase abbreviation:

```python
def _state_slug(state_abbr: str) -> str:
    return state_abbr.lower()
```

This is trivial but keeps the URL construction consistent and greppable.

## Files Modified

| File | Change |
|------|--------|
| `app.py` | Add `view_state()` route, update `view_snapshot()` for city link + breadcrumbs, update `view_city()` breadcrumb URL, update `index()` for featured cities, update `sitemap_xml()` for state pages |
| `templates/state.html` | New template |
| `static/css/state.css` | New stylesheet |
| `templates/city.html` | Health-only card variant |
| `static/css/city.css` | `.city-address-card--health-only` + `.city-score-pill--health-only` styles |
| `templates/snapshot.html` | "More evaluations in [City]" link |
| `static/css/report.css` | `.report-city-link` styles |
| `templates/index.html` | Featured cities section |
| `static/css/homepage.css` | `.hp-cities` styles |

## Files NOT Modified

| File | Reason |
|------|--------|
| `models.py` | No new queries needed — `get_cities_with_snapshots()` and `get_city_stats()` already exist |
| `coverage_config.py` | Read-only import of `COVERAGE_MANIFEST` |
| `census.py` | State pages don't fetch Census data |

## Open Questions Resolved (per CMO)

1. **Show all addresses, visually distinguish non-Tier-1** — prevents thin content, maintains transparency
2. **No pre-generated pages** — hard no on Census-only pages without evaluations
3. **Springfield problem** — handled by `/city/<state>/<slug>` URL structure + `state_abbr + city` composite key
