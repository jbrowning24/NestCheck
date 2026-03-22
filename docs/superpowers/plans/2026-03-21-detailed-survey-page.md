# NES-363: Detailed Survey Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone survey page at `GET /feedback/<snapshot_id>` that collects willingness-to-pay data and per-dimension accuracy ratings from report recipients.

**Architecture:** Single-template monolith — one new Jinja template, one GET route, one POST endpoint, one SQLite table. No auth required. CSRF-protected via existing `csrfFetch` pattern. In-page thank-you swap on submission.

**Tech Stack:** Python/Flask, SQLite, Jinja2, vanilla JS, CSS custom properties from `tokens.css`

**Spec:** `docs/superpowers/specs/2026-03-21-detailed-survey-page-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `models.py` | `feedback` table DDL in `init_db()`, `save_feedback()` helper |
| `app.py` | `GET /feedback/<snapshot_id>` route, `POST /api/feedback` endpoint |
| `templates/feedback.html` | Survey form template (extends `_base.html`) |
| `static/css/feedback.css` | Survey-specific styles (segmented radios, dim cards, textareas) |
| `tests/test_feedback.py` | Route + endpoint tests |

---

## Task 1: Database — feedback table and save_feedback()

**Files:**
- Modify: `models.py` (add table DDL at ~line 182, add `save_feedback()` after `log_event()` at ~line 469)
- Create: `tests/test_feedback.py`

- [ ] **Step 1: Write the failing test for save_feedback()**

```python
# tests/test_feedback.py
"""Tests for the feedback survey system (NES-363)."""
import json
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_db(tmp_path):
    """Create a fresh test database and patch models to use it."""
    import models
    db_path = str(tmp_path / "test.db")
    original = models.DB_PATH
    models.DB_PATH = db_path
    models.init_db()
    return db_path, original


def test_save_feedback_inserts_row(tmp_path):
    import models
    db_path, original = _fresh_db(tmp_path)
    try:
        response = json.dumps({"overall_accuracy": 4})
        models.save_feedback(
            snapshot_id="abc12345",
            feedback_type="detailed_survey",
            response_json=response,
            address_norm="123 Main St, White Plains, NY",
            visitor_id="visitor123",
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM feedback WHERE snapshot_id = 'abc12345'").fetchone()
        conn.close()

        assert row is not None
        assert row["feedback_type"] == "detailed_survey"
        assert row["address_norm"] == "123 Main St, White Plains, NY"
        assert row["visitor_id"] == "visitor123"
        assert json.loads(row["response_json"])["overall_accuracy"] == 4
        assert row["created_at"] is not None
    finally:
        models.DB_PATH = original


def test_save_feedback_works_without_optional_fields(tmp_path):
    import models
    db_path, original = _fresh_db(tmp_path)
    try:
        models.save_feedback(
            snapshot_id="def67890",
            feedback_type="detailed_survey",
            response_json="{}",
        )

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM feedback WHERE snapshot_id = 'def67890'").fetchone()
        conn.close()

        assert row is not None
        assert row["address_norm"] is None
        assert row["visitor_id"] is None
    finally:
        models.DB_PATH = original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py -v`
Expected: FAIL — `save_feedback` not defined or `feedback` table doesn't exist

- [ ] **Step 3: Add feedback table DDL to init_db()**

In `models.py`, find the `state_votes` index (line ~182) inside the `conn.executescript(""" ... """)` block. Add the feedback table DDL just before the closing `""")`:

```sql
        CREATE TABLE IF NOT EXISTS feedback (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL,
            feedback_type TEXT NOT NULL,
            response_json TEXT NOT NULL,
            address_norm TEXT,
            visitor_id  TEXT,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_snapshot
            ON feedback(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_type
            ON feedback(feedback_type);
```

- [ ] **Step 4: Add save_feedback() function**

Add after `log_event()` (~line 469) in `models.py`:

```python
def save_feedback(snapshot_id, feedback_type, response_json,
                  address_norm=None, visitor_id=None):
    """Save a user feedback submission to the feedback table."""
    now = datetime.now(timezone.utc).isoformat()
    for attempt in range(3):
        conn = _get_db()
        try:
            conn.execute(
                """INSERT INTO feedback
                   (snapshot_id, feedback_type, response_json,
                    address_norm, visitor_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (snapshot_id, feedback_type, response_json,
                 address_norm, visitor_id, now),
            )
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if ("locked" in str(e).lower() or "busy" in str(e).lower()) and attempt < 2:
                time.sleep(0.1 * (attempt + 1))
            else:
                raise
        finally:
            conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add models.py tests/test_feedback.py
git commit -m "feat(NES-363): add feedback table and save_feedback() helper"
```

---

## Task 2: POST /api/feedback endpoint

**Files:**
- Modify: `app.py` (add endpoint after `/api/event` at ~line 3762)
- Modify: `tests/test_feedback.py` (add endpoint tests)

- [ ] **Step 1: Write the failing tests for the POST endpoint**

Append to `tests/test_feedback.py`:

```python
def test_post_feedback_success(tmp_path):
    """POST /api/feedback with valid data returns success."""
    import models
    db_path, original = _fresh_db(tmp_path)
    try:
        from app import app
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        # Seed a snapshot so the snapshot_id is valid
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO snapshots (snapshot_id, address_input, result_json, created_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            ("snap1234", "123 Main St", json.dumps({"tier2_scores": []})),
        )
        conn.commit()
        conn.close()

        with app.test_client() as client:
            resp = client.post("/api/feedback", json={
                "snapshot_id": "snap1234",
                "feedback_type": "detailed_survey",
                "response_json": json.dumps({"overall_accuracy": 4}),
            })
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True

        # Verify row was inserted
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM feedback WHERE snapshot_id = 'snap1234'").fetchone()
        conn.close()
        assert row is not None
    finally:
        models.DB_PATH = original


def test_post_feedback_missing_fields(tmp_path):
    """POST /api/feedback without required fields returns 400."""
    import models
    _, original = _fresh_db(tmp_path)
    try:
        from app import app
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        with app.test_client() as client:
            # Missing snapshot_id
            resp = client.post("/api/feedback", json={
                "feedback_type": "detailed_survey",
                "response_json": "{}",
            })
            assert resp.status_code == 400

            # Missing response_json
            resp = client.post("/api/feedback", json={
                "snapshot_id": "snap1234",
                "feedback_type": "detailed_survey",
            })
            assert resp.status_code == 400
    finally:
        models.DB_PATH = original


def test_post_feedback_invalid_json(tmp_path):
    """POST /api/feedback with invalid response_json returns 400."""
    import models
    _, original = _fresh_db(tmp_path)
    try:
        from app import app
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        with app.test_client() as client:
            resp = client.post("/api/feedback", json={
                "snapshot_id": "snap1234",
                "feedback_type": "detailed_survey",
                "response_json": "not valid json{{{",
            })
            assert resp.status_code == 400
    finally:
        models.DB_PATH = original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py::test_post_feedback_success tests/test_feedback.py::test_post_feedback_missing_fields tests/test_feedback.py::test_post_feedback_invalid_json -v`
Expected: FAIL — endpoint doesn't exist (404)

- [ ] **Step 3: Implement POST /api/feedback endpoint**

In `app.py`, add after the `/api/event` endpoint (~line 3762):

```python
@app.route("/api/feedback", methods=["POST"])
def submit_feedback():
    """Save user feedback from the detailed survey page."""
    data = request.get_json(silent=True) or {}

    snapshot_id = (data.get("snapshot_id") or "").strip()
    feedback_type = (data.get("feedback_type") or "").strip()
    response_json_str = data.get("response_json")

    # Validate required fields
    if not snapshot_id or not feedback_type:
        return jsonify({"success": False, "error": "snapshot_id and feedback_type are required"}), 400

    if not response_json_str:
        return jsonify({"success": False, "error": "response_json is required"}), 400

    # Validate response_json is parseable JSON
    try:
        json.loads(response_json_str)
    except (json.JSONDecodeError, TypeError):
        return jsonify({"success": False, "error": "response_json must be valid JSON"}), 400

    # Look up snapshot for address_norm
    snapshot = get_snapshot(snapshot_id)
    address_norm = snapshot.get("address_norm") if snapshot else None

    save_feedback(
        snapshot_id=snapshot_id,
        feedback_type=feedback_type,
        response_json=response_json_str,
        address_norm=address_norm,
        visitor_id=g.visitor_id,
    )

    log_event("feedback_submitted", snapshot_id=snapshot_id,
              visitor_id=g.visitor_id,
              metadata={"feedback_type": feedback_type})

    return jsonify({"success": True})
```

Add `save_feedback` to the imports from `models` at the top of `app.py` (find the existing `from models import ...` block).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py tests/test_feedback.py
git commit -m "feat(NES-363): add POST /api/feedback endpoint"
```

---

## Task 3: GET /feedback/<snapshot_id> route

**Files:**
- Modify: `app.py` (add route near the `view_snapshot` route at ~line 3445)
- Modify: `tests/test_feedback.py` (add route tests)

- [ ] **Step 1: Write failing tests for the GET route**

Append to `tests/test_feedback.py`:

```python
def test_get_feedback_valid_snapshot(tmp_path):
    """GET /feedback/<snapshot_id> returns 200 for a valid snapshot."""
    import models
    db_path, original = _fresh_db(tmp_path)
    try:
        from app import app
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        # Seed a snapshot with dimension_summaries
        result = {
            "tier1_checks": [],
            "tier2_scores": [],
            "final_score": 76,
            "coordinates": {"lat": 41.0, "lng": -73.7},
            "dimension_summaries": [
                {"name": "Coffee & Social Spots", "score": 8, "max_score": 10,
                 "data_confidence": "verified", "band": {"key": "strong", "label": "Strong"}},
                {"name": "Road Noise", "score": 7, "max_score": 10,
                 "data_confidence": "not_scored", "band": {"key": "not_scored", "label": "Not scored"}},
            ],
        }
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO snapshots (snapshot_id, address_input, address_norm, "
            "result_json, final_score, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            ("feedtest", "123 Main St", "123 Main St, White Plains, NY",
             json.dumps(result), 76),
        )
        conn.commit()
        conn.close()

        with app.test_client() as client:
            resp = client.get("/feedback/feedtest")
            assert resp.status_code == 200
            html = resp.data.decode()
            # Should contain the address
            assert "123 Main St" in html
            # Should contain the scored dimension
            assert "Coffee" in html
            # Should NOT contain the not_scored dimension
            assert "Road Noise" not in html
    finally:
        models.DB_PATH = original


def test_get_feedback_invalid_snapshot(tmp_path):
    """GET /feedback/<bad_id> returns 404."""
    import models
    _, original = _fresh_db(tmp_path)
    try:
        from app import app
        app.config["TESTING"] = True

        with app.test_client() as client:
            resp = client.get("/feedback/nonexistent")
            assert resp.status_code == 404
    finally:
        models.DB_PATH = original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py::test_get_feedback_valid_snapshot tests/test_feedback.py::test_get_feedback_invalid_snapshot -v`
Expected: FAIL — 404 (route doesn't exist)

- [ ] **Step 3: Implement the GET route**

In `app.py`, add near `view_snapshot()` (~line 3445):

```python
@app.route("/feedback/<snapshot_id>")
def feedback_survey(snapshot_id):
    """Render the detailed feedback survey for a snapshot."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        abort(404)

    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)

    # Only show dimensions with actual scores and non-not_scored confidence
    graded_dims = [d for d in result.get("dimension_summaries", [])
                   if d.get("score") is not None
                   and d.get("data_confidence") != "not_scored"]

    return render_template("feedback.html",
                           snapshot=snapshot,
                           result=result,
                           graded_dims=graded_dims)
```

- [ ] **Step 4: Create a minimal feedback.html template (placeholder)**

Create `templates/feedback.html` with just enough to make the test pass:

```jinja2
{% extends "_base.html" %}

{% block title %}Feedback — NestCheck{% endblock %}

{% block content %}
<div style="max-width: 640px; margin: 0 auto; padding: 32px 16px;">
  <h1>Feedback</h1>
  <p>{{ snapshot.address_input }}</p>
  {% for dim in graded_dims %}
  <p>{{ dim.name }}: {{ dim.score }}/{{ dim.max_score }}</p>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py templates/feedback.html tests/test_feedback.py
git commit -m "feat(NES-363): add GET /feedback/<snapshot_id> route with placeholder template"
```

---

## Task 4: CSS — feedback.css

**Files:**
- Create: `static/css/feedback.css`

- [ ] **Step 1: Create feedback.css**

Create `static/css/feedback.css` with all survey-specific styles. Reference `tokens.css` variables throughout — no hardcoded colors, spacing, or fonts.

```css
/* ================================================================
   feedback.css — Detailed survey page (NES-363)
   Extends tokens.css. No hardcoded values.
   ================================================================ */

/* Page layout */
.feedback-page {
  max-width: 640px;
  margin: 0 auto;
  padding: var(--space-xl) var(--space-base);
}

/* Consent bar */
.feedback-consent {
  padding: var(--space-md) var(--space-base);
  background: var(--color-bg-page);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-small);
  color: var(--color-text-secondary);
  line-height: var(--line-height-relaxed);
  margin-bottom: var(--space-xl);
}

/* Address context bar */
.feedback-context {
  display: flex;
  align-items: center;
  gap: var(--space-base);
  padding: var(--space-lg) var(--space-xl);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  margin-bottom: var(--space-xl);
}

.feedback-context-address {
  font-size: var(--type-l3-size);
  font-weight: var(--type-l3-weight);
  color: var(--type-l3-color);
}

.feedback-context-meta {
  font-size: var(--font-size-small);
  color: var(--color-text-secondary);
  margin-top: var(--space-xs);
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

/* Section headers — L2 typographic level */
.feedback-section-label {
  font-size: var(--type-l2-size);
  font-weight: var(--type-l2-weight);
  line-height: var(--type-l2-leading);
  letter-spacing: var(--type-l2-tracking);
  color: var(--type-l2-color);
  text-transform: uppercase;
  margin-bottom: var(--space-base);
  margin-top: var(--space-2xl);
}

.feedback-section-label:first-of-type {
  margin-top: 0;
}

/* Question text */
.feedback-question {
  font-size: var(--font-size-body);
  color: var(--color-text-primary);
  line-height: var(--line-height-relaxed);
  margin-bottom: var(--space-md);
}

/* Question group spacing */
.feedback-group {
  margin-bottom: var(--space-lg);
}

/* Segmented radio controls */
.radio-group {
  display: flex;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.radio-group input[type="radio"] {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.radio-group label {
  flex: 1;
  text-align: center;
  padding: var(--space-sm) var(--space-md);
  font-size: var(--font-size-small);
  color: var(--color-text-secondary);
  border-right: 1px solid var(--color-border);
  cursor: pointer;
  transition: background var(--transition-fast), color var(--transition-fast);
  user-select: none;
}

.radio-group label:last-of-type {
  border-right: none;
}

.radio-group input[type="radio"]:checked + label {
  background: var(--color-accent-light);
  color: var(--color-accent);
  font-weight: var(--font-weight-medium);
}

.radio-group input[type="radio"]:focus-visible + label {
  outline: 2px solid var(--color-accent);
  outline-offset: -2px;
}

/* Dimension accuracy cards */
.feedback-dim-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-base) var(--space-lg);
  margin-bottom: var(--space-base);
  border-left-width: 3px;
  border-left-style: solid;
}

.feedback-dim-card--strong {
  border-left-color: var(--color-band-strong);
}

.feedback-dim-card--moderate {
  border-left-color: var(--color-band-moderate);
}

.feedback-dim-card--limited {
  border-left-color: var(--color-band-limited);
}

.feedback-dim-header {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  margin-bottom: var(--space-md);
}

.feedback-dim-name {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}

.feedback-dim-pill {
  display: inline-block;
  padding: 2px var(--space-sm);
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-semibold);
}

.feedback-dim-pill--strong {
  color: var(--color-band-strong);
  background: #F0FDF4;
}

.feedback-dim-pill--moderate {
  color: var(--color-band-moderate);
  background: #FFFBEB;
}

.feedback-dim-pill--limited {
  color: var(--color-band-limited);
  background: #F3F4F6;
}

.feedback-dim-band {
  font-size: var(--type-l5-size);
  text-transform: uppercase;
  letter-spacing: var(--type-l5-tracking);
  font-weight: var(--type-l5-weight);
}

/* Textareas */
.feedback-textarea {
  width: 100%;
  min-height: 80px;
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-family: var(--font-body);
  font-size: var(--font-size-input);
  color: var(--color-text-primary);
  resize: vertical;
  box-sizing: border-box;
}

.feedback-textarea:focus {
  outline: none;
  border-color: var(--color-accent);
  box-shadow: 0 0 0 2px var(--color-accent-light);
}

.feedback-textarea--short {
  min-height: 60px;
}

/* Submit button */
.feedback-submit {
  display: inline-block;
  padding: var(--space-md) var(--space-2xl);
  background: var(--color-accent);
  color: var(--color-text-inverse);
  border: none;
  border-radius: var(--radius-sm);
  font-size: var(--font-size-button);
  font-weight: var(--font-weight-semibold);
  font-family: var(--font-body);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.feedback-submit:hover {
  background: var(--color-accent-hover);
}

.feedback-submit:disabled {
  background: var(--color-disabled-bg);
  cursor: not-allowed;
}

/* Error message */
.feedback-error {
  color: var(--color-fail);
  font-size: var(--font-size-small);
  margin-bottom: var(--space-base);
  display: none;
}

/* Thank-you state */
.feedback-thank-you {
  text-align: center;
  padding: var(--space-3xl) var(--space-base);
}

.feedback-thank-you h2 {
  font-size: var(--font-size-h2);
  color: var(--color-text-primary);
  margin-bottom: var(--space-base);
}

.feedback-thank-you p {
  font-size: var(--font-size-body);
  color: var(--color-text-secondary);
  line-height: var(--line-height-relaxed);
}

/* Mobile: 5-point scales show numbers only */
@media (max-width: 640px) {
  .radio-group label .radio-label-text {
    display: none;
  }

  .feedback-context {
    padding: var(--space-base);
    gap: var(--space-md);
  }

  .feedback-dim-header {
    flex-wrap: wrap;
  }
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add static/css/feedback.css
git commit -m "feat(NES-363): add feedback.css with segmented radios and dim cards"
```

---

## Task 5: Full template — feedback.html

**Files:**
- Modify: `templates/feedback.html` (replace placeholder with full template)

- [ ] **Step 1: Replace placeholder feedback.html with the full template**

```jinja2
{% extends "_base.html" %}
{% from "_macros.html" import score_ring %}

{% block title %}Feedback — NestCheck{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/report.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/feedback.css') }}">
{% endblock %}

{% block content %}
<div class="feedback-page">

  {# Consent #}
  <div class="feedback-consent">
    By submitting this survey, you consent to NestCheck using your responses
    to improve the accuracy of future evaluations. Your feedback is anonymous
    and will not be shared.
  </div>

  {# Address context bar #}
  {% set score = result.get('final_score', 0) %}
  {% set band = result.get('score_band', {}) %}
  {% set band_key = band.get('key', 'moderate') if band else 'moderate' %}
  <div class="feedback-context">
    {{ score_ring(score, band_class='band-' ~ band_key, size_class='score-ring-container score-ring--small') }}
    <div>
      <div class="feedback-context-address">{{ snapshot.address_norm or snapshot.address_input }}</div>
      <div class="feedback-context-meta">
        {% if band %}
        <span class="feedback-dim-pill feedback-dim-pill--{{ band_key }}">{{ band.get('label', '') }}</span>
        {% endif %}
        {% if snapshot.evaluated_at %}
        <span>Evaluated {{ snapshot.evaluated_at[:10] }}</span>
        {% endif %}
      </div>
    </div>
  </div>

  {# Survey form #}
  <form id="feedback-form">

    {# ── Section 1: Willingness to Pay ── #}
    <h2 class="feedback-section-label">Willingness to Pay</h2>

    <div class="feedback-group">
      <p class="feedback-question">
        If you hadn't seen the full report, would you have paid $10–15 to get
        this evaluation before making your housing decision?
      </p>
      <div class="radio-group">
        <input type="radio" name="wtp_would_pay" value="definitely_yes" id="wtp1a">
        <label for="wtp1a"><span class="radio-label-num"></span>Definitely yes</label>
        <input type="radio" name="wtp_would_pay" value="probably_yes" id="wtp1b">
        <label for="wtp1b"><span class="radio-label-num"></span>Probably yes</label>
        <input type="radio" name="wtp_would_pay" value="probably_no" id="wtp1c">
        <label for="wtp1c"><span class="radio-label-num"></span>Probably no</label>
        <input type="radio" name="wtp_would_pay" value="definitely_no" id="wtp1d">
        <label for="wtp1d"><span class="radio-label-num"></span>Definitely no</label>
      </div>
    </div>

    <div class="feedback-group">
      <p class="feedback-question">
        What's the most you'd pay for a report like this?
      </p>
      <div class="radio-group">
        <input type="radio" name="wtp_max_price" value="free" id="wtp2a">
        <label for="wtp2a">Free only</label>
        <input type="radio" name="wtp_max_price" value="5" id="wtp2b">
        <label for="wtp2b">$5</label>
        <input type="radio" name="wtp_max_price" value="10" id="wtp2c">
        <label for="wtp2c">$10</label>
        <input type="radio" name="wtp_max_price" value="15" id="wtp2d">
        <label for="wtp2d">$15</label>
        <input type="radio" name="wtp_max_price" value="25_plus" id="wtp2e">
        <label for="wtp2e">$25+</label>
      </div>
    </div>

    {# ── Section 2: Dimension Accuracy ── #}
    {% if graded_dims %}
    <h2 class="feedback-section-label">Dimension Accuracy</h2>

    {% for dim in graded_dims %}
    {% set dim_band = dim.get('band', {}).get('key', 'limited') %}
    <div class="feedback-dim-card feedback-dim-card--{{ dim_band }}">
      <div class="feedback-dim-header">
        <span class="feedback-dim-name">{{ dim.name }}</span>
        <span class="feedback-dim-pill feedback-dim-pill--{{ dim_band }}">{{ dim.score }}/{{ dim.max_score }}</span>
        <span class="feedback-dim-band" style="color: var(--color-band-{{ dim_band }})">{{ dim.band.label }}</span>
      </div>
      <p class="feedback-question">How accurate is this for your experience at this address?</p>
      <div class="radio-group">
        {% for val, num, text in [(1, '1', 'Way off'), (2, '2', 'Somewhat off'), (3, '3', 'About right'), (4, '4', 'Quite accurate'), (5, '5', 'Spot on')] %}
        <input type="radio" name="dim_{{ loop.index }}_accuracy" value="{{ val }}" id="dim{{ loop.index }}_{{ val }}">
        <label for="dim{{ loop.index }}_{{ val }}"><strong>{{ num }}</strong> <span class="radio-label-text">{{ text }}</span></label>
        {% endfor %}
      </div>
      <textarea class="feedback-textarea feedback-textarea--short"
                name="dim_{{ loop.index }}_comment"
                data-dim-name="{{ dim.name }}"
                placeholder="What would you change about this score? (optional)"></textarea>
    </div>
    {% endfor %}
    {% endif %}

    {# ── Section 3: Health Check Accuracy ── #}
    <h2 class="feedback-section-label">Health Check Accuracy</h2>

    <div class="feedback-group">
      <p class="feedback-question">
        Were there any health or environmental concerns at this address that
        the report missed?
      </p>
      <textarea class="feedback-textarea" name="health_missed"
                placeholder="e.g., nearby construction, industrial noise, odors..."></textarea>
    </div>

    <div class="feedback-group">
      <p class="feedback-question">
        Were any of the health warnings inaccurate or overstated?
      </p>
      <textarea class="feedback-textarea" name="health_overstated"
                placeholder="e.g., the gas station flagged was actually closed, the road is much quieter than suggested..."></textarea>
    </div>

    {# ── Section 4: Overall ── #}
    <h2 class="feedback-section-label">Overall</h2>

    <div class="feedback-group">
      <p class="feedback-question">Overall, how accurate was this report?</p>
      <div class="radio-group">
        {% for val, num, text in [(1, '1', 'Way off'), (2, '2', 'Somewhat off'), (3, '3', 'About right'), (4, '4', 'Quite accurate'), (5, '5', 'Spot on')] %}
        <input type="radio" name="overall_accuracy" value="{{ val }}" id="overall_{{ val }}">
        <label for="overall_{{ val }}"><strong>{{ num }}</strong> <span class="radio-label-text">{{ text }}</span></label>
        {% endfor %}
      </div>
    </div>

    <div class="feedback-group">
      <p class="feedback-question">What was the single most useful thing in the report?</p>
      <textarea class="feedback-textarea" name="most_useful"
                placeholder="e.g., the health checks, the walkability analysis, learning about nearby parks..."></textarea>
    </div>

    <div class="feedback-group">
      <p class="feedback-question">What was missing that you expected to see?</p>
      <textarea class="feedback-textarea" name="missing_expected"
                placeholder="e.g., school quality data, parking availability, commute times to specific locations..."></textarea>
    </div>

    {# Submit #}
    <div id="feedback-error" class="feedback-error"></div>
    <div style="text-align: center; margin-top: var(--space-xl);">
      <button type="submit" class="feedback-submit" id="feedback-submit-btn">
        Submit Feedback
      </button>
    </div>

  </form>

  {# Thank-you (hidden until submission) #}
  <div id="feedback-thank-you" class="feedback-thank-you" style="display: none;">
    <h2>Thank you for your feedback</h2>
    <p>Your responses help us improve the accuracy of future NestCheck evaluations.</p>
    <p style="margin-top: var(--space-lg);">
      <a href="/s/{{ snapshot.snapshot_id }}" style="color: var(--color-accent);">
        Back to your report
      </a>
    </p>
  </div>

</div>
{% endblock %}

{% block scripts %}
<script>
(function() {
  /* ---- CSRF helpers (same pattern as index.html) ---- */
  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]').getAttribute('content');
  }

  function refreshCsrfToken() {
    return fetch('/csrf-token').then(function(r) { return r.json(); }).then(function(d) {
      document.querySelector('meta[name="csrf-token"]').setAttribute('content', d.csrf_token);
      return d.csrf_token;
    });
  }

  function csrfFetch(url, options) {
    function doFetch(token) {
      var opts = Object.assign({}, options);
      opts.headers = Object.assign({'Accept': 'application/json'}, opts.headers, {'X-CSRFToken': token});
      return fetch(url, opts);
    }
    function handleResp(resp, isRetry) {
      if (!resp.ok) {
        var ct = resp.headers.get('content-type') || '';
        if (ct.indexOf('application/json') !== -1) {
          return resp.json().then(function(data) {
            if (!isRetry && resp.status === 400 && data.error_code === 'csrf_expired') {
              return refreshCsrfToken().then(function(newToken) {
                return doFetch(newToken).then(function(r) { return handleResp(r, true); });
              });
            }
            return data;
          });
        }
        return resp.text().then(function() {
          throw new Error('Server error (' + resp.status + '). Please try again.');
        });
      }
      return resp.json();
    }
    return doFetch(csrfToken()).then(function(resp) { return handleResp(resp, false); });
  }

  /* ---- Form serialization ---- */
  function serializeForm() {
    var form = document.getElementById('feedback-form');
    var data = {};

    // WTP radios
    var wtpPay = form.querySelector('input[name="wtp_would_pay"]:checked');
    data.wtp_would_pay = wtpPay ? wtpPay.value : null;

    var wtpPrice = form.querySelector('input[name="wtp_max_price"]:checked');
    data.wtp_max_price = wtpPrice ? wtpPrice.value : null;

    // Dimension accuracy
    data.dimensions = {};
    var dimCards = form.querySelectorAll('.feedback-dim-card');
    dimCards.forEach(function(card, i) {
      var idx = i + 1;
      var radio = card.querySelector('input[name="dim_' + idx + '_accuracy"]:checked');
      var textarea = card.querySelector('textarea[data-dim-name]');
      var dimName = textarea ? textarea.getAttribute('data-dim-name') : '';
      if (dimName) {
        data.dimensions[dimName] = {
          accuracy: radio ? parseInt(radio.value) : null,
          comment: textarea && textarea.value.trim() ? textarea.value.trim() : null
        };
      }
    });

    // Health textareas
    var healthMissed = form.querySelector('textarea[name="health_missed"]');
    data.health_missed = healthMissed && healthMissed.value.trim() ? healthMissed.value.trim() : null;

    var healthOverstated = form.querySelector('textarea[name="health_overstated"]');
    data.health_overstated = healthOverstated && healthOverstated.value.trim() ? healthOverstated.value.trim() : null;

    // Overall
    var overallRadio = form.querySelector('input[name="overall_accuracy"]:checked');
    data.overall_accuracy = overallRadio ? parseInt(overallRadio.value) : null;

    var mostUseful = form.querySelector('textarea[name="most_useful"]');
    data.most_useful = mostUseful && mostUseful.value.trim() ? mostUseful.value.trim() : null;

    var missingExpected = form.querySelector('textarea[name="missing_expected"]');
    data.missing_expected = missingExpected && missingExpected.value.trim() ? missingExpected.value.trim() : null;

    return data;
  }

  /* ---- Submit handler ---- */
  var form = document.getElementById('feedback-form');
  var submitBtn = document.getElementById('feedback-submit-btn');
  var errorDiv = document.getElementById('feedback-error');

  form.addEventListener('submit', function(e) {
    e.preventDefault();
    errorDiv.style.display = 'none';
    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting\u2026';

    var payload = {
      snapshot_id: '{{ snapshot.snapshot_id }}',
      feedback_type: 'detailed_survey',
      response_json: JSON.stringify(serializeForm())
    };

    csrfFetch('/api/feedback', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    }).then(function(data) {
      if (data.success) {
        document.getElementById('feedback-form').style.display = 'none';
        document.getElementById('feedback-thank-you').style.display = 'block';
        window.scrollTo({top: 0, behavior: 'smooth'});
      } else {
        errorDiv.textContent = data.error || 'Something went wrong. Please try again.';
        errorDiv.style.display = 'block';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit Feedback';
      }
    }).catch(function(err) {
      errorDiv.textContent = err.message || 'Something went wrong. Please try again.';
      errorDiv.style.display = 'block';
      submitBtn.disabled = false;
      submitBtn.textContent = 'Submit Feedback';
    });
  });
})();
</script>
{% endblock %}
```

- [ ] **Step 2: Update the GET route test to verify full template content**

The existing tests from Task 3 should still pass since the full template still renders the address and dimension names. Run them to verify:

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py -v`
Expected: 7 passed

- [ ] **Step 3: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add templates/feedback.html static/css/feedback.css
git commit -m "feat(NES-363): full feedback template with segmented radios and JS submission"
```

---

## Task 6: Smoke test and visual QA

**Files:** None (verification only)

- [ ] **Step 1: Run all tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py -v`
Expected: 7 passed

- [ ] **Step 2: Run the existing test suite to check for regressions**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/ -v --timeout=30`
Expected: All existing tests still pass

- [ ] **Step 3: Manual smoke test**

Start the dev server and test manually:

```bash
cd /Users/jeremybrowning/NestCheck && python app.py
```

1. Navigate to `http://localhost:5000/feedback/<valid_snapshot_id>` (use a real snapshot_id from the database)
2. Verify: consent text, address context bar with score ring, all four sections render
3. Verify: dimension cards show only scored/non-not_scored dimensions with correct band colors
4. Verify: segmented radio controls highlight on click
5. Verify: submit button posts and shows thank-you message
6. Verify: `GET /feedback/nonexistent` returns 404
7. Check mobile viewport (375px) — radio labels should show numbers only

- [ ] **Step 4: Verify database entry**

After submitting via the form, check the database:

```bash
cd /Users/jeremybrowning/NestCheck && sqlite3 nestcheck.db "SELECT * FROM feedback ORDER BY id DESC LIMIT 1;"
```

Expected: Row with correct `snapshot_id`, `feedback_type`, populated `response_json`, `created_at` timestamp

- [ ] **Step 5: Final commit**

If any fixes were needed during QA, commit them:

```bash
cd /Users/jeremybrowning/NestCheck
git add -A
git commit -m "fix(NES-363): visual QA fixes for feedback survey"
```
