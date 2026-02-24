# NES-42 Discovery Report: CSS Architecture & Template Audit

**Generated:** 2026-02-12
**Plan:** `issues/plan-nes42-restyle-phase1-css-extraction.md`

---

## 1. Flask Static Config

- **App init (app.py line 52):** `app = Flask(__name__)` — no `static_folder` or `static_url_path` args.
- **Flask defaults apply:** `static_folder="static"` (relative to app root), `static_url_path="/static"`.
- **`static/` directory:** Does NOT exist yet. Must be created.
- **No explicit static routes:** No `send_from_directory` calls in app.py. `send_from_directory` is not even imported.
- **Deployment (Procfile / Railway):** Gunicorn via `gunicorn app:app -c gunicorn_config.py`. No static file config. Flask will serve static files directly via Gunicorn workers, which is fine for this app's scale.
- **Conclusion:** Creating `static/css/` and using `url_for('static', filename='css/base.css')` in templates will work with zero config changes.

## 2. CSS Selector Inventory

### SHARED — Identical in both index.html and snapshot.html

These selectors have **identical rules** in both files. All go into `report.css`.

| Selector | Category |
|----------|----------|
| `.verdict-card` | Verdict |
| `.verdict-address` | Verdict |
| `.score-header` | Verdict |
| `.score-number` | Verdict |
| `.score-band` | Verdict |
| `.score-scale` | Verdict |
| `.dimension-list` | Verdict |
| `.dimension-row` | Verdict |
| `.dimension-name` | Verdict |
| `.dimension-summary` | Verdict |
| `.dimension-score` | Verdict |
| `.report-section` | Report |
| `.report-section h2` | Report |
| `.section-empty` | Report |
| `.collapsible-toggle` | Report |
| `.collapsible-toggle h2` | Report |
| `.collapse-icon` | Report |
| `.collapsible-body` | Report |
| `.collapsible-body.collapsed` | Report |
| `.place-item` | Places |
| `.place-item:last-child` | Places |
| `.place-name` | Places |
| `.place-meta` | Places |
| `.place-time` | Places |
| `.badge` | Badges |
| `.badge-pass` | Badges |
| `.badge-borderline` | Badges |
| `.badge-fail` | Badges |
| `.badge-great` | Badges |
| `.badge-ok` | Badges |
| `.badge-painful` | Badges |
| `.check-row` | Checks |
| `.check-row:last-child` | Checks |
| `.check-icon` | Checks |
| `.check-pass` | Checks |
| `.check-fail` | Checks |
| `.check-unknown` | Checks |
| `.check-text` | Checks |
| `.check-label` | Checks |
| `.check-detail` | Checks |
| `.proximity-item` | Proximity |
| `.proximity-neutral` | Proximity |
| `.proximity-notable` | Proximity |
| `.proximity-very_close` | Proximity |
| `.proximity-name` | Proximity |
| `.proximity-detail` | Proximity |
| `.score-row` | Dead CSS |
| `.score-row:last-child` | Dead CSS |
| `.score-info` | Dead CSS |
| `.score-name` | Dead CSS |
| `.score-detail` | Dead CSS |
| `.score-pts` | Dead CSS |
| `.scoring-explanation` | Scoring |
| `.section-insight` | Scoring |
| `.band-table` | Scoring |
| `.band-row` | Scoring |
| `.band-range` | Scoring |
| `.band-label` | Scoring |
| `.scoring-note` | Scoring |
| `.missing-section` | Missing |
| `.missing-section h2` | Missing |
| `.missing-item` | Missing |
| `.missing-bullet` | Missing |
| `.missing-text` | Missing |
| `.subscore-grid` | Subscores |
| `.subscore-card` | Subscores |
| `.subscore-label` | Subscores |
| `.subscore-label .est` | Subscores |
| `.subscore-value` | Subscores |
| `.subscore-reason` | Subscores |
| `.hub-row` | Transit |
| `.hub-row:last-child` | Transit |
| `.hub-info` | Transit |
| `.hub-name` | Transit |
| `.hub-detail` | Transit |
| `.hub-right` | Transit |
| `.hub-time` | Transit |
| `.walkscore-row` | Transit |
| `.walkscore-pill` | Transit |
| `.walkscore-pill .ws-label` | Transit |
| `.walkscore-pill .ws-value` | Transit |
| `.walkscore-pill .ws-desc` | Transit |
| `.neighborhood-category` | Neighborhood |
| `.neighborhood-category:last-child` | Neighborhood |
| `.category-label` | Neighborhood |
| `.place-cards` | Neighborhood |
| `.place-card` | Neighborhood |
| `.place-card .place-name` | Neighborhood |
| `.place-name a` | Neighborhood |
| `.place-name a:hover` | Neighborhood |
| `.place-card .place-meta` | Neighborhood |
| `.place-card .place-rating` | Neighborhood |
| `.place-card .place-reviews` | Neighborhood |
| `.place-card .place-time` | Neighborhood |
| `.disclaimer` | Footer |
| `.disclaimer strong` | Footer |
| `.share-btn` | Share |
| `.share-btn:hover` | Share |
| `.share-btn.copied` | Share |

**Total: 88 shared selectors** (6 are dead CSS `.score-row` family)

### SHARED-DIVERGED — Exists in both, rules differ

| Selector | index.html | snapshot.html | Resolution |
|----------|-----------|---------------|------------|
| `.report` | `margin: 30px auto 60px` | `margin: 16px auto 60px` | Use index version in `report.css`. Snapshot override: `margin-top: 16px` in `snapshot.css` |
| `.share-bar` | `margin: 0 auto 16px; justify-content: flex-end` | `margin: 20px auto 0; justify-content: space-between` | Put structural props in `report.css`. Both variants need page-specific overrides in `index.css` / `snapshot.css` |
| `@media (max-width: 640px)` | Missing: `.hub-row`, `.hub-right` rules | Has: `.hub-row { flex-direction: column; ... }`, `.hub-right { padding-left: 0; }` | **Bug fix:** Put hub-row/hub-right rules in `report.css` responsive block (both pages get it) |
| `@media (max-width: 640px)` | Missing: `.share-bar`, `.share-btn` rules | Has: `.share-bar { flex-direction: column; ... }`, `.share-btn { justify-content: center; }` | Snapshot-only responsive (share-bar layout differs) → `snapshot.css` |
| `@media print` | Hides: `nav, .search-section, .share-bar, .loading-overlay, footer` | Hides: `nav, .share-bar, .snapshot-cta, footer` | Base print in `report.css`: hide `nav, .share-bar, footer`. Page-specific print rules: `.search-section, .loading-overlay` in `index.css`, `.snapshot-cta` in `snapshot.css` |

### INDEX-ONLY — Only in index.html

| Selector | Category |
|----------|----------|
| `.hero` | Landing |
| `.hero h1` | Landing |
| `.hero .tagline` | Landing |
| `.why-block` | Landing |
| `.why-block p` | Landing |
| `.why-block p:last-child` | Landing |
| `.why-block strong` | Landing |
| `.search-section` | Form |
| `.search-box` | Form |
| `.search-box:focus-within` | Form |
| `.search-box input[type="text"]` | Form |
| `.search-box input[type="text"]::placeholder` | Form |
| `.search-box button` | Form |
| `.search-box button:hover` | Form |
| `.search-box button:disabled` | Form |
| `.who-its-for` | Landing |
| `.features` | Landing |
| `.feature-card` | Landing |
| `.feature-card h3` | Landing |
| `.feature-card p` | Landing |
| `.loading-overlay` | Loading |
| `.loading-overlay.active` | Loading |
| `.error-banner` (×2 — duplicate!) | Error |
| `.error-banner strong` (×2) | Error |
| `.error-banner .error-msg` | Error |
| `.spinner` | Loading |
| `@keyframes spin` | Loading |
| `.loading-text` | Loading |
| `.loading-sub` | Loading |
| `@media (max-width: 640px)` rules for: `.hero h1`, `.search-box`, `.search-box button` | Responsive |
| `@media print` rule for: `.search-section`, `.loading-overlay` | Print |

**Total: ~28 index-only selectors** (includes 2 duplicate `.error-banner` defs)

### SNAPSHOT-ONLY — Only in snapshot.html

| Selector | Category |
|----------|----------|
| `.share-bar .snapshot-meta` | Share |
| `.data-unavailable` | Fallback |
| `.snapshot-cta` | CTA |
| `.snapshot-cta h3` | CTA |
| `.snapshot-cta p` | CTA |
| `.snapshot-cta a` | CTA |
| `.snapshot-cta a:hover` | CTA |
| `@media (max-width: 640px)` rules for: `.share-bar`, `.share-btn` | Responsive |
| `@media print` rule for: `.snapshot-cta` | Print |

**Total: ~9 snapshot-only selectors**

## 3. Hardcoded Values → Proposed Tokens

### Colors (≥3 occurrences across all templates)

| Value | Occurrences | Proposed Token | Usage |
|-------|------------|----------------|-------|
| `#0f3460` | ~25 | `--color-primary` | Buttons, links, brand accent, score-pts, hub-time, band-range |
| `#16213e` | ~15 | `--color-primary-dark` | Logo, headings, button hover, ws-value, subscore-value |
| `#f0f2f5` | ~6 | `--color-bg` | Body background, report-section h2 border-bottom |
| `#fff` / `#ffffff` | ~12 | `--color-surface` | Cards, nav, footer background |
| `#f8f9fb` | ~6 | `--color-surface-subtle` | Subscore cards, walkscore pills, place cards, band-table |
| `#f8f9fa` | ~3 | (merge with above) | Proximity-neutral bg, map fallback |
| `#1a1a2e` | ~10 | `--color-text` | Body text, place-name, check-label, score-name |
| `#1e293b` | ~3 | `--color-text-strong` | Score-number, proximity-name |
| `#333` / `#333333` | ~3 | `--color-text-dark` | Loading text, why-block strong |
| `#334155` | ~3 | `--color-text-heading` | Score-band, dimension-score, JSON/CSV button bg |
| `#475569` | ~3 | `--color-text-secondary` | Dimension-name |
| `#555` | ~8 | `--color-text-muted` | Tagline, feature-card p, scoring-explanation, band-label |
| `#64748b` | ~3 | `--color-text-dim` | Dimension-summary, proximity-detail |
| `#666` | ~6 | `--color-text-light` | Check-detail, ws-desc, subscore-label, snapshot-cta p |
| `#777` | ~6 | `--color-text-lighter` | Place-meta, hub-detail, score-detail, disclaimer strong |
| `#888` | ~10 | `--color-text-faint` | Verdict-address, category-label, collapse-icon, scoring-note, drive-time |
| `#94a3b8` | ~3 | `--color-text-faintest` | Score-scale, map attribution |
| `#999` | ~5 | `--color-text-disabled` | Placeholder, place-reviews, disclaimer, footer |
| `#e0e0e0` | ~4 | `--color-border` | Nav border, footer border |
| `#e2e8f0` | ~3 | `--color-border-muted` | Verdict-card border, proximity-neutral border |
| `#f5f5f5` | ~8 | `--color-border-light` | Row separators (check-row, place-item, hub-row, score-row) |
| `#f0f0f0` | ~3 | (merge with border-light) | Walkscore border-top, green-spaces border-top |
| `#f1f5f9` | ~1 | (merge with border-light) | Dimension-list border-top |
| `#eee` | ~1 | (merge with border-light) | Feature-card border |
| `#eef0f4` | ~1 | (merge with border-muted) | Place-card border |
| `#d1fae5` | ~3 | `--color-pass-bg` | Badge-pass, badge-great, check-pass |
| `#065f46` | ~4 | `--color-pass-text` | Badge-pass, badge-great, check-pass, share-btn.copied |
| `#fee2e2` | ~3 | `--color-fail-bg` | Badge-fail, badge-painful, check-fail |
| `#991b1b` | ~4 | `--color-fail-text` | Badge-fail, badge-painful, check-fail, error-banner |
| `#fff3e0` | ~1 | `--color-borderline-bg` | Badge-borderline |
| `#e65100` | ~1 | `--color-borderline-text` | Badge-borderline |
| `#fff3cd` | ~1 | `--color-ok-bg` | Badge-ok |
| `#856404` | ~1 | `--color-ok-text` | Badge-ok |
| `#fef3c7` | ~1 | `--color-warning-bg` | Check-unknown |
| `#92400e` | ~3 | `--color-warning-text` | Check-unknown, missing-section h2 |
| `#d97706` | ~4 | `--color-amber` | Missing-bullet, place-rating, subscore-label .est |
| `#fde68a` | ~2 | `--color-warning-border` | Missing-section border |
| `#fffbeb` | ~3 | `--color-warning-surface` | Missing-section bg, proximity-notable bg |
| `#fef2f2` | ~3 | `--color-danger-surface` | Error-banner bg, proximity-very_close bg |
| `#fca5a5` | ~2 | `--color-danger-border` | Error-banner border |
| `#ef4444` | ~1 | `--color-danger` | Proximity very_close border |
| `#f59e0b` | ~1 | `--color-amber-border` | Proximity notable border |
| `#fbbf24` | ~1 | `--color-builder-accent` | Builder dashboard link (inline style in nav) |

### Font Stacks

| Value | Occurrences | Proposed Token |
|-------|------------|----------------|
| `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif` | 4 (index, snapshot, pricing, 404) | `--font-sans` |

### Border Radii

| Value | Occurrences | Proposed Token |
|-------|------------|----------------|
| `12px` | ~8 | `--radius-lg` |
| `10px` | ~4 | `--radius-card` (or merge with lg) |
| `8px` | ~10 | `--radius-md` |
| `6px` | ~2 | `--radius-sm` |

**Recommendation:** Merge `10px` and `12px` into `--radius-lg: 12px` and update the 10px usages. The visual difference is negligible and reducing to 3 tiers (sm/md/lg) is cleaner.

### Box Shadows

| Value | Occurrences | Proposed Token |
|-------|------------|----------------|
| `0 4px 20px rgba(0,0,0,0.08)` | 2 | `--shadow-elevated` |
| `0 1px 6px rgba(0,0,0,0.04)` | 2 | `--shadow-card` |

## 4. Inline Style Audit — `_result_sections.html`

### LAYOUT-HACK — Should be extracted to classes

| Line(s) | Element | Inline Style | Proposed Class |
|---------|---------|-------------|----------------|
| 46–47 | `div#neighborhood-map` (map present) | `text-align: center; padding: 0; overflow: hidden; border-radius: 8px;` | `.map-container` |
| 48–50 | `img` (map image) | `width: 100%; height: auto; display: block;` | `.map-image` |
| 52–53 | `div` (map attribution) | `font-size: 0.75em; color: #94a3b8; padding: 8px; text-align: right;` | `.map-attribution` |
| 58–62 | `div#neighborhood-map` (no map fallback) | `background: #f8f9fa; min-height: 120px; display: flex; align-items: center; justify-content: center; color: #94a3b8; border-radius: 8px; font-size: 0.9em;` | `.map-placeholder` |
| 120 | `div#your-neighborhood` (fallback) | `display: none;` | `.hidden` (utility) |
| 136 | `div` (Nearest Transit label) | `font-size: 0.82em; color: #888; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 8px;` | `.section-label` (reuse `.category-label` — same styles) |
| 149 | `span` (drive time) | `font-size: 0.82em; color: #888;` | `.text-faint-sm` |
| 154 | `div` (Nearest Transit label, bus fallback) | Same as line 136 | `.section-label` (same class) |
| 225 | `div` (best park wrapper) | `margin-bottom: 16px;` | `.park-highlight` |
| 226 | `div.place-item` | `border-bottom: none; padding-bottom: 4px;` | `.place-item--no-border` (modifier) |
| 235 | `div` (park score right side) | `text-align: right;` | `.text-right` (utility) |
| 237 | `div` (daily value label) | `font-size: 0.82em; color: #666; margin-top: 2px;` | `.park-daily-value` |
| 260–261 | `div` (OSM data note) | `margin-top: 8px; font-size: 0.78em; color: #888;` | `.osm-note` |
| 274 | `div` (other green spaces container) | `margin-top: 8px; padding-top: 12px; border-top: 1px solid #f0f0f0;` | `.subsection-divider` |
| 275 | `div` (other green spaces label) | `font-size: 0.82em; color: #888; text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 8px;` | `.section-label` (same reusable class) |
| 279 | `div.place-name` | `font-weight: 500;` | `.place-name--light` (modifier) |
| 291 | `span.badge` | `margin-left: 6px;` | `.badge--inline` (modifier) |
| 335 | `div.check-detail` | `color: #555; margin-top: 4px; font-size: 0.85em;` | `.check-explanation` |

**Total: 18 layout-hack inline styles**

### DATA-DRIVEN — Keep inline (value depends on template variables)

| Line | Element | Inline Style | Why it stays |
|------|---------|-------------|-------------|
| 238 | `strong` (daily walk value) | `color: {% if park.daily_walk_value >= 7 %}#065f46{% elif park.daily_walk_value >= 5 %}#856404{% else %}#991b1b{% endif %};` | Color determined by score threshold at render time |

**Total: 1 data-driven inline style**

### Note: Inline styles in snapshot.html (not in partial)

These are in `snapshot.html` itself (lines 621, 626–627), not `_result_sections.html`:
- `style="display: flex; gap: 8px; align-items: center;"` on share button wrapper — LAYOUT-HACK
- `style="text-decoration: none; background: #334155;"` on JSON/CSV links (×2) — LAYOUT-HACK

These should be extracted when refactoring snapshot.html.

## 5. Nav & Footer HTML Diff

### Nav

**index.html (lines 751–758):**
```html
<nav>
  <a href="/" class="logo">Nest<span>Check</span></a>
  <div>
    {% if is_builder %}
      <a href="/builder/dashboard" class="nav-link" style="color: #fbbf24;">Dashboard</a>
    {% endif %}
  </div>
</nav>
```

**snapshot.html (lines 608–613):**
```html
<nav>
  <a href="/" class="logo">Nest<span>Check</span></a>
  <div>
    <a href="/" class="nav-link">Evaluate an address</a>
  </div>
</nav>
```

**pricing.html (lines 154–160):**
```html
<nav>
  <a href="/" class="logo">Nest<span>Check</span></a>
  <div>
    <a href="/" class="nav-link">Home</a>
    <a href="/pricing" class="nav-link">Pricing</a>
  </div>
</nav>
```

**404.html (lines 63–65):**
```html
<nav>
  <a href="/" class="logo">Nest<span>Check</span></a>
</nav>
```

**Differences:**
- Logo is identical everywhere
- Right-side links differ per page
- Builder dashboard link uses an inline `style="color: #fbbf24;"` (should become a class)
- 404 has no nav links div at all

**Resolution for `_base.html`:** Canonical nav has logo + `{% block nav_links %}{% endblock %}`. Each template fills in its own links. The builder dashboard link color becomes a `.nav-link--builder` class.

### Footer

**index.html (lines 852–854):**
```html
<footer>
  NestCheck &middot; Livability evaluation for families and remote workers choosing where to live.
</footer>
```

**snapshot.html (lines 635–637):**
```html
<footer>
  NestCheck &middot; Decision support for families optimizing daily life.
</footer>
```

**pricing.html (lines 205–207):**
```html
<footer>
  NestCheck &middot; Decision support for families optimizing daily life.
</footer>
```

**404.html:** No footer.

**Differences:**
- index.html has different tagline text than snapshot/pricing
- 404 has no footer

**Resolution for `_base.html`:** Use a `{% block footer %}` with a default (the more common "Decision support..." version). index.html overrides the block with its version. 404 overrides with an empty block.

## 6. Deployment Check

- **Procfile (Railway):** Gunicorn with `app:app`. No static file serving configuration. (`render.yaml` also exists but is legacy config from a previous deployment target.)
- **Procfile:** Same — `gunicorn app:app`.
- **Flask default behavior:** Flask automatically serves files from `./static/` at `/static/` when running through any WSGI server (including Gunicorn). No explicit static route needed.
- **Conclusion:** Creating `static/css/` and referencing via `url_for('static', filename='css/base.css')` will work on both local dev and Railway **with zero config changes**.

## 7. Snapshot Re-render Verification

**Confirmed:** Snapshots store evaluation data (a `result` dict), NOT rendered HTML.

The snapshot route (`app.py` lines 1157–1184):
1. Loads stored data via `get_snapshot(snapshot_id)`
2. Backfills newer fields (`score_band`, `dimension_summaries`, `insights`) for old snapshots
3. Renders through the current `snapshot.html` template every time

**Impact:** Any CSS class added or removed will immediately affect all snapshots. `.score-row` is safe to remove — it's not referenced in `_result_sections.html` and old data doesn't depend on it.

---

## Summary of Actionable Findings

| Finding | Action |
|---------|--------|
| No `static/` directory exists | Create `static/css/` |
| No Flask config changes needed | None |
| No Procfile/Railway config changes needed | None |
| 88 shared CSS selectors | → `report.css` |
| 5 diverged selectors | → canonical in `report.css`, overrides in page-specific CSS |
| ~28 index-only selectors | → `index.css` |
| ~9 snapshot-only selectors | → `snapshot.css` |
| 6 dead `.score-row` selectors | Delete |
| Duplicate `.error-banner` in index.html | Merge into one definition in `index.css` |
| Hub-row 640px missing from index | Bug fix — add to `report.css` responsive |
| 18 layout-hack inline styles | Extract to classes |
| 1 data-driven inline style | Leave as-is |
| Nav links differ per page | `{% block nav_links %}` in `_base.html` |
| Footer text differs | `{% block footer %}` with default |
| Builder nav link has inline color | → `.nav-link--builder` class |
| ~45 unique color values | → ~30 CSS custom properties (some merge) |
