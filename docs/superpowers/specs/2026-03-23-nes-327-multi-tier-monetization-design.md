# NES-327: Multi-Tier Monetization Design

## Overview

Transform NestCheck's flat $9 payment model into a three-tier monetization system: free health-only evaluations, single-report purchases, and a monthly subscription for active home searchers. Includes a B2B licensing spec document (no implementation).

**Linear:** [NES-327](https://linear.app/nestcheck/issue/NES-327/multi-tier-monetization-free-health-only-subscription-b2b-path)

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Free tier content | Show dimension scores, gate detail | Score alone is provocative but not actionable — maximizes upsell trigger |
| Subscription price | $39/mo | Middle of PRD range; breakpoint at ~3 single reports creates clear value |
| Post-expiry access | Retain access to reports generated during subscription | Reduces churn anxiety; snapshots are point-in-time data that loses value anyway |
| Free tier cap | 10 evals per email per rolling 30-day window | Protects API costs (~$0.15–0.25/eval) while being invisible to legitimate users |
| Subscription duration | Monthly recurring only, cancel-anytime | Simpler than 30/60/90 day options; industry standard |
| Architecture | Thin flag in route handler (Approach A) | Follows existing patterns; no middleware/decorator abstraction needed |
| Tier names (CMO) | Health Check / Full Evaluation / Active Search | Reflects user journey, not billing structure |

## Section 1: Free Tier Rework

### Schema

Keep `free_tier_usage` table with `email_hash` as PRIMARY KEY. Add two columns via idempotent migration in `init_db()`:

```sql
ALTER TABLE free_tier_usage ADD COLUMN eval_count INTEGER DEFAULT 1;
ALTER TABLE free_tier_usage ADD COLUMN window_start TEXT;
```

Backfill existing rows:
```sql
UPDATE free_tier_usage SET eval_count = 1, window_start = created_at WHERE eval_count IS NULL;
```

### Two Independent Gates

**1. Job creation gate (`POST /`):** `check_free_tier_available(email_hash)` reads the single row. If `window_start` > 30 days old, reset count. If `eval_count < 10`, allow. Over cap → 402. Paid jobs (with `payment_token`) skip this check entirely and don't increment the counter.

**2. View gate (`view_snapshot()`):** `is_full_access` flag determines what renders. Free-tier snapshots show health-only. Independent of the cap — users can always view their existing reports.

### Atomic Upsert for `record_free_tier_usage()`

The counter model tracks evals per email, not per job. The `job_id` and `snapshot_id` columns are dropped from the upsert — they no longer make sense as single values on a counter row.

```sql
INSERT INTO free_tier_usage (email_hash, email_raw, created_at, eval_count, window_start)
VALUES (?, ?, ?, 1, datetime('now'))
ON CONFLICT(email_hash) DO UPDATE SET
  eval_count = CASE
    WHEN window_start < datetime('now', '-30 days') THEN 1
    ELSE eval_count + 1
  END,
  window_start = CASE
    WHEN window_start < datetime('now', '-30 days') THEN datetime('now')
    ELSE window_start
  END
```

Single atomic statement, no TOCTOU race.

### Reissue Flow (`delete_free_tier_usage`)

The existing `delete_free_tier_usage(job_id)` deletes the row when a job fails. Under the counter model, deleting the row would reset the entire counter. Replace with a decrement: `UPDATE free_tier_usage SET eval_count = MAX(0, eval_count - 1) WHERE email_hash = ?`. The function signature changes from `(job_id)` to `(email_hash)`.

### `update_free_tier_snapshot()` Removal

This function backfills `snapshot_id` onto the free tier row. With the counter model, the single `snapshot_id` column is no longer meaningful. Remove `update_free_tier_snapshot()` and its call site. The `snapshot_id` and `job_id` columns remain in the table (no DROP COLUMN in SQLite) but are no longer written to.

### Cached Snapshot Bypass

The existing `is_snapshot_fresh()` check in `POST /` short-circuits before `record_free_tier_usage()`. This behavior is preserved — cached results do not increment `eval_count`.

## Section 2: Content Gating (Presentation Layer)

### Access Resolution

`_check_full_access(snapshot_id, user_email=None) -> bool`, checked in priority order:

1. `g.is_builder` → `True`
2. `REQUIRE_PAYMENT` is `False` → `True`
3. Payment for this snapshot via job join:
   ```sql
   SELECT 1 FROM payments p JOIN evaluation_jobs j ON p.job_id = j.job_id
   WHERE j.snapshot_id = ? AND p.status = 'redeemed'
   ```
   → `True`
4. If `user_email` is not None — active subscription:
   ```sql
   SELECT 1 FROM subscriptions
   WHERE user_email = ? AND status IN ('active', 'canceled')
   AND period_end > datetime('now')
   ```
   → `True`
5. If `user_email` is not None — past subscription covering this snapshot:
   ```sql
   SELECT 1 FROM subscriptions s
   JOIN snapshots snap ON snap.snapshot_id = ?
   WHERE s.user_email = ?
   AND snap.evaluated_at BETWEEN s.period_start AND s.period_end
   ```
   → `True`
6. Otherwise → `False`

**Email sourcing:** `user_email = current_user.email if current_user.is_authenticated else None`. The email MUST come from the authenticated session, never from a request parameter — an attacker submitting someone else's email could gain subscription access.

Add index on `evaluation_jobs.snapshot_id` if missing.

### Server-Side Gating

Content gating runs AFTER `_prepare_snapshot_for_display()` (the canonical migration pipeline), since it depends on the fully-migrated result dict.

When `is_full_access = False`, strip gated data from the result dict before passing to template:

```python
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

### Template Gating

`{% if is_full_access %}` blocks control layout. The `{% else %}` branch renders a blurred placeholder CTA with static placeholder text (not real data):

```html
<div class="gated-section">
    <div class="gated-section__blur" aria-hidden="true">...</div>
    <div class="gated-section__cta">
        <p>Unlock the full evaluation</p>
        <a href="/pricing">See full report</a>
    </div>
</div>
```

CSS: `.gated-section__blur { filter: blur(6px); pointer-events: none; user-select: none; }`

### What's Always Visible (Free)

- Composite score + band
- Narrative verdict
- Health checks (Tier 1 + Tier 2 with full detail)
- Dimension scores grid (names + points + band labels only)

### What's Gated

- Dimension detail (venue lists, walk times, subscores, summary text)
- Parks & Green Space detail
- Getting Around detail
- Area Context (schools, demographics, data sources)
- Sidebar walkability snapshot

## Section 3: Single Report Purchase

### One Checkout Route with `tier` Param

`POST /checkout/create` accepts:
- `email` (required)
- `snapshot_id` (optional — for unlocking existing report)
- `tier` (optional — `single` default, `subscription`)

**Unlocking existing report** (`snapshot_id` provided): Payment row gets `snapshot_id` immediately. Success URL → `/s/<snapshot_id>?payment_token={payment_id}`. Redemption happens in `view_snapshot()`.

**Over-cap upfront purchase** (`snapshot_id` omitted): Payment row has no `snapshot_id` yet. Success URL → `/?payment_token={payment_id}&email=...`. Redemption happens in `POST /`, same as today.

### Worker Backfills `payments.snapshot_id`

After `complete_job()` and `save_snapshot()` in `worker.py`:
```python
# UPDATE payments SET snapshot_id = ? WHERE job_id = ? AND snapshot_id IS NULL
update_payment_snapshot_id(snapshot_id, job_id)
```

Closes the gap for legacy payments and new over-cap purchases. Column already exists — no migration.

### Free Tier Credit Guard

Paid evaluations do NOT increment `eval_count`. Existing guard: `if not _payment_id_for_job and not g.is_builder and email: record_free_tier_usage(...)`. Add explicit test: user at 10/10 pays → evaluation runs → `eval_count` stays at 10.

### Price

Keep configurable via `_STRIPE_PRICE_ID` env var. No code change needed to test $12–15.

## Section 4: Search Subscription ($39/mo)

### `subscriptions` Table

```sql
CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    stripe_subscription_id TEXT UNIQUE,
    stripe_customer_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_email ON subscriptions(user_email);
```

### Status Machine

```
active (created/renewed)
  ↓ (user cancels — cancel_at_period_end=true)
canceled (still has access until period_end, no renewal)
  ↓ (period_end reached)
expired
```

`canceled` means "won't renew but still has access until `period_end`."

### Stripe Webhook Additions

Add to existing `/webhook/stripe` handler:
- `customer.subscription.created` → insert row, status `active`
- `customer.subscription.updated` → update status/period (handles renewals, cancellations)
- `customer.subscription.deleted` → status = `expired`

**Customer-to-email lookup chain:** Webhook provides `customer` ID → look up `stripe_customer_id` in `users` table → get `email`. If customer not found in DB, look up via `stripe.Customer.retrieve(customer_id)` to get `email` directly. If neither resolves, log warning and skip — don't create orphaned subscription rows.

### Subscription Checkout

`POST /checkout/create` with `tier=subscription`:
- Stripe session with `mode='subscription'`
- Price = `_STRIPE_SUBSCRIPTION_PRICE_ID` env var (`price_1TEB5E2Epwo6ud7NZ9dEhFAT`)
- Success URL → `/my-reports?subscription=active`
- Reuses `_get_or_create_stripe_customer()`

### Report Retention After Expiry

No junction table. Timestamp comparison in `_check_full_access()`:
```sql
SELECT 1 FROM subscriptions s
JOIN snapshots snap ON snap.snapshot_id = ?
WHERE s.user_email = ?
AND snap.evaluated_at BETWEEN s.period_start AND s.period_end
```

Zero new tables, zero worker changes, zero new write paths.

### Subscription Users Skip Free Tier Gate

In `POST /`, `is_subscription_active(email)` → skip `check_free_tier_available()` and skip `record_free_tier_usage()`.

## Section 5: Pricing Page

### Positioning

"NestCheck evaluates what you can't renovate — the location."

### Tiers

| | Health Check (Free) | Full Evaluation ($9) | Active Search ($39/mo) |
|---|---|---|---|
| **Headline** | "Is this address safe to live at?" | "Everything about this location" | "Evaluate every address on your list" |
| **Features** | Environmental health screening, Hazard proximity analysis, Overall livability score, Up to 10 addresses/month | All health checks plus: Nearby cafes, groceries, gyms with walk times, Park and green space access, Transit and walkability detail, School district context | Unlimited full evaluations, Perfect for your 3–6 month home search, Cancel anytime |
| **CTA** | "Check an address" → `/` | "Evaluate an address" → `/` | "Start searching" → Stripe |

### Email Collection on Subscribe CTA

- Logged in: hidden input pre-filled with `current_user.email`, CTA submits directly
- Not logged in: inline email input field, then submits to `POST /checkout/create` with `tier=subscription`

**Trust boundary note:** For non-logged-in subscription checkout, the user-supplied email becomes `user_email` in the `subscriptions` table. Stripe sends a receipt to this email, providing implicit verification. The subscription grants access to reports created *during* the subscription for that email — if a user provides someone else's email, they pay for someone else's access. This is a self-limiting abuse vector (attacker pays $39/mo to give someone else free reports). No additional email verification required for V1.

### Technical

Update `templates/pricing.html`. Reuse `pricing.css` monochrome sub-palette.

**Price display:** Hardcode "$9" and "$39/mo" in the template for V1. If price testing ($12–15) happens via `_STRIPE_PRICE_ID` swap, update the template copy in the same commit. A dynamic price-from-Stripe approach is over-engineered at current scale.

## Section 6: B2B Licensing (Spec Document Only)

**No code implementation.** Output is `docs/b2b-api-spec.md`.

### API Contract

```
POST /api/v1/evaluate
Authorization: Bearer <api_key>
Content-Type: application/json

{"address": "123 Main St, White Plains, NY 10601", "place_id": "ChIJ..."}

Response: result_to_dict() output shape
```

Rate limits: 100 requests/hour per API key. Authentication via API key in `partner_api_keys` table.

### Aligned Partners

- Relocation companies (Cartus, SIRVA)
- Corporate HR — employee relocation packages
- Home insurers — underwriting enrichment
- Home inspection firms — pre-inspection environmental screening

### Partner Onboarding Flow

1. Partner inquiry → 2. NDA + licensing agreement → 3. API key provisioned → 4. Sandbox testing → 5. Production access

## Section 7: Migration & Backward Compatibility

### Existing Data

- Paid snapshots (`payment_status = 'redeemed'`) retain full access via payments join — zero regression
- Existing `free_tier_usage` rows backfilled with `eval_count = 1, window_start = created_at`
- Users who used their one free eval can now run 9 more (within 30 days)

### `REQUIRE_PAYMENT` Env Var

- `false`: `_check_full_access()` returns `True` for all snapshots (dev mode unchanged)
- `true`: content gating applies

### New Env Vars

- `STRIPE_SUBSCRIPTION_PRICE_ID` — Stripe Price ID for $39/mo subscription

### Database Migrations (all idempotent in `init_db()`)

```sql
ALTER TABLE free_tier_usage ADD COLUMN eval_count INTEGER DEFAULT 1;
ALTER TABLE free_tier_usage ADD COLUMN window_start TEXT;
CREATE TABLE IF NOT EXISTS subscriptions (...);
CREATE INDEX IF NOT EXISTS idx_subscriptions_email ON subscriptions(user_email);
UPDATE free_tier_usage SET eval_count = 1, window_start = created_at WHERE eval_count IS NULL;
```

### Worker Change

One line after `save_snapshot()`: `UPDATE payments SET snapshot_id = ? WHERE job_id = ? AND snapshot_id IS NULL`

### No Changes To

- `result_to_dict()`, `evaluate_property()`, export routes, compare route
- Payment state machine, `redeem_payment()`, CAS guards
- Webhook signature verification

## Files Affected

| File | Changes |
|------|---------|
| `models.py` | `subscriptions` table DDL, `free_tier_usage` migration, subscription CRUD functions |
| `app.py` | `_check_full_access()`, updated `view_snapshot()`, updated `POST /`, updated `POST /checkout/create`, new webhook events |
| `worker.py` | One-line `payments.snapshot_id` backfill after `save_snapshot()` |
| `templates/_result_sections.html` | `{% if is_full_access %}` gating blocks |
| `templates/pricing.html` | Three-tier redesign |
| `templates/snapshot.html` | Pass `is_full_access` to template context |
| `static/css/pricing.css` | Updated for three-tier layout |
| `static/css/report.css` | `.gated-section` styles |
| `.env.example` | `STRIPE_SUBSCRIPTION_PRICE_ID=` |
| `docs/b2b-api-spec.md` | New file — B2B API spec |
| `tests/conftest.py` | Add `subscriptions` to `_fresh_db` cleanup |
| `smoke_test.py` | Update markers if element IDs change |
