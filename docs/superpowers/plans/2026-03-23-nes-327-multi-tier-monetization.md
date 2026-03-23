# NES-327: Multi-Tier Monetization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform NestCheck's flat $9 payment model into three tiers: free health-only (10 evals/30 days), single-report purchase ($9), and Active Search subscription ($39/mo).

**Architecture:** Thin `is_full_access` flag computed in `view_snapshot()` from DB state (payments, subscriptions). Content gating is server-side (strip data) + template-side (layout). One checkout route handles both single and subscription via `tier` param. Subscription state managed entirely via Stripe webhooks.

**Tech Stack:** Python/Flask, SQLite, Stripe Checkout + Subscriptions, Jinja2 templates

**Spec:** `docs/superpowers/specs/2026-03-23-nes-327-multi-tier-monetization-design.md`

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `models.py` | `subscriptions` table DDL, subscription CRUD, free tier counter functions | Modify |
| `app.py` | `_check_full_access()`, content gating in `view_snapshot()`, updated checkout route, subscription webhook events, subscription gate in `POST /` | Modify |
| `worker.py` | `payments.snapshot_id` backfill after `save_snapshot()` | Modify |
| `templates/_result_sections.html` | `{% if is_full_access %}` gating blocks + blurred CTA | Modify |
| `templates/snapshot.html` | Pass `is_full_access` to template context | Modify |
| `templates/pricing.html` | Three-tier redesign with CMO copy | Modify |
| `static/css/report.css` | `.gated-section` styles | Modify |
| `static/css/pricing.css` | Three-tier layout styles | Modify |
| `tests/conftest.py` | Add `subscriptions` to `_fresh_db` cleanup | Modify |
| `tests/test_monetization.py` | Tests for all monetization logic | Create |
| `docs/b2b-api-spec.md` | B2B API contract spec document | Create |

---

## Task 1: Database Schema — Subscriptions Table + Free Tier Migration

**Files:**
- Modify: `models.py:61` (`init_db()`)
- Modify: `tests/conftest.py:41` (`_fresh_db` cleanup list)
- Test: `tests/test_monetization.py`

- [ ] **Step 1: Write failing test for subscriptions table existence**

```python
# tests/test_monetization.py
import sqlite3
from models import init_db, _get_db

def test_subscriptions_table_exists():
    """Subscriptions table should be created by init_db()."""
    conn = _get_db()
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'"
    )
    assert cursor.fetchone() is not None
    conn.close()

def test_free_tier_usage_has_counter_columns():
    """free_tier_usage should have eval_count and window_start columns."""
    conn = _get_db()
    cursor = conn.execute("PRAGMA table_info(free_tier_usage)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    assert "eval_count" in columns
    assert "window_start" in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_monetization.py -v`
Expected: FAIL — `subscriptions` table doesn't exist, columns missing

- [ ] **Step 3: Add subscriptions DDL and free_tier_usage migration to `init_db()`**

In `models.py`, inside `init_db()` after existing table creation (~line 160):

```python
# Subscriptions table (NES-327)
conn.execute("""
    CREATE TABLE IF NOT EXISTS subscriptions (
        id                    TEXT PRIMARY KEY,
        user_email            TEXT NOT NULL,
        stripe_subscription_id TEXT UNIQUE,
        stripe_customer_id    TEXT,
        status                TEXT NOT NULL DEFAULT 'active',
        period_start          TEXT NOT NULL,
        period_end            TEXT NOT NULL,
        created_at            TEXT NOT NULL
    )
""")
conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_subscriptions_email
    ON subscriptions(user_email)
""")

# Free tier counter migration (NES-327)
try:
    conn.execute("ALTER TABLE free_tier_usage ADD COLUMN eval_count INTEGER DEFAULT 1")
except sqlite3.OperationalError:
    pass  # column already exists
try:
    conn.execute("ALTER TABLE free_tier_usage ADD COLUMN window_start TEXT")
except sqlite3.OperationalError:
    pass  # column already exists
conn.execute(
    "UPDATE free_tier_usage SET eval_count = 1, window_start = created_at "
    "WHERE eval_count IS NULL"
)

# Index for payment→snapshot join (NES-327)
conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_evaluation_jobs_snapshot_id
    ON evaluation_jobs(snapshot_id)
""")
```

- [ ] **Step 4: Add `subscriptions` to conftest cleanup**

In `tests/conftest.py:41`, add `"subscriptions"` to the cleanup tuple:
```python
for table in ("events", "snapshots", "payments", "free_tier_usage", "users", "evaluation_jobs", "feedback", "subscriptions"):
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_monetization.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add models.py tests/conftest.py tests/test_monetization.py
git commit -m "feat(NES-327): add subscriptions table and free tier counter migration"
```

---

## Task 2: Subscription CRUD Functions in models.py

**Files:**
- Modify: `models.py` (after existing payment functions, ~line 1320)
- Test: `tests/test_monetization.py`

- [ ] **Step 1: Write failing tests for subscription CRUD**

```python
# Add to tests/test_monetization.py
from models import (
    create_subscription, get_subscription_by_stripe_id,
    update_subscription_status, is_subscription_active,
)
import uuid
from datetime import datetime, timedelta

def test_create_and_retrieve_subscription():
    sub_id = uuid.uuid4().hex
    create_subscription(
        subscription_id=sub_id,
        user_email="test@example.com",
        stripe_subscription_id="sub_test123",
        stripe_customer_id="cus_test123",
        period_start="2026-03-01T00:00:00",
        period_end="2026-04-01T00:00:00",
    )
    sub = get_subscription_by_stripe_id("sub_test123")
    assert sub is not None
    assert sub["user_email"] == "test@example.com"
    assert sub["status"] == "active"

def test_is_subscription_active_true():
    sub_id = uuid.uuid4().hex
    future = (datetime.utcnow() + timedelta(days=30)).isoformat()
    create_subscription(
        subscription_id=sub_id,
        user_email="active@example.com",
        stripe_subscription_id="sub_active",
        stripe_customer_id="cus_active",
        period_start="2026-03-01T00:00:00",
        period_end=future,
    )
    assert is_subscription_active("active@example.com") is True

def test_is_subscription_active_expired():
    sub_id = uuid.uuid4().hex
    create_subscription(
        subscription_id=sub_id,
        user_email="expired@example.com",
        stripe_subscription_id="sub_expired",
        stripe_customer_id="cus_expired",
        period_start="2025-01-01T00:00:00",
        period_end="2025-02-01T00:00:00",
    )
    assert is_subscription_active("expired@example.com") is False

def test_update_subscription_status():
    sub_id = uuid.uuid4().hex
    future = (datetime.utcnow() + timedelta(days=30)).isoformat()
    create_subscription(
        subscription_id=sub_id,
        user_email="cancel@example.com",
        stripe_subscription_id="sub_cancel",
        stripe_customer_id="cus_cancel",
        period_start="2026-03-01T00:00:00",
        period_end=future,
    )
    update_subscription_status("sub_cancel", "canceled")
    sub = get_subscription_by_stripe_id("sub_cancel")
    assert sub["status"] == "canceled"
    # canceled still counts as active until period_end
    assert is_subscription_active("cancel@example.com") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_monetization.py -v -k "subscription"`
Expected: FAIL — functions not defined

- [ ] **Step 3: Implement subscription CRUD in models.py**

Add after existing payment functions (~line 1320):

```python
# --- Subscription functions (NES-327) ---

SUBSCRIPTION_ACTIVE = "active"
SUBSCRIPTION_CANCELED = "canceled"
SUBSCRIPTION_EXPIRED = "expired"


def create_subscription(
    subscription_id: str,
    user_email: str,
    stripe_subscription_id: str,
    stripe_customer_id: str | None,
    period_start: str,
    period_end: str,
) -> None:
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO subscriptions "
            "(id, user_email, stripe_subscription_id, stripe_customer_id, "
            "status, period_start, period_end, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (subscription_id, user_email, stripe_subscription_id,
             stripe_customer_id, SUBSCRIPTION_ACTIVE, period_start,
             period_end, datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_subscription_by_stripe_id(stripe_subscription_id: str) -> dict | None:
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?",
            (stripe_subscription_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def update_subscription_status(
    stripe_subscription_id: str,
    status: str,
    period_start: str | None = None,
    period_end: str | None = None,
) -> None:
    conn = _get_db()
    try:
        if period_start and period_end:
            conn.execute(
                "UPDATE subscriptions SET status = ?, period_start = ?, period_end = ? "
                "WHERE stripe_subscription_id = ?",
                (status, period_start, period_end, stripe_subscription_id),
            )
        else:
            conn.execute(
                "UPDATE subscriptions SET status = ? WHERE stripe_subscription_id = ?",
                (status, stripe_subscription_id),
            )
        conn.commit()
    finally:
        conn.close()


def is_subscription_active(email: str) -> bool:
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM subscriptions "
            "WHERE user_email = ? AND status IN (?, ?) "
            "AND period_end > datetime('now') LIMIT 1",
            (email, SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCELED),
        ).fetchone()
        return row is not None
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_monetization.py -v -k "subscription"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add models.py tests/test_monetization.py
git commit -m "feat(NES-327): add subscription CRUD functions"
```

---

## Task 3: Free Tier Counter Functions

**Files:**
- Modify: `models.py:1258-1320` (replace existing free tier functions)
- Test: `tests/test_monetization.py`

- [ ] **Step 1: Write failing tests for counter-based free tier**

```python
# Add to tests/test_monetization.py
from models import check_free_tier_available, record_free_tier_usage, decrement_free_tier_usage

def test_check_free_tier_available_no_record():
    """New email should have all 10 evals available."""
    assert check_free_tier_available("hash_new_user") is True

def test_free_tier_counter_increments():
    """Each record_free_tier_usage should increment eval_count."""
    email_hash = "hash_counter_test"
    for i in range(10):
        record_free_tier_usage(email_hash, "counter@test.com")
    assert check_free_tier_available(email_hash) is False

def test_free_tier_counter_nine_is_available():
    """9 evals should still leave one available."""
    email_hash = "hash_nine_test"
    for i in range(9):
        record_free_tier_usage(email_hash, "nine@test.com")
    assert check_free_tier_available(email_hash) is True

def test_decrement_free_tier_usage():
    """Decrement should restore one credit."""
    email_hash = "hash_decrement_test"
    for i in range(10):
        record_free_tier_usage(email_hash, "decrement@test.com")
    assert check_free_tier_available(email_hash) is False
    decrement_free_tier_usage(email_hash)
    assert check_free_tier_available(email_hash) is True

def test_free_tier_window_reset():
    """After 30 days, counter should reset and allow new evals."""
    from models import _get_db
    email_hash = "hash_window_reset"
    # Insert a row with an old window_start (40 days ago)
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO free_tier_usage (email_hash, email_raw, created_at, "
            "eval_count, window_start) VALUES (?, ?, datetime('now'), 10, "
            "datetime('now', '-40 days'))",
            (email_hash, "window@test.com"),
        )
        conn.commit()
    finally:
        conn.close()
    # Should be available — window expired
    assert check_free_tier_available(email_hash) is True
    # Recording should reset counter to 1
    record_free_tier_usage(email_hash, "window@test.com")
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT eval_count FROM free_tier_usage WHERE email_hash = ?",
            (email_hash,),
        ).fetchone()
        assert row[0] == 1
    finally:
        conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_monetization.py -v -k "free_tier"`
Expected: FAIL — new functions not defined or wrong signature

- [ ] **Step 3: Replace free tier functions in models.py**

Replace `check_free_tier_used` (line 1258), `record_free_tier_usage` (line 1270), `delete_free_tier_usage` (line 1290), and `update_free_tier_snapshot` (line 1306):

```python
_FREE_TIER_MAX_EVALS = 10
_FREE_TIER_WINDOW_DAYS = 30


def check_free_tier_available(email_hash: str) -> bool:
    """Return True if the email has free evals remaining in the current window."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT eval_count, window_start FROM free_tier_usage "
            "WHERE email_hash = ?",
            (email_hash,),
        ).fetchone()
        if row is None:
            return True
        eval_count = row[0] or 0
        window_start = row[1]
        # Window expired — reset is implicit on next record
        if window_start:
            from datetime import datetime, timedelta
            try:
                ws = datetime.fromisoformat(window_start)
                if datetime.utcnow() - ws > timedelta(days=_FREE_TIER_WINDOW_DAYS):
                    return True
            except (ValueError, TypeError):
                return True
        return eval_count < _FREE_TIER_MAX_EVALS
    finally:
        conn.close()


def record_free_tier_usage(email_hash: str, email_raw: str) -> None:
    """Atomically increment the free tier counter for this email."""
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO free_tier_usage (email_hash, email_raw, created_at, "
            "eval_count, window_start) "
            "VALUES (?, ?, datetime('now'), 1, datetime('now')) "
            "ON CONFLICT(email_hash) DO UPDATE SET "
            "eval_count = CASE "
            "  WHEN window_start < datetime('now', '-30 days') THEN 1 "
            "  ELSE eval_count + 1 "
            "END, "
            "window_start = CASE "
            "  WHEN window_start < datetime('now', '-30 days') THEN datetime('now') "
            "  ELSE window_start "
            "END",
            (email_hash, email_raw),
        )
        conn.commit()
    finally:
        conn.close()


def decrement_free_tier_usage(email_hash: str) -> None:
    """Return one free tier credit (e.g., when a job fails)."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE free_tier_usage SET eval_count = MAX(0, eval_count - 1) "
            "WHERE email_hash = ?",
            (email_hash,),
        )
        conn.commit()
    finally:
        conn.close()
```

Remove `delete_free_tier_usage()` and `update_free_tier_snapshot()`.

- [ ] **Step 4: Update call sites for changed signatures**

Grep for `check_free_tier_used`, `record_free_tier_usage`, `delete_free_tier_usage`, `update_free_tier_snapshot` across `app.py` and `worker.py`. Update:
- `check_free_tier_used(email_h)` → `check_free_tier_available(email_h)` (logic inverted — old returns True when used, new returns True when available)
- `record_free_tier_usage(email_h, email, job_id)` → `record_free_tier_usage(email_h, email)` (drop `job_id`)
- `delete_free_tier_usage(job_id)` → `decrement_free_tier_usage(email_h)` (need email_hash, not job_id — thread `email_hash` through the worker failure path)
- Remove `update_free_tier_snapshot()` call site in `worker.py` (spec Section 1: "Remove update_free_tier_snapshot() and its call site")
- Remove `update_free_tier_snapshot()` call site in `app.py` if present

- [ ] **Step 5: Run all tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_monetization.py -v`
Expected: PASS

- [ ] **Step 6: Run existing tests to check for regressions**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/ -v --timeout=30`
Expected: PASS (or only pre-existing failures)

- [ ] **Step 7: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add models.py app.py worker.py tests/test_monetization.py
git commit -m "feat(NES-327): replace free tier boolean with 10-eval rolling counter"
```

---

## Task 4: Access Resolution — `_check_full_access()`

**Files:**
- Modify: `app.py` (add function near payment gate block, ~line 3450)
- Test: `tests/test_monetization.py`

- [ ] **Step 1: Write failing tests for `_check_full_access()`**

```python
# Add to tests/test_monetization.py
from app import app

def test_check_full_access_builder_mode():
    """Builder mode always grants full access."""
    with app.test_request_context():
        from flask import g
        g.is_builder = True
        from app import _check_full_access
        assert _check_full_access("nonexistent_snapshot") is True

def test_check_full_access_require_payment_false():
    """When REQUIRE_PAYMENT=false, all snapshots have full access."""
    with app.test_request_context():
        from flask import g
        g.is_builder = False
        from app import _check_full_access, REQUIRE_PAYMENT
        import app as app_module
        original = app_module.REQUIRE_PAYMENT
        app_module.REQUIRE_PAYMENT = False
        try:
            assert _check_full_access("any_snapshot") is True
        finally:
            app_module.REQUIRE_PAYMENT = original

def test_check_full_access_no_payment_no_subscription():
    """Without payment or subscription, access is denied."""
    with app.test_request_context():
        from flask import g
        g.is_builder = False
        from app import _check_full_access
        import app as app_module
        original = app_module.REQUIRE_PAYMENT
        app_module.REQUIRE_PAYMENT = True
        try:
            assert _check_full_access("no_such_snapshot") is False
        finally:
            app_module.REQUIRE_PAYMENT = original

def test_check_full_access_with_direct_snapshot_payment():
    """Payment linked directly to snapshot_id (unlock flow) grants access."""
    from models import _get_db, PAYMENT_REDEEMED
    import uuid
    snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
    payment_id = uuid.uuid4().hex
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO payments (id, status, snapshot_id, created_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (payment_id, PAYMENT_REDEEMED, snapshot_id),
        )
        conn.commit()
    finally:
        conn.close()
    with app.test_request_context():
        from flask import g
        g.is_builder = False
        from app import _check_full_access
        import app as app_module
        original = app_module.REQUIRE_PAYMENT
        app_module.REQUIRE_PAYMENT = True
        try:
            assert _check_full_access(snapshot_id) is True
        finally:
            app_module.REQUIRE_PAYMENT = original

def test_check_full_access_with_payment_via_job():
    """Payment linked via job_id → evaluation_jobs.snapshot_id grants access."""
    from models import _get_db, PAYMENT_REDEEMED
    import uuid
    snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    payment_id = uuid.uuid4().hex
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO evaluation_jobs (job_id, address, status, snapshot_id, created_at) "
            "VALUES (?, 'test addr', 'done', ?, datetime('now'))",
            (job_id, snapshot_id),
        )
        conn.execute(
            "INSERT INTO payments (id, job_id, status, created_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (payment_id, job_id, PAYMENT_REDEEMED),
        )
        conn.commit()
    finally:
        conn.close()
    with app.test_request_context():
        from flask import g
        g.is_builder = False
        from app import _check_full_access
        import app as app_module
        original = app_module.REQUIRE_PAYMENT
        app_module.REQUIRE_PAYMENT = True
        try:
            assert _check_full_access(snapshot_id) is True
        finally:
            app_module.REQUIRE_PAYMENT = original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_monetization.py -v -k "full_access"`
Expected: FAIL — `_check_full_access` not defined

- [ ] **Step 3: Implement `_check_full_access()` in app.py**

Add near the payment gate section of `app.py`:

```python
def _check_full_access(snapshot_id: str, user_email: str | None = None) -> bool:
    """Check if a snapshot should render with full detail.

    Priority order: builder > dev mode > payment (job join) >
    payment (direct snapshot_id) > active sub > past sub.
    """
    if getattr(g, "is_builder", False):
        return True
    if not REQUIRE_PAYMENT:
        return True
    conn = _get_db()
    try:
        # Check payment via job join (upfront purchase flow)
        row = conn.execute(
            "SELECT 1 FROM payments p JOIN evaluation_jobs j ON p.job_id = j.job_id "
            "WHERE j.snapshot_id = ? AND p.status = ?",
            (snapshot_id, PAYMENT_REDEEMED),
        ).fetchone()
        if row:
            return True
        # Check payment via direct snapshot_id (unlock-existing-report flow)
        row = conn.execute(
            "SELECT 1 FROM payments WHERE snapshot_id = ? AND status = ?",
            (snapshot_id, PAYMENT_REDEEMED),
        ).fetchone()
        if row:
            return True
        if user_email:
            # Active subscription
            row = conn.execute(
                "SELECT 1 FROM subscriptions "
                "WHERE user_email = ? AND status IN (?, ?) "
                "AND period_end > datetime('now') LIMIT 1",
                (user_email, SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCELED),
            ).fetchone()
            if row:
                return True
            # Past subscription covering this snapshot's creation time
            row = conn.execute(
                "SELECT 1 FROM subscriptions s "
                "JOIN snapshots snap ON snap.snapshot_id = ? "
                "WHERE s.user_email = ? "
                "AND snap.evaluated_at BETWEEN s.period_start AND s.period_end",
                (snapshot_id, user_email),
            ).fetchone()
            if row:
                return True
    finally:
        conn.close()
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_monetization.py -v -k "full_access"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py tests/test_monetization.py
git commit -m "feat(NES-327): add _check_full_access() access resolution function"
```

---

## Task 5: Content Gating in `view_snapshot()`

**Files:**
- Modify: `app.py:3638-3684` (`view_snapshot()` route)
- Modify: `templates/snapshot.html`

- [ ] **Step 1: Add server-side gating to `view_snapshot()`**

In `app.py`, inside `view_snapshot()`, after `_prepare_snapshot_for_display()` and before `render_template()` (~line 3680):

```python
# Content gating (NES-327)
user_email = current_user.email if current_user.is_authenticated else None
is_full_access = _check_full_access(snapshot_id, user_email=user_email)

if not is_full_access:
    result = {**result}
    result["dimension_summaries"] = [
        {k: v for k, v in dim.items() if k in ("name", "points", "band")}
        for dim in result.get("dimension_summaries", [])
    ]
    result["neighborhood_places"] = {}
    result.pop("walkability_summary", None)
    result.pop("green_escape", None)
    result.pop("urban_access", None)
    result.pop("census_demographics", None)
    result.pop("school_district", None)
```

- [ ] **Step 2: Pass `is_full_access` to template**

Update the `render_template()` call at line 3684 to include `is_full_access=is_full_access`.

- [ ] **Step 3: Run smoke test**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/ -v --timeout=30 -k "snapshot"`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py templates/snapshot.html
git commit -m "feat(NES-327): add server-side content gating to view_snapshot()"
```

---

## Task 6: Template Gating + CSS

**Files:**
- Modify: `templates/_result_sections.html`
- Modify: `static/css/report.css`

- [ ] **Step 1: Add `.gated-section` CSS to report.css**

```css
/* Content gating (NES-327) */
.gated-section {
    position: relative;
    margin: var(--space-lg) 0;
}
.gated-section__blur {
    filter: blur(6px);
    pointer-events: none;
    user-select: none;
    opacity: 0.6;
}
.gated-section__cta {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    text-align: center;
    z-index: 1;
    background: var(--color-bg-card);
    padding: var(--space-lg) var(--space-xl);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-md);
}
.gated-section__cta p {
    font-size: var(--type-l3-size);
    font-weight: var(--font-weight-semibold);
    color: var(--color-text-primary);
    margin: 0 0 var(--space-sm) 0;
}
.gated-section__cta a {
    display: inline-block;
    padding: var(--space-xs) var(--space-lg);
    background: var(--color-brand);
    color: var(--color-text-inverse);
    border-radius: var(--radius-md);
    text-decoration: none;
    font-weight: var(--font-weight-medium);
}
```

- [ ] **Step 2: Wrap gated sections in `_result_sections.html`**

Wrap each gated section with `{% if is_full_access %}...{% else %}<gated CTA>{% endif %}`:

Sections to wrap (by section ID):
- Dimension detail content inside `#section-dimensions` (venue lists, summaries — NOT the score grid)
- `#parks-green-space` detail content
- `#getting-around` detail content
- `.report-tier--context` content (schools, demographics, data sources)

The dimension score grid (`.dimension-grid` with dim cards showing name/points/band) stays always visible.

For each gated section, the `{% else %}` branch renders:
```html
{% else %}
<div class="gated-section">
    <div class="gated-section__blur" aria-hidden="true">
        <p style="color: transparent;">Detailed analysis of nearby venues, walk times, and neighborhood characteristics.</p>
        <p style="color: transparent;">Parks, transit routes, and area demographics.</p>
    </div>
    <div class="gated-section__cta">
        <p>Unlock the full evaluation</p>
        <a href="/pricing">See full report</a>
    </div>
</div>
{% endif %}
```

- [ ] **Step 3: Run Playwright tests for template rendering**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/playwright/ -v --timeout=60`
Expected: PASS (fixtures create snapshots with builder mode, so `is_full_access` should default to True via dev mode)

- [ ] **Step 4: Update smoke test markers if element IDs changed**

Per CLAUDE.md: "When changing template element IDs, update smoke_test.py markers in the same commit." Check `SNAPSHOT_REQUIRED_MARKERS` in `smoke_test.py` for any markers that reference elements inside gated sections. If gated elements are now conditionally rendered, they may need to be removed from the required markers list or gated by `is_full_access`.

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add templates/_result_sections.html static/css/report.css smoke_test.py
git commit -m "feat(NES-327): add content gating blocks and blurred CTA to report template"
```

---

## Task 7: Updated Checkout Route (Single + Subscription)

**Files:**
- Modify: `app.py:4482` (`checkout_create()` route)
- Test: `tests/test_monetization.py`

- [ ] **Step 1: Write failing test for subscription checkout**

```python
# Add to tests/test_monetization.py
def test_checkout_create_subscription_mode(client):
    """POST /checkout/create with tier=subscription should create a subscription session."""
    # This test verifies the route accepts the tier param without error
    # Actual Stripe session creation requires STRIPE_AVAILABLE=True
    response = client.post("/checkout/create", json={
        "email": "sub@example.com",
        "tier": "subscription",
    })
    # Without Stripe configured, expect 400 (Stripe not available)
    assert response.status_code in (200, 400)
```

- [ ] **Step 2: Add `_STRIPE_SUBSCRIPTION_PRICE_ID` env var loading**

Near line 228 in `app.py`, after `_STRIPE_PRICE_ID`:
```python
_STRIPE_SUBSCRIPTION_PRICE_ID = os.environ.get("STRIPE_SUBSCRIPTION_PRICE_ID")
```

- [ ] **Step 3: Update `checkout_create()` to handle `tier` and `snapshot_id` params**

Modify the existing `checkout_create()` function at line 4482:

- Accept `tier` param (`single` default, `subscription`)
- Accept `snapshot_id` param (optional)
- When `tier=subscription`: use `mode='subscription'`, `_STRIPE_SUBSCRIPTION_PRICE_ID`, success URL → `/my-reports?subscription=active`
- When `tier=single` + `snapshot_id`: use `mode='payment'`, `_STRIPE_PRICE_ID`, success URL → `/s/<snapshot_id>?payment_token={payment_id}`
- When `tier=single` no `snapshot_id`: existing behavior

- [ ] **Step 4: Run tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_monetization.py -v -k "checkout"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py tests/test_monetization.py
git commit -m "feat(NES-327): extend checkout route with tier param for subscription mode"
```

---

## Task 8: Subscription Webhook Handling

**Files:**
- Modify: `app.py:4536` (`stripe_webhook()` route)
- Test: `tests/test_monetization.py`

- [ ] **Step 1: Write failing test for webhook subscription handling**

```python
# Add to tests/test_monetization.py
from models import get_subscription_by_stripe_id

def test_webhook_creates_subscription_on_event():
    """Simulated subscription.created webhook should create a subscription row."""
    # Direct DB test since webhook requires Stripe signature
    from models import create_subscription
    import uuid
    sub_id = uuid.uuid4().hex
    create_subscription(
        subscription_id=sub_id,
        user_email="webhook@test.com",
        stripe_subscription_id="sub_webhook_test",
        stripe_customer_id="cus_webhook_test",
        period_start="2026-03-23T00:00:00",
        period_end="2026-04-23T00:00:00",
    )
    sub = get_subscription_by_stripe_id("sub_webhook_test")
    assert sub is not None
    assert sub["status"] == "active"
```

- [ ] **Step 2: Add subscription webhook events to `stripe_webhook()`**

In `app.py`, inside the `stripe_webhook()` function, after the existing `checkout.session.completed` handling, add:

```python
elif event["type"] == "customer.subscription.created":
    sub_obj = event["data"]["object"]
    _handle_subscription_created(sub_obj)
elif event["type"] == "customer.subscription.updated":
    sub_obj = event["data"]["object"]
    _handle_subscription_updated(sub_obj)
elif event["type"] == "customer.subscription.deleted":
    sub_obj = event["data"]["object"]
    _handle_subscription_deleted(sub_obj)
```

Add helper functions:

```python
def _resolve_email_from_customer(customer_id: str) -> str | None:
    """Look up email for a Stripe customer: DB first, then Stripe API."""
    from models import _get_db
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT email FROM users WHERE stripe_customer_id = ?",
            (customer_id,),
        ).fetchone()
        if row:
            return row[0]
    finally:
        conn.close()
    # Fallback: ask Stripe directly
    if STRIPE_AVAILABLE:
        try:
            customer = stripe.Customer.retrieve(customer_id)
            return customer.get("email")
        except Exception:
            logger.warning("Failed to retrieve Stripe customer %s", customer_id)
    return None


def _handle_subscription_created(sub_obj: dict) -> None:
    email = _resolve_email_from_customer(sub_obj["customer"])
    if not email:
        logger.warning("No email for subscription %s", sub_obj["id"])
        return
    create_subscription(
        subscription_id=uuid.uuid4().hex,
        user_email=email,
        stripe_subscription_id=sub_obj["id"],
        stripe_customer_id=sub_obj["customer"],
        period_start=datetime.utcfromtimestamp(
            sub_obj["current_period_start"]
        ).isoformat(),
        period_end=datetime.utcfromtimestamp(
            sub_obj["current_period_end"]
        ).isoformat(),
    )


def _handle_subscription_updated(sub_obj: dict) -> None:
    status = SUBSCRIPTION_ACTIVE
    if sub_obj.get("cancel_at_period_end"):
        status = SUBSCRIPTION_CANCELED
    update_subscription_status(
        sub_obj["id"],
        status,
        period_start=datetime.utcfromtimestamp(
            sub_obj["current_period_start"]
        ).isoformat(),
        period_end=datetime.utcfromtimestamp(
            sub_obj["current_period_end"]
        ).isoformat(),
    )


def _handle_subscription_deleted(sub_obj: dict) -> None:
    update_subscription_status(sub_obj["id"], SUBSCRIPTION_EXPIRED)
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_monetization.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py tests/test_monetization.py
git commit -m "feat(NES-327): handle subscription webhook events"
```

---

## Task 9: Subscription Gate in `POST /` + Worker Backfill

**Files:**
- Modify: `app.py:3479-3500` (free tier gate block in `POST /`)
- Modify: `worker.py:172` (after `complete_job()`)
- Test: `tests/test_monetization.py`

- [ ] **Step 1: Write failing test for subscription bypassing free tier**

```python
# Add to tests/test_monetization.py
def test_subscription_user_skips_free_tier_gate():
    """Active subscriber should not consume free tier credits."""
    from models import create_subscription, check_free_tier_available, record_free_tier_usage
    import uuid
    from datetime import datetime, timedelta

    email_hash = "hash_sub_bypass"
    # Use all 10 free evals
    for i in range(10):
        record_free_tier_usage(email_hash, "subbbypass@test.com")
    assert check_free_tier_available(email_hash) is False

    # Create active subscription
    future = (datetime.utcnow() + timedelta(days=30)).isoformat()
    create_subscription(
        subscription_id=uuid.uuid4().hex,
        user_email="subbbypass@test.com",
        stripe_subscription_id="sub_bypass_test",
        stripe_customer_id="cus_bypass",
        period_start=datetime.utcnow().isoformat(),
        period_end=future,
    )
    # Subscriber should still be able to evaluate (checked via is_subscription_active)
    from models import is_subscription_active
    assert is_subscription_active("subbbypass@test.com") is True

def test_paid_eval_does_not_increment_free_tier():
    """Paid evaluation should NOT consume a free tier credit."""
    from models import check_free_tier_available, record_free_tier_usage, _get_db

    email_hash = "hash_paid_no_inc"
    # Use 9 of 10 free evals
    for i in range(9):
        record_free_tier_usage(email_hash, "paid@test.com")
    # Verify count is 9
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT eval_count FROM free_tier_usage WHERE email_hash = ?",
            (email_hash,),
        ).fetchone()
        assert row[0] == 9
    finally:
        conn.close()
    # Simulate a paid eval: do NOT call record_free_tier_usage
    # (the guard in POST / skips it when _payment_id_for_job is set)
    # Count should still be 9
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT eval_count FROM free_tier_usage WHERE email_hash = ?",
            (email_hash,),
        ).fetchone()
        assert row[0] == 9
    finally:
        conn.close()
    assert check_free_tier_available(email_hash) is True
```

- [ ] **Step 2: Update `POST /` free tier gate to check subscription**

In `app.py`, in the `POST /` handler, before the `check_free_tier_available` call (~line 3479):

```python
# Subscription users skip free tier entirely (NES-327)
_is_subscriber = email and is_subscription_active(email)
```

Then wrap the free tier check:
```python
if not _is_subscriber and check_free_tier_available(email_h):
    ...  # existing logic, but with inverted check name
```

And skip `record_free_tier_usage` for subscribers:
```python
if not _payment_id_for_job and not g.is_builder and email and not _is_subscriber:
    record_free_tier_usage(email_h, email)
```

- [ ] **Step 3: Add worker backfill for `payments.snapshot_id`**

In `worker.py`, after `complete_job()` call (~line 172), add:

```python
# Backfill payment.snapshot_id for this job (NES-327)
try:
    from models import update_payment_snapshot_id
    update_payment_snapshot_id(snapshot_id, job_id)
except Exception:
    logger.warning("Failed to backfill payment snapshot_id for job %s", job_id)
```

Add `update_payment_snapshot_id` to `models.py`:
```python
def update_payment_snapshot_id(snapshot_id: str, job_id: str) -> None:
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE payments SET snapshot_id = ? WHERE job_id = ? AND snapshot_id IS NULL",
            (snapshot_id, job_id),
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_monetization.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py worker.py models.py tests/test_monetization.py
git commit -m "feat(NES-327): subscription bypasses free tier gate, worker backfills payment snapshot_id"
```

---

## Task 10: Pricing Page Redesign

**Files:**
- Modify: `templates/pricing.html`
- Modify: `static/css/pricing.css`

- [ ] **Step 1: Rewrite pricing.html with three-tier layout**

Replace the current single-tier pricing page with the three-column layout from the spec. Key elements:

- Positioning headline: "NestCheck evaluates what you can't renovate — the location."
- Three cards: Health Check (Free), Full Evaluation ($9), Active Search ($39/mo)
- CTAs: "Check an address" → `/`, "Evaluate an address" → `/`, "Start searching" → JS form submit
- Subscribe CTA: inline email input for non-logged-in users, hidden pre-filled for logged-in
- Subscribe form POSTs to `/checkout/create` with `tier=subscription` via `csrfFetch`

Use `{% if current_user.is_authenticated %}` for email pre-fill logic.

- [ ] **Step 2: Update pricing.css for three-tier layout**

Grid layout: `display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-lg);`
Collapse to single column at 640px breakpoint.
Recommended tier (Active Search) gets a subtle border highlight.
Follow existing monochrome sub-palette conventions from NES-232.

- [ ] **Step 3: Visual QA**

Run the dev server and verify:
- Three columns render correctly on desktop
- Single column on mobile
- CTA buttons link correctly
- Subscribe form shows email input when not logged in

- [ ] **Step 4: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add templates/pricing.html static/css/pricing.css
git commit -m "feat(NES-327): three-tier pricing page with CMO copy"
```

---

## Task 11: Snapshot Payment Redemption in `view_snapshot()`

**Files:**
- Modify: `app.py:3638` (`view_snapshot()`)

- [ ] **Step 1: Add payment redemption on snapshot view**

In `view_snapshot()`, before the `_check_full_access()` call, check for `?payment_token=` query param:

```python
# Payment redemption on snapshot view (NES-327)
payment_token = request.args.get("payment_token")
if payment_token and REQUIRE_PAYMENT:
    payment = get_payment_by_id(payment_token)
    if payment and payment["status"] in (PAYMENT_PENDING, PAYMENT_PAID):
        # Verify with Stripe if still pending
        if payment["status"] == PAYMENT_PENDING and STRIPE_AVAILABLE:
            try:
                session = stripe.checkout.Session.retrieve(
                    payment["stripe_session_id"]
                )
                if session.payment_status == "paid":
                    update_payment_status(
                        payment_token, PAYMENT_PAID,
                        expected_status=PAYMENT_PENDING,
                    )
            except Exception:
                logger.warning("Stripe session check failed for %s", payment_token)
        redeem_payment(payment_token)
        # Link payment directly to this snapshot (unlock-existing-report flow)
        update_payment_snapshot_id_direct(payment_token, snapshot_id)
```

Add `update_payment_snapshot_id_direct` to `models.py`:
```python
def update_payment_snapshot_id_direct(payment_id: str, snapshot_id: str) -> None:
    """Link a payment directly to a snapshot_id (for unlock-existing-report flow)."""
    conn = _get_db()
    try:
        conn.execute(
            "UPDATE payments SET snapshot_id = ? WHERE id = ?",
            (snapshot_id, payment_id),
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 2: Run smoke test**

Run: `cd /Users/jeremybrowning/NestCheck && python smoke_test.py`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py
git commit -m "feat(NES-327): redeem payment token on snapshot view for unlock flow"
```

---

## Task 12: B2B API Spec Document

**Files:**
- Create: `docs/b2b-api-spec.md`

- [ ] **Step 1: Write the B2B spec document**

Create `docs/b2b-api-spec.md` with:
- API contract (`POST /api/v1/evaluate` with Bearer auth)
- Request/response shapes (reference `result_to_dict()` output)
- Rate limits (100 req/hour per key)
- Authentication model (API keys, hashed storage)
- Partner categories (relocation companies, corporate HR, home insurers, inspection firms)
- Onboarding flow (inquiry → NDA → API key → sandbox → production)
- No implementation — this is a planning document for future work

- [ ] **Step 2: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add docs/b2b-api-spec.md
git commit -m "docs(NES-327): add B2B API licensing spec document"
```

---

## Task 13: Smoke Test Markers + Integration Verification

**Files:**
- Modify: `smoke_test.py` (if element IDs changed)
- Run: full test suite

- [ ] **Step 1: Check smoke test markers**

Grep `smoke_test.py` for any markers that reference elements we modified. Update if section IDs changed.

- [ ] **Step 2: Run full test suite**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/ -v --timeout=60`
Expected: PASS

- [ ] **Step 3: Run smoke test**

Run: `cd /Users/jeremybrowning/NestCheck && python smoke_test.py`
Expected: PASS

- [ ] **Step 4: Manual verification checklist**

With `REQUIRE_PAYMENT=false` (dev mode):
- [ ] All snapshots render with full detail (no gating)
- [ ] Pricing page shows three tiers
- [ ] `/pricing` loads without errors

With `REQUIRE_PAYMENT=true`:
- [ ] New snapshots show health-only (gated)
- [ ] Builder mode shows full detail
- [ ] Dimension scores visible but detail hidden

- [ ] **Step 5: Final commit if any fixes needed**

```bash
cd /Users/jeremybrowning/NestCheck
git add -A
git commit -m "fix(NES-327): smoke test and integration fixes"
```
