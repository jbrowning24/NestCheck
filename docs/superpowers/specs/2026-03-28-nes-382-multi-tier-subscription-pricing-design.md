# NES-382: Multi-Tier Subscription Pricing (30D/60D/90D)

## Summary

Replace the single `STRIPE_SUBSCRIPTION_PRICE_ID` env var with three duration-based subscription tiers (`STRIPE_PRICE_30D`, `STRIPE_PRICE_60D`, `STRIPE_PRICE_90D`). Update the checkout endpoint to accept a `plan` parameter routing to the correct Stripe price. Update the pricing page to present three plan options with volume discount framing.

## Design Decisions

- **Tier distinction is purely a Stripe/pricing concern.** All three tiers create identical subscription records. The backend checks `is_subscription_active(email)` — it never needs to know which tier was purchased. Stripe manages billing intervals and period dates.
- **Human-readable plan slugs** (`30d`, `60d`, `90d`) in the API, not Stripe price IDs. Keeps URLs, logs, and analytics readable.
- **Single endpoint, dict lookup.** One `/checkout-subscription` endpoint with a `plan` parameter. No separate routes per tier.
- **CMO-guided pricing and framing.** Duration-based names ("30-Day Search"), volume discount psychology ($39/$59/$79), 60D default-selected with "Most popular" badge, per-day cost shown.

## 1. Environment Variables

### Remove

```
STRIPE_SUBSCRIPTION_PRICE_ID
```

### Add

```
STRIPE_PRICE_30D=price_xxx
STRIPE_PRICE_60D=price_yyy
STRIPE_PRICE_90D=price_zzz
```

### Update `.env.example`

Replace the `STRIPE_SUBSCRIPTION_PRICE_ID` line with three new lines.

## 2. Backend — `app.py`

### Config block (~line 304)

Remove:
```python
_STRIPE_SUBSCRIPTION_PRICE_ID = os.environ.get("STRIPE_SUBSCRIPTION_PRICE_ID")
```

Add:
```python
_STRIPE_SUBSCRIPTION_PRICES = {
    "30d": os.environ.get("STRIPE_PRICE_30D"),
    "60d": os.environ.get("STRIPE_PRICE_60D"),
    "90d": os.environ.get("STRIPE_PRICE_90D"),
}
```

### `_STRIPE_PLAN_MAP` (~line 308, NES-384 coordination)

The existing `_STRIPE_PLAN_MAP` (added by NES-384) maps Stripe price IDs back to plan slugs for the webhook handler's plan-column feature. Currently populated from the single `_STRIPE_SUBSCRIPTION_PRICE_ID`. Update to derive from `_STRIPE_SUBSCRIPTION_PRICES`:

```python
_STRIPE_PLAN_MAP: dict[str, str] = {
    v: k for k, v in _STRIPE_SUBSCRIPTION_PRICES.items() if v
}
```

### `checkout_subscription()` route (~line 4897)

Current guard:
```python
if not _STRIPE_SUBSCRIPTION_PRICE_ID:
    return jsonify({"error": "Subscription pricing not configured"}), 503
```

New logic:
```python
# Check at least one plan is configured
if not any(_STRIPE_SUBSCRIPTION_PRICES.values()):
    return jsonify({"error": "Subscription pricing not configured"}), 503

# Validate plan parameter
plan = data.get("plan", "").strip().lower()
if plan not in _STRIPE_SUBSCRIPTION_PRICES:
    return jsonify({"error": "Invalid plan. Must be one of: 30d, 60d, 90d"}), 400

price_id = _STRIPE_SUBSCRIPTION_PRICES[plan]
if not price_id:
    return jsonify({"error": "Plan not configured"}), 503
```

`line_items` changes from:
```python
"line_items": [{"price": _STRIPE_SUBSCRIPTION_PRICE_ID, "quantity": 1}],
```
to:
```python
"line_items": [{"price": price_id, "quantity": 1}],
```

Everything else in the route is unchanged: email validation, `_apply_stripe_customer`, success/cancel URLs, error handling.

### No changes to

- Webhook handler (`_handle_subscription_event`)
- `models.py` (subscription table, `is_subscription_active`, `create_subscription`, etc.)
- Any subscription access gating logic

## 3. Pricing Page — `templates/pricing.html`

### Structure change

The single "Active Search" `pricing-card--recommended` is replaced with a subscription section containing three plan options and a shared form.

#### Plan options

| Plan | Price | Per-day | Badge |
|------|-------|---------|-------|
| 30-Day Search | $39 | ~$1.30/day | — |
| 60-Day Search | $59 | ~$0.98/day | Most popular |
| 90-Day Search | $79 | ~$0.88/day | Best value |

#### UI behavior

- Three selectable plan cards (radio pattern) inside one subscription container.
- 60D is pre-selected on page load.
- One email input + one submit button shared across all three.
- Selected plan visually highlighted (border/background change using existing pricing CSS patterns).
- Headline above the plans: "Unlimited evaluations during your search. Compare every address you tour."

#### JavaScript

`handleSubscribe()` updated to read the selected plan and include it in the POST body:

```javascript
var selectedPlan = form.querySelector('input[name="plan"]:checked').value;
body: JSON.stringify({email: email, plan: selectedPlan})
```

### Meta description and OG tags

Update price references from "$39/mo" to reflect the multi-tier offering (e.g., "Plans from $39").

## 4. Tests — `tests/test_payments.py`

Update `TestCheckoutSubscription`:

| Test | POST body | Expected |
|------|-----------|----------|
| `test_happy_path` | `{email, plan: "60d"}` | 200, `checkout_url` |
| `test_all_plan_slugs` | `{email, plan}` for each of 30d, 60d, 90d | 200 for each |
| `test_missing_plan` | `{email}` (no plan) | 400 |
| `test_invalid_plan` | `{email, plan: "120d"}` | 400 |
| `test_plan_not_configured` | `{email, plan: "90d"}` (env var unset) | 503 |
| `test_missing_email` | `{plan: "30d"}` (no email) | 400 |
| `test_subscription_not_configured` | all three env vars unset | 503 |
| `test_payments_not_enabled` | `REQUIRE_PAYMENT=false` | 400 |
| `test_stripe_api_error` | `{email, plan: "60d"}` + Stripe raises | 500 |

Test env setup: set `STRIPE_PRICE_30D` and `STRIPE_PRICE_60D` in test fixtures; leave `STRIPE_PRICE_90D` unset to test the partial-configuration path.

## 5. Files Changed

| File | Change |
|------|--------|
| `app.py` | Config block: replace single var with dict + update `_STRIPE_PLAN_MAP`. Route: add plan validation + lookup |
| `templates/pricing.html` | Replace single subscription card with three-plan selector + shared form |
| `static/css/pricing.css` | Styles for plan selector (radio cards, selected state, per-day text) |
| `tests/test_payments.py` | Update subscription checkout tests for plan parameter |
| `.env.example` (if exists) | Replace `STRIPE_SUBSCRIPTION_PRICE_ID` with three new vars |
| `CLAUDE.md` | Update "Two checkout routes" section to document `plan` parameter and multi-price config |

## 6. Out of Scope

- No changes to subscription lifecycle (webhook, status transitions, access gating)
- No changes to `models.py` subscription schema
- No plan/tier stored in our DB — Stripe is the source of truth for which price was purchased
- No changes to single-payment ($9) checkout flow
- No changes to free tier logic
