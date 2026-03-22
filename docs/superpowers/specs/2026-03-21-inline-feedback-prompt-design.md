# NES-362: Inline Feedback Prompt at Bottom of Report Page

**Status:** Approved
**Parent:** NES-360 (Feedback initiative)
**Approach:** A — Minimal (single endpoint, inline in app.py)

## Summary

Add a lightweight inline feedback prompt at the bottom of the report page, capturing the immediate "did this surprise you?" reaction while the report is fresh. The prompt appears below "How We Score" and above the footer, inside a neutral callout component.

## Decisions

| Decision | Resolution | Source |
|----------|-----------|--------|
| Anonymous vs authenticated | Both — layered `user_id` / `visitor_id` | CTO consultation |
| Freshness timestamp | `evaluated_at` (not `created_at`) | CTO consultation |
| Freshness constant | `FEEDBACK_PROMPT_MAX_AGE_DAYS = 30` in `app.py` | CTO consultation |
| `csrfFetch` location | Extract from `index.html` to `_base.html` | CTO consultation |
| Visitor identity | `nestcheck_vid` cookie (UUID, 30-day, `SameSite=Lax`) | CTO consultation |
| Yes/No required | Required before submit; free text optional | User confirmation |
| Architecture | Approach A — routes in `app.py`, models in `models.py`, no Blueprint | User confirmation |

## 1. Database Schema & Models

### New table (`models.py`)

```sql
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL,
    user_id INTEGER,
    visitor_id TEXT,
    feedback_type TEXT NOT NULL DEFAULT 'inline_reaction',
    told_something_new INTEGER NOT NULL,  -- 1 or 0
    free_text TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_snapshot_user
    ON feedback(snapshot_id, user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_snapshot_visitor
    ON feedback(snapshot_id, visitor_id);
```

### Helper functions

- **`save_feedback(snapshot_id, user_id, visitor_id, feedback_type, told_something_new, free_text)`** — INSERT with retry pattern matching existing `models.py` style. Calls `has_feedback()` first; returns `True` on success, `False` on duplicate.
- **`has_feedback(snapshot_id, user_id, visitor_id)`** — checks both `user_id` (if not None) and `visitor_id`. Returns `bool`.

No UNIQUE constraint on the composite because SQLite treats NULL as always-distinct. Dedup is check-then-insert; a race produces a duplicate row (low stakes).

## 2. API Endpoints

### `POST /api/feedback`

- **Request body (JSON):** `{snapshot_id, feedback_type, told_something_new, free_text}`
- **Identity:** `current_user.id` if authenticated; `request.cookies.get('nestcheck_vid')` for anonymous
- **Validation:** snapshot exists (`get_snapshot`), `told_something_new` is `0` or `1`, `free_text` max 1000 chars, at least one identity present
- **Responses:**
  - `201 {"status": "ok"}` — saved
  - `200 {"status": "duplicate"}` — already submitted
  - `400 {"error": "..."}` — validation failure
  - `404 {"error": "..."}` — snapshot not found
- **CSRF:** Protected via Flask-WTF; client uses `csrfFetch`

### `GET /api/feedback/<snapshot_id>/status`

- **Identity:** `current_user.id` and/or `request.cookies.get('nestcheck_vid')`
- **Response:** `{"submitted": true/false}`
- **No auth required** — identity comes from session/cookie

Both endpoints return JSON. Error handlers already cover 400/404/500 for JSON clients.

## 3. Template & Frontend

### Placement

In `_result_sections.html`, below "How We Score" section, above footer. Wrapped in `{% if show_feedback_prompt %}`.

### Component structure

Uses the `callout` macro from `_macros.html` for the outer wrapper, with an `id="feedback-prompt"` on a containing div for JS targeting:

```html
{% if show_feedback_prompt %}
<div id="feedback-prompt">
  {% call callout(variant='neutral') %}
    <!-- consent line -->
    <!-- Yes/No toggle buttons -->
    <!-- optional free text (3-line textarea) -->
    <!-- Submit button (disabled until Yes/No selected) -->
  {% endcall %}
</div>
{% endif %}
```

### UI states

1. **Fresh form** — Yes/No unselected, submit disabled
2. **Yes/No selected** — active button gets `.feedback-btn--selected`, submit enabled
3. **Submitting** — submit shows "Sending...", disabled
4. **Success** — form replaced with "Thanks! Your feedback has been recorded."
5. **Error** — inline "Something went wrong -- your feedback wasn't saved" with retry
6. **Already submitted** — on page load, status check replaces form with "You've already shared feedback. Thank you!"

### Content

```
Your feedback helps improve NestCheck. We won't share your responses outside our development team.

Did this report tell you something you didn't already know about this address?
[Yes]  [No]

Anything specific that stood out? (optional)
[free text field, 3 lines]

[Submit feedback]
```

### JavaScript (~25 lines, inline in `_result_sections.html`)

- Yes/No toggle handler: sets hidden value, enables submit button
- Submit handler: `csrfFetch('/api/feedback', {method: 'POST', body: JSON.stringify({...})})`
- On success: swap `#feedback-prompt` innerHTML to thank-you text
- On error: show error message with retry button
- On page load: plain `fetch('/api/feedback/{snapshot_id}/status')` (GET — no CSRF needed) — if `submitted: true`, show "already shared" message

### `view_snapshot()` in `app.py`

```python
FEEDBACK_PROMPT_MAX_AGE_DAYS = 30

evaluated_at = datetime.fromisoformat(snapshot["evaluated_at"])
show_feedback_prompt = (
    datetime.now(timezone.utc) - evaluated_at
).days <= FEEDBACK_PROMPT_MAX_AGE_DAYS
```

Pass `show_feedback_prompt` to `render_template()`.

**Scope:** Only snapshot pages (`/s/<snapshot_id>`). The homepage live evaluation does not show the prompt — `show_feedback_prompt` is only set by `view_snapshot()`.

## 4. Shared Infrastructure Changes

### `_base.html`

1. **`csrfFetch` extraction** — move function from `index.html` to `<script>` block at end of `<body>` (before `{% block page_scripts %}`). Remove from `index.html`. All pages inherit.

2. **`nestcheck_vid` cookie** — inline script in `<head>`:
   ```javascript
   if (!document.cookie.match(/nestcheck_vid=/)) {
       document.cookie = 'nestcheck_vid=' + crypto.randomUUID() +
           '; path=/; max-age=' + (30*86400) + '; SameSite=Lax';
   }
   ```

### CSS

The `callout` macro exists in `_macros.html` but has no backing CSS. Add `.callout` and `.callout--neutral` styles to `report.css` (left-border accent, padding, background per design system section 4.7). Use the `callout` macro from `_macros.html` for the component wrapper rather than raw HTML divs. Vanilla form inputs use existing form CSS from `base.css`.

New in `report.css`:
- `.callout` — base callout component (left border accent, padding, subtle background)
- `.callout--neutral` — neutral variant (uses `--color-border-light` / `--color-bg-surface-alt`)
- `.feedback-btn` — Yes/No toggle button base style
- `.feedback-btn--selected` — active state highlight

### Files changed

| File | Change |
|------|--------|
| `models.py` | Add `feedback` table creation, `save_feedback()`, `has_feedback()` |
| `app.py` | Add `FEEDBACK_PROMPT_MAX_AGE_DAYS`, `POST /api/feedback`, `GET /api/feedback/<snapshot_id>/status`, `show_feedback_prompt` in `view_snapshot()` |
| `templates/_base.html` | Add `csrfFetch` script block, `nestcheck_vid` cookie script |
| `templates/index.html` | Remove `csrfFetch` definition (now inherited) |
| `templates/_result_sections.html` | Add feedback prompt HTML + inline JS |
| `static/css/report.css` | Add `.feedback-btn`, `.feedback-btn--selected` |

### Files NOT changed

- `smoke_test.py` — feedback prompt is behind `{% if %}` guard, doesn't affect markers
- `scoring_config.py` — `FEEDBACK_PROMPT_MAX_AGE_DAYS` is a UX threshold, not scoring
- `snapshot.html` — no changes needed; it includes `_result_sections.html` which has the form
- No new JS files — all inline
