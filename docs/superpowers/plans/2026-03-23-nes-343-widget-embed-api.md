# NES-343: Widget Badge, Data API & Embed Code Generator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable third-party embedding of NestCheck scores via SVG badge, JSON API, and a copy-paste embed code generator on the report page.

**Architecture:** Three thin Flask routes (`widget_badge`, `api_widget_data`, embed modal served inline) reusing the existing `get_snapshot()` → `_prepare_snapshot_for_display()` → `get_score_band()` pipeline. One new SVG template. Embed generator is vanilla JS in `_result_sections.html`.

**Tech Stack:** Python/Flask, Jinja2 SVG templates, vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-23-nes-343-widget-embed-api-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `app.py` | Modify | Add `widget_badge()` and `api_widget_data()` routes |
| `templates/widget_badge.html` | Create | SVG Jinja2 template with banner and square variants |
| `templates/_result_sections.html` | Modify | Add Embed button to share bar + embed modal HTML/CSS/JS |
| `static/css/report.css` | Modify | Add embed modal CSS + print hide rule (spec said inline CSS, but `report.css` is the established pattern for report-page styles — cleaner than inline) |
| `tests/test_widget_api.py` | Create | Unit tests for badge route, API route, response headers |

---

### Task 1: Widget Data API Route

The simplest component — a JSON endpoint with no template. Ship this first since the embed modal's API tab will fetch from it.

**Files:**
- Modify: `app.py` (after the `widget_card` route, ~line 3740)
- Create: `tests/test_widget_api.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_widget_api.py`:

```python
"""Tests for widget badge and data API routes (NES-343)."""

import json
import pytest
from app import app
from models import save_snapshot


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def snapshot_id(client):
    """Save a minimal snapshot and return its ID."""
    result = {
        "address": "123 Main St, White Plains, NY",
        "final_score": 72,
        "tier1_checks": [],
        "tier2_scores": [],
    }
    sid = save_snapshot("123 Main St", "123 Main St, White Plains, NY", result)
    return sid


class TestWidgetDataAPI:
    def test_returns_json(self, client, snapshot_id):
        resp = client.get(f"/api/v1/widget-data/{snapshot_id}")
        assert resp.status_code == 200
        assert resp.content_type == "application/json"
        data = resp.get_json()
        assert data["score"] == 72
        assert data["address"] == "123 Main St, White Plains, NY"
        assert "band" in data
        assert "report_url" in data
        assert "clear_count" in data
        assert "concern_count" in data
        assert "health_summary" in data

    def test_cors_header(self, client, snapshot_id):
        resp = client.get(f"/api/v1/widget-data/{snapshot_id}")
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    def test_cache_header(self, client, snapshot_id):
        resp = client.get(f"/api/v1/widget-data/{snapshot_id}")
        assert "max-age=86400" in resp.headers.get("Cache-Control", "")

    def test_404_returns_json(self, client):
        resp = client.get("/api/v1/widget-data/nonexistent")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["error"] == "Snapshot not found"
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    def test_report_url_is_absolute(self, client, snapshot_id):
        resp = client.get(f"/api/v1/widget-data/{snapshot_id}")
        data = resp.get_json()
        assert data["report_url"].startswith("http")
        assert f"/s/{snapshot_id}" in data["report_url"]

    def test_health_summary_no_concerns(self, client, snapshot_id):
        resp = client.get(f"/api/v1/widget-data/{snapshot_id}")
        data = resp.get_json()
        # Minimal snapshot has no presented_checks, so 0 clear / 0 concerns
        assert "clear" in data["health_summary"]

    def test_health_summary_pluralization(self, client):
        """Snapshot with 1 concern should say 'concern' not 'concerns'."""
        result = {
            "address": "456 Oak Ave, Scarsdale, NY",
            "final_score": 45,
            "tier1_checks": [],
            "tier2_scores": [],
            "presented_checks": [
                {"name": "Gas station", "result_type": "CONFIRMED_ISSUE"},
                {"name": "Power lines", "result_type": "CLEAR"},
            ],
        }
        sid = save_snapshot("456 Oak Ave", "456 Oak Ave, Scarsdale, NY", result)
        resp = client.get(f"/api/v1/widget-data/{sid}")
        data = resp.get_json()
        assert data["concern_count"] == 1
        assert "1 concern" in data["health_summary"]
        assert "concerns" not in data["health_summary"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_widget_api.py -v 2>&1 | head -40`

Expected: FAIL — route doesn't exist yet, 404 on all requests.

- [ ] **Step 3: Implement the API route**

Add to `app.py` after the `widget_card` route (~line 3740):

```python
@app.route("/api/v1/widget-data/<snapshot_id>")
def api_widget_data(snapshot_id):
    """Widget data API — returns JSON for programmatic access (NES-343)."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        resp = jsonify({"error": "Snapshot not found"})
        resp.status_code = 404
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)

    checks = result.get("presented_checks", [])
    clear_count = sum(1 for c in checks if c.get("result_type") == "CLEAR")
    concern_count = sum(
        1 for c in checks
        if c.get("result_type") in ("CONFIRMED_ISSUE", "WARNING_DETECTED")
    )

    score = result.get("final_score") or 0
    band = get_score_band(score)

    if concern_count == 0:
        health_summary = f"{clear_count} clear"
    else:
        concern_word = "concern" if concern_count == 1 else "concerns"
        health_summary = f"{clear_count} clear / {concern_count} {concern_word}"

    report_url = request.host_url.rstrip("/") + "/s/" + snapshot_id

    resp = jsonify({
        "score": score,
        "band": band["label"],
        "address": result.get("address", snapshot.get("address_norm", "")),
        "health_summary": health_summary,
        "clear_count": clear_count,
        "concern_count": concern_count,
        "report_url": report_url,
    })
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_widget_api.py::TestWidgetDataAPI -v`

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py tests/test_widget_api.py
git commit -m "feat(NES-343): add widget data API endpoint

GET /api/v1/widget-data/<snapshot_id> returns JSON with score, band,
address, health summary, and report URL. CORS *, 24hr cache, no auth."
```

---

### Task 2: Badge SVG Template + Route

**Files:**
- Modify: `app.py` (add route before `widget_card`)
- Create: `templates/widget_badge.html` (SVG Jinja2 template)
- Modify: `tests/test_widget_api.py` (add badge tests)

- [ ] **Step 1: Write badge tests**

Append to `tests/test_widget_api.py`:

```python
class TestWidgetBadge:
    def test_banner_returns_svg(self, client, snapshot_id):
        resp = client.get(f"/widget/badge/{snapshot_id}.svg")
        assert resp.status_code == 200
        assert resp.content_type == "image/svg+xml"
        assert b"<svg" in resp.data
        assert b"nestcheck" in resp.data.lower()

    def test_square_returns_svg(self, client, snapshot_id):
        resp = client.get(f"/widget/badge/{snapshot_id}.svg?style=square")
        assert resp.status_code == 200
        assert b"<svg" in resp.data
        # Square dimensions
        assert b'width="120"' in resp.data
        assert b'height="120"' in resp.data

    def test_banner_dimensions(self, client, snapshot_id):
        resp = client.get(f"/widget/badge/{snapshot_id}.svg")
        assert b'width="200"' in resp.data
        assert b'height="60"' in resp.data

    def test_cors_header(self, client, snapshot_id):
        resp = client.get(f"/widget/badge/{snapshot_id}.svg")
        assert resp.headers.get("Access-Control-Allow-Origin") == "*"

    def test_cache_header(self, client, snapshot_id):
        resp = client.get(f"/widget/badge/{snapshot_id}.svg")
        assert "max-age=86400" in resp.headers.get("Cache-Control", "")

    def test_csp_header(self, client, snapshot_id):
        resp = client.get(f"/widget/badge/{snapshot_id}.svg")
        assert resp.headers.get("Content-Security-Policy") == "frame-ancestors *"

    def test_404_for_missing_snapshot(self, client):
        resp = client.get("/widget/badge/nonexistent.svg")
        assert resp.status_code == 404

    def test_contains_score(self, client, snapshot_id):
        resp = client.get(f"/widget/badge/{snapshot_id}.svg")
        # Score 72 should appear in the SVG text
        assert b"72" in resp.data

    def test_contains_utm_link(self, client, snapshot_id):
        resp = client.get(f"/widget/badge/{snapshot_id}.svg")
        assert b"utm_source=widget" in resp.data
        assert b"utm_medium=badge" in resp.data

    def test_invalid_style_defaults_to_banner(self, client, snapshot_id):
        resp = client.get(f"/widget/badge/{snapshot_id}.svg?style=invalid")
        assert resp.status_code == 200
        assert b'width="200"' in resp.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_widget_api.py::TestWidgetBadge -v 2>&1 | head -30`

Expected: FAIL — route doesn't exist.

- [ ] **Step 3: Create the SVG template**

Create `templates/widget_badge.html`:

```xml
{% if style == 'square' %}
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="120" height="120" viewBox="0 0 120 120">
  <a xlink:href="/s/{{ snapshot_id }}?utm_source=widget&amp;utm_medium=badge&amp;utm_content=square">
    <rect width="120" height="120" rx="8" fill="#FFFFFF" stroke="#E2E8F0" stroke-width="1"/>

    {# Score number #}
    <text x="60" y="48" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="32" font-weight="700" fill="{{ band_color }}">{{ score }}</text>

    {# Band label #}
    <text x="60" y="68" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="11" font-weight="500" fill="#475569">{{ band_label }}</text>

    {# Health status #}
    {% if concern_count == 0 %}
      <circle cx="36" cy="85" r="4" fill="#16A34A"/>
      <text x="44" y="89" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="10" fill="#475569">{{ clear_count }} Clear</text>
    {% else %}
      <circle cx="28" cy="85" r="4" fill="#D97706"/>
      <text x="36" y="89" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="10" fill="#475569">{{ concern_count }} Concern{{ 's' if concern_count != 1 else '' }}</text>
    {% endif %}

    {# Branding #}
    <text x="60" y="110" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="9" fill="#94A3B8">NestCheck</text>
  </a>
</svg>
{% else %}
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="200" height="60" viewBox="0 0 200 60">
  <a xlink:href="/s/{{ snapshot_id }}?utm_source=widget&amp;utm_medium=badge&amp;utm_content=banner">
    <rect width="200" height="60" rx="6" fill="#FFFFFF" stroke="#E2E8F0" stroke-width="1"/>

    {# Logo mark — two skewed rectangles #}
    <g transform="translate(12, 15)">
      <rect width="8" height="22" rx="1.5" fill="#0B1D3A" transform="skewX(-8)"/>
      <rect x="6" width="8" height="22" rx="1.5" fill="#0B1D3A" opacity="0.6" transform="skewX(-8)"/>
    </g>

    {# Score pill #}
    <rect x="36" y="12" width="36" height="24" rx="5" fill="{{ band_color }}"/>
    <text x="54" y="30" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="16" font-weight="700" fill="#FFFFFF">{{ score }}</text>

    {# Health status #}
    {% if concern_count == 0 %}
      <circle cx="82" cy="24" r="4" fill="#16A34A"/>
      <text x="90" y="28" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="11" fill="#475569">{{ clear_count }} Clear</text>
    {% else %}
      <circle cx="82" cy="24" r="4" fill="#D97706"/>
      <text x="90" y="28" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="11" fill="#475569">{{ concern_count }} Concern{{ 's' if concern_count != 1 else '' }}</text>
    {% endif %}

    {# Site URL #}
    <text x="188" y="50" text-anchor="end" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="8" fill="#94A3B8">nestcheck.org</text>
  </a>
</svg>
{% endif %}
```

- [ ] **Step 4: Add the badge route to app.py**

Add before the `widget_card` route in `app.py`:

```python
@app.route("/widget/badge/<snapshot_id>.svg")
def widget_badge(snapshot_id):
    """Embeddable SVG badge — returns self-contained SVG for <img> embedding (NES-343)."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        abort(404)

    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)

    checks = result.get("presented_checks", [])
    clear_count = sum(1 for c in checks if c.get("result_type") == "CLEAR")
    concern_count = sum(
        1 for c in checks
        if c.get("result_type") in ("CONFIRMED_ISSUE", "WARNING_DETECTED")
    )

    score = result.get("final_score") or 0
    band = get_score_band(score)

    # Map css_class to hex color (same mapping as widget_card.html)
    band_colors = {
        "band-exceptional": "#16A34A",
        "band-strong": "#65A30D",
        "band-moderate": "#D97706",
        "band-limited": "#EA580C",
        "band-concerning": "#DC2626",
    }
    band_color = band_colors.get(band["css_class"], "#DC2626")

    style = request.args.get("style", "banner")
    if style not in ("banner", "square"):
        style = "banner"

    resp = make_response(render_template(
        "widget_badge.html",
        snapshot_id=snapshot_id,
        score=score,
        band_label=band["label"],
        band_color=band_color,
        clear_count=clear_count,
        concern_count=concern_count,
        style=style,
    ))
    resp.headers["Content-Type"] = "image/svg+xml"
    resp.headers["Content-Security-Policy"] = "frame-ancestors *"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_widget_api.py -v`

Expected: All tests pass (both API and badge classes).

- [ ] **Step 6: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py templates/widget_badge.html tests/test_widget_api.py
git commit -m "feat(NES-343): add SVG badge widget

GET /widget/badge/<snapshot_id>.svg with ?style=banner|square.
Self-contained SVG with score pill, health status, NestCheck branding.
CORS *, 24hr cache, CSP frame-ancestors *."
```

---

### Task 3: Embed Code Generator (Button + Modal)

**Files:**
- Modify: `templates/_result_sections.html` (add button + modal HTML + JS)
- Modify: `static/css/report.css` (add modal CSS)

- [ ] **Step 1: Add embed modal CSS to report.css**

Add before the `@media print` section in `static/css/report.css` (~line 2202):

```css
/* --- Embed Modal (NES-343) --- */
.embed-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
}
.embed-overlay[hidden] { display: none; }
.embed-modal {
  background: var(--color-bg-card);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.16);
  width: 540px;
  max-width: 92vw;
  max-height: 80vh;
  overflow-y: auto;
}
.embed-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px 0 20px;
}
.embed-modal__header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin: 0;
}
.embed-modal__close {
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  color: var(--color-text-muted);
  line-height: 1;
}
.embed-modal__close:hover { color: var(--color-text-primary); }
.embed-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid var(--color-border-light);
  padding: 12px 20px 0 20px;
}
.embed-tab {
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-muted);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  margin-bottom: -1px;
}
.embed-tab:hover { color: var(--color-text-primary); }
.embed-tab--active {
  color: var(--color-text-primary);
  border-bottom-color: var(--color-brand);
}
.embed-panel { padding: 16px 20px 20px 20px; }
.embed-panel[hidden] { display: none; }
.embed-preview {
  background: var(--color-bg-page);
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  padding: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
  min-height: 80px;
}
.embed-snippet {
  position: relative;
}
.embed-snippet pre {
  background: var(--color-bg-page);
  border: 1px solid var(--color-border-light);
  border-radius: 6px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--color-text-secondary);
  margin: 0;
}
.embed-copy-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  cursor: pointer;
}
.embed-copy-btn:hover { background: var(--color-bg-subtle); }
.embed-copy-btn.copied {
  background: var(--color-pass-text);
  color: #fff;
  border-color: var(--color-pass-text);
}
.embed-style-toggle {
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}
.embed-style-toggle button {
  padding: 4px 12px;
  font-size: 12px;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  cursor: pointer;
}
.embed-style-toggle button:hover { background: var(--color-bg-subtle); }
.embed-style-toggle button.active {
  background: var(--color-brand);
  color: #fff;
  border-color: var(--color-brand);
}
```

- [ ] **Step 2: Add Embed button and modal HTML to _result_sections.html**

In `_result_sections.html`, add the Embed button after the CSV link (line 1333) and before the `{% if compare_index %}` block (line 1334):

```html
        <button class="share-btn share-btn--secondary" onclick="document.getElementById('embedModal').hidden=false" aria-label="Get embed code">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
          <span>Embed</span>
        </button>
```

Then add the modal HTML after the share bar `</div>` closing tags (after line 1345, before the city page link):

```html
    {# ── EMBED MODAL (NES-343) ── #}
    <div class="embed-overlay" id="embedModal" hidden>
      <div class="embed-modal" onclick="event.stopPropagation()">
        <div class="embed-modal__header">
          <h3>Embed this report</h3>
          <button class="embed-modal__close" onclick="document.getElementById('embedModal').hidden=true" aria-label="Close">&times;</button>
        </div>
        <div class="embed-tabs" role="tablist">
          <button class="embed-tab embed-tab--active" role="tab" data-embed-tab="badge" aria-selected="true">Badge</button>
          <button class="embed-tab" role="tab" data-embed-tab="card" aria-selected="false">Card</button>
          <button class="embed-tab" role="tab" data-embed-tab="api" aria-selected="false">API</button>
        </div>

        {# Badge panel #}
        <div class="embed-panel" id="embed-panel-badge" role="tabpanel">
          <div class="embed-style-toggle">
            <button class="active" data-badge-style="banner">Banner</button>
            <button data-badge-style="square">Square</button>
          </div>
          <div class="embed-preview">
            <img id="embedBadgePreview" src="/widget/badge/{{ snapshot_id }}.svg" alt="NestCheck Badge" width="200" height="60">
          </div>
          <div class="embed-snippet">
            <button class="embed-copy-btn" onclick="copyEmbedSnippet(this)">Copy</button>
            <pre id="embedBadgeCode"></pre>
          </div>
        </div>

        {# Card panel #}
        <div class="embed-panel" id="embed-panel-card" role="tabpanel" hidden>
          <div class="embed-preview">
            <iframe src="/widget/card/{{ snapshot_id }}" width="300" height="200" frameborder="0" style="border: none;"></iframe>
          </div>
          <div class="embed-snippet">
            <button class="embed-copy-btn" onclick="copyEmbedSnippet(this)">Copy</button>
            <pre id="embedCardCode"></pre>
          </div>
        </div>

        {# API panel #}
        <div class="embed-panel" id="embed-panel-api" role="tabpanel" hidden>
          <div class="embed-preview" style="justify-content: flex-start;">
            <pre id="embedApiPreview" style="font-size: 11px; margin: 0; white-space: pre-wrap; word-break: break-all;"></pre>
          </div>
          <div class="embed-snippet">
            <button class="embed-copy-btn" onclick="copyEmbedSnippet(this)">Copy</button>
            <pre id="embedApiCode"></pre>
          </div>
        </div>
      </div>
    </div>
```

- [ ] **Step 3: Add embed modal JS to _result_sections.html**

Add inside the existing `<script>` block at the bottom of `_result_sections.html`:

```javascript
/* ── Embed Modal (NES-343) ── */
(function() {
  var sid = '{{ snapshot_id | e }}';
  var baseUrl = location.origin;
  var score = {{ result.final_score or 0 }};
  var band = '{{ band_label | e }}';

  // Snippet generators
  function badgeSnippet(style) {
    var w = style === 'square' ? 120 : 200;
    var h = style === 'square' ? 120 : 60;
    var styleParam = style === 'square' ? '?style=square' : '';
    var alt = 'NestCheck Score: ' + score + ' (' + band + ')';
    return '<a href="' + baseUrl + '/s/' + sid + '?utm_source=widget&utm_medium=badge" rel="noopener noreferrer">\n  <img src="' + baseUrl + '/widget/badge/' + sid + '.svg' + styleParam + '" alt="' + alt + '" width="' + w + '" height="' + h + '">\n</a>';
  }

  var cardSnippet = '<iframe src="' + baseUrl + '/widget/card/' + sid + '" width="300" height="200" frameborder="0" style="border: none;"></iframe>';

  var apiSnippet = 'curl ' + baseUrl + '/api/v1/widget-data/' + sid;

  // Initialize snippets
  var badgeCode = document.getElementById('embedBadgeCode');
  var cardCode = document.getElementById('embedCardCode');
  var apiCode = document.getElementById('embedApiCode');
  var apiPreview = document.getElementById('embedApiPreview');

  if (badgeCode) badgeCode.textContent = badgeSnippet('banner');
  if (cardCode) cardCode.textContent = cardSnippet;
  if (apiCode) apiCode.textContent = apiSnippet;

  // Fetch API preview
  if (apiPreview) {
    fetch('/api/v1/widget-data/' + sid)
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) { if (data) apiPreview.textContent = JSON.stringify(data, null, 2); })
      .catch(function() { apiPreview.textContent = '(Could not load preview)'; });
  }

  // Tab switching
  document.querySelectorAll('[data-embed-tab]').forEach(function(tab) {
    tab.addEventListener('click', function() {
      document.querySelectorAll('[data-embed-tab]').forEach(function(t) {
        t.classList.remove('embed-tab--active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('embed-tab--active');
      tab.setAttribute('aria-selected', 'true');
      document.querySelectorAll('.embed-panel').forEach(function(p) { p.hidden = true; });
      var panel = document.getElementById('embed-panel-' + tab.dataset.embedTab);
      if (panel) panel.hidden = false;
    });
  });

  // Badge style toggle
  document.querySelectorAll('[data-badge-style]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('[data-badge-style]').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
      var style = btn.dataset.badgeStyle;
      var img = document.getElementById('embedBadgePreview');
      if (img) {
        img.src = '/widget/badge/' + sid + '.svg' + (style === 'square' ? '?style=square' : '');
        img.width = style === 'square' ? 120 : 200;
        img.height = style === 'square' ? 120 : 60;
      }
      if (badgeCode) badgeCode.textContent = badgeSnippet(style);
    });
  });

  // Close modal on overlay click or Escape
  var overlay = document.getElementById('embedModal');
  if (overlay) {
    overlay.addEventListener('click', function(e) {
      if (e.target === overlay) overlay.hidden = true;
    });
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && !overlay.hidden) overlay.hidden = true;
    });
  }
})();

function copyEmbedSnippet(btn) {
  var pre = btn.parentElement.querySelector('pre');
  if (!pre) return;
  navigator.clipboard.writeText(pre.textContent).then(function() {
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(function() { btn.textContent = 'Copy'; btn.classList.remove('copied'); }, 2000);
  });
}
```

- [ ] **Step 4: Hide embed modal in print CSS**

In `static/css/report.css`, update the print media query (line ~2204) to include `.embed-overlay`:

Change: `nav, .share-bar, footer { display: none; }`
To: `nav, .share-bar, .embed-overlay, footer { display: none; }`

- [ ] **Step 5: Manual verification**

Run the Flask dev server and verify:
1. Navigate to any snapshot page
2. "Embed" button appears in the share bar
3. Clicking it opens the modal with three tabs
4. Badge tab: banner/square toggle works, preview updates, snippet updates
5. Card tab: shows live iframe preview
6. API tab: shows live JSON preview
7. Copy buttons work
8. Modal closes on overlay click, X button, and Escape key

Run: `cd /Users/jeremybrowning/NestCheck && python app.py`

- [ ] **Step 6: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add templates/_result_sections.html static/css/report.css
git commit -m "feat(NES-343): add embed code generator modal

Embed button in share bar opens modal with Badge/Card/API tabs.
Badge tab has banner/square toggle with live preview. Copy-paste
snippets for all three widget types."
```

---

### Task 4: Update CLAUDE.md + Smoke Test Markers

**Files:**
- Modify: `CLAUDE.md` (already has NES-349 widget section — extend it)
- Modify: `smoke_test.py` (add widget endpoints to smoke checks if applicable)

- [ ] **Step 1: Update CLAUDE.md decision log**

Add to the Decision Log table:

```
| 2026-03 | Badge SVG + widget data API + embed generator (NES-343) | CTO-guided scope: badge SVG (banner/square), JSON API, embed modal. Excluded: API keys, rate limiting, JS widget, PNG. Three new deserialization paths (badge, API, embed modal preview). Badge uses `abort(404)` (HTML fine for direct browser access); API uses `jsonify()` 404 (JSON consumers). `band_colors` dict in badge route maps `css_class` → hex, same mapping as `widget_card.html` Jinja2 conditionals |
```

- [ ] **Step 2: Add widget route docs to CLAUDE.md**

Add under the "Embeddable Widget Templates" section:

```markdown
- **Badge route (`widget_badge`)**: `GET /widget/badge/<snapshot_id>.svg?style=banner|square`. Returns SVG. Route maps `band["css_class"]` to hex color via `band_colors` dict (unlike card widget which maps in Jinja2). Invalid `style` param defaults to `banner`.
- **Widget data API (`api_widget_data`)**: `GET /api/v1/widget-data/<snapshot_id>`. Returns JSON. 404 uses `jsonify()` (not `abort()`). `health_summary` string uses same pluralization as card widget template.
- **Embed modal**: Vanilla JS in `_result_sections.html`. Three tabs (Badge/Card/API). Badge tab fetches live SVG preview and updates snippet on style toggle. API tab fetches from widget-data endpoint on modal open. Modal CSS in `report.css` (`.embed-*` prefix). Hidden in print CSS.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with NES-343 widget/embed patterns"
```
