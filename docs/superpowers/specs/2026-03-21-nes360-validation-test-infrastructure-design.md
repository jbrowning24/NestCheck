# NES-360: Validation Test Infrastructure — 5-User Feedback Collection + Results Aggregation

**Date:** 2026-03-21
**Status:** Draft
**Linear:** [NES-360](https://linear.app/nestcheck/issue/NES-360/validation-test-infrastructure-5-user-feedback-collection-results)
**Supersedes:** NES-361 (validation_feedback table), NES-362 (inline feedback prompt), NES-363 (detailed survey page)

---

## Overview

Build the measurement layer for the 5-user validation test. The evaluation pipeline is production-ready — what's missing is the mechanism to capture whether evaluations were useful and aggregate results against falsification criteria.

Three components:
1. **Phase 1 inline feedback** — 3-field widget on every report page
2. **Phase 2 survey page** — dimension-by-dimension accuracy grading
3. **Builder dashboard aggregation** — falsification tallies, per-user breakdown, accuracy heatmap

Zero additional API cost. Pure Flask + SQLite.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Feedback visibility | Always visible on every report (Approach A) | No auth gate needed for 5 users. Filter at aggregation, not collection |
| Post-submission suppression | Cookie-based (`nc_feedback_<snapshot_id>`) | Follows `nestcheck_recent` cookie pattern. Simpler than API check |
| WTP question placement | Phase 1 (inline) | Gut reaction while report is fresh predicts purchasing behavior better than post-reflection |
| WTP options | Yes / Maybe / No | Three options — "maybe" is real signal at $10-15 |
| Survey dimension display | Actual scores shown alongside rating inputs (Option B) | Testers can't grade accuracy without seeing what NestCheck said |
| Survey data source | `_prepare_snapshot_for_display()` | Canonical migration pipeline. No parallel deserialization |
| Health checks in survey | Yes | Test B testers who live at the address can grade proximity checks |
| Storage | Single `validation_feedback` table, JSON blob for ratings | 5 users doesn't justify normalization |
| Dashboard aggregation | All three levels (tallies + per-user + dimension accuracy) | Per-user IS the analysis at n=5. Dimension accuracy identifies which scorers to fix |
| Dashboard queries | Direct on page load, no caching | ~10-25 rows total. `json_extract()` is fine |
| Consent text | None | Friends testing the product, not research subjects |

## Data Model

### Table: `validation_feedback` (in `nestcheck.db`)

```sql
CREATE TABLE IF NOT EXISTS validation_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',      -- from snapshots.email, '' if NULL
    feedback_phase TEXT NOT NULL,        -- 'inline' or 'survey'
    something_new TEXT,                  -- 'yes' or 'no' (Phase 1 only)
    would_pay TEXT,                      -- 'yes', 'maybe', 'no' (Phase 1 only)
    comment TEXT,                        -- free text (both phases)
    dimension_ratings TEXT,              -- JSON blob (Phase 2 only)
    health_ratings TEXT,                 -- JSON blob (Phase 2 only)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(snapshot_id, email, feedback_phase)
);
CREATE INDEX IF NOT EXISTS idx_feedback_snapshot ON validation_feedback(snapshot_id);
```

UNIQUE constraint prevents duplicate submissions. INSERT OR REPLACE handles resubmission. Email uses `''` sentinel when `snapshots.email` is NULL — avoids SQLite's NULL-is-distinct-in-UNIQUE behavior that would allow unlimited anonymous submissions per snapshot.

### JSON blob structure (dimension_ratings / health_ratings)

```json
{
  "Coffee & Social Spots": {"rating": "accurate", "comment": ""},
  "Provisioning": {"rating": "partially_accurate", "comment": "Missing Trader Joe's"},
  "Fitness": {"rating": "inaccurate", "comment": "Planet Fitness is 5 min not 15"}
}
```

Rating values: `accurate`, `partially_accurate`, `inaccurate`. Keyed by dimension/check display name.

### Model functions (`models.py`)

- `save_validation_feedback(snapshot_id, email, phase, **fields)` — INSERT OR REPLACE. Coerces `None` email to `''`
- `get_feedback_for_snapshot(snapshot_id)` — returns list of feedback rows for both phases
- `get_all_validation_feedback()` — returns all rows for dashboard aggregation
- `has_feedback(snapshot_id, phase)` — lightweight existence check (returns bool). Used by survey page to decide between form vs read-only view, and by the inline widget's server-side rendering fallback when cookies are cleared

## Phase 1: Inline Feedback Widget

### Location
Bottom of `_result_sections.html`, below the share/export bar.

### Fields
1. "Did this report tell you something you didn't already know?" — **Yes / No** toggle buttons
2. "If you hadn't seen the full report, would you have paid $10–15 to unlock it?" — **Yes / Maybe / No** toggle buttons
3. "Anything else?" (optional) — textarea

### Behavior
- Toggle-style buttons (one selected at a time per question, highlighted with brand border on selection)
- Submit POSTs to `POST /api/feedback` via `csrfFetch()`
- On success: widget replaced with "Thanks for your feedback!" message
- Sets `nc_feedback_<snapshot_id>` cookie (30-day expiry, `SameSite=Lax`, `Path=/`)
- On page load: if cookie exists, render "Thanks" state instead of form
- Email pulled from `snapshots.email` for the given snapshot_id — not asked from user. If `snapshots.email` is NULL, feedback is stored with `email = ''` (anonymous). Dashboard shows "Anonymous" for blank emails
- Section header: "QUICK FEEDBACK" (L5 uppercase label style)

### Styling
- Contained in a new `.feedback-card` div (`background: var(--color-bg-card)`, `border: 1px solid var(--color-border-light)`, `border-radius: 12px`, `padding: 24px 28px`) with `max-width: 560px`
- Toggle buttons: pill-style, `border: 1px solid var(--color-border-light)`, selected state uses `border-color: var(--color-brand)` + `background: var(--color-bg-page)`
- Submit button: `background: var(--color-brand)`, `color: var(--color-text-inverse)`
- Uses existing design tokens throughout

## Phase 2: Survey Page

### Route
`GET /survey/<snapshot_id>` — new route in `app.py`

### Template
New `templates/survey.html` extending `_base.html`.

### Content
Loads snapshot via `_prepare_snapshot_for_display()`. Renders:

1. **Address header** — shows which address this survey is for
2. **Dimension accuracy section** — for each scored dimension:
   - Dimension name + score (e.g., "Coffee & Social Spots: 7/10")
   - Summary text from `dimension_summaries`
   - Radio group: Accurate / Partially Accurate / Inaccurate
   - Optional comment textarea (collapsed by default, "Add comment" link to expand)
3. **Health check accuracy section** — for each presented health check:
   - Check name + result (PASS/WARNING/ISSUE)
   - Context text
   - Same radio group + optional comment
4. **Free text** — "What did we get wrong?" textarea
5. **Submit button**

### Behavior
- Submits to `POST /api/feedback` via `csrfFetch()` — JSON POST with `feedback_phase: 'survey'`
- `dimension_ratings` and `health_ratings` JSON blobs built client-side from form state
- If `has_feedback(snapshot_id, 'survey')` returns true, show read-only summary of previous responses instead of form
- No auth gate — URL is the secret (sent manually to testers)
- Returns 404 if `snapshot_id` not found

## Builder Dashboard Aggregation

### Location
New "Validation Results" section in existing `/builder/dashboard` route and `builder_dashboard.html` template.

### Subsection 1: Falsification Check
Two lines where Y = actual inline submission count (not hardcoded 5):
- "Something new: X/Y" — green background if X ≥ 3, red if X < 3, gray "insufficient data" if Y < 5
- "Would pay: X/Y" — green if X ≥ 2, red if X < 2, gray if Y < 5 (counts "yes" only; "maybe" count shown separately)

Thresholds: `FALSIFICATION_SOMETHING_NEW = 3`, `FALSIFICATION_WOULD_PAY = 2` (constants, not magic numbers).

### Subsection 2: Per-User Breakdown
Table with columns: Email | Something New | Would Pay | Comment | Snapshot Link | Submitted At

Rows: one per inline feedback submission. Sorted by `created_at`. Snapshot link goes to `/s/<snapshot_id>`. Survey link goes to `/survey/<snapshot_id>` (shown as a separate column so you can copy/send it to the tester).

### Subsection 3: Dimension Accuracy Heatmap
Table with rows = dimension/check names, columns = Accurate / Partially Accurate / Inaccurate counts.

Cell background colors (using generic status colors, not health-scoped tokens):
- Green (`#dcfce7`) for Accurate majority
- Yellow (`#fef9c3`) for Partially Accurate majority
- Red (`#fee2e2`) for Inaccurate majority

Only renders when Phase 2 survey responses exist. Built from `json_extract()` on `dimension_ratings` and `health_ratings` blobs.

### Data flow
Route handler queries `get_all_validation_feedback()`, computes aggregates in Python (not Jinja), passes structured dicts to template. No caching, no pre-computation.

## API Endpoint

### `POST /api/feedback`

**Request body (JSON):**
```json
{
  "snapshot_id": "abc123",
  "feedback_phase": "inline",
  "something_new": "yes",
  "would_pay": "maybe",
  "comment": "The transit score surprised me",
  "dimension_ratings": null,
  "health_ratings": null
}
```

**Validation:**
- `snapshot_id` must exist in `snapshots` table
- `feedback_phase` must be `inline` or `survey`
- `something_new` must be `yes`, `no`, or null
- `would_pay` must be `yes`, `maybe`, `no`, or null
- `dimension_ratings` and `health_ratings` must be valid JSON or null

**Email resolution:** Pulled from `snapshots.email` for the given `snapshot_id`. Not sent by client.

**Response:** `{"status": "ok"}` on success. `{"error": "description"}` with 400 status on validation failure.

**CSRF:** Both inline widget and survey page use `csrfFetch()` for JSON POST. No traditional form submission.

## Files Changed

| File | Change |
|------|--------|
| `models.py` | Add `validation_feedback` table DDL to `init_db()`. Add 4 helper functions |
| `app.py` | Add `POST /api/feedback` endpoint. Add `GET /survey/<snapshot_id>` route. Add validation results data to builder dashboard route |
| `templates/_result_sections.html` | Add inline feedback widget at bottom |
| `templates/survey.html` | New template for Phase 2 survey page |
| `templates/builder_dashboard.html` | Add "Validation Results" section with 3 subsections |

## Files NOT Changed

- `property_evaluator.py` — no evaluation logic changes
- `scoring_config.py` — no scoring changes
- `worker.py` — no job queue changes
- `email_service.py` — survey links sent manually, not via automated email

## What's NOT Built (per issue scope)

- PDF export (Cmd+P works)
- Follow-up email cron (manual send for 5 users)
- Content-gated free tier before validation
- A/B testing infrastructure
- Consent text
- Automated survey link emails

## Pre-Test Checklist (from issue)

- [ ] Dimension list frozen (no renames between now and test)
- [ ] Test B addresses collected from each tester
- [ ] Builder mode keys distributed to testers
- [ ] Report email delivery verified via Resend
