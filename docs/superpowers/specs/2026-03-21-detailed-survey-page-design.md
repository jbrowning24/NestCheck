# NES-363: Detailed Survey Page Design

**Date:** 2026-03-21
**Status:** Draft
**Linear:** [NES-363](https://linear.app/nestcheck/issue/NES-363/detailed-survey-page-get-feedbacksnapshot-id)
**Parent:** NES-360

---

## Overview

Build a standalone survey page at `GET /feedback/<snapshot_id>` for collecting detailed user feedback on evaluation accuracy and willingness to pay. The page is shared via email (no auth required) and renders a Jinja form with four sections: willingness to pay, per-dimension accuracy grading, health check accuracy, and overall assessment.

## Approach

**Approach A: Single-template monolith.** One new template, one new route, one new endpoint, one new table. Simplest option — follows existing patterns and YAGNI. No macros, no wizard, no composition abstraction.

## Data Model

### New table: `feedback` in `nestcheck.db`

```sql
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL,
    feedback_type TEXT NOT NULL,
    response_json TEXT NOT NULL,
    address_norm TEXT,
    visitor_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_snapshot ON feedback(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback(feedback_type);
```

- Created in `init_db()` alongside existing tables.
- `created_at` set explicitly in Python via `datetime.now(timezone.utc).isoformat()` — no SQLite DEFAULT.
- `address_norm` denormalized for join-free aggregate analysis.
- `visitor_id` from cookie for analytics correlation, not user identity.

### Helper: `save_feedback()` in `models.py`

```python
def save_feedback(snapshot_id, feedback_type, response_json, address_norm=None, visitor_id=None):
```

Follows `log_event()` pattern: open connection inside `try`, `finally: conn.close()`, retry up to 3x on `OperationalError` with "locked"/"busy".

### Response JSON schema for `feedback_type='detailed_survey'`

```json
{
  "wtp_would_pay": "definitely_yes|probably_yes|probably_no|definitely_no",
  "wtp_max_price": "free|5|10|15|25_plus",
  "dimensions": {
    "Coffee & Social Spots": {"accuracy": 3, "comment": "..."},
    "Groceries": {"accuracy": 5, "comment": null}
  },
  "health_missed": "free text or null",
  "health_overstated": "free text or null",
  "overall_accuracy": 4,
  "most_useful": "free text or null",
  "missing_expected": "free text or null"
}
```

Dimension keys are display names at time of survey — historical data, not migrated when names change.

### Analytics event

In addition to saving to the `feedback` table, log a `feedback_submitted` event via `log_event()` with metadata `{"feedback_type": "detailed_survey"}`. Analytics pipeline knows when feedback was submitted without querying a separate table.

## Route: `GET /feedback/<snapshot_id>`

```python
@app.route("/feedback/<snapshot_id>")
def feedback_survey(snapshot_id):
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        abort(404)
    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)

    graded_dims = [d for d in result.get("dimension_summaries", [])
                   if d.get("score") is not None
                   and d.get("data_confidence") != "not_scored"]

    return render_template("feedback.html",
                           snapshot=snapshot,
                           result=result,
                           graded_dims=graded_dims)
```

- No auth required.
- Invalid/missing `snapshot_id` returns 404.
- Preview snapshots (`is_preview=True`) render with empty `graded_dims` — Sections 1, 3, 4 still apply.
- Shallow-copies `result` before `_prepare_snapshot_for_display()` per existing pattern.

### Dimension filtering

Only show dimensions where `points is not None` and `data_confidence != "not_scored"`. Estimated-confidence dimensions (capped at 8/10) are included — their accuracy ratings are the most valuable signal for calibrating the confidence system.

## Endpoint: `POST /api/feedback`

- CSRF-protected via `csrfFetch` pattern (no `@csrf.exempt`).
- Validates: `snapshot_id` required, `feedback_type` required, `response_json` is valid JSON string.
- Calls `save_feedback()` then `log_event("feedback_submitted", ...)`.
- Returns `{"success": true}` on success, `{"success": false, "error": "..."}` with 400 on validation failure.

### Security decisions

- **No auth**: Link shared via email — auth kills response rates.
- **No replay protection**: Low-stakes data collection from known audience. Duplicate rows filtered in analysis, not at submission. CTO guidance: add later if abuse appears in data.
- **CSRF**: Non-negotiable. Uses existing `csrfFetch` auto-retry pattern with `X-CSRFToken` header from `<meta>` tag.

## Template: `feedback.html`

Extends `_base.html`. Single scrollable form with four sections and in-page thank-you swap.

### Structure

```
feedback.html
├── {% block title %} — "Feedback — NestCheck"
├── {% block extra_css %} — feedback.css
├── {% block content %}
│   ├── Consent text (one line, subtle card)
│   ├── Address context bar (score ring + address + band + date)
│   ├── <form id="feedback-form">
│   │   ├── Section 1: WILLINGNESS TO PAY (L2 header)
│   │   │   ├── "Would you have paid $10-15?" — 4-option segmented control
│   │   │   └── "Most you'd pay?" — 5-option segmented control
│   │   ├── Section 2: DIMENSION ACCURACY (L2 header)
│   │   │   └── {% for dim in graded_dims %}
│   │   │       ├── Dim card (left border + score pill + band label)
│   │   │       ├── 1-5 segmented scale
│   │   │       └── Optional textarea
│   │   ├── Section 3: HEALTH CHECK ACCURACY (L2 header)
│   │   │   ├── "Concerns the report missed?" — textarea
│   │   │   └── "Warnings inaccurate/overstated?" — textarea
│   │   ├── Section 4: OVERALL (L2 header)
│   │   │   ├── "Overall accuracy?" — 1-5 segmented scale
│   │   │   ├── "Most useful thing?" — textarea
│   │   │   └── "What was missing?" — textarea
│   │   └── Submit button (accent blue)
│   └── <div id="thank-you" style="display:none">
│       └── Thank-you message
├── {% block scripts %}
│   ├── csrfFetch() (same pattern as index.html)
│   ├── Form serialize → JSON
│   ├── POST /api/feedback
│   └── On success: hide form, show #thank-you, scroll to top
```

### Visual design (CDO-approved)

**Address context bar:** Score ring (reuse `score_ring` macro from `_macros.html`), address in `--type-l3-*`, band pill, evaluation date. White card with border + subtle shadow.

**Section headers:** `--type-l2-*` tokens (12px uppercase, `--color-text-faint`, `--tracking-section`). Matches report section label pattern.

**Segmented radio controls:** Horizontal row of labeled segments. Hidden radio + label styling. `var(--color-border)` dividers, `var(--color-accent-light)` selected state with `var(--color-accent)` text, `var(--radius-sm)` corners.

**Mobile (< 640px) for 5-point scales:** Show number only in segment, full label text as `<legend>` above the group.

**Dimension accuracy cards:** Reuse `.dim-card` visual pattern — left border in band color (`--color-band-strong/moderate/limited`), score pill, uppercase band label. Compact read-only form (no summary paragraph). Each card contains its radio scale and optional textarea below.

**Textareas:** `var(--color-border)` border, `var(--radius-sm)`, `var(--font-size-input)` (16px — prevents iOS zoom), accent focus ring (`box-shadow: 0 0 0 2px var(--color-accent-light)`), `resize: vertical`.

**Submit button:** `var(--color-accent)` background, white text, `var(--radius-sm)`, `var(--font-weight-semibold)`, hover darkens to `var(--color-accent-hover)`.

### Thank-you state

On successful POST: hide `#feedback-form`, show `#thank-you` div, scroll to top. Pre-rendered in template. No dedicated route, no page reload. Three lines of JS.

## JS Behavior

Minimal vanilla JS in `{% block scripts %}`:

1. **`csrfFetch` copy** — token from `<meta>` tag, auto-retry on expired CSRF.
2. **Form serialization** — collect radio values + textarea values into `response_json` structure.
3. **Submit handler** — disable button, show "Submitting..." text, POST to `/api/feedback`. On success: hide form, show thank-you. On error: show inline error message above submit button (`var(--color-fail)` text).
4. **No client-side validation** — all fields optional, partial submission allowed. Only `snapshot_id` is required (from URL, not user input).

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Invalid `snapshot_id` | 404 (existing template) |
| Missing snapshot | 404 |
| Preview snapshot (`is_preview=True`) | Survey renders — Section 2 empty, Sections 1/3/4 still apply |
| POST validation failure | 400 + `{"success": false, "error": "..."}` |
| Empty form submission | Allowed — partial feedback better than none |
| DB locked on INSERT | Retry up to 3x with backoff (matches `log_event()` pattern) |

## Files Changed

| File | Change |
|------|--------|
| `models.py` | Add `feedback` table to `init_db()`, add `save_feedback()` function |
| `app.py` | Add `GET /feedback/<snapshot_id>` route, add `POST /api/feedback` endpoint |
| `templates/feedback.html` | New template extending `_base.html` |
| `static/css/feedback.css` | New stylesheet (segmented radios, dim cards, textareas, context bar) |

No changes to existing templates, CSS, or models. No migrations. Clean addition.

## Testing

- Smoke test: `GET /feedback/<valid_snapshot_id>` returns 200 with form
- Smoke test: `GET /feedback/nonexistent` returns 404
- POST with valid JSON returns `{"success": true}` and row appears in `feedback` table
- POST without CSRF token returns 400
- POST with empty `response_json` still succeeds (all fields optional)
- Dimension cards render only for scored, non-`not_scored` dimensions
- Preview snapshots render without dimension cards
