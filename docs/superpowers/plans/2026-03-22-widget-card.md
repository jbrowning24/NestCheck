# Widget Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an embeddable score card widget at `GET /widget/card/<snapshot_id>` that returns a self-contained HTML document for iframe embedding.

**Architecture:** Single Flask route loads snapshot via `get_snapshot()`, runs `_prepare_snapshot_for_display()` on a shallow copy, then renders a standalone Jinja template with inline `<style>` block. Zero external CSS/JS dependencies. CDO-approved layout: score pill + band label, address, health summary, CTA bar.

**Tech Stack:** Flask route, Jinja2 standalone template, inline CSS only.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app.py` | Modify (~line 3493, after `view_snapshot`) | Add `widget_card()` route |
| `templates/widget_card.html` | Create | Self-contained HTML document with inline CSS |

No test files — this is pure presentation HTML with no business logic beyond what's already tested (snapshot loading, display prep, score bands).

---

### Task 1: Add the widget card route to app.py

**Files:**
- Modify: `app.py` (after `view_snapshot()` at ~line 3493)

- [ ] **Step 1: Add the route handler**

Insert after `view_snapshot()` (line ~3493):

```python
@app.route("/widget/card/<snapshot_id>")
def widget_card(snapshot_id):
    """Embeddable score card widget — returns complete HTML for iframe."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        abort(404)

    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)

    # Health summary counts
    checks = result.get("presented_checks", [])
    clear_count = sum(
        1 for c in checks if c.get("result_type") == "CLEAR"
    )
    concern_count = sum(
        1 for c in checks
        if c.get("result_type") in ("CONFIRMED_ISSUE", "WARNING_DETECTED")
    )

    # Score band
    score = result.get("final_score", 0)
    band = get_score_band(score)

    # Configurable dimensions via query params
    width = request.args.get("w", 300, type=int)
    height = request.args.get("h", 200, type=int)

    resp = make_response(render_template(
        "widget_card.html",
        snapshot_id=snapshot_id,
        address=result.get("address", snapshot.get("address_norm", "")),
        score=score,
        band_label=band["label"],
        band_css_class=band["css_class"],
        clear_count=clear_count,
        concern_count=concern_count,
        width=width,
        height=height,
    ))
    resp.headers["X-Frame-Options"] = "ALLOWALL"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp
```

Key decisions:
- `X-Frame-Options: ALLOWALL` — explicitly designed for iframe embedding.
- CORS `*` for cross-origin access.
- 24hr public cache (`max-age=86400`).
- Width/height passed to template for responsive sizing.
- No `increment_view_count()` — widget impressions should not inflate snapshot view counts.

- [ ] **Step 2: Verify route loads without errors**

Run: `cd /Users/jeremybrowning/NestCheck && python -c "from app import app; print('OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(NES-349): add /widget/card/<snapshot_id> route"
```

---

### Task 2: Create the widget card template

**Files:**
- Create: `templates/widget_card.html`

- [ ] **Step 1: Create the standalone HTML template**

Create `templates/widget_card.html` with:
- Complete `<!DOCTYPE html>` document (does NOT extend `_base.html`)
- Inline `<style>` block with all CSS — zero external dependencies
- System font stack (no Inter/Google Fonts)
- CDO-approved layout: score pill → band label → address → health summary → CTA bar
- Band color mapping via Jinja conditional (hardcoded hex values matching token system)
- UTM-tagged CTA link: `utm_source=widget&utm_medium=iframe&utm_content=card`
- `rel="noopener noreferrer"` on CTA link (per CLAUDE.md rule)
- Responsive via `max-width: 100%; box-sizing: border-box`

Band color mapping (hardcoded, mirroring tokens.css):
- `band-exceptional` → `#16A34A`
- `band-strong` → `#65A30D`
- `band-moderate` → `#D97706`
- `band-limited` → `#EA580C`
- `band-poor` → `#DC2626`

Layout zones (CDO spec):
1. **Score row** (~44px): Score pill (band-colored bg, white number, 20px semibold) + band label (13px, secondary text)
2. **Address** (~28px): Full address, 13px, primary text, ellipsis overflow
3. **Health summary** (~28px): Colored dot + summary text, 12px
4. **Spacer**: flex-grow
5. **CTA bar** (~40px): Full-width navy bar, white text, 12px

Health summary logic:
- Zero concerns: green dot (#16A34A) + "All checks clear"
- Non-zero: amber dot (#D97706) + "N concern(s) flagged"

- [ ] **Step 2: Verify template renders**

Run the dev server and test with a known snapshot ID:
```bash
cd /Users/jeremybrowning/NestCheck && python -c "
from app import app
with app.test_client() as c:
    # Use a snapshot that exists in the local DB
    resp = c.get('/widget/card/test-nonexistent')
    print(f'404 test: {resp.status_code}')
"
```
Expected: `404 test: 404`

- [ ] **Step 3: Commit**

```bash
git add templates/widget_card.html
git commit -m "feat(NES-349): add widget_card.html standalone template"
```

---

### Task 3: Manual visual verification

- [ ] **Step 1: Find a valid snapshot ID for testing**

```bash
cd /Users/jeremybrowning/NestCheck && python -c "
from models import _get_db
conn = _get_db()
row = conn.execute('SELECT snapshot_id FROM evaluation_snapshots ORDER BY rowid DESC LIMIT 1').fetchone()
conn.close()
print(row[0] if row else 'No snapshots')
"
```

- [ ] **Step 2: Test the widget endpoint in browser or curl**

```bash
curl -s "http://localhost:5001/widget/card/<SNAPSHOT_ID>" | head -50
```

Verify:
- Returns complete HTML document
- Contains inline `<style>` block
- Score, band label, address, health summary, CTA all present
- `X-Frame-Options: ALLOWALL` header
- `Access-Control-Allow-Origin: *` header
- `Cache-Control: public, max-age=86400` header

- [ ] **Step 3: Test with width/height params**

```bash
curl -s "http://localhost:5001/widget/card/<SNAPSHOT_ID>?w=400&h=250" | grep "max-width"
```

Verify the dimensions are reflected in the template.

- [ ] **Step 4: Final commit (if any fixes needed)**

---

## Embed Code Reference

```html
<iframe src="https://nestcheck.org/widget/card/<id>" width="300" height="200" frameborder="0"></iframe>
```
