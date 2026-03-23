# NES-343: Widget Badge, Data API & Embed Code Generator

**Date:** 2026-03-23
**Status:** Approved
**Linear:** NES-343

## Scope

Three components to enable third-party embedding of NestCheck scores:

1. **Health Score Badge (SVG)** — lightweight `<img>`-embeddable badge
2. **Widget Data API** — JSON endpoint for programmatic access
3. **Embed Code Generator** — modal on report page with copy-paste snippets

**Explicitly excluded (per CTO guidance):** API key table, rate limiting, JS widget with shadow DOM, PNG badge rendering. These ship when distribution numbers justify the complexity.

## 1. Badge SVG Route

**Endpoint:** `GET /widget/badge/<snapshot_id>.svg`

**Query params:**
- `style` — `banner` (200×60, default) or `square` (120×120)

**Implementation:**
- Jinja2 SVG template: `templates/widget_badge.html`
- Self-contained SVG with inline text and shapes — no Pillow, no external fonts, no external dependencies
- System font stack via SVG `font-family` attribute (`-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`)
- Route maps `band["css_class"]` to hex color via a Python `band_colors` dict and passes `band_color` directly to the template (cleaner than the card widget's Jinja2 `{% if/elif %}` pattern — no logic duplication in the SVG template)

**Banner layout (200×60):**
- NestCheck logo mark (two skewed rectangles, simplified for SVG)
- Score pill (colored rounded rect + white score number)
- Health status text: "10 Clear" or "2 Concerns"
- "nestcheck.org" in small text at right

**Square layout (120×120):**
- Score number (large, centered, colored)
- Band label below score ("Strong", "Moderate", etc.)
- Health status line ("10 Clear")
- "NestCheck" at bottom

**Link:** The SVG contains an `<a>` link to `/s/<snapshot_id>?utm_source=widget&utm_medium=badge&utm_content=<style>`. Note: this link is only functional when the SVG is opened directly in a browser, not when embedded via `<img>`. The embed snippet wraps the `<img>` in an `<a>` tag for clickability.

**Route handler pattern:** Mirrors `widget_card()` exactly:
- `get_snapshot(snapshot_id)` → 404 if missing
- `{**snapshot["result"]}` → `_prepare_snapshot_for_display(result)`
- Extract `clear_count`, `concern_count` from `presented_checks`
- `get_score_band(score)` for band color and label
- `make_response()` with headers

**Response headers:**
- `Content-Type: image/svg+xml`
- `Content-Security-Policy: frame-ancestors *`
- `Access-Control-Allow-Origin: *`
- `Cache-Control: public, max-age=86400`

**No view count tracking** (same policy as card widget — iframe/img embeds would inflate counts).

## 2. Widget Data API

**Endpoint:** `GET /api/v1/widget-data/<snapshot_id>`

**Response (200):**
```json
{
  "score": 72,
  "band": "Moderate",
  "address": "123 Main St, White Plains, NY",
  "health_summary": "10 clear",
  "clear_count": 10,
  "concern_count": 0,
  "report_url": "https://nestcheck.org/s/abc123"
}
```

**Response (404):**
```json
{"error": "Snapshot not found"}
```

**Implementation:**
- ~20 lines in `app.py`
- Reuses `get_snapshot()` + `_prepare_snapshot_for_display()` + `get_score_band()`
- `report_url` uses `request.host_url.rstrip('/') + '/s/' + snapshot_id` for absolute URL
- `health_summary` string: `f"{clear_count} clear"` when no concerns, `f"{clear_count} clear / {concern_count} concern{'s' if concern_count != 1 else ''}"` when concerns exist
- 404 returns `jsonify({"error": "Snapshot not found"}), 404` directly (not `abort(404)`, which returns HTML by default)
- No auth, no API keys

**Response headers:**
- `Content-Type: application/json` (Flask `jsonify` default)
- `Access-Control-Allow-Origin: *`
- `Cache-Control: public, max-age=86400`

## 3. Embed Code Generator

**Trigger:** "Embed" button in the share bar (`share-bar__actions`), placed after CSV and before Compare. Uses `share-btn share-btn--secondary` class with a `</>` code icon SVG.

**Modal (`#embedModal`):**
- Vanilla JS + inline CSS in `_result_sections.html` (follows existing patterns)
- Three tabs: **Badge** | **Card** | **API**
- Each tab contains:
  - Live preview area
  - Code snippet in a `<pre>` block
  - "Copy" button that copies the snippet to clipboard

**Badge tab:**
- Banner/square toggle (two small buttons)
- Preview: `<img>` tag pointing at `/widget/badge/<snapshot_id>.svg?style=<selected>`
- Snippet updates dynamically when toggle changes — both `?style=` param and `width`/`height` attributes:
  - Banner: `width="200" height="60"` (default, `?style=banner` omitted)
  - Square: `width="120" height="120"`, `?style=square` appended
- Snippet:
  ```html
  <a href="https://nestcheck.org/s/<id>?utm_source=widget&utm_medium=badge">
    <img src="https://nestcheck.org/widget/badge/<id>.svg" alt="NestCheck Score: 72 (Moderate)" width="200" height="60">
  </a>
  ```

**Card tab:**
- Preview: live `<iframe>` pointing at existing `/widget/card/<snapshot_id>`
- Snippet:
  ```html
  <iframe src="https://nestcheck.org/widget/card/<id>" width="300" height="200" frameborder="0" style="border: none;"></iframe>
  ```

**API tab:**
- Preview: formatted JSON response (fetched from widget-data endpoint)
- Snippet:
  ```
  curl https://nestcheck.org/api/v1/widget-data/<id>
  ```

**Modal behavior:**
- Dismissed by: clicking outside, X button, Escape key
- Uses `position: fixed; inset: 0` overlay pattern
- `z-index` above all other page content
- No scroll lock on body (keep it simple)

**CSS:** Inline in `_result_sections.html` within the existing `<style>` block. Follows existing modal patterns if any exist in the codebase; otherwise minimal custom CSS.

## Files Changed

| File | Change |
|------|--------|
| `app.py` | Add `widget_badge()` route, `api_widget_data()` route |
| `templates/widget_badge.html` | New — SVG Jinja2 template (banner + square variants) |
| `templates/_result_sections.html` | Add Embed button to share bar, embed modal HTML/CSS/JS |

**Note:** Badge and API routes are new deserialization paths (6th and 7th). Both must call `_prepare_snapshot_for_display()` for old-snapshot compatibility.

## Testing

- Playwright test: navigate to badge SVG URL, verify SVG content renders (status code 200, content-type `image/svg+xml`)
- Playwright test: verify embed button appears on snapshot page, opens modal
- Manual: embed badge `<img>` and card `<iframe>` on a test HTML page to verify cross-origin rendering
- curl the widget-data API and verify JSON shape

## Open Questions (Deferred)

- Auto-update when re-evaluated? Currently shows the snapshot it was created from. Fine for now.
- Pro widget tier with white-label? Not until B2B partners request it.
- Widget for unevaluated addresses? Not in scope — widgets require an existing snapshot.
