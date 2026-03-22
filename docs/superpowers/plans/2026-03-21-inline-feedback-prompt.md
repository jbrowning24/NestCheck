# NES-362: Inline Feedback Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an inline feedback form at the bottom of the report page that captures "did this surprise you?" reactions.

**Architecture:** Two new API endpoints in `app.py`, a `feedback` table in `models.py`, a visitor identity cookie in `_base.html`, extraction of `csrfFetch` to shared scope, and a feedback form section in `_result_sections.html`. All vanilla JS, no frameworks.

**Tech Stack:** Python/Flask, SQLite, Jinja2, vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-21-inline-feedback-prompt-design.md`

---

### Task 1: Database schema and model functions

**Files:**
- Modify: `models.py:47-183` (inside `init_db()` executescript block)
- Modify: `models.py` (add functions after existing model functions)
- Create: `tests/test_feedback.py`

- [ ] **Step 1: Write failing tests for `save_feedback` and `has_feedback`**

Create `tests/test_feedback.py`:

```python
"""Feedback model unit tests (NES-362)."""

import pytest
from models import save_feedback, has_feedback


class TestSaveFeedback:
    def test_saves_with_visitor_id(self):
        result = save_feedback(
            snapshot_id="snap_abc",
            user_id=None,
            visitor_id="vid_123",
            feedback_type="inline_reaction",
            told_something_new=1,
            free_text="Great report!",
        )
        assert result is True

    def test_saves_with_user_id(self):
        result = save_feedback(
            snapshot_id="snap_def",
            user_id=42,
            visitor_id=None,
            feedback_type="inline_reaction",
            told_something_new=0,
            free_text=None,
        )
        assert result is True

    def test_duplicate_visitor_returns_false(self):
        save_feedback("snap_dup", None, "vid_dup", "inline_reaction", 1, None)
        result = save_feedback("snap_dup", None, "vid_dup", "inline_reaction", 0, "changed mind")
        assert result is False

    def test_duplicate_user_returns_false(self):
        save_feedback("snap_dup2", 99, None, "inline_reaction", 1, None)
        result = save_feedback("snap_dup2", 99, None, "inline_reaction", 0, None)
        assert result is False

    def test_different_snapshots_same_visitor_both_save(self):
        assert save_feedback("snap_a", None, "vid_same", "inline_reaction", 1, None) is True
        assert save_feedback("snap_b", None, "vid_same", "inline_reaction", 0, None) is True


class TestHasFeedback:
    def test_no_feedback_returns_false(self):
        assert has_feedback("snap_empty", None, "vid_nobody") is False

    def test_finds_by_visitor_id(self):
        save_feedback("snap_find", None, "vid_find", "inline_reaction", 1, None)
        assert has_feedback("snap_find", None, "vid_find") is True

    def test_finds_by_user_id(self):
        save_feedback("snap_find2", 77, None, "inline_reaction", 0, None)
        assert has_feedback("snap_find2", 77, None) is True

    def test_user_id_match_ignores_visitor_id(self):
        save_feedback("snap_both", 88, "vid_orig", "inline_reaction", 1, None)
        # Same user_id, different visitor_id — should still find it
        assert has_feedback("snap_both", 88, "vid_different") is True

    def test_no_identity_returns_false(self):
        assert has_feedback("snap_noid", None, None) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py -v`
Expected: ImportError — `save_feedback` and `has_feedback` don't exist yet.

- [ ] **Step 3: Add feedback table to `init_db()`**

In `models.py`, inside the `init_db()` function's `conn.executescript()` block, add the following before the closing `""")` (after the `state_votes` index around line 182):

```sql
        -- Feedback (NES-362)
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT NOT NULL,
            user_id INTEGER,
            visitor_id TEXT,
            feedback_type TEXT NOT NULL DEFAULT 'inline_reaction',
            told_something_new INTEGER NOT NULL,
            free_text TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_snapshot_user
            ON feedback(snapshot_id, user_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_snapshot_visitor
            ON feedback(snapshot_id, visitor_id);
```

- [ ] **Step 4: Implement `has_feedback()` and `save_feedback()`**

Add these functions to `models.py` after the existing model functions (after `save_evaluation_coverage` around line 1265):

```python
# ---------------------------------------------------------------------------
# Feedback (NES-362)
# ---------------------------------------------------------------------------

def has_feedback(snapshot_id: str, user_id=None, visitor_id=None) -> bool:
    """Check if feedback already exists for this snapshot + identity.

    Checks user_id first (if authenticated), then visitor_id.
    Returns False if neither identity is provided.
    """
    if not user_id and not visitor_id:
        return False
    conn = _get_db()
    try:
        if user_id:
            row = conn.execute(
                "SELECT 1 FROM feedback WHERE snapshot_id = ? AND user_id = ?",
                (snapshot_id, user_id),
            ).fetchone()
            if row:
                return True
        if visitor_id:
            row = conn.execute(
                "SELECT 1 FROM feedback WHERE snapshot_id = ? AND visitor_id = ?",
                (snapshot_id, visitor_id),
            ).fetchone()
            if row:
                return True
        return False
    finally:
        conn.close()


def save_feedback(snapshot_id: str, user_id, visitor_id, feedback_type: str,
                  told_something_new: int, free_text=None) -> bool:
    """Save feedback for a snapshot. Returns True on success, False if duplicate.

    Uses check-then-insert (not atomic) — a race produces a duplicate row,
    which is low stakes for feedback data.
    """
    if has_feedback(snapshot_id, user_id, visitor_id):
        return False

    now = datetime.now(timezone.utc).isoformat()
    last_err = None
    for attempt in range(3):
        try:
            conn = _get_db()
            try:
                conn.execute(
                    """INSERT INTO feedback
                       (snapshot_id, user_id, visitor_id, feedback_type,
                        told_something_new, free_text, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (snapshot_id, user_id, visitor_id, feedback_type,
                     told_something_new, free_text, now),
                )
                conn.commit()
                return True
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" in str(e) or "busy" in str(e):
                logger.warning("save_feedback retry %d/3: %s", attempt + 1, e)
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    raise last_err
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add models.py tests/test_feedback.py
git commit -m "feat(NES-362): add feedback table and model functions

Add feedback table to init_db(), plus save_feedback() and has_feedback()
helper functions with dedup via check-then-insert pattern."
```

---

### Task 2: Extract csrfFetch to _base.html

**Files:**
- Modify: `templates/_base.html:77-105` (add script block before `</body>`)
- Modify: `templates/index.html:437-474` (remove csrfFetch functions)

- [ ] **Step 1: Add csrfFetch script block to `_base.html`**

In `templates/_base.html`, add a `<script>` block after the `{% block scripts %}{% endblock %}` (line 77) and before the cookie banner (line 79). This ensures csrfFetch is available to all pages:

```html
<!-- Shared CSRF-aware fetch utility (NES-362: extracted from index.html) -->
<script>
  function csrfToken() {
    var el = document.querySelector('meta[name="csrf-token"]');
    return el ? el.getAttribute('content') : '';
  }
  function refreshCsrfToken() {
    return fetch('/csrf-token', { method: 'GET', headers: { 'Accept': 'application/json' } })
      .then(function(resp) { return resp.json(); })
      .then(function(data) {
        if (data.csrf_token) {
          document.querySelector('meta[name="csrf-token"]').setAttribute('content', data.csrf_token);
        }
        return data.csrf_token || '';
      })
      .catch(function() { return csrfToken(); });
  }
  function csrfFetch(url, options) {
    function doFetch(token) {
      var opts = Object.assign({}, options);
      opts.headers = Object.assign({ 'Accept': 'application/json' }, opts.headers, { 'X-CSRFToken': token });
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
</script>
```

- [ ] **Step 2: Add nestcheck_vid cookie script to `_base.html`**

In `templates/_base.html`, inside the `<head>` section (after the CSRF meta tag), add:

```html
<!-- Visitor identity cookie for anonymous feedback (NES-362) -->
<script>
if (!document.cookie.match(/nestcheck_vid=/)) {
    document.cookie = 'nestcheck_vid=' + crypto.randomUUID() +
        '; path=/; max-age=' + (30*86400) + '; SameSite=Lax';
}
</script>
```

- [ ] **Step 3: Remove csrfToken, refreshCsrfToken, and csrfFetch from `index.html`**

In `templates/index.html`, remove the three functions at lines 437–474 (`csrfToken`, `refreshCsrfToken`, `csrfFetch`). These are now inherited from `_base.html`. Leave any surrounding code intact — verify that nothing else in the `<script>` block depends on these functions being defined locally (they are called by other functions in the same block, which will now find them in the global scope from `_base.html`).

- [ ] **Step 4: Verify index.html still works**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest smoke_test.py -v -k "test_landing_page_loads"`
Expected: PASS — landing page renders without JS errors.

Also verify by inspecting that the `csrfFetch` calls in `index.html` (e.g., `submitEvaluation`, `checkCachedSnapshots`) don't break when the function is defined in a prior script block.

- [ ] **Step 5: Commit**

```bash
git add templates/_base.html templates/index.html
git commit -m "refactor(NES-362): extract csrfFetch to _base.html

Move csrfToken, refreshCsrfToken, and csrfFetch from index.html to
_base.html so all pages can use CSRF-protected fetch. Also add
nestcheck_vid cookie for anonymous visitor identification."
```

---

### Task 3: API endpoints

**Files:**
- Modify: `app.py:843` (add `FEEDBACK_PROMPT_MAX_AGE_DAYS` constant)
- Modify: `app.py` (add two new routes near existing `/api/` routes around line 3731)
- Create: `tests/test_feedback.py` (append endpoint tests)

- [ ] **Step 1: Write failing tests for POST /api/feedback**

Append to `tests/test_feedback.py`:

```python
from app import app


class TestFeedbackEndpoints:
    """API endpoint tests for feedback submission and status."""

    @pytest.fixture(autouse=True)
    def client(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

    def test_post_feedback_success(self):
        # First create a snapshot to reference
        from models import save_snapshot
        sid = save_snapshot("123 Main St", "123 Main St, Scarsdale, NY",
                           {"final_score": 75, "passed_tier1": True, "verdict": "Strong"})

        resp = self.client.post("/api/feedback",
            json={
                "snapshot_id": sid,
                "feedback_type": "inline_reaction",
                "told_something_new": 1,
                "free_text": "Very helpful!",
            },
            headers={"Cookie": "nestcheck_vid=test-visitor-123"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_post_feedback_missing_told_something_new(self):
        from models import save_snapshot
        sid = save_snapshot("456 Oak Ave", "456 Oak Ave, Scarsdale, NY",
                           {"final_score": 60, "passed_tier1": True, "verdict": "Moderate"})

        resp = self.client.post("/api/feedback",
            json={"snapshot_id": sid, "feedback_type": "inline_reaction"},
            headers={"Cookie": "nestcheck_vid=test-visitor-456"})
        assert resp.status_code == 400

    def test_post_feedback_invalid_told_value(self):
        from models import save_snapshot
        sid = save_snapshot("789 Elm", "789 Elm, Scarsdale, NY",
                           {"final_score": 50, "passed_tier1": True, "verdict": "Moderate"})

        resp = self.client.post("/api/feedback",
            json={"snapshot_id": sid, "feedback_type": "inline_reaction",
                  "told_something_new": 5},
            headers={"Cookie": "nestcheck_vid=test-visitor-789"})
        assert resp.status_code == 400

    def test_post_feedback_nonexistent_snapshot(self):
        resp = self.client.post("/api/feedback",
            json={"snapshot_id": "nonexistent", "feedback_type": "inline_reaction",
                  "told_something_new": 1},
            headers={"Cookie": "nestcheck_vid=test-visitor-nope"})
        assert resp.status_code == 404

    def test_post_feedback_no_identity(self):
        from models import save_snapshot
        sid = save_snapshot("111 Pine", "111 Pine, Scarsdale, NY",
                           {"final_score": 80, "passed_tier1": True, "verdict": "Strong"})

        resp = self.client.post("/api/feedback",
            json={"snapshot_id": sid, "feedback_type": "inline_reaction",
                  "told_something_new": 1})
        assert resp.status_code == 400

    def test_post_feedback_duplicate_returns_200(self):
        from models import save_snapshot
        sid = save_snapshot("222 Maple", "222 Maple, Scarsdale, NY",
                           {"final_score": 70, "passed_tier1": True, "verdict": "Moderate"})

        self.client.post("/api/feedback",
            json={"snapshot_id": sid, "feedback_type": "inline_reaction",
                  "told_something_new": 1},
            headers={"Cookie": "nestcheck_vid=test-dup-visitor"})
        resp = self.client.post("/api/feedback",
            json={"snapshot_id": sid, "feedback_type": "inline_reaction",
                  "told_something_new": 0},
            headers={"Cookie": "nestcheck_vid=test-dup-visitor"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "duplicate"

    def test_post_feedback_free_text_too_long(self):
        from models import save_snapshot
        sid = save_snapshot("333 Long", "333 Long, Scarsdale, NY",
                           {"final_score": 65, "passed_tier1": True, "verdict": "Moderate"})

        resp = self.client.post("/api/feedback",
            json={"snapshot_id": sid, "feedback_type": "inline_reaction",
                  "told_something_new": 1, "free_text": "x" * 1001},
            headers={"Cookie": "nestcheck_vid=test-long-text"})
        assert resp.status_code == 400


class TestFeedbackStatus:
    @pytest.fixture(autouse=True)
    def client(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

    def test_status_not_submitted(self):
        resp = self.client.get("/api/feedback/snap_never/status",
            headers={"Cookie": "nestcheck_vid=test-status-visitor"})
        assert resp.status_code == 200
        assert resp.get_json()["submitted"] is False

    def test_status_submitted(self):
        from models import save_feedback
        save_feedback("snap_status", None, "test-status-yes", "inline_reaction", 1, None)

        resp = self.client.get("/api/feedback/snap_status/status",
            headers={"Cookie": "nestcheck_vid=test-status-yes"})
        assert resp.status_code == 200
        assert resp.get_json()["submitted"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py::TestFeedbackEndpoints -v`
Expected: 404 errors — routes don't exist yet.

- [ ] **Step 3: Add `FEEDBACK_PROMPT_MAX_AGE_DAYS` constant**

In `app.py`, after the `_EJSCREEN_CROSS_REFS` block (around line 843), add:

```python
# -- Feedback prompt (NES-362) -----------------------------------------------
FEEDBACK_PROMPT_MAX_AGE_DAYS = 30
```

- [ ] **Step 4: Implement POST /api/feedback endpoint**

In `app.py`, near the existing API endpoints (around line 3731, after `api_snapshot_fresh`), add:

```python
@app.route("/api/feedback", methods=["POST"])
def api_submit_feedback():
    """Accept inline feedback for a snapshot (NES-362)."""
    data = request.get_json(silent=True) or {}

    snapshot_id = data.get("snapshot_id")
    if not snapshot_id:
        return jsonify({"error": "snapshot_id is required"}), 400

    told = data.get("told_something_new")
    if told not in (0, 1, True, False):
        return jsonify({"error": "told_something_new must be 0 or 1"}), 400
    told = int(told)

    free_text = data.get("free_text")
    if free_text and len(free_text) > 1000:
        return jsonify({"error": "free_text must be 1000 characters or fewer"}), 400

    feedback_type = data.get("feedback_type", "inline_reaction")

    # Identity: prefer authenticated user, fall back to visitor cookie
    user_id = None
    if current_user.is_authenticated:
        user_id = current_user.id
    visitor_id = request.cookies.get("nestcheck_vid")

    if not user_id and not visitor_id:
        return jsonify({"error": "No identity available — enable cookies or sign in"}), 400

    # Verify snapshot exists
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({"error": "Snapshot not found"}), 404

    saved = save_feedback(snapshot_id, user_id, visitor_id, feedback_type,
                          told, free_text)
    if not saved:
        return jsonify({"status": "duplicate"}), 200

    return jsonify({"status": "ok"}), 201
```

- [ ] **Step 5: Implement GET /api/feedback/<snapshot_id>/status**

Add immediately after the POST route:

```python
@app.route("/api/feedback/<snapshot_id>/status")
def api_feedback_status(snapshot_id):
    """Check if the current user/visitor already submitted feedback (NES-362)."""
    user_id = None
    if current_user.is_authenticated:
        user_id = current_user.id
    visitor_id = request.cookies.get("nestcheck_vid")

    submitted = has_feedback(snapshot_id, user_id, visitor_id)
    return jsonify({"submitted": submitted})
```

- [ ] **Step 6: Add imports to `app.py`**

At the top of `app.py`, add `save_feedback` and `has_feedback` to the existing `from models import ...` block.

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py -v`
Expected: All tests PASS (model tests + endpoint tests).

- [ ] **Step 8: Commit**

```bash
git add app.py tests/test_feedback.py
git commit -m "feat(NES-362): add feedback API endpoints

POST /api/feedback — accepts inline reactions with CSRF protection.
GET /api/feedback/<snapshot_id>/status — checks if already submitted.
Validates identity (user_id or visitor_id cookie), snapshot existence,
told_something_new value, and free_text length (max 1000 chars)."
```

---

### Task 4: Callout CSS and feedback button styles

**Files:**
- Modify: `static/css/report.css` (append new styles before the `@media print` block)

- [ ] **Step 1: Add callout and feedback button CSS**

In `static/css/report.css`, before the `@media print` block (which starts around line 2020), add:

```css
/* ── Callout component (NES-362) ──────────────────────────────────── */

.callout {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
  padding: var(--space-base) var(--space-lg);
  border-left: 3px solid var(--color-border-strong);
  background: var(--color-surface-subtle);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  margin: var(--space-lg) 0;
}

.callout--neutral {
  border-left-color: var(--color-border-strong);
  background: var(--color-surface-subtle);
}

.callout--caution {
  border-left-color: var(--color-health-caution);
  background: #FFFBEB;
}

.callout__icon {
  flex-shrink: 0;
  line-height: 1;
}

.callout__text {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
  line-height: var(--leading-relaxed);
}

/* ── Feedback prompt (NES-362) ────────────────────────────────────── */

.feedback-consent {
  font-size: var(--font-size-small);
  color: var(--color-text-muted);
  margin-bottom: var(--space-base);
}

.feedback-question {
  font-size: var(--font-size-base);
  color: var(--color-text-primary);
  font-weight: var(--font-weight-medium);
  margin-bottom: var(--space-sm);
}

.feedback-btn-group {
  display: flex;
  gap: var(--space-sm);
  margin-bottom: var(--space-base);
}

.feedback-btn {
  padding: var(--space-xs) var(--space-lg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  font-size: var(--font-size-base);
  cursor: pointer;
  transition: border-color 200ms ease, background 200ms ease;
}

.feedback-btn:hover {
  border-color: var(--color-border-strong);
}

.feedback-btn--selected {
  border-color: var(--color-brand);
  background: var(--color-bg-page);
  color: var(--color-text-primary);
  font-weight: var(--font-weight-medium);
}

.feedback-textarea {
  width: 100%;
  max-width: 480px;
  padding: var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-family: var(--font-body);
  font-size: var(--font-size-base);
  color: var(--color-text-primary);
  resize: vertical;
  margin-bottom: var(--space-base);
}

.feedback-textarea:focus {
  outline: none;
  border-color: var(--color-brand);
}

.feedback-submit {
  padding: var(--space-xs) var(--space-lg);
  border: none;
  border-radius: var(--radius-sm);
  background: var(--color-brand);
  color: var(--color-text-inverse, #FFFFFF);
  font-size: var(--font-size-base);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  transition: opacity 200ms ease;
}

.feedback-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.feedback-submit:not(:disabled):hover {
  opacity: 0.9;
}

.feedback-thanks {
  font-size: var(--font-size-base);
  color: var(--color-text-secondary);
  font-style: italic;
}

.feedback-error {
  font-size: var(--font-size-small);
  color: var(--color-health-fail);
  margin-top: var(--space-xs);
}

.feedback-retry {
  background: none;
  border: none;
  color: var(--color-brand);
  text-decoration: underline;
  cursor: pointer;
  font-size: var(--font-size-small);
  padding: 0;
  margin-left: var(--space-xs);
}
```

- [ ] **Step 2: Verify CSS loads without errors**

Run: `cd /Users/jeremybrowning/NestCheck && python -c "from app import app; app.test_client().get('/static/css/report.css')" && echo "OK"`
Expected: OK — no syntax errors in CSS.

- [ ] **Step 3: Commit**

```bash
git add static/css/report.css
git commit -m "feat(NES-362): add callout and feedback prompt CSS

Add .callout component styles (neutral + caution variants) and feedback
form styles (button group, textarea, submit, thank-you, error states).
All values use design system tokens from tokens.css."
```

---

### Task 5: Template — feedback form and inline JS

**Files:**
- Modify: `templates/_result_sections.html:1167-1169` (insert feedback form)
- Modify: `app.py:3446-3471` (add `show_feedback_prompt` to `view_snapshot()`)

- [ ] **Step 1: Add `show_feedback_prompt` to `view_snapshot()`**

In `app.py`, inside `view_snapshot()` (around line 3458, after `_prepare_snapshot_for_display(result)`), add:

```python
    # NES-362: show feedback prompt for recent snapshots only
    show_feedback_prompt = False
    evaluated_at_str = snapshot.get("evaluated_at")
    if evaluated_at_str:
        try:
            evaluated_at = datetime.fromisoformat(evaluated_at_str)
            age_days = (datetime.now(timezone.utc) - evaluated_at).days
            show_feedback_prompt = age_days <= FEEDBACK_PROMPT_MAX_AGE_DAYS
        except (ValueError, TypeError):
            pass
```

Then add `show_feedback_prompt=show_feedback_prompt` to the `render_template()` call's keyword arguments.

- [ ] **Step 2: Add feedback form HTML to `_result_sections.html`**

In `templates/_result_sections.html`, after the `{% endif %}` for the state_code block (around line 1167) and before the closing `</div>{# #how-we-score #}` (around line 1169), insert the feedback prompt. Actually — the feedback should be OUTSIDE the `#how-we-score` div but still inside the `{% if not is_preview %}` guard. Insert it after line 1169 (`</div>{# #how-we-score #}`) and before line 1170 (`{% endif %}`):

```html

        {# ── INLINE FEEDBACK (NES-362) ── #}
        {% if show_feedback_prompt %}
        <div id="feedback-prompt" class="callout callout--neutral" data-snapshot-id="{{ snapshot_id }}">
          <div>
            <p class="feedback-consent">Your feedback helps improve NestCheck. We won't share your responses outside our development team.</p>
            <p class="feedback-question">Did this report tell you something you didn't already know about this address?</p>
            <div class="feedback-btn-group">
              <button type="button" class="feedback-btn" data-value="1" onclick="feedbackSelect(this)">Yes</button>
              <button type="button" class="feedback-btn" data-value="0" onclick="feedbackSelect(this)">No</button>
            </div>
            <label class="feedback-consent" for="feedback-text">Anything specific that stood out? (optional)</label>
            <textarea id="feedback-text" class="feedback-textarea" rows="3" maxlength="1000"></textarea>
            <button type="button" class="feedback-submit" disabled onclick="feedbackSubmit()">Submit feedback</button>
            <div class="feedback-error" style="display:none"></div>
          </div>
        </div>
        {% endif %}
```

- [ ] **Step 3: Add inline JS for feedback form**

In `templates/_result_sections.html`, at the very end of the file (after all HTML, inside a `<script>` block), add:

```html
{% if show_feedback_prompt %}
<script>
(function() {
  var prompt = document.getElementById('feedback-prompt');
  if (!prompt) return;

  var snapshotId = prompt.getAttribute('data-snapshot-id');
  var selectedValue = null;

  // Check if already submitted
  fetch('/api/feedback/' + snapshotId + '/status', {
    headers: { 'Accept': 'application/json' }
  })
  .then(function(r) { return r.ok ? r.json() : null; })
  .then(function(data) {
    if (data && data.submitted) {
      prompt.innerHTML = '<div><p class="feedback-thanks">You\'ve already shared feedback. Thank you!</p></div>';
    }
  })
  .catch(function() { /* status check failure is non-fatal */ });

  window.feedbackSelect = function(btn) {
    selectedValue = parseInt(btn.getAttribute('data-value'));
    var btns = prompt.querySelectorAll('.feedback-btn');
    btns.forEach(function(b) { b.classList.remove('feedback-btn--selected'); });
    btn.classList.add('feedback-btn--selected');
    prompt.querySelector('.feedback-submit').disabled = false;
  };

  window.feedbackSubmit = function() {
    var submitBtn = prompt.querySelector('.feedback-submit');
    var errorDiv = prompt.querySelector('.feedback-error');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending...';
    errorDiv.style.display = 'none';

    var textarea = document.getElementById('feedback-text');
    var body = {
      snapshot_id: snapshotId,
      feedback_type: 'inline_reaction',
      told_something_new: selectedValue,
      free_text: textarea ? textarea.value.trim() || null : null
    };

    csrfFetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    .then(function(data) {
      if (data.status === 'ok' || data.status === 'duplicate') {
        prompt.innerHTML = '<div><p class="feedback-thanks">Thanks! Your feedback has been recorded.</p></div>';
      } else if (data.error) {
        throw new Error(data.error);
      }
    })
    .catch(function(err) {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Submit feedback';
      errorDiv.style.display = 'block';
      errorDiv.innerHTML = 'Something went wrong \u2014 your feedback wasn\'t saved. <button class="feedback-retry" onclick="feedbackSubmit()">Try again</button>';
    });
  };
})();
</script>
{% endif %}
```

- [ ] **Step 4: Verify the template renders without errors**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest smoke_test.py -v -k "test_snapshot"`
Expected: PASS — snapshot page renders. The feedback form will be hidden for snapshots older than 30 days but the template compiles without error.

- [ ] **Step 5: Commit**

```bash
git add templates/_result_sections.html app.py
git commit -m "feat(NES-362): add inline feedback form to report page

Add feedback prompt below How We Score section, gated by
show_feedback_prompt (snapshots <= 30 days old). Includes Yes/No
toggle, optional free text, submit via csrfFetch, and status check
on page load. Six UI states: fresh, selected, submitting, success,
error with retry, and already-submitted."
```

---

### Task 6: End-to-end verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_feedback.py -v`
Expected: All tests PASS.

- [ ] **Step 2: Run smoke tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest smoke_test.py -v`
Expected: All smoke tests PASS (landing page, snapshot page markers unaffected).

- [ ] **Step 3: Run scoring regression tests (sanity check)**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_scoring_regression.py -v`
Expected: All PASS — no scoring logic was touched.

- [ ] **Step 4: Manual browser check (if dev server available)**

Start: `cd /Users/jeremybrowning/NestCheck && FLASK_DEBUG=1 python -m flask run`

1. Navigate to a recent snapshot page (`/s/<id>`)
2. Verify feedback form appears below "How We Score"
3. Click "Yes" — verify button highlights, submit enables
4. Type optional text
5. Click "Submit feedback" — verify thank-you message
6. Reload page — verify "already shared" message appears

- [ ] **Step 5: Commit any fixes if needed**

If manual testing reveals issues, fix and commit.
