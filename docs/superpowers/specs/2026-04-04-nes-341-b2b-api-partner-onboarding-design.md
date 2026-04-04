# NES-341: B2B Licensing — API Spec & Partner Onboarding Design

**Status:** Approved
**Date:** 2026-04-04
**Ticket:** NES-341

## Overview

Design for NestCheck's B2B API and partner onboarding system. Partners (relocation companies, corporate HR, insurers, home inspectors) integrate via a REST API to run property evaluations programmatically. v1 is intentionally manual — no partner portal, no billing automation, no webhooks.

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Sandbox strategy | Snapshot replay | Zero API cost, deterministic, real-looking data |
| Onboarding model | Fully manual v1 | No portal — CLI provisioning, manual NDA, manual invoicing |
| Billing | Manual invoicing + usage logging | No billing automation; measure first, price later |
| Result delivery | Polling only | Reuses existing job queue; webhooks deferred |
| Response schema | Curated B2B subset | Decouples API contract from internal representation |
| Auth model | One test + one live key per partner | `nc_test_` / `nc_live_` prefix convention |
| Versioning | URL path (`/api/v1/`), no breaking changes for 12 months | Don't over-engineer versioning before v2 exists |
| Geographic scope | Same as consumer | 422 for out-of-coverage addresses |
| Architecture | Flask Blueprint in `b2b/` package | Keeps `app.py` from growing; self-contained B2B concerns |

---

## 1. Database Schema

Four new tables in `models.py`, following existing migration patterns (PRAGMA table_info -> ALTER TABLE if missing).

### `partners`

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| name | TEXT NOT NULL | Company name (e.g., "Cartus Relocation") |
| contact_email | TEXT NOT NULL | Primary technical contact |
| status | TEXT NOT NULL | `active`, `suspended`, `revoked` |
| monthly_quota | INTEGER NOT NULL | Default 500 |
| notes | TEXT | Internal notes (NDA date, agreement details) |
| created_at | TIMESTAMP | Default CURRENT_TIMESTAMP |

### `partner_api_keys`

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| partner_id | INTEGER FK | References partners.id |
| key_hash | TEXT NOT NULL UNIQUE | SHA-256 of full key |
| key_prefix | TEXT NOT NULL | Prefix + first 8 hex chars, 16 chars total (e.g., `nc_live_a1b2c3d4`) for log identification |
| environment | TEXT NOT NULL | `test` or `live` |
| revoked_at | TIMESTAMP | NULL = active |
| created_at | TIMESTAMP | Default CURRENT_TIMESTAMP |

### `partner_quota_usage`

Counter table for O(1) quota checks. Avoids scanning usage_log on every request.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| partner_id | INTEGER FK | References partners.id |
| period | TEXT NOT NULL | Year-month string, e.g., `"2026-04"` |
| request_count | INTEGER NOT NULL | Default 0 |
| UNIQUE(partner_id, period) | | |

Quota check: `UPDATE SET request_count = request_count + 1 WHERE partner_id = ? AND period = ?`. If zero rows affected, INSERT. Single-row lookup, O(1) forever.

### `partner_usage_log`

Detailed log for analytics and debugging. NOT used for quota enforcement.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| key_id | INTEGER FK | References partner_api_keys.id |
| address | TEXT NOT NULL | Requested address |
| snapshot_id | INTEGER | FK to snapshots.id, NULL for failed requests |
| status_code | INTEGER NOT NULL | HTTP response code |
| response_time_ms | INTEGER | End-to-end latency |
| api_cost_cents | INTEGER | Google Maps cost, nullable/best-effort from nc_trace |
| created_at | TIMESTAMP | Default CURRENT_TIMESTAMP |

Index: `partner_usage_log(key_id, created_at)` for monthly usage queries.

### Existing table migration: `evaluation_jobs`

Add `partner_id` column for B2B job ownership enforcement:
```sql
ALTER TABLE evaluation_jobs ADD COLUMN partner_id INTEGER
```
Follow existing PRAGMA table_info pattern. NULL for consumer-initiated jobs; populated for B2B API jobs. Enables `GET /api/v1/b2b/jobs/{id}` to verify the requesting partner owns the job.

### SQLite concurrency note

Quota increment uses SQLite upsert to avoid race conditions between gunicorn workers:
```sql
INSERT INTO partner_quota_usage (partner_id, period, request_count)
VALUES (?, ?, 1)
ON CONFLICT(partner_id, period) DO UPDATE SET request_count = request_count + 1
```

---

## 2. Blueprint Structure

```
b2b/
├── __init__.py          # Flask Blueprint registration
├── auth.py              # API key validation decorator
├── routes.py            # /api/v1/b2b/evaluate, /api/v1/b2b/jobs/<id>
├── schema.py            # Curated response builder (subset of result_to_dict)
├── quota.py             # Rate limiting + quota enforcement
└── cli.py               # flask partner create/revoke/list/usage commands
```

Blueprint registered in `app.py`:
```python
from b2b import b2b_bp
app.register_blueprint(b2b_bp)
```

Blueprint defined in `b2b/__init__.py`:
```python
from flask import Blueprint
b2b_bp = Blueprint('b2b', __name__, url_prefix='/api/v1/b2b')
```

**URL prefix is `/api/v1/b2b/`** (not bare `/api/v1/`) to avoid prefix overlap with existing routes like `/api/v1/widget-data/<id>` in `app.py`. This ensures the Blueprint's `before_request` hooks (auth, rate limiting) never intercept consumer API routes.

File structure includes `sandbox.py` for sandbox dispatch logic (kept separate from `schema.py` response transformation):
```
b2b/
├── __init__.py          # Flask Blueprint registration
├── auth.py              # API key validation decorator
├── routes.py            # /api/v1/b2b/evaluate, /api/v1/b2b/jobs/<id>
├── schema.py            # Curated response builder (subset of result_to_dict)
├── sandbox.py           # Sandbox address mapping + snapshot replay
├── quota.py             # Rate limiting + quota enforcement
└── cli.py               # flask partner create/revoke/list/usage commands
```

---

## 3. Authentication (`b2b/auth.py`)

### API Key Format

- Test keys: `nc_test_<32 hex chars>` (e.g., `nc_test_a1b2c3d4e5f6...`)
- Live keys: `nc_live_<32 hex chars>`
- Generated via `secrets.token_hex(16)` prefixed with `nc_test_` or `nc_live_`
- Stored as SHA-256 hash; plaintext shown only once at provisioning

### `@require_api_key` Decorator

1. Extract `Authorization: Bearer nc_live_...` header
2. SHA-256 hash the token
3. Look up `partner_api_keys WHERE key_hash = ? AND revoked_at IS NULL`
4. Join to `partners WHERE status = 'active'`
5. If valid: attach `g.partner` and `g.api_key` to Flask request context
6. If invalid/missing/revoked/suspended: return 401 JSON error
7. Test keys (`nc_test_`) route to sandbox snapshot replay
8. Live keys (`nc_live_`) route to real evaluation

---

## 4. Rate Limiting & Quota (`b2b/quota.py`)

### Flask-Limiter initialization

Instantiate `Limiter` in `b2b/__init__.py`:
```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,  # default fallback for unauthenticated requests
    storage_uri="memory://",       # acceptable for single-process Railway deployment; resets on deploy
)
```
Call `limiter.init_app(app)` from `app.py` after Blueprint registration.

### Two-tier limiting

1. **Burst rate limit**: 100 requests/hour via Flask-Limiter
   - **Pre-auth (brute-force protection):** Keyed by IP via default `get_remote_address`. Applies to all B2B routes including invalid auth attempts.
   - **Post-auth (per-partner):** Individual route decorators use `key_func=lambda: str(g.api_key.id)` to limit per API key, not per IP. Partners behind load balancers get correct limits.
   - IMPORTANT: Flask-Limiter 4.x — use `@limiter.request_filter` decorator, NOT constructor argument (NES-58 lesson)
2. **Monthly quota**: Checked against `partner_quota_usage` counter table post-auth, enforced per `partners.monthly_quota`. This is application-level logic in the `@require_api_key` decorator, not Flask-Limiter.

### Response headers (every request)

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1712260800
X-Quota-Limit: 500
X-Quota-Used: 123
X-Quota-Reset: 2026-05-01
```

### 429 response

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Hourly rate limit of 100 requests exceeded. Resets in 1423 seconds.",
    "type": "rate_limit"
  }
}
```

Separate error code for quota: `quota_exceeded` with monthly reset date.

---

## 5. API Endpoints (`b2b/routes.py`)

### `POST /api/v1/b2b/evaluate`

**Auth:** `@require_api_key` (live keys only)

**Request:**
```json
{
  "address": "123 Main St, White Plains, NY 10601",
  "place_id": "ChIJ..."  // optional, skips geocoding if provided
}
```

**Response (202 Accepted):**
```json
{
  "job_id": "uuid",
  "status": "queued",
  "poll_url": "/api/v1/b2b/jobs/<job_id>"
}
```

**Behavior:**
- Validates address is within coverage area (422 if not)
- Increments `partner_quota_usage` counter (upsert pattern)
- Creates job via existing `models.py` job queue
- Passes `place_id` (if provided) to `create_job()` to skip redundant geocoding
- Tags job with `partner_id` for ownership enforcement (new column on `evaluation_jobs`)
- Logs to `partner_usage_log` (snapshot_id populated on completion)

### `GET /api/v1/b2b/jobs/{job_id}`

**Auth:** `@require_api_key` (same partner must own the job)

**Response (running):**
```json
{
  "job_id": "...",
  "status": "running",
  "stage": "Analyzing transit access..."
}
```

**Response (complete):**
```json
{
  "job_id": "...",
  "status": "done",
  "result": {
    "address": "123 Main St, White Plains, NY 10601",
    "coordinates": {"lat": 41.033, "lng": -73.763},
    "composite_score": 7,
    "composite_band": "Strong",
    "health": {
      "checks": [
        {
          "name": "Gas Station Proximity",
          "status": "pass",
          "distance_ft": 2150,
          "description": "No gas stations within 1,500 ft"
        }
      ],
      "clear_count": 12,
      "issue_count": 1,
      "warning_count": 0
    },
    "dimensions": {
      "walkability": {"score": 8, "band": "Strong", "walk_score": 82},
      "green_space": {"score": 7, "band": "Strong"},
      "transit": {"score": 6, "band": "Moderate"},
      "third_place": {"score": 8, "band": "Strong"},
      "fitness": {"score": 5, "band": "Moderate"},
      "provisioning": {"score": 7, "band": "Strong"}
    },
    "data_confidence": "verified",
    "snapshot_id": "a1b2c3d4e5f6",
    "snapshot_url": "https://nestcheck.com/s/abc123",
    "evaluated_at": "2026-04-04T14:30:00Z"
  }
}
```

**Response (failed):**
```json
{
  "job_id": "...",
  "status": "failed",
  "error": "Evaluation could not be completed for this address."
}
```
Error messages use `_sanitize_error()` — never expose raw exceptions.

### `POST /api/v1/b2b/evaluate` (test keys — sandbox)

Same request interface. Returns immediately (no job queue).

- Matches requested address against pre-computed sandbox snapshot set
- If no exact match, returns the closest sandbox snapshot with a note
- Response includes `"sandbox": true` flag at top level
- Does NOT increment quota counter
- Does NOT log to usage_log (or logs with a `sandbox` flag)

### Error Response Format (all endpoints)

```json
{
  "error": {
    "code": "error_code_here",
    "message": "Human-readable explanation.",
    "type": "error_category"
  }
}
```

**Error codes:**

| Code | HTTP | When |
|------|------|------|
| `unauthorized` | 401 | Missing, invalid, or revoked API key |
| `suspended` | 403 | Partner account suspended |
| `invalid_request` | 400 | Malformed request body |
| `address_not_in_coverage` | 422 | Address outside supported geography |
| `rate_limit_exceeded` | 429 | Hourly burst limit hit |
| `quota_exceeded` | 429 | Monthly quota exhausted |
| `not_found` | 404 | Job ID not found or not owned by this partner |
| `evaluation_failed` | 500 | Evaluation engine error (sanitized) |
| `internal_error` | 500 | Unexpected server error (sanitized) |

---

## 6. Curated Response Schema (`b2b/schema.py`)

`build_b2b_response(snapshot_result: dict) -> dict`

Receives the already-serialized dict (output of `result_to_dict()` called from the route handler). Does NOT import `result_to_dict` directly — avoids circular imports with `app.py`.

### Included

- Composite score (integer 0-10) + band label
- All dimension scores + bands: walkability, green_space, transit, third_place, fitness, provisioning
- Health checks: name, status (pass/warning/fail), distance_ft, description
- Health summary: clear_count, issue_count, warning_count
- Key metrics: walk_score, transit_score, bike_score (from Walk Score API)
- Coordinates (lat/lng), formatted address
- Snapshot ID + public URL (partners can link users to full consumer report)
- `evaluated_at` ISO 8601 timestamp
- `data_confidence`: `verified`, `estimated`, or `limited`

### Excluded

- Raw venue lists (individual coffee shops, gyms, parks with coordinates)
- Scoring intermediaries (quality ceiling inputs, piecewise curve values, raw piecewise scores)
- Presentation metadata (icon names, CSS classes, display captions, band colors)
- Trace/debug data (API call timings, cache hit rates)
- EJScreen raw percentiles (health checks surface as pass/fail, not raw numbers)
- Internal IDs, worker metadata, job queue internals

### Stability guarantee

The B2B response schema is the API contract. Internal refactors to `result_to_dict()`, scoring, or presentation logic must NOT change the B2B schema without a versioned migration. `schema.py` is the translation layer that absorbs internal changes.

---

## 7. Sandbox Implementation

### Sandbox Address Set

Pre-compute evaluations for 10-15 addresses spanning the coverage area and evaluation outcomes:

- 3-4 Westchester addresses (mix of scores: strong, moderate, limited)
- 3-4 DMV addresses (DC, MD, VA — one each minimum)
- 2-3 addresses with health concerns (near gas station, flood zone, highway)
- 1-2 addresses with suppressed dimensions (limited data)
- 1 address that would be out-of-coverage (for testing error handling)

Store snapshot IDs in a `SANDBOX_ADDRESSES` dict in `b2b/sandbox.py`:
```python
SANDBOX_ADDRESSES = {
    "10 Main Street, White Plains, NY 10601": "snapshot_id_1",
    "1600 Pennsylvania Ave NW, Washington, DC 20500": "snapshot_id_2",
    ...
}
```

### Sandbox matching

1. Normalize input address (lowercase, strip whitespace)
2. Exact match against `SANDBOX_ADDRESSES` keys
3. If no match, return a default sandbox snapshot with `"sandbox_note": "No exact match for this address. Returning sample evaluation data for integration testing."`

---

## 8. Partner Onboarding Flow

### Step 1: Inquiry
Partner contacts NestCheck (email or future web form). Manual triage by team.

### Step 2: Qualification
Verify partner is in an aligned category per PRD:
- **Approved:** Relocation companies (Cartus, SIRVA, Graebel), corporate HR departments, home insurers, home inspection firms
- **Rejected:** MLS platforms, brokerages, listing aggregators (misaligned incentives per PRD)

### Step 3: Agreement
NDA + licensing agreement signed offline (DocuSign or equivalent). Terms include:
- Usage limits and overage policy
- Data usage restrictions: no resale, no public scraping, no redistribution
- Attribution requirements (link to NestCheck when displaying scores)
- Termination and data deletion provisions

### Step 4: Provisioning
```bash
flask partner create --name "Cartus Relocation" --email "tech@cartus.com" --quota 500
```
Output:
```
Partner created: Cartus Relocation (id=1)
Test key: nc_test_a1b2c3d4e5f6789012345678abcdef01  (SAVE THIS — shown only once)
Live key: nc_live_f0e1d2c3b4a5968778695a4b3c2d1e0f  (SAVE THIS — shown only once)
Monthly quota: 500 evaluations
```
Keys stored as SHA-256 hashes. Plaintext never recoverable.

### Step 5: Sandbox Integration
Partner integrates against `nc_test_` key. We provide:
- List of sandbox test addresses with expected response shapes
- Sample code snippets (Python, curl, JavaScript)
- Integration checklist: auth works, polling works, error handling works

### Step 6: Go Live
Partner confirms sandbox integration, switches to `nc_live_` key. Team monitors `partner_usage_log` for the first week — watch for error rates, unexpected addresses, unusual patterns.

### Step 7: Ongoing
- Monthly usage email (SQL query -> formatted summary)
- Monthly invoice (manual, based on usage)
- Quarterly check-in call
- Key rotation on request via CLI

---

## 9. CLI Commands (`b2b/cli.py`)

All commands registered under `flask partner`:

| Command | Description |
|---------|-------------|
| `flask partner create --name "X" --email "Y" --quota 500` | Provision partner + test/live keys |
| `flask partner list` | Show all partners with status, quota, current usage |
| `flask partner show --name "X"` | Detail view: keys, usage history, notes |
| `flask partner usage --name "X" --month 2026-04` | Monthly usage summary with top addresses |
| `flask partner revoke-key --prefix nc_live_a1b2c3d4` | Revoke a specific key |
| `flask partner rotate-key --prefix nc_live_a1b2c3d4` | Revoke old key, issue new one, print new plaintext |
| `flask partner suspend --name "X"` | Set status to `suspended`, all API calls return 403 |
| `flask partner reactivate --name "X"` | Restore status to `active` |
| `flask partner set-quota --name "X" --quota 1000` | Update monthly quota |

---

## 10. API Documentation Structure

Publishable markdown document for partners. Sections:

1. **Overview** — What NestCheck evaluates, coverage area, data sources at a high level
2. **Authentication** — API key format, test vs. live environments, header format
3. **Quick Start** — curl example: create evaluation, poll for result, parse response
4. **Endpoints Reference** — POST /evaluate, GET /jobs/{id} with full request/response specs
5. **Response Schema** — Field-by-field reference for the curated response object
6. **Health Checks Reference** — All possible check names, what they detect, severity levels
7. **Dimension Scores Reference** — What each dimension measures, 0-10 scale, band labels and thresholds
8. **Error Handling** — Error codes, rate limits, quota behavior, retry guidance
9. **Sandbox Testing** — Test addresses, expected responses, integration checklist
10. **Best Practices** — Recommended polling intervals (2s), caching guidance, attribution requirements
11. **Changelog** — Versioned list of API changes (starts empty)

---

## 11. Existing Endpoint Conflicts

The codebase already has `/api/snapshot/<id>/json` and `/api/v1/widget-data/<id>`. The new B2B endpoints live under `/api/v1/b2b/evaluate` and `/api/v1/b2b/jobs/<id>` — no URL conflicts. The Blueprint's `url_prefix='/api/v1/b2b'` isolates B2B routes from existing consumer API routes, ensuring Blueprint-level `before_request` hooks (auth, rate limiting) never intercept consumer traffic.

**Check before implementation:** Grep `@app.route` for any existing `/api/v1/b2b/evaluate` or `/api/v1/b2b/jobs` to confirm no conflicts (per CLAUDE.md: "Duplicate Flask route URLs shadow silently").

---

## 12. Cost Tracking (Best-Effort)

Per CTO guidance, `api_cost_cents` in `partner_usage_log` is populated best-effort from `nc_trace.py` data:

- `nc_trace.TraceContext` already records API calls with endpoint names
- After evaluation completes, tally Google Maps API costs from the trace:
  - Geocoding: $5/1000 = $0.005/call
  - Places Nearby: $32/1000 = $0.032/call
  - Text Search: $32/1000 = $0.032/call
  - Distance Matrix: $5/1000 per element = $0.005/element
- Store total as integer cents (rounded up)
- NULL when trace data unavailable or calculation fails
- This data informs pricing decisions — not exposed to partners

---

## 13. Security Considerations

- API keys are SHA-256 hashed at rest; plaintext shown only once at provisioning
- `_sanitize_error()` for all error messages — no stack traces, no internal paths
- Partner can only poll their own jobs (ownership check on job_id)
- Rate limiting prevents brute-force key guessing (100 req/hour + 429 on invalid auth)
- Test keys cannot trigger real evaluations (sandbox only)
- Coverage validation before queuing prevents wasted API spend on unsupported addresses
- No PII in usage logs beyond the requested address (which is public data)
