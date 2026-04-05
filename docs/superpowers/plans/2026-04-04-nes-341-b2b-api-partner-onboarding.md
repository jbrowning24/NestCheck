# NES-341: B2B API & Partner Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a B2B REST API that lets partners (relocation companies, HR, insurers) run property evaluations programmatically, with API key auth, rate limiting, curated response schema, sandbox mode, and CLI partner management.

**Architecture:** Flask Blueprint at `/api/v1/b2b/` with 6 modules: auth, routes, schema, sandbox, quota, cli. Four new DB tables (partners, partner_api_keys, partner_quota_usage, partner_usage_log) plus one migration (partner_id on evaluation_jobs). Reuses existing job queue and evaluation engine.

**Tech Stack:** Flask Blueprint, Flask-Limiter 4.x (memory:// storage), SHA-256 key hashing, SQLite upsert for quota, Click CLI commands.

**Spec:** `docs/superpowers/specs/2026-04-04-nes-341-b2b-api-partner-onboarding-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `b2b/__init__.py` | Create | Blueprint definition, Flask-Limiter init |
| `b2b/auth.py` | Create | `@require_api_key` decorator, key validation |
| `b2b/quota.py` | Create | Monthly quota check, quota increment (upsert) |
| `b2b/schema.py` | Create | `build_b2b_response()` — curated response builder |
| `b2b/sandbox.py` | Create | Sandbox address map, snapshot replay |
| `b2b/routes.py` | Create | POST /evaluate, GET /jobs/{id} endpoints |
| `b2b/cli.py` | Create | `flask partner` CLI command group |
| `models.py` | Modify | 4 new tables + partner_id migration on evaluation_jobs |
| `app.py` | Modify | Register Blueprint, pass partner_id to create_job |
| `tests/test_b2b_auth.py` | Create | Auth decorator tests |
| `tests/test_b2b_quota.py` | Create | Quota enforcement tests |
| `tests/test_b2b_schema.py` | Create | Response schema tests |
| `tests/test_b2b_routes.py` | Create | Endpoint integration tests |
| `tests/test_b2b_cli.py` | Create | CLI command tests |
| `tests/conftest.py` | Modify | Add new tables to `_fresh_db` cleanup list |

---

## Task 1: Database Schema — New Tables + Migration

**Files:**
- Modify: `models.py:116-392` (init_db function, table creation + migration section)
- Modify: `tests/conftest.py:28-30` (_fresh_db table cleanup list)
- Test: `tests/test_b2b_auth.py` (new file, first test)

- [ ] **Step 1: Write failing test for partner table creation**

Create `tests/test_b2b_auth.py`:
```python
"""Tests for B2B partner authentication and key management."""
import pytest
from models import _get_db, init_db


def test_partners_table_exists():
    """init_db() creates the partners table."""
    conn = _get_db()
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "partners" in tables


def test_partner_api_keys_table_exists():
    conn = _get_db()
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "partner_api_keys" in tables


def test_partner_quota_usage_table_exists():
    conn = _get_db()
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "partner_quota_usage" in tables


def test_partner_usage_log_table_exists():
    conn = _get_db()
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert "partner_usage_log" in tables


def test_evaluation_jobs_has_partner_id_column():
    conn = _get_db()
    cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(evaluation_jobs)").fetchall()
    }
    conn.close()
    assert "partner_id" in cols
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_b2b_auth.py -v`
Expected: 5 FAIL — tables don't exist yet

- [ ] **Step 3: Implement table creation in models.py**

Add to `init_db()` in `models.py`, after existing CREATE TABLE statements (around line 140), add:

```python
# ── B2B Partner tables ────────────────────────────────────────
conn.execute("""
    CREATE TABLE IF NOT EXISTS partners (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        contact_email TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'active',
        monthly_quota INTEGER NOT NULL DEFAULT 500,
        notes         TEXT,
        created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )
""")

conn.execute("""
    CREATE TABLE IF NOT EXISTS partner_api_keys (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        partner_id  INTEGER NOT NULL REFERENCES partners(id),
        key_hash    TEXT NOT NULL UNIQUE,
        key_prefix  TEXT NOT NULL,
        environment TEXT NOT NULL,
        revoked_at  TEXT,
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )
""")
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON partner_api_keys(key_hash)"
)

conn.execute("""
    CREATE TABLE IF NOT EXISTS partner_quota_usage (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        partner_id    INTEGER NOT NULL REFERENCES partners(id),
        period        TEXT NOT NULL,
        request_count INTEGER NOT NULL DEFAULT 0,
        UNIQUE(partner_id, period)
    )
""")

conn.execute("""
    CREATE TABLE IF NOT EXISTS partner_usage_log (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        key_id           INTEGER NOT NULL REFERENCES partner_api_keys(id),
        address          TEXT NOT NULL,
        snapshot_id      TEXT,
        status_code      INTEGER NOT NULL,
        response_time_ms INTEGER,
        api_cost_cents   INTEGER,
        created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )
""")
conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_usage_log_key_date "
    "ON partner_usage_log(key_id, created_at)"
)
```

In the migration section (around line 330), add the `partner_id` column migration for `evaluation_jobs`:

```python
# Migration: B2B partner_id on evaluation_jobs
job_cols = {
    row["name"]
    for row in conn.execute("PRAGMA table_info(evaluation_jobs)").fetchall()
}
if "partner_id" not in job_cols:
    conn.execute(
        "ALTER TABLE evaluation_jobs ADD COLUMN partner_id INTEGER"
    )
```

- [ ] **Step 4: Update conftest.py _fresh_db cleanup**

In `tests/conftest.py`, add the new tables to the cleanup loop (line 28-30):

Add these tables to the cleanup tuple **before** `evaluation_jobs`, in FK-safe order (children before parents):

```python
for table in ("events", "snapshots", "payments", "free_tier_usage", "users",
              "partner_usage_log", "partner_quota_usage", "partner_api_keys", "partners",
              "evaluation_jobs", "feedback", "subscriptions", "canopy_cache"):
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_b2b_auth.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add models.py tests/conftest.py tests/test_b2b_auth.py
git commit -m "feat(NES-341): add B2B partner database tables and migrations"
```

---

## Task 2: API Key Auth Decorator

**Files:**
- Create: `b2b/__init__.py`
- Create: `b2b/auth.py`
- Modify: `tests/test_b2b_auth.py`

- [ ] **Step 1: Write failing tests for auth decorator**

Append to `tests/test_b2b_auth.py`:

```python
import hashlib
import secrets
from datetime import datetime, timezone

from models import _get_db


def _create_partner(name="Test Corp", email="test@corp.com", quota=500):
    """Helper to insert a partner and return its id."""
    conn = _get_db()
    cursor = conn.execute(
        "INSERT INTO partners (name, contact_email, monthly_quota) VALUES (?, ?, ?)",
        (name, email, quota),
    )
    partner_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return partner_id


def _create_api_key(partner_id, environment="live"):
    """Helper to insert an API key and return (full_key, key_id)."""
    prefix = "nc_test_" if environment == "test" else "nc_live_"
    raw = prefix + secrets.token_hex(16)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    key_prefix = raw[:16]
    conn = _get_db()
    cursor = conn.execute(
        "INSERT INTO partner_api_keys (partner_id, key_hash, key_prefix, environment) "
        "VALUES (?, ?, ?, ?)",
        (partner_id, key_hash, key_prefix, environment),
    )
    key_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return raw, key_id


class TestRequireApiKey:
    """Tests for the @require_api_key decorator."""

    def test_missing_auth_header_returns_401(self, client):
        resp = client.post("/api/v1/b2b/evaluate", json={"address": "123 Main St"})
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["error"]["code"] == "unauthorized"

    def test_invalid_key_returns_401(self, client):
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St"},
            headers={"Authorization": "Bearer nc_live_invalidkey1234567890abcdef"},
        )
        assert resp.status_code == 401

    def test_valid_key_does_not_return_401(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St"},
            headers={"Authorization": "Bearer " + key},
        )
        # Should NOT be 401 — may be 422 (out of coverage) or 202, but not auth failure
        assert resp.status_code != 401

    def test_revoked_key_returns_401(self, client):
        pid = _create_partner()
        key, key_id = _create_api_key(pid)
        conn = _get_db()
        conn.execute(
            "UPDATE partner_api_keys SET revoked_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), key_id),
        )
        conn.commit()
        conn.close()
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St"},
            headers={"Authorization": "Bearer " + key},
        )
        assert resp.status_code == 401

    def test_suspended_partner_returns_403(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        conn = _get_db()
        conn.execute("UPDATE partners SET status = 'suspended' WHERE id = ?", (pid,))
        conn.commit()
        conn.close()
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St"},
            headers={"Authorization": "Bearer " + key},
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"]["code"] == "suspended"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_b2b_auth.py::TestRequireApiKey -v`
Expected: FAIL — b2b module doesn't exist yet

- [ ] **Step 3: Create b2b/__init__.py**

Create `b2b/__init__.py`:

```python
"""B2B API Blueprint for partner integrations."""

from flask import Blueprint

b2b_bp = Blueprint("b2b", __name__, url_prefix="/api/v1/b2b")

# Import routes to register them on the Blueprint.
# This must happen after b2b_bp is created to avoid circular imports.
from b2b import routes as _routes  # noqa: F401, E402
```

- [ ] **Step 4: Create b2b/auth.py**

Create `b2b/auth.py`:

```python
"""API key authentication for B2B partners."""

import hashlib
from functools import wraps

from flask import g, jsonify, request

from models import _get_db


def require_api_key(f):
    """Decorator that validates Bearer token and sets g.partner + g.api_key.

    Returns 401 for missing/invalid/revoked keys.
    Returns 403 for suspended partner accounts.
    Sets g.api_key_environment to 'test' or 'live'.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": {
                "code": "unauthorized",
                "message": "Missing or malformed Authorization header. Expected: Bearer <api_key>",
                "type": "auth",
            }}), 401

        token = auth_header[7:]  # strip "Bearer "
        if not token.startswith(("nc_live_", "nc_test_")):
            return jsonify({"error": {
                "code": "unauthorized",
                "message": "Invalid API key format.",
                "type": "auth",
            }}), 401

        key_hash = hashlib.sha256(token.encode()).hexdigest()
        conn = _get_db()
        try:
            row = conn.execute(
                """SELECT k.id AS key_id, k.partner_id, k.environment, k.revoked_at,
                          p.name AS partner_name, p.status, p.monthly_quota
                   FROM partner_api_keys k
                   JOIN partners p ON p.id = k.partner_id
                   WHERE k.key_hash = ?""",
                (key_hash,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return jsonify({"error": {
                "code": "unauthorized",
                "message": "Invalid API key.",
                "type": "auth",
            }}), 401

        if row["revoked_at"] is not None:
            return jsonify({"error": {
                "code": "unauthorized",
                "message": "This API key has been revoked.",
                "type": "auth",
            }}), 401

        if row["status"] == "suspended":
            return jsonify({"error": {
                "code": "suspended",
                "message": "Partner account is suspended. Contact support.",
                "type": "auth",
            }}), 403

        if row["status"] == "revoked":
            return jsonify({"error": {
                "code": "unauthorized",
                "message": "Partner account has been revoked.",
                "type": "auth",
            }}), 401

        # Set request context
        g.partner = {
            "id": row["partner_id"],
            "name": row["partner_name"],
            "status": row["status"],
            "monthly_quota": row["monthly_quota"],
        }
        g.api_key = {
            "id": row["key_id"],
            "environment": row["environment"],
        }

        return f(*args, **kwargs)
    return decorated
```

- [ ] **Step 5: Create minimal b2b/routes.py stub**

Create `b2b/routes.py` with a stub evaluate endpoint so tests can exercise auth:

```python
"""B2B API route handlers."""

from flask import jsonify, request

from b2b import b2b_bp
from b2b.auth import require_api_key


@b2b_bp.route("/evaluate", methods=["POST"])
@require_api_key
def evaluate():
    """Create a property evaluation job. Full implementation in Task 5."""
    # Stub — will be implemented in Task 5
    return jsonify({"error": {
        "code": "not_implemented",
        "message": "Endpoint under construction.",
        "type": "server",
    }}), 501
```

- [ ] **Step 6: Register Blueprint in app.py**

In `app.py`, after the `app = Flask(__name__)` initialization block (around line 75), add:

```python
from b2b import b2b_bp
app.register_blueprint(b2b_bp)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_b2b_auth.py -v`
Expected: ALL PASS (table tests + auth tests)

- [ ] **Step 8: Commit**

```bash
git add b2b/__init__.py b2b/auth.py b2b/routes.py app.py tests/test_b2b_auth.py
git commit -m "feat(NES-341): add B2B API key auth decorator and Blueprint"
```

---

## Task 3: Quota Enforcement

**Files:**
- Create: `b2b/quota.py`
- Create: `tests/test_b2b_quota.py`

- [ ] **Step 1: Write failing tests for quota**

Create `tests/test_b2b_quota.py`:

```python
"""Tests for B2B quota enforcement."""

import pytest

from models import _get_db, init_db


# Reuse helpers from auth tests
from tests.test_b2b_auth import _create_partner, _create_api_key


class TestQuotaIncrement:
    def test_first_request_creates_period_row(self):
        from b2b.quota import increment_quota
        pid = _create_partner(quota=100)
        increment_quota(pid, "2026-04")
        conn = _get_db()
        row = conn.execute(
            "SELECT request_count FROM partner_quota_usage "
            "WHERE partner_id = ? AND period = ?",
            (pid, "2026-04"),
        ).fetchone()
        conn.close()
        assert row["request_count"] == 1

    def test_subsequent_requests_increment(self):
        from b2b.quota import increment_quota
        pid = _create_partner(quota=100)
        increment_quota(pid, "2026-04")
        increment_quota(pid, "2026-04")
        increment_quota(pid, "2026-04")
        conn = _get_db()
        row = conn.execute(
            "SELECT request_count FROM partner_quota_usage "
            "WHERE partner_id = ? AND period = ?",
            (pid, "2026-04"),
        ).fetchone()
        conn.close()
        assert row["request_count"] == 3


class TestQuotaCheck:
    def test_under_quota_returns_true(self):
        from b2b.quota import check_quota
        pid = _create_partner(quota=100)
        allowed, used, limit = check_quota(pid)
        assert allowed is True
        assert used == 0
        assert limit == 100

    def test_at_quota_returns_false(self):
        from b2b.quota import increment_quota, check_quota
        pid = _create_partner(quota=2)
        increment_quota(pid, "2026-04")
        increment_quota(pid, "2026-04")
        allowed, used, limit = check_quota(pid, period="2026-04")
        assert allowed is False
        assert used == 2

    def test_different_periods_are_independent(self):
        from b2b.quota import increment_quota, check_quota
        pid = _create_partner(quota=1)
        increment_quota(pid, "2026-03")
        allowed, used, limit = check_quota(pid, period="2026-04")
        assert allowed is True
        assert used == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_b2b_quota.py -v`
Expected: FAIL — b2b.quota module doesn't exist

- [ ] **Step 3: Implement b2b/quota.py**

Create `b2b/quota.py`:

```python
"""Monthly quota enforcement for B2B partners."""

from datetime import datetime, timezone

from models import _get_db


def _current_period() -> str:
    """Return current year-month string, e.g. '2026-04'."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def increment_quota(partner_id: int, period: str | None = None) -> int:
    """Increment the request counter for the given period. Returns new count.

    Uses SQLite upsert to avoid race conditions between workers.
    """
    period = period or _current_period()
    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO partner_quota_usage (partner_id, period, request_count)
               VALUES (?, ?, 1)
               ON CONFLICT(partner_id, period)
               DO UPDATE SET request_count = request_count + 1""",
            (partner_id, period),
        )
        row = conn.execute(
            "SELECT request_count FROM partner_quota_usage "
            "WHERE partner_id = ? AND period = ?",
            (partner_id, period),
        ).fetchone()
        conn.commit()
        return row["request_count"]
    finally:
        conn.close()


def check_quota(partner_id: int, period: str | None = None) -> tuple[bool, int, int]:
    """Check if partner is within their monthly quota.

    Returns (allowed, used, limit).
    """
    period = period or _current_period()
    conn = _get_db()
    try:
        partner = conn.execute(
            "SELECT monthly_quota FROM partners WHERE id = ?",
            (partner_id,),
        ).fetchone()
        if not partner:
            return False, 0, 0

        row = conn.execute(
            "SELECT request_count FROM partner_quota_usage "
            "WHERE partner_id = ? AND period = ?",
            (partner_id, period),
        ).fetchone()

        used = row["request_count"] if row else 0
        limit = partner["monthly_quota"]
        return used < limit, used, limit
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_b2b_quota.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add b2b/quota.py tests/test_b2b_quota.py
git commit -m "feat(NES-341): add B2B quota enforcement with SQLite upsert"
```

---

## Task 4: Curated Response Schema

**Files:**
- Create: `b2b/schema.py`
- Create: `tests/test_b2b_schema.py`

- [ ] **Step 1: Write failing tests for schema builder**

Create `tests/test_b2b_schema.py`:

```python
"""Tests for B2B curated response schema builder."""

import pytest


def _make_snapshot_result():
    """Minimal snapshot result dict that mirrors result_to_dict() output."""
    return {
        "address": "123 Main St, White Plains, NY 10601",
        "coordinates": {"lat": 41.033, "lng": -73.763},
        "walk_scores": {"walk_score": 82, "transit_score": 55, "bike_score": 60},
        "composite_score": 7,
        "composite_band": "Strong",
        "data_confidence": "verified",
        "tier2_scores": {
            "walkability": {"points": 8, "band": "Strong"},
            "green_space": {"points": 7, "band": "Strong"},
            "transit": {"points": 6, "band": "Moderate"},
            "third_place": {"points": 8, "band": "Strong"},
            "fitness": {"points": 5, "band": "Moderate"},
            "provisioning": {"points": 7, "band": "Strong"},
        },
        "checks": [
            {
                "name": "Gas Station Proximity",
                "status": "pass",
                "distance_ft": 2150,
                "description": "No gas stations within 1,500 ft",
                "icon": "gas-station",
                "css_class": "check-pass",
            },
        ],
        "health_summary": {"clear": 12, "issues": 1, "warnings": 0},
        # Internal fields that should NOT appear in B2B response
        "_trace": {"api_calls": 15, "total_ms": 12000},
        "quality_ceiling_inputs": {"sub_types": 3},
    }


class TestBuildB2bResponse:
    def test_includes_composite_score(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert resp["composite_score"] == 7
        assert resp["composite_band"] == "Strong"

    def test_includes_dimensions(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert "walkability" in resp["dimensions"]
        assert resp["dimensions"]["walkability"]["score"] == 8
        assert resp["dimensions"]["walkability"]["band"] == "Strong"

    def test_includes_health_checks(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert len(resp["health"]["checks"]) == 1
        check = resp["health"]["checks"][0]
        assert check["name"] == "Gas Station Proximity"
        assert check["status"] == "pass"

    def test_excludes_internal_fields(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert "_trace" not in resp
        assert "quality_ceiling_inputs" not in resp

    def test_health_checks_exclude_presentation_fields(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        check = resp["health"]["checks"][0]
        assert "icon" not in check
        assert "css_class" not in check

    def test_includes_snapshot_metadata(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert resp["snapshot_id"] == "snap123"
        assert "evaluated_at" in resp

    def test_includes_walk_scores(self):
        from b2b.schema import build_b2b_response
        resp = build_b2b_response(_make_snapshot_result(), "snap123")
        assert resp["dimensions"]["walkability"]["walk_score"] == 82
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_b2b_schema.py -v`
Expected: FAIL — b2b.schema doesn't exist

- [ ] **Step 3: Implement b2b/schema.py**

Create `b2b/schema.py`:

```python
"""Curated B2B response schema builder.

Transforms the internal result_to_dict() output into a stable, documented
API response. This is the translation layer that absorbs internal changes
without breaking the B2B API contract.
"""

from datetime import datetime, timezone

# Fields to keep from each health check (strip presentation metadata)
_CHECK_FIELDS = {"name", "status", "distance_ft", "description"}


def build_b2b_response(snapshot_result: dict, snapshot_id: str) -> dict:
    """Build the curated B2B API response from a snapshot result dict.

    Args:
        snapshot_result: Output of result_to_dict(), already serialized.
        snapshot_id: The snapshot identifier for linking.

    Returns:
        Curated dict matching the B2B API schema.
    """
    tier2 = snapshot_result.get("tier2_scores", {})
    walk_scores = snapshot_result.get("walk_scores") or {}
    health_summary = snapshot_result.get("health_summary", {})
    checks_raw = snapshot_result.get("checks", [])

    # Build curated health checks — strip presentation fields
    checks = []
    for c in checks_raw:
        checks.append({k: v for k, v in c.items() if k in _CHECK_FIELDS})

    # Build dimension scores
    dimensions = {}
    for dim_name, dim_data in tier2.items():
        entry = {
            "score": dim_data.get("points"),
            "band": dim_data.get("band"),
        }
        # Attach walk_score/transit_score/bike_score to relevant dimensions
        if dim_name == "walkability" and walk_scores.get("walk_score") is not None:
            entry["walk_score"] = walk_scores["walk_score"]
        if dim_name == "transit" and walk_scores.get("transit_score") is not None:
            entry["transit_score"] = walk_scores["transit_score"]
        dimensions[dim_name] = entry

    return {
        "address": snapshot_result.get("address"),
        "coordinates": snapshot_result.get("coordinates"),
        "composite_score": snapshot_result.get("composite_score"),
        "composite_band": snapshot_result.get("composite_band"),
        "health": {
            "checks": checks,
            "clear_count": health_summary.get("clear", 0),
            "issue_count": health_summary.get("issues", 0),
            "warning_count": health_summary.get("warnings", 0),
        },
        "dimensions": dimensions,
        "data_confidence": snapshot_result.get("data_confidence"),
        "snapshot_id": snapshot_id,
        "snapshot_url": f"https://nestcheck.com/s/{snapshot_id}",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_b2b_schema.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add b2b/schema.py tests/test_b2b_schema.py
git commit -m "feat(NES-341): add B2B curated response schema builder"
```

---

## Task 5: Sandbox Snapshot Replay

**Files:**
- Create: `b2b/sandbox.py`
- Modify: `tests/test_b2b_schema.py` (add sandbox tests, or create separate file)

- [ ] **Step 1: Write failing tests for sandbox**

Append to `tests/test_b2b_schema.py` or create `tests/test_b2b_sandbox.py`:

```python
"""Tests for B2B sandbox snapshot replay."""


class TestSandboxLookup:
    def test_exact_match_returns_snapshot_id(self):
        from b2b.sandbox import get_sandbox_snapshot_id
        # SANDBOX_ADDRESSES must have at least one entry
        from b2b.sandbox import SANDBOX_ADDRESSES
        if not SANDBOX_ADDRESSES:
            pytest.skip("No sandbox addresses configured")
        first_addr = next(iter(SANDBOX_ADDRESSES))
        result = get_sandbox_snapshot_id(first_addr)
        assert result is not None

    def test_no_match_returns_default(self):
        from b2b.sandbox import get_sandbox_snapshot_id, DEFAULT_SANDBOX_SNAPSHOT
        result = get_sandbox_snapshot_id("999 Nonexistent Blvd, Nowhere, XX 00000")
        assert result == DEFAULT_SANDBOX_SNAPSHOT

    def test_case_insensitive_match(self):
        from b2b.sandbox import get_sandbox_snapshot_id, SANDBOX_ADDRESSES
        if not SANDBOX_ADDRESSES:
            pytest.skip("No sandbox addresses configured")
        first_addr = next(iter(SANDBOX_ADDRESSES))
        result = get_sandbox_snapshot_id(first_addr.upper())
        assert result is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_b2b_schema.py::TestSandboxLookup -v`
Expected: FAIL

- [ ] **Step 3: Implement b2b/sandbox.py**

Create `b2b/sandbox.py`:

```python
"""Sandbox address mapping and snapshot replay for B2B test keys.

Sandbox keys return pre-computed evaluation snapshots instead of running
real evaluations. Zero API cost, deterministic responses.

TODO: Populate SANDBOX_ADDRESSES with real snapshot IDs after running
evaluations for these addresses. Until then, sandbox returns a default
placeholder response.
"""

# Map of normalized addresses -> snapshot IDs.
# Populated after running evaluations for these test addresses.
# Keys should be lowercase, stripped.
SANDBOX_ADDRESSES: dict[str, str] = {
    # Westchester
    # "10 main street, white plains, ny 10601": "snapshot_id_here",
    # DMV
    # "1600 pennsylvania ave nw, washington, dc 20500": "snapshot_id_here",
}

# Fallback snapshot when no address matches.
# Set to a real snapshot ID once available.
DEFAULT_SANDBOX_SNAPSHOT: str | None = None


def get_sandbox_snapshot_id(address: str) -> str | None:
    """Look up a sandbox snapshot for the given address.

    Returns snapshot_id if found, DEFAULT_SANDBOX_SNAPSHOT otherwise.
    """
    normalized = address.strip().lower()
    return SANDBOX_ADDRESSES.get(normalized, DEFAULT_SANDBOX_SNAPSHOT)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_b2b_schema.py::TestSandboxLookup -v`
Expected: PASS (tests skip gracefully when no sandbox addresses configured)

- [ ] **Step 5: Commit**

```bash
git add b2b/sandbox.py tests/test_b2b_schema.py
git commit -m "feat(NES-341): add B2B sandbox snapshot replay module"
```

---

## Task 6: API Route Endpoints

**Files:**
- Modify: `b2b/routes.py` (replace stub with full implementation)
- Modify: `models.py` (add partner_id param to create_job)
- Create: `tests/test_b2b_routes.py`

- [ ] **Step 1: Write failing tests for routes**

Create `tests/test_b2b_routes.py`:

```python
"""Integration tests for B2B API endpoints."""

import json
import pytest

from models import _get_db, create_job, complete_job, get_job
from tests.test_b2b_auth import _create_partner, _create_api_key


class TestEvaluateEndpoint:
    def test_missing_address_returns_400(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "invalid_request"

    def test_test_key_returns_sandbox_response(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid, environment="test")
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St, White Plains, NY 10601"},
            headers={"Authorization": f"Bearer {key}"},
        )
        data = resp.get_json()
        # Sandbox may return 200 with sandbox flag or 503 if no snapshots configured
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            assert data.get("sandbox") is True

    def test_quota_exceeded_returns_429(self, client):
        pid = _create_partner(quota=1)
        key, _ = _create_api_key(pid)
        # First request — should succeed (or at least not be 429)
        resp1 = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St, White Plains, NY 10601"},
            headers={"Authorization": f"Bearer {key}"},
        )
        # Second request — should hit quota
        resp2 = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "456 Oak Ave, Scarsdale, NY 10583"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp2.status_code == 429
        assert resp2.get_json()["error"]["code"] == "quota_exceeded"


class TestJobStatusEndpoint:
    def test_nonexistent_job_returns_404(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        resp = client.get(
            "/api/v1/b2b/jobs/nonexistent123",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 404

    def test_other_partners_job_returns_404(self, client):
        """Partner A cannot see Partner B's jobs."""
        pid_a = _create_partner(name="Partner A")
        pid_b = _create_partner(name="Partner B")
        key_a, _ = _create_api_key(pid_a)
        key_b, _ = _create_api_key(pid_b)
        # Create a job for partner B
        job_id = create_job("123 Main St", partner_id=pid_b)
        resp = client.get(
            f"/api/v1/b2b/jobs/{job_id}",
            headers={"Authorization": f"Bearer {key_a}"},
        )
        assert resp.status_code == 404

    def test_own_job_returns_status(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        job_id = create_job("123 Main St", partner_id=pid)
        resp = client.get(
            f"/api/v1/b2b/jobs/{job_id}",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["job_id"] == job_id
        assert data["status"] in ("queued", "running", "done", "failed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_b2b_routes.py -v`
Expected: FAIL — routes not implemented, create_job doesn't accept partner_id

- [ ] **Step 3: Add partner_id parameter to create_job in models.py**

In `models.py`, modify `create_job()` (line ~1157) to accept `partner_id`:

Add `partner_id: int = None` to the function signature (after `user_id`).

Update the INSERT statement (around line 1173) to include `partner_id`:

```python
# Before:
conn.execute(
    """INSERT INTO evaluation_jobs
       (job_id, address, status, visitor_id, request_id, place_id,
        email_hash, email_raw, user_id, created_at)
       VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)""",
    (job_id, address, visitor_id, request_id, place_id,
     email_hash, email_raw, user_id, now),
)

# After:
conn.execute(
    """INSERT INTO evaluation_jobs
       (job_id, address, status, visitor_id, request_id, place_id,
        email_hash, email_raw, user_id, partner_id, created_at)
       VALUES (?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)""",
    (job_id, address, visitor_id, request_id, place_id,
     email_hash, email_raw, user_id, partner_id, now),
)
```

- [ ] **Step 4: Implement full b2b/routes.py**

Replace the stub in `b2b/routes.py`:

```python
"""B2B API route handlers."""

import logging
import time
from datetime import datetime, timezone

from flask import g, jsonify, request

from b2b import b2b_bp
from b2b.auth import require_api_key
from b2b.quota import check_quota, increment_quota
from b2b.sandbox import get_sandbox_snapshot_id
from b2b.schema import build_b2b_response
from models import _get_db, create_job, get_job, get_snapshot

logger = logging.getLogger(__name__)


def _log_usage(key_id: int, address: str, status_code: int,
               response_time_ms: int = None, snapshot_id: str = None) -> None:
    """Write a row to partner_usage_log."""
    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO partner_usage_log
               (key_id, address, status_code, response_time_ms, snapshot_id)
               VALUES (?, ?, ?, ?, ?)""",
            (key_id, address, status_code, response_time_ms, snapshot_id),
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to write partner usage log")
    finally:
        conn.close()


@b2b_bp.route("/evaluate", methods=["POST"])
@require_api_key
def evaluate():
    """Create a property evaluation job (live) or return sandbox data (test)."""
    start = time.monotonic()
    data = request.get_json(silent=True) or {}
    address = data.get("address", "").strip()

    if not address:
        return jsonify({"error": {
            "code": "invalid_request",
            "message": "Missing required field: address",
            "type": "validation",
        }}), 400

    partner_id = g.partner["id"]
    key_id = g.api_key["id"]

    # Sandbox mode for test keys
    if g.api_key["environment"] == "test":
        snapshot_id = get_sandbox_snapshot_id(address)
        if not snapshot_id:
            return jsonify({"error": {
                "code": "sandbox_not_configured",
                "message": "No sandbox snapshots available. Contact support.",
                "type": "server",
            }}), 503

        snapshot = get_snapshot(snapshot_id)
        if not snapshot:
            return jsonify({"error": {
                "code": "sandbox_not_configured",
                "message": "Sandbox snapshot not found. Contact support.",
                "type": "server",
            }}), 503

        result = snapshot["result"]
        b2b_result = build_b2b_response(result, snapshot_id)
        b2b_result["sandbox"] = True
        b2b_result["sandbox_note"] = (
            "This is sandbox data for integration testing. "
            "Results are pre-computed and may not match the requested address."
        )
        elapsed = int((time.monotonic() - start) * 1000)
        _log_usage(key_id, address, 200, elapsed, snapshot_id)
        return jsonify(b2b_result), 200

    # Live mode — check quota
    allowed, used, limit = check_quota(partner_id)
    if not allowed:
        period_end = _next_month_start()
        elapsed = int((time.monotonic() - start) * 1000)
        _log_usage(key_id, address, 429, elapsed)
        return jsonify({"error": {
            "code": "quota_exceeded",
            "message": f"Monthly quota of {limit} evaluations exceeded. Resets {period_end}.",
            "type": "quota",
        }}), 429

    # Increment quota and create job
    increment_quota(partner_id)
    place_id = data.get("place_id")
    job_id = create_job(address=address, place_id=place_id, partner_id=partner_id)

    elapsed = int((time.monotonic() - start) * 1000)
    _log_usage(key_id, address, 202, elapsed)

    return jsonify({
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/api/v1/b2b/jobs/{job_id}",
    }), 202


@b2b_bp.route("/jobs/<job_id>", methods=["GET"])
@require_api_key
def job_status(job_id):
    """Poll for evaluation job status. Partners can only see their own jobs."""
    job = get_job(job_id)

    if not job or job.get("partner_id") != g.partner["id"]:
        return jsonify({"error": {
            "code": "not_found",
            "message": "Job not found.",
            "type": "client",
        }}), 404

    resp = {
        "job_id": job_id,
        "status": job["status"],
    }

    if job["current_stage"]:
        resp["stage"] = job["current_stage"]

    if job["status"] == "done" and job["snapshot_id"]:
        snapshot = get_snapshot(job["snapshot_id"])
        if snapshot:
            result = snapshot["result"]
            resp["result"] = build_b2b_response(result, job["snapshot_id"])

    if job["status"] == "failed" and job["error"]:
        resp["error_message"] = job["error"]

    return jsonify(resp), 200


def _next_month_start() -> str:
    """Return ISO date of the first day of next month."""
    now = datetime.now(timezone.utc)
    if now.month == 12:
        return f"{now.year + 1}-01-01"
    return f"{now.year}-{now.month + 1:02d}-01"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_b2b_routes.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add b2b/routes.py models.py tests/test_b2b_routes.py
git commit -m "feat(NES-341): implement B2B evaluate and job status endpoints"
```

---

## Task 7: CLI Partner Management Commands

**Files:**
- Create: `b2b/cli.py`
- Modify: `app.py` (register CLI commands)
- Create: `tests/test_b2b_cli.py`

- [ ] **Step 1: Write failing tests for CLI commands**

Create `tests/test_b2b_cli.py`:

```python
"""Tests for B2B partner CLI commands."""

import pytest
from app import app


@pytest.fixture
def runner():
    return app.test_cli_runner(mix_stderr=False)


class TestPartnerCreate:
    def test_creates_partner_and_keys(self, runner):
        result = runner.invoke(args=[
            "partner", "create",
            "--name", "Test Corp",
            "--email", "dev@testcorp.com",
        ])
        assert result.exit_code == 0
        assert "Test Corp" in result.output
        assert "nc_test_" in result.output
        assert "nc_live_" in result.output

    def test_custom_quota(self, runner):
        result = runner.invoke(args=[
            "partner", "create",
            "--name", "Big Corp",
            "--email", "dev@bigcorp.com",
            "--quota", "1000",
        ])
        assert result.exit_code == 0
        assert "1000" in result.output


class TestPartnerList:
    def test_empty_list(self, runner):
        result = runner.invoke(args=["partner", "list"])
        assert result.exit_code == 0
        assert "No partners" in result.output or "partner" in result.output.lower()

    def test_shows_created_partner(self, runner):
        runner.invoke(args=[
            "partner", "create",
            "--name", "Listed Corp",
            "--email", "dev@listed.com",
        ])
        result = runner.invoke(args=["partner", "list"])
        assert result.exit_code == 0
        assert "Listed Corp" in result.output


class TestPartnerSuspend:
    def test_suspend_and_reactivate(self, runner):
        runner.invoke(args=[
            "partner", "create",
            "--name", "Suspend Corp",
            "--email", "dev@suspend.com",
        ])
        result = runner.invoke(args=["partner", "suspend", "--name", "Suspend Corp"])
        assert result.exit_code == 0
        assert "suspended" in result.output.lower()

        result = runner.invoke(args=["partner", "reactivate", "--name", "Suspend Corp"])
        assert result.exit_code == 0
        assert "active" in result.output.lower() or "reactivated" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_b2b_cli.py -v`
Expected: FAIL — partner CLI group doesn't exist

- [ ] **Step 3: Implement b2b/cli.py**

Create `b2b/cli.py`:

```python
"""CLI commands for B2B partner management.

Usage:
    flask partner create --name "Cartus" --email "tech@cartus.com"
    flask partner list
    flask partner usage --name "Cartus" --month 2026-04
    flask partner suspend --name "Cartus"
    flask partner reactivate --name "Cartus"
    flask partner revoke-key --prefix nc_live_a1b2c3d4
    flask partner rotate-key --prefix nc_live_a1b2c3d4
    flask partner set-quota --name "Cartus" --quota 1000
"""

import hashlib
import secrets
import sys

import click
from flask.cli import AppGroup

from models import _get_db

partner_cli = AppGroup("partner", help="Manage B2B partners and API keys.")


def _generate_key(environment: str) -> tuple[str, str, str]:
    """Generate an API key. Returns (plaintext, sha256_hash, prefix)."""
    prefix = "nc_test_" if environment == "test" else "nc_live_"
    raw = prefix + secrets.token_hex(16)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    key_prefix = raw[:16]
    return raw, key_hash, key_prefix


def _find_partner(name: str):
    """Look up partner by name. Exits with error if not found."""
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM partners WHERE name = ?", (name,)
    ).fetchone()
    conn.close()
    if not row:
        click.echo(f"Error: No partner named '{name}'.", err=True)
        sys.exit(1)
    return dict(row)


@partner_cli.command("create")
@click.option("--name", required=True, help="Partner company name.")
@click.option("--email", required=True, help="Primary technical contact email.")
@click.option("--quota", default=500, type=int, help="Monthly evaluation quota (default: 500).")
@click.option("--notes", default="", help="Internal notes.")
def create_partner(name, email, quota, notes):
    """Provision a new B2B partner with test and live API keys."""
    conn = _get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO partners (name, contact_email, monthly_quota, notes) "
            "VALUES (?, ?, ?, ?)",
            (name, email, quota, notes),
        )
        partner_id = cursor.lastrowid

        test_raw, test_hash, test_prefix = _generate_key("test")
        live_raw, live_hash, live_prefix = _generate_key("live")

        conn.execute(
            "INSERT INTO partner_api_keys (partner_id, key_hash, key_prefix, environment) "
            "VALUES (?, ?, ?, ?)",
            (partner_id, test_hash, test_prefix, "test"),
        )
        conn.execute(
            "INSERT INTO partner_api_keys (partner_id, key_hash, key_prefix, environment) "
            "VALUES (?, ?, ?, ?)",
            (partner_id, live_hash, live_prefix, "live"),
        )
        conn.commit()
    finally:
        conn.close()

    click.echo(f"Partner created: {name} (id={partner_id})")
    click.echo(f"Monthly quota: {quota}")
    click.echo(f"Test key: {test_raw}  (SAVE THIS — shown only once)")
    click.echo(f"Live key: {live_raw}  (SAVE THIS — shown only once)")


@partner_cli.command("list")
def list_partners():
    """Show all partners with status and quota."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT id, name, contact_email, status, monthly_quota, created_at "
        "FROM partners ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    if not rows:
        click.echo("No partners found.")
        return

    click.echo(f"{'ID':<5} {'Name':<30} {'Status':<12} {'Quota':<8} {'Email'}")
    click.echo("-" * 80)
    for r in rows:
        click.echo(
            f"{r['id']:<5} {r['name']:<30} {r['status']:<12} "
            f"{r['monthly_quota']:<8} {r['contact_email']}"
        )


@partner_cli.command("usage")
@click.option("--name", required=True, help="Partner name.")
@click.option("--month", default=None, help="Month (YYYY-MM). Defaults to current month.")
def show_usage(name, month):
    """Show usage summary for a partner."""
    from b2b.quota import _current_period
    partner = _find_partner(name)
    period = month or _current_period()

    conn = _get_db()
    row = conn.execute(
        "SELECT request_count FROM partner_quota_usage "
        "WHERE partner_id = ? AND period = ?",
        (partner["id"], period),
    ).fetchone()
    used = row["request_count"] if row else 0

    log_count = conn.execute(
        """SELECT COUNT(*) as cnt FROM partner_usage_log l
           JOIN partner_api_keys k ON k.id = l.key_id
           WHERE k.partner_id = ? AND l.created_at LIKE ?""",
        (partner["id"], f"{period}%"),
    ).fetchone()["cnt"]
    conn.close()

    click.echo(f"Partner: {name}")
    click.echo(f"Period: {period}")
    click.echo(f"Quota: {used} / {partner['monthly_quota']}")
    click.echo(f"Logged requests: {log_count}")


@partner_cli.command("suspend")
@click.option("--name", required=True, help="Partner name.")
def suspend_partner(name):
    """Suspend a partner account. All API calls will return 403."""
    partner = _find_partner(name)
    conn = _get_db()
    conn.execute("UPDATE partners SET status = 'suspended' WHERE id = ?", (partner["id"],))
    conn.commit()
    conn.close()
    click.echo(f"Partner '{name}' suspended.")


@partner_cli.command("reactivate")
@click.option("--name", required=True, help="Partner name.")
def reactivate_partner(name):
    """Reactivate a suspended partner account."""
    partner = _find_partner(name)
    conn = _get_db()
    conn.execute("UPDATE partners SET status = 'active' WHERE id = ?", (partner["id"],))
    conn.commit()
    conn.close()
    click.echo(f"Partner '{name}' reactivated to active.")


@partner_cli.command("show")
@click.option("--name", required=True, help="Partner name.")
def show_partner(name):
    """Show detailed info for a partner: keys, usage, notes."""
    partner = _find_partner(name)
    conn = _get_db()
    keys = conn.execute(
        "SELECT key_prefix, environment, revoked_at, created_at "
        "FROM partner_api_keys WHERE partner_id = ? ORDER BY created_at",
        (partner["id"],),
    ).fetchall()
    conn.close()

    click.echo(f"Partner: {partner['name']} (id={partner['id']})")
    click.echo(f"Status: {partner['status']}")
    click.echo(f"Email: {partner['contact_email']}")
    click.echo(f"Quota: {partner['monthly_quota']}/month")
    click.echo(f"Created: {partner['created_at']}")
    if partner.get("notes"):
        click.echo(f"Notes: {partner['notes']}")
    click.echo(f"\nAPI Keys ({len(keys)}):")
    for k in keys:
        status = "REVOKED" if k["revoked_at"] else "active"
        click.echo(f"  {k['key_prefix']}...  {k['environment']}  {status}  ({k['created_at']})")


@partner_cli.command("set-quota")
@click.option("--name", required=True, help="Partner name.")
@click.option("--quota", required=True, type=int, help="New monthly quota.")
def set_quota(name, quota):
    """Update a partner's monthly evaluation quota."""
    partner = _find_partner(name)
    conn = _get_db()
    conn.execute("UPDATE partners SET monthly_quota = ? WHERE id = ?", (quota, partner["id"]))
    conn.commit()
    conn.close()
    click.echo(f"Partner '{name}' quota updated to {quota}.")


@partner_cli.command("revoke-key")
@click.option("--prefix", required=True, help="Key prefix (e.g., nc_live_a1b2c3d4).")
def revoke_key(prefix):
    """Revoke an API key by its prefix."""
    from datetime import datetime, timezone
    conn = _get_db()
    now = datetime.now(timezone.utc).isoformat()
    result = conn.execute(
        "UPDATE partner_api_keys SET revoked_at = ? WHERE key_prefix = ? AND revoked_at IS NULL",
        (now, prefix),
    )
    conn.commit()
    conn.close()
    if result.rowcount:
        click.echo(f"Key {prefix}... revoked.")
    else:
        click.echo(f"No active key found with prefix {prefix}.", err=True)
        sys.exit(1)


@partner_cli.command("rotate-key")
@click.option("--prefix", required=True, help="Key prefix to rotate (e.g., nc_live_a1b2c3d4).")
def rotate_key(prefix):
    """Revoke an existing key and issue a new one for the same partner."""
    from datetime import datetime, timezone
    conn = _get_db()
    now = datetime.now(timezone.utc).isoformat()

    old_key = conn.execute(
        "SELECT id, partner_id, environment FROM partner_api_keys "
        "WHERE key_prefix = ? AND revoked_at IS NULL",
        (prefix,),
    ).fetchone()
    if not old_key:
        conn.close()
        click.echo(f"No active key found with prefix {prefix}.", err=True)
        sys.exit(1)

    # Revoke old key
    conn.execute("UPDATE partner_api_keys SET revoked_at = ? WHERE id = ?", (now, old_key["id"]))

    # Issue new key
    new_raw, new_hash, new_prefix = _generate_key(old_key["environment"])
    conn.execute(
        "INSERT INTO partner_api_keys (partner_id, key_hash, key_prefix, environment) "
        "VALUES (?, ?, ?, ?)",
        (old_key["partner_id"], new_hash, new_prefix, old_key["environment"]),
    )
    conn.commit()
    conn.close()

    click.echo(f"Old key {prefix}... revoked.")
    click.echo(f"New key: {new_raw}  (SAVE THIS — shown only once)")
```

- [ ] **Step 4: Register CLI in app.py**

In `app.py`, after the Blueprint registration, add:

```python
from b2b.cli import partner_cli
app.cli.add_command(partner_cli)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_b2b_cli.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add b2b/cli.py app.py tests/test_b2b_cli.py
git commit -m "feat(NES-341): add flask partner CLI commands for B2B management"
```

---

## Task 8: Rate Limiting with Flask-Limiter

**Files:**
- Modify: `b2b/__init__.py` (add Limiter)
- Modify: `b2b/routes.py` (add rate limit decorators)
- Modify: `app.py` (init limiter)

- [ ] **Step 1: Install Flask-Limiter**

Run: `pip install flask-limiter`

Check `requirements.txt` — add `flask-limiter` if not already present.

- [ ] **Step 2: Write failing test for rate limiting**

Add to `tests/test_b2b_routes.py`:

```python
class TestRateLimiting:
    def test_rate_limit_headers_present(self, client):
        pid = _create_partner()
        key, _ = _create_api_key(pid)
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St"},
            headers={"Authorization": f"Bearer {key}"},
        )
        # Rate limit headers should be present on any authenticated response
        assert "X-Quota-Limit" in resp.headers or resp.status_code in (202, 429)
```

- [ ] **Step 3: Add Flask-Limiter to b2b/__init__.py**

Update `b2b/__init__.py`:

```python
"""B2B API Blueprint for partner integrations."""

from flask import Blueprint
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

b2b_bp = Blueprint("b2b", __name__, url_prefix="/api/v1/b2b")

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=[],  # No default — apply per-route
)

from b2b import routes as _routes  # noqa: F401, E402
```

- [ ] **Step 4: Init limiter in app.py**

After Blueprint registration in `app.py`:

```python
from b2b import limiter as b2b_limiter
b2b_limiter.init_app(app)
```

- [ ] **Step 5: Add rate limit decorator + quota headers to routes**

In `b2b/routes.py`, add the `@limiter.limit()` decorator to the evaluate endpoint and add quota headers to responses via `@b2b_bp.after_request`:

```python
from flask import g
from flask_limiter.util import get_remote_address
from b2b import limiter

# On the evaluate function — @require_api_key MUST be outermost (runs first)
# so g.api_key is populated before limiter's key_func executes:
@b2b_bp.route("/evaluate", methods=["POST"])
@require_api_key
@limiter.limit("100/hour", key_func=lambda: str(g.api_key["id"]))
def evaluate():
    ...
```

Add an `after_request` hook to inject quota headers:

```python
@b2b_bp.after_request
def add_quota_headers(response):
    """Add quota information headers to every B2B response."""
    if hasattr(g, "partner"):
        _, used, limit = check_quota(g.partner["id"])
        response.headers["X-Quota-Limit"] = str(limit)
        response.headers["X-Quota-Used"] = str(used)
        response.headers["X-Quota-Reset"] = _next_month_start()
    return response
```

- [ ] **Step 6: Run all B2B tests**

Run: `python -m pytest tests/test_b2b_*.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add b2b/__init__.py b2b/routes.py app.py requirements.txt tests/test_b2b_routes.py
git commit -m "feat(NES-341): add Flask-Limiter rate limiting to B2B endpoints"
```

---

## Task 9: Full Integration Test + CI Update

**Files:**
- Modify: `tests/test_b2b_routes.py` (add end-to-end test)
- Modify: `.github/workflows/ci.yml` (add B2B tests to scoring-tests job)
- Modify: `Makefile` (add test-b2b target)

- [ ] **Step 1: Write end-to-end integration test**

Add to `tests/test_b2b_routes.py`:

```python
class TestEndToEnd:
    def test_full_lifecycle_create_poll_complete(self, client):
        """Simulate: create partner → create job → poll → complete → get result."""
        pid = _create_partner()
        key, _ = _create_api_key(pid)

        # Create evaluation
        resp = client.post(
            "/api/v1/b2b/evaluate",
            json={"address": "123 Main St, White Plains, NY 10601"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 202
        data = resp.get_json()
        job_id = data["job_id"]
        assert data["status"] == "queued"

        # Poll — should be queued
        resp = client.get(
            f"/api/v1/b2b/jobs/{job_id}",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "queued"

        # Simulate worker completing the job with a snapshot
        from models import save_snapshot, complete_job
        import json
        result_dict = {
            "address": "123 Main St, White Plains, NY 10601",
            "coordinates": {"lat": 41.033, "lng": -73.763},
            "composite_score": 7,
            "composite_band": "Strong",
            "data_confidence": "verified",
            "walk_scores": {"walk_score": 82},
            "tier2_scores": {
                "walkability": {"points": 8, "band": "Strong"},
            },
            "checks": [],
            "health_summary": {"clear": 12, "issues": 0, "warnings": 0},
        }
        snapshot_id = save_snapshot(
            address_input="123 Main St",
            address_norm="123 Main St, White Plains, NY 10601",
            result_dict=result_dict,
        )
        complete_job(job_id, snapshot_id)

        # Poll again — should be done with result
        resp = client.get(
            f"/api/v1/b2b/jobs/{job_id}",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "done"
        assert "result" in data
        assert data["result"]["composite_score"] == 7
        assert data["result"]["snapshot_id"] == snapshot_id
```

- [ ] **Step 2: Run all B2B tests**

Run: `python -m pytest tests/test_b2b_*.py -v`
Expected: ALL PASS

- [ ] **Step 3: Update Makefile**

Add a `test-b2b` target to the Makefile:

```makefile
test-b2b:
	python -m pytest tests/test_b2b_*.py -v
```

Update the existing `ci` target to include `test-b2b` while preserving all existing targets:
```makefile
ci: test-scoring test-b2b test-browser validate
```

- [ ] **Step 4: Update CI workflow**

In `.github/workflows/ci.yml`, add the B2B test files to the `scoring-tests` job's pytest command, or add them as a separate step in the same job.

- [ ] **Step 5: Update `_OLDEST_SCHEMA` in test_schema_migration.py**

Per CLAUDE.md: "New tables -> DO copy into `_OLDEST_SCHEMA`." Add the 4 new CREATE TABLE statements (`partners`, `partner_api_keys`, `partner_quota_usage`, `partner_usage_log`) to `_OLDEST_SCHEMA` in `tests/test_schema_migration.py`. This ensures the migration test covers these tables.

- [ ] **Step 6: Run make test-scoring to ensure no regressions**

Run: `make test-scoring`
Expected: ALL PASS (existing tests unaffected)

- [ ] **Step 7: Commit**

```bash
git add tests/test_b2b_routes.py tests/test_schema_migration.py Makefile .github/workflows/ci.yml
git commit -m "feat(NES-341): add B2B integration tests and CI configuration"
```

---

## Task 10: API Documentation

**Files:**
- Create: `docs/b2b-api-reference.md`

- [ ] **Step 1: Write the partner-facing API reference document**

Create `docs/b2b-api-reference.md` covering:

1. Overview — what NestCheck evaluates, coverage area
2. Authentication — key format, Bearer header, test vs. live
3. Quick Start — curl examples for create + poll
4. POST /api/v1/b2b/evaluate — full request/response spec
5. GET /api/v1/b2b/jobs/{job_id} — full response spec per status
6. Response Schema — field-by-field reference
7. Health Checks Reference — all check names and meanings
8. Dimension Scores — what each measures, 0-10 bands
9. Error Handling — all error codes, rate limits, quota
10. Sandbox Testing — test addresses, expected behavior
11. Best Practices — polling intervals (2s), caching, attribution

Use the existing draft at `docs/b2b-api-spec.md` as a starting point but restructure for the partner audience (not internal design doc).

- [ ] **Step 2: Commit**

```bash
git add docs/b2b-api-reference.md
git commit -m "docs(NES-341): add partner-facing B2B API reference"
```

---

## Summary

| Task | What it builds | Files created/modified |
|------|---------------|----------------------|
| 1 | Database tables + migration | models.py, conftest.py |
| 2 | Auth decorator + Blueprint | b2b/__init__.py, b2b/auth.py, b2b/routes.py (stub), app.py |
| 3 | Quota enforcement | b2b/quota.py |
| 4 | Response schema | b2b/schema.py |
| 5 | Sandbox replay | b2b/sandbox.py |
| 6 | API endpoints (full) | b2b/routes.py, models.py |
| 7 | CLI commands | b2b/cli.py, app.py |
| 8 | Rate limiting | b2b/__init__.py, b2b/routes.py, app.py |
| 9 | Integration tests + CI | tests, Makefile, ci.yml |
| 10 | API documentation | docs/b2b-api-reference.md |
