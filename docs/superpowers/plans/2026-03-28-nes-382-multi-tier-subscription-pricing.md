# NES-382: Multi-Tier Subscription Pricing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single subscription price with three duration-based tiers (30D/60D/90D) and update the pricing page to present plan options.

**Architecture:** Single `/checkout-subscription` endpoint with a `plan` parameter that maps to one of three Stripe price env vars via a dict lookup. Tier distinction is purely a Stripe concern — all tiers create identical subscription records in our DB.

**Tech Stack:** Python/Flask, Stripe Checkout API, Jinja templates, vanilla JS, pytest

**Spec:** `docs/superpowers/specs/2026-03-28-nes-382-multi-tier-subscription-pricing-design.md`

---

### Task 1: Backend — Replace single price var with multi-price dict

**Files:**
- Modify: `app.py:300-310` (config block)
- Modify: `app.py:4904-4921` (checkout route)
- Modify: `.env.example:20`

- [ ] **Step 1: Update config block in `app.py`**

Replace lines 304 and 308-310:

```python
# OLD (line 304):
_STRIPE_SUBSCRIPTION_PRICE_ID = os.environ.get("STRIPE_SUBSCRIPTION_PRICE_ID")

# OLD (lines 308-310):
_STRIPE_PLAN_MAP: dict[str, str] = {}
if _STRIPE_SUBSCRIPTION_PRICE_ID:
    _STRIPE_PLAN_MAP[_STRIPE_SUBSCRIPTION_PRICE_ID] = "30d"
```

With:

```python
_STRIPE_SUBSCRIPTION_PRICES = {
    "30d": os.environ.get("STRIPE_PRICE_30D"),
    "60d": os.environ.get("STRIPE_PRICE_60D"),
    "90d": os.environ.get("STRIPE_PRICE_90D"),
}

# Map Stripe price IDs to plan names for subscription tier tracking (NES-384).
_STRIPE_PLAN_MAP: dict[str, str] = {
    v: k for k, v in _STRIPE_SUBSCRIPTION_PRICES.items() if v
}
```

- [ ] **Step 2: Update `checkout_subscription()` route in `app.py`**

Replace the guard and line_items in the route (~lines 4904-4921):

```python
@app.route("/checkout-subscription", methods=["POST"])
def checkout_subscription():
    """Create a Stripe Checkout Session for a recurring subscription."""
    if not REQUIRE_PAYMENT:
        return jsonify({"error": "Payments not enabled"}), 400
    if not STRIPE_AVAILABLE:
        return jsonify({"error": "Payment system not configured"}), 503
    if not any(_STRIPE_SUBSCRIPTION_PRICES.values()):
        return jsonify({"error": "Subscription pricing not configured"}), 503

    data = request.get_json(silent=True) or {}
    email = data.get("email", request.form.get("email", "")).strip()
    if not email:
        return jsonify({"error": "Email required for subscription"}), 400

    plan = data.get("plan", "").strip().lower()
    if plan not in _STRIPE_SUBSCRIPTION_PRICES:
        return jsonify({"error": "Invalid plan. Must be one of: 30d, 60d, 90d"}), 400

    price_id = _STRIPE_SUBSCRIPTION_PRICES[plan]
    if not price_id:
        return jsonify({"error": "Plan not configured"}), 503

    base_url = request.url_root.rstrip("/")
    try:
        session_kwargs = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{base_url}/my-reports?subscription=active",
            "cancel_url": f"{base_url}/pricing",
        }
        _apply_stripe_customer(session_kwargs)
        if "customer" not in session_kwargs and "customer_email" not in session_kwargs:
            session_kwargs["customer_email"] = email

        checkout_session = stripe.checkout.Session.create(**session_kwargs)
        return jsonify({"checkout_url": checkout_session.url})
    except Exception:
        logger.exception("Stripe subscription checkout creation failed")
        return jsonify({"error": "Payment system error"}), 500
```

- [ ] **Step 3: Update `.env.example`**

Replace line 20:

```
STRIPE_SUBSCRIPTION_PRICE_ID=
```

With:

```
STRIPE_PRICE_30D=
STRIPE_PRICE_60D=
STRIPE_PRICE_90D=
```

- [ ] **Step 4: Verify no remaining references to `_STRIPE_SUBSCRIPTION_PRICE_ID`**

Run: `grep -r "STRIPE_SUBSCRIPTION_PRICE_ID" app.py .env.example`
Expected: no matches (only docs/specs/plans and tests should remain, tests are updated in Task 2)

- [ ] **Step 5: Commit**

```bash
git add app.py .env.example
git commit -m "feat(NES-382): replace single subscription price with multi-tier dict

Replace _STRIPE_SUBSCRIPTION_PRICE_ID with _STRIPE_SUBSCRIPTION_PRICES dict
mapping plan slugs (30d/60d/90d) to env vars. Update checkout route to
validate plan parameter and look up the correct price ID."
```

---

### Task 2: Tests — Update subscription checkout tests

**Files:**
- Modify: `tests/test_payments.py:238-300` (TestCheckoutSubscription class)

- [ ] **Step 1: Rewrite `TestCheckoutSubscription` tests**

Replace the entire `TestCheckoutSubscription` class (lines 238-300) with:

```python
class TestCheckoutSubscription:
    """Tests for POST /checkout-subscription."""

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app._STRIPE_SUBSCRIPTION_PRICES", {"30d": "price_30d", "60d": "price_60d", "90d": "price_90d"})
    @patch("app.stripe")
    def test_happy_path(self, mock_stripe, client):
        mock_session = MagicMock()
        mock_session.id = "cs_sub_001"
        mock_session.url = "https://checkout.stripe.com/pay/cs_sub_001"
        mock_stripe.checkout.Session.create.return_value = mock_session

        resp, body = _post_json(client, "/checkout-subscription", data={
            "email": "buyer@example.com",
            "plan": "60d",
        })

        assert resp.status_code == 200
        assert body["checkout_url"] == mock_session.url
        assert "payment_id" not in body

        call_kwargs = mock_stripe.checkout.Session.create.call_args.kwargs
        assert call_kwargs["mode"] == "subscription"
        assert call_kwargs["line_items"] == [{"price": "price_60d", "quantity": 1}]

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app._STRIPE_SUBSCRIPTION_PRICES", {"30d": "price_30d", "60d": "price_60d", "90d": "price_90d"})
    @patch("app.stripe")
    def test_all_plan_slugs(self, mock_stripe, client):
        """Each valid plan slug routes to its price ID."""
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/pay/cs_test"
        mock_stripe.checkout.Session.create.return_value = mock_session

        for plan, expected_price in [("30d", "price_30d"), ("60d", "price_60d"), ("90d", "price_90d")]:
            resp, body = _post_json(client, "/checkout-subscription", data={
                "email": "buyer@example.com",
                "plan": plan,
            })
            assert resp.status_code == 200, f"Plan {plan} failed"
            call_kwargs = mock_stripe.checkout.Session.create.call_args.kwargs
            assert call_kwargs["line_items"] == [{"price": expected_price, "quantity": 1}]

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app._STRIPE_SUBSCRIPTION_PRICES", {"30d": "price_30d", "60d": "price_60d", "90d": "price_90d"})
    def test_missing_email(self, client):
        resp, body = _post_json(client, "/checkout-subscription", data={"plan": "30d"})
        assert resp.status_code == 400
        assert "Email required" in body["error"]

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app._STRIPE_SUBSCRIPTION_PRICES", {"30d": "price_30d", "60d": "price_60d", "90d": "price_90d"})
    def test_missing_plan(self, client):
        resp, body = _post_json(client, "/checkout-subscription", data={
            "email": "buyer@example.com",
        })
        assert resp.status_code == 400
        assert "Invalid plan" in body["error"]

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app._STRIPE_SUBSCRIPTION_PRICES", {"30d": "price_30d", "60d": "price_60d", "90d": "price_90d"})
    def test_invalid_plan(self, client):
        resp, body = _post_json(client, "/checkout-subscription", data={
            "email": "buyer@example.com",
            "plan": "120d",
        })
        assert resp.status_code == 400
        assert "Invalid plan" in body["error"]

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app._STRIPE_SUBSCRIPTION_PRICES", {"30d": "price_30d", "60d": "price_60d", "90d": None})
    def test_plan_not_configured(self, client):
        resp, body = _post_json(client, "/checkout-subscription", data={
            "email": "buyer@example.com",
            "plan": "90d",
        })
        assert resp.status_code == 503
        assert "not configured" in body["error"]

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app._STRIPE_SUBSCRIPTION_PRICES", {"30d": None, "60d": None, "90d": None})
    def test_subscription_not_configured(self, client):
        resp, body = _post_json(client, "/checkout-subscription", data={
            "email": "buyer@example.com",
            "plan": "60d",
        })
        assert resp.status_code == 503
        assert "not configured" in body["error"]

    @patch("app.REQUIRE_PAYMENT", False)
    def test_payments_not_enabled(self, client):
        resp, body = _post_json(client, "/checkout-subscription", data={
            "email": "buyer@example.com",
            "plan": "60d",
        })
        assert resp.status_code == 400
        assert "not enabled" in body["error"]

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app._STRIPE_SUBSCRIPTION_PRICES", {"30d": "price_30d", "60d": "price_60d", "90d": "price_90d"})
    @patch("app.stripe")
    def test_stripe_api_error(self, mock_stripe, client):
        mock_stripe.checkout.Session.create.side_effect = Exception("Stripe down")

        resp, body = _post_json(client, "/checkout-subscription", data={
            "email": "buyer@example.com",
            "plan": "60d",
        })
        assert resp.status_code == 500
        assert "Payment system error" in body["error"]
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_payments.py::TestCheckoutSubscription -v`
Expected: all 9 tests PASS

- [ ] **Step 3: Run full payment test suite**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_payments.py -v`
Expected: all tests PASS (webhook tests unchanged, single-payment tests unchanged)

- [ ] **Step 4: Commit**

```bash
git add tests/test_payments.py
git commit -m "test(NES-382): update subscription tests for multi-tier plan parameter

Replace _STRIPE_SUBSCRIPTION_PRICE_ID patches with _STRIPE_SUBSCRIPTION_PRICES
dict patches. Add tests for missing plan, invalid plan, plan not configured,
all plan slugs, and stripe API error."
```

---

### Task 3: Pricing page — Three-plan selector UI

**Files:**
- Modify: `templates/pricing.html`
- Modify: `static/css/pricing.css`

- [ ] **Step 1: Update `templates/pricing.html`**

Replace the Active Search card (lines 62-85 — the `pricing-card--recommended` div) with the subscription section:

```html
    <!-- Active Search plans -->
    <div class="pricing-card pricing-card--plans">
      <div class="pricing-card-header">
        <h2 class="pricing-card-name">Active Search</h2>
        <p class="pricing-card-headline">Unlimited evaluations during your search. Compare every address you tour.</p>
      </div>

      <div class="pricing-plan-options">
        <label class="pricing-plan-option">
          <input type="radio" name="plan" value="30d">
          <div class="pricing-plan-option-content">
            <span class="pricing-plan-option-name">30-Day Search</span>
            <span class="pricing-plan-option-price">$39</span>
            <span class="pricing-plan-option-daily">~$1.30/day</span>
          </div>
        </label>

        <label class="pricing-plan-option">
          <input type="radio" name="plan" value="60d" checked>
          <div class="pricing-plan-option-content">
            <span class="pricing-plan-option-badge">Most popular</span>
            <span class="pricing-plan-option-name">60-Day Search</span>
            <span class="pricing-plan-option-price">$59</span>
            <span class="pricing-plan-option-daily">~$0.98/day</span>
          </div>
        </label>

        <label class="pricing-plan-option">
          <input type="radio" name="plan" value="90d">
          <div class="pricing-plan-option-content">
            <span class="pricing-plan-option-badge pricing-plan-option-badge--value">Best value</span>
            <span class="pricing-plan-option-name">90-Day Search</span>
            <span class="pricing-plan-option-price">$79</span>
            <span class="pricing-plan-option-daily">~$0.88/day</span>
          </div>
        </label>
      </div>

      <form class="pricing-subscribe-form" onsubmit="return handleSubscribe(event)">
        {% if current_user.is_authenticated %}
        <input type="hidden" name="email" value="{{ current_user.email }}">
        {% else %}
        <input type="email" name="email" placeholder="Your email" required
          autocomplete="off" data-1p-ignore data-lpignore="true" data-form-type="other">
        {% endif %}
        <button type="submit" class="pricing-cta pricing-cta--primary">Start searching</button>
        <p class="pricing-error" style="color: #dc2626; font-size: 13px; margin: 8px 0 0; min-height: 1em;"></p>
      </form>
    </div>
```

- [ ] **Step 2: Update meta description and OG tags**

Replace the price text in both the `<meta name="description">` (line 5) and `<meta property="og:description">` (line 9) — change `$39/mo unlimited` to `plans from $39`:

```
NestCheck pricing — free health checks, $9 full evaluations, plans from $39.
```

- [ ] **Step 3: Update `handleSubscribe()` in the script block**

Replace the existing `handleSubscribe` function (lines 97-115):

```javascript
async function handleSubscribe(event) {
    event.preventDefault();
    var form = event.target;
    var email = form.querySelector('[name="email"]').value;
    var planInput = document.querySelector('input[name="plan"]:checked');
    var plan = planInput ? planInput.value : '60d';
    try {
        var data = await csrfFetch('/checkout-subscription', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({email: email, plan: plan})
        });
        if (data && data.checkout_url) {
            window.location.href = data.checkout_url;
        }
    } catch (err) {
        console.error('Subscription checkout failed:', err);
        var errEl = form.querySelector('.pricing-error');
        if (errEl) errEl.textContent = 'Something went wrong. Please try again.';
    }
}
```

Note: `planInput` is queried from `document` (not `form`) because the radio inputs are siblings of the form, not children of it — both are inside `.pricing-card--plans`.

- [ ] **Step 4: Commit template changes**

```bash
git add templates/pricing.html
git commit -m "feat(NES-382): update pricing page with three subscription plan options

Replace single Active Search card with 30D/60D/90D plan selector.
60D pre-selected as 'Most popular'. Per-day costs shown.
handleSubscribe sends plan parameter to checkout endpoint."
```

---

### Task 4: Pricing CSS — Plan selector styles

**Files:**
- Modify: `static/css/pricing.css`

- [ ] **Step 1: Remove orphaned CSS and add plan selector styles to `pricing.css`**

First, remove the now-orphaned selectors:
- `.pricing-card--recommended` (lines 72-74) — the card is replaced by `.pricing-card--plans`
- `.pricing-card-badge` (lines 77-91) — badge moved into plan options
- `.pricing-card-period` (lines 110-113) — `/mo` text removed from template

Then add before the `/* ── Footer note */` section:

Also update `.pricing-grid` (line 51) from `repeat(3, 1fr)` to `repeat(2, 1fr)` — the grid now has two regular cards (Free, $9) plus one full-width plans card. Three columns would leave an empty gap.

```css
/* ── Plan selector (NES-382) ─────────────────────────────── */
.pricing-card--plans {
  grid-column: 1 / -1;
  border: 2px solid var(--color-brand);
}

.pricing-plan-options {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-sm);
}

.pricing-plan-option {
  cursor: pointer;
  position: relative;
}

.pricing-plan-option input[type="radio"] {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.pricing-plan-option-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-lg) var(--space-base);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  transition: border-color var(--transition-fast), background var(--transition-fast);
  text-align: center;
}

.pricing-plan-option input[type="radio"]:checked + .pricing-plan-option-content {
  border-color: var(--color-brand);
  background: rgba(11, 29, 58, 0.03);
}

.pricing-plan-option-badge {
  font-size: 10px;
  font-weight: var(--font-weight-semibold);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: var(--color-brand);
  color: var(--color-text-inverse);
  padding: 2px var(--space-sm);
  border-radius: var(--radius-full);
}

.pricing-plan-option-badge--value {
  background: #111111;
}

.pricing-plan-option-name {
  font-family: var(--font-heading);
  font-size: 15px;
  font-weight: var(--font-weight-semibold);
  color: #111111;
}

.pricing-plan-option-price {
  font-family: var(--font-heading);
  font-size: 32px;
  font-weight: var(--font-weight-bold);
  letter-spacing: -0.03em;
  color: #111111;
  line-height: var(--line-height-none);
}

.pricing-plan-option-daily {
  font-size: 13px;
  color: #666666;
}
```

- [ ] **Step 2: Add mobile responsive rules for plan selector**

Add inside the `@media (max-width: 768px)` block (after line 241):

```css
  .pricing-plan-options {
    grid-template-columns: 1fr;
  }

  .pricing-plan-option-content {
    flex-direction: row;
    justify-content: space-between;
    padding: var(--space-base) var(--space-lg);
  }

  .pricing-plan-option-price {
    font-size: 24px;
  }
```

- [ ] **Step 3: Verify the page renders**

Run: `cd /Users/jeremybrowning/NestCheck && python -c "from app import app; app.test_client().get('/pricing')" && echo "OK"`
Expected: no exceptions, "OK" printed

- [ ] **Step 4: Commit**

```bash
git add static/css/pricing.css
git commit -m "style(NES-382): add plan selector styles to pricing page

Full-width plan card with 3-col radio selector grid. Selected state
uses brand border + subtle background. Stacks to 1-col on mobile
with horizontal layout per option."
```

---

### Task 5: Update CLAUDE.md

**Files:**
- Modify: `.claude/CLAUDE.md`

- [ ] **Step 1: Update the "Two checkout routes" section in CLAUDE.md**

Find the `Two checkout routes — single-payment vs subscription (NES-385)` entry in the `### Stripe Integration (Payments)` section. Replace it with:

```
- **Two checkout routes — single-payment vs subscription (NES-385, NES-382)**: `POST /checkout/create` handles single-payment evaluations (requires `address`, creates a `payments` record, returns `checkout_url` + `payment_id`). `POST /checkout-subscription` handles recurring subscriptions (requires `email` + `plan`, no `payments` record — the webhook `customer.subscription.created` handles everything via `create_subscription()`). The `plan` parameter must be one of `30d`, `60d`, `90d` — mapped to `STRIPE_PRICE_30D`/`STRIPE_PRICE_60D`/`STRIPE_PRICE_90D` env vars via `_STRIPE_SUBSCRIPTION_PRICES` dict. `_STRIPE_PLAN_MAP` (NES-384) is derived from this dict as a reverse lookup (`price_id → plan_slug`). Shared Stripe customer wiring is in `_apply_stripe_customer(session_kwargs)`. The subscription route also pre-fills `customer_email` for non-authenticated users since the email is already required. When adding a new checkout flow, decide whether it uses the payment state machine (single) or the subscription lifecycle (subscription) — do not mix them.
```

- [ ] **Step 2: Add decision log entry**

Add to the Decision Log table:

```
| 2026-03 | Multi-tier subscription pricing (NES-382) | Replaced single `STRIPE_SUBSCRIPTION_PRICE_ID` with `STRIPE_PRICE_30D/60D/90D` dict. Checkout accepts `plan` parameter (30d/60d/90d). Tier distinction is purely Stripe-side — all tiers create identical subscription records; `is_subscription_active(email)` doesn't know or care which tier. Pricing: $39/59/79 with volume discount framing per CMO guidance. 60D default-selected as "Most popular" |
```

- [ ] **Step 3: Commit**

```bash
git add .claude/CLAUDE.md
git commit -m "docs(NES-382): update CLAUDE.md with multi-tier subscription patterns"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_payments.py -v`
Expected: all tests PASS

- [ ] **Step 2: Verify no stale references in production code**

Run: `grep -rn "_STRIPE_SUBSCRIPTION_PRICE_ID" app.py tests/ .env.example`
Expected: no matches in `app.py` or `.env.example`. Tests should only show the new `_STRIPE_SUBSCRIPTION_PRICES` pattern.

- [ ] **Step 3: Smoke test pricing page renders**

Run: `cd /Users/jeremybrowning/NestCheck && python -c "from app import app; c = app.test_client(); r = c.get('/pricing'); assert r.status_code == 200; assert b'30-Day Search' in r.data; assert b'60-Day Search' in r.data; assert b'90-Day Search' in r.data; print('Pricing page OK')" `
Expected: "Pricing page OK"

- [ ] **Step 4: Verify CI tests pass**

Run: `cd /Users/jeremybrowning/NestCheck && make test-scoring`
Expected: PASS (payment tests are included in the scoring test gate)
