# NES-352: City Page Route + Template + Snapshot Aggregation Queries

**Date:** 2026-03-22
**Status:** Draft
**Parent:** NES-344 (Area Pages)

## Overview

Build city-level area pages that aggregate evaluations for a given city. Route: `GET /city/<state>/<city_slug>` (e.g., `/city/ny/white-plains`).

## Architecture Decision: Denormalized Columns

Add `city` and `state_abbr` columns to the `snapshots` table. City name sourced from Census-cleaned `demographics.place_name` in `result_json`. State abbreviation derived from `demographics.state_fips` via reverse FIPS lookup.

**Why not `json_extract` at query time:** CLAUDE.md documents that `json_extract()` on large tables is expensive (~350ms per table). City pages are user-facing — must be fast.

## Schema Changes (models.py)

### 1. New columns via `ALTER TABLE` in `init_db()`

```sql
ALTER TABLE snapshots ADD COLUMN city TEXT;
ALTER TABLE snapshots ADD COLUMN state_abbr TEXT;
```

Use the established `PRAGMA table_info(snapshots)` pattern (lines 199-218 of `models.py`): read column names into a set, then `if "city" not in cols:` before ALTER. Consistent with existing migrations for `user_id`, `is_preview`, etc.

### 2. Composite index

```sql
CREATE INDEX IF NOT EXISTS idx_snapshots_city_state
    ON snapshots(state_abbr, city);
```

### 3. Populate on save

Both `save_snapshot()` and `save_snapshot_for_place()` extract city/state from `result_dict`:

```python
def _extract_city_state(result_dict):
    """Extract city name and state abbreviation from result demographics."""
    demographics = result_dict.get("demographics") or {}
    city = demographics.get("place_name") or None
    state_fips = demographics.get("state_fips") or ""
    state_abbr = _FIPS_TO_STATE.get(state_fips)  # reverse lookup
    return city, state_abbr
```

`_FIPS_TO_STATE` is computed by inverting `_STATE_FIPS` from `coverage_config.py`: `_FIPS_TO_STATE = {v: k for k, v in _STATE_FIPS.items()}`. Import directly — `coverage_config.py` has no Flask dependency and is safe to import from `models.py`.

### 4. Backfill function

```python
def backfill_city_state():
    """One-time backfill of city/state_abbr from result_json demographics."""
```

- SELECT snapshots WHERE `city IS NULL AND is_preview = 0`
- Parse `result_json`, extract `demographics.place_name` and `demographics.state_fips`
- UPDATE in batches of 100
- Runs on every startup — the SELECT returns 0 rows once everything is populated, so cost is negligible
- Catches unlocked previews: snapshots unlocked via `unlock_snapshot()` after a previous backfill run will have `is_preview = 0` and `city IS NULL`, picked up on next restart
- Idempotent — safe to re-run

## Query Functions (models.py)

### `get_city_snapshots(state_abbr, city_name)`

```sql
SELECT snapshot_id, address_norm, final_score, passed_tier1, evaluated_at
FROM snapshots
WHERE state_abbr = ? AND city = ? AND is_preview = 0
ORDER BY evaluated_at DESC
```

Returns `list[dict]` with each dict containing: `snapshot_id`, `address` (from `address_norm`), `final_score`, `score_band` (computed from `final_score` via `get_score_band()`), `tier1_passed` (bool from `passed_tier1`).

**Optimization:** Do NOT load `result_json` here. Compute `score_band` from `final_score` using `get_score_band()` in Python — avoids parsing 100KB+ JSON per snapshot. Only load `result_json` for snapshots that need dimension averages (done separately in the stats computation).

### `get_city_stats(state_abbr, city_name)`

```sql
SELECT COUNT(*) as eval_count,
       AVG(final_score) as avg_score,
       SUM(CASE WHEN passed_tier1 = 1 THEN 1 ELSE 0 END) as health_pass_count
FROM snapshots
WHERE state_abbr = ? AND city = ? AND is_preview = 0
```

Returns `dict` with: `eval_count`, `avg_score` (rounded int), `health_pass_rate` (percentage), plus dimension averages computed from loaded snapshots.

Dimension averages require parsing `result_json` — compute in Python from the snapshot list rather than a separate query.

### `get_cities_with_snapshots(min_count=3)`

```sql
SELECT state_abbr, city, COUNT(*) as snapshot_count
FROM snapshots
WHERE city IS NOT NULL AND state_abbr IS NOT NULL AND is_preview = 0
GROUP BY state_abbr, city
HAVING COUNT(*) >= ?
ORDER BY state_abbr, city
```

Returns `list[dict]` with `state_abbr`, `city`, `snapshot_count`. Used by sitemap and future state page.

## Slugification

Module-level helper in `app.py`:

```python
def _city_slug(city_name: str) -> str:
    """Convert city name to URL slug. 'White Plains' -> 'white-plains'."""
    return re.sub(r'[^a-z0-9]+', '-', city_name.lower()).strip('-')
```

Reverse lookup: dedicated query function in `models.py` instead of loading all cities and filtering in Python:

```python
def get_city_name_by_slug(state_abbr: str, city_slug: str, min_count: int = 3) -> Optional[str]:
    """Resolve a URL slug to canonical city name. Returns None if not found or below threshold."""
```

```sql
SELECT city, COUNT(*) as cnt
FROM snapshots
WHERE state_abbr = ? AND city IS NOT NULL AND is_preview = 0
GROUP BY city
HAVING cnt >= ?
```

Then iterate the (small) result set in Python to match `_city_slug(row["city"]) == city_slug`. This avoids loading ALL cities across ALL states on every request — only loads cities for the one state. The `min_count` parameter enforces the threshold at query time, so the handler never fetches snapshots for a city it will 404 on.

## Route Handler (app.py)

```python
@app.route("/city/<state>/<city_slug>")
def view_city(state, city_slug):
```

### Flow:

1. Normalize `state` to uppercase
2. Resolve `city_slug` → canonical `city_name` via `_resolve_city_from_slug()`
3. 404 if city not found
4. `get_city_snapshots(state, city_name)` → snapshots list
5. 404 if `len(snapshots) < 3` (minimum threshold)
6. For snapshots that need full display data (dimension averages), load `result_json` and run `_prepare_snapshot_for_display()`. **This is the 5th deserialization path** (after view_snapshot, export_json, export_csv, compare) — must be maintained alongside the other 4 per CLAUDE.md
7. Compute stats: eval count, avg score, health pass rate, dimension averages
8. Fetch census data: `get_demographics(lat, lng)` using the first snapshot's coordinates. Verify the returned `place_name` matches `city_name` — if they diverge (edge-of-boundary resolution), skip the demographics section rather than showing mismatched data
9. Build breadcrumbs: `[{"name": "Home", "url": "/"}, {"name": STATE_NAME, "url": None}, {"name": city_name, "url": None}]`
   - State page URL is `None` for now (NES-344 will add state pages later)
10. Render `city.html`

### Template variables:

- `city_name`, `state_abbr`, `state_name` (full name from `TARGET_STATES`)
- `snapshots` (list of prepared snapshot dicts)
- `stats` (eval_count, avg_score, health_pass_rate, dimension_averages)
- `demographics` (CityProfile dict or None)
- `breadcrumbs`

## Template (city.html)

Extends `_base.html`. Structure:

```
{% block title %}{{ city_name }}, {{ state_abbr }} — NestCheck{% endblock %}

Breadcrumbs: Home > [State] > [City]

<h1>{{ city_name }}, {{ state_abbr }}</h1>

{% if demographics %}
Census overview section:
  - Population, Median income, Median age
  - Compact pills, same pattern as report "ABOUT {CITY}" section
{% endif %}

Health summary:
  "X of Y evaluated addresses passed all health checks"

Average dimension scores:
  - Compact pills using existing .summary-pill / .dim-band--* classes
  - Score/10 + dimension name

Evaluated addresses list:
  - Cards with: address, score pill (band-colored), band label, link to /s/<id>
  - Sorted by evaluated_at desc (most recent first)

CTA: "Evaluate an address in {{ city_name }}"
```

### CSS

New `city.css` file with `city-` prefixed class names per page-scoped naming convention. Reuse tokens and existing component patterns (`.summary-pill`, `.dim-band--*`). No hover effects on non-interactive cards.

## SEO

### Title
`{{ city_name }}, {{ state_abbr }} — NestCheck Property Evaluations`

### Meta description
`{{ stats.eval_count }} property evaluations in {{ city_name }}, {{ state_abbr }}. Average score: {{ stats.avg_score }}/100. {{ stats.health_pass_rate }}% passed all health checks.`

### Canonical URL
`{{ request.url.split('?')[0] }}` (existing pattern from `_base.html`)

### JSON-LD

```json
{
  "@context": "https://schema.org",
  "@type": "CollectionPage",
  "name": "{{ city_name }}, {{ state_abbr }} Property Evaluations",
  "description": "...",
  "url": "{{ canonical_url }}",
  "breadcrumb": { BreadcrumbList },
  "numberOfItems": {{ stats.eval_count }},
  "mainEntity": {
    "@type": "City",
    "name": "{{ city_name }}",
    "containedInPlace": {
      "@type": "State",
      "name": "{{ state_name }}"
    }
  }
}
```

### Sitemap

Add city pages to `sitemap_xml()`:

```python
cities = get_cities_with_snapshots(min_count=3)
for city in cities:
    slug = _city_slug(city["city"])
    state = city["state_abbr"].lower()
    urls.append({
        "loc": f"/city/{state}/{slug}",
        "changefreq": "weekly",
        "priority": "0.6",
    })
```

Priority 0.6 — between list pages (0.7) and individual snapshots (0.5).

## State Name Mapping

`_STATE_FULL_NAMES` dict in `app.py` for display. Import `_STATE_FIPS` from `coverage_config.py` and derive:

```python
from coverage_config import _STATE_FIPS
_STATE_FULL_NAMES = {
    "NY": "New York", "NJ": "New Jersey", "CT": "Connecticut",
    "MI": "Michigan", "CA": "California", "TX": "Texas",
    "FL": "Florida", "IL": "Illinois",
}
```

Note: `coverage_config.py` has `_STATE_FIPS` (abbr→FIPS) but not abbr→full_name. `startup_ingest.py` has `TARGET_STATES` with `full_name` but importing from `startup_ingest` would trigger ingest machinery. Keep a local `_STATE_FULL_NAMES` dict — this is editorial display content (like `_CLEAR_HEADLINES`), not a data source that drifts. Adding a new state requires a CLAUDE.md-level checklist item anyway.

## Snapshot Save Path Updates

Per CLAUDE.md: "All snapshot save paths must include new columns."

Three INSERT paths to update:
1. `save_snapshot()` — add `city` and `state_abbr` to INSERT
2. `save_snapshot_for_place()` INSERT branch — add `city` and `state_abbr`
3. `save_snapshot_for_place()` UPDATE branch — add `city` and `state_abbr` to SET (always overwrite from new `result_dict`, not `COALESCE` — re-evaluations may produce updated Census data)

## Edge Cases

- **Snapshots without demographics:** Pre-NES-257 snapshots have no `demographics` in `result_json`. Backfill falls back to parsing state abbreviation from `address_norm` (format: "123 Main St, City, ST 12345" — regex `r',\s*([A-Z]{2})\s+\d{5}'`). City name extraction requires Census API, so those snapshots will have `state_abbr` but NULL `city` — they won't appear on city pages. Acceptable tradeoff.
- **Same city name in different states:** Handled by the `state_abbr + city` composite key.
- **City name variations:** Census cleaning normalizes names. Two addresses in "White Plains" should both get `place_name: "White Plains"` from Census. Edge case: if Census returns different place types (Incorporated Place vs CDP) with different names for nearby addresses — unlikely but possible. Accept for now.
- **No census data for city page:** Demographics section is hidden (`{% if demographics %}`). City page still renders with just the evaluation list.

## Files Changed

| File | Change |
|------|--------|
| `models.py` | Add columns, backfill, 3 query functions, update 3 save paths |
| `app.py` | Route handler, `_city_slug()`, `_resolve_city_from_slug()`, `_STATE_NAMES`, sitemap addition |
| `templates/city.html` | New template |
| `static/css/city.css` | New stylesheet |
| `smoke_test.py` | Add city page marker check (required per CLAUDE.md) |

## Not In Scope

- State pages (`/state/<code>`) — separate ticket under NES-344
- OG images for city pages — static fallback sufficient for launch (same as list pages)
- City page for cities with < 3 snapshots (404 — prevents thin content)
- Breadcrumb links to state pages (URLs are None until state pages exist)
