# NES-64: End-to-End Payment Flow Smoke Testing

**Overall Progress:** `100%`

## TLDR
Automated pytest suite testing all payment state transitions, route logic, and edge cases (mocked Stripe) + a manual runbook for one real Stripe test-mode transaction on Railway. Gate for flipping `REQUIRE_PAYMENT=true`.

## Critical Decisions
- **Mock Stripe entirely in automated tests** — we're testing our handler logic, not Stripe's SDK
- **Flask test client** — first use in the project; set up in conftest.py with temp SQLite DB
- **Atomic SQL verification only** — no thread-level concurrency tests; `WHERE status = ?` guard + rowcount assertion is sufficient
- **Known gap noted inline** — redeem-before-job-link window (app.py:1350→1372) documented as comment, not fixed in this ticket
- **BUILDER_MODE_ENV patched to False** — .env sets BUILDER_MODE=true which bypasses payment; tests patch this to exercise the payment path

## Tasks

- [x] 🟩 **Step 1: Test infrastructure setup**
  - [x] 🟩 Create `tests/conftest.py` with Flask test client fixture, temp DB, and auto-reset
  - [x] 🟩 Add env vars (SECRET_KEY, GOOGLE_MAPS_API_KEY) before app import
  - [x] 🟩 Helper `_make_payment()` to create a payment in known state

- [x] 🟩 **Step 2: Payment model unit tests** (`tests/test_payments.py`)
  - [x] 🟩 `create_payment` → row exists with status `pending`
  - [x] 🟩 `update_payment_status` with `expected_status` → succeeds when matching, fails when not
  - [x] 🟩 `redeem_payment` → `paid` → `redeemed` succeeds; second call returns `False`
  - [x] 🟩 `redeem_payment` → `failed_reissued` → `redeemed` succeeds (retry path)
  - [x] 🟩 `redeem_payment` → `pending` → returns `False` (can't redeem unpaid)
  - [x] 🟩 `get_payment_by_session` / `get_payment_by_id` / `get_payment_by_job_id` lookups

- [x] 🟩 **Step 3: Credit reissue tests** (`tests/test_payments.py`)
  - [x] 🟩 `_reissue_payment_if_needed` transitions `redeemed` → `failed_reissued`
  - [x] 🟩 Reissue on non-redeemed payment is a no-op
  - [x] 🟩 Reissue on job without payment is a no-op
  - [x] 🟩 Reissued credit can be redeemed again

- [x] 🟩 **Step 4: Checkout creation route tests** (`tests/test_payments.py`)
  - [x] 🟩 `POST /checkout/create` with valid address → returns `checkout_url`, creates pending payment in DB
  - [x] 🟩 `POST /checkout/create` with missing address → 400
  - [x] 🟩 `POST /checkout/create` when `REQUIRE_PAYMENT=false` → 400
  - [x] 🟩 Stripe API error during session creation → 500

- [x] 🟩 **Step 5: Webhook handler tests** (`tests/test_payments.py`)
  - [x] 🟩 Valid `checkout.session.completed` event → payment transitions `pending` → `paid`
  - [x] 🟩 Webhook for already-redeemed payment → no status overwrite (TOCTOU guard)
  - [x] 🟩 Invalid signature → 400 (mock exposes real exception class)
  - [x] 🟩 Unhandled event type → 200 (acknowledge without action)

- [x] 🟩 **Step 6: Return-from-Stripe flow tests** (`tests/test_payments.py`)
  - [x] 🟩 `POST /` with payment_token for `paid` payment → redeems, creates job, returns job_id
  - [x] 🟩 `POST /` with payment_token still `pending` + Stripe confirms paid → verifies, redeems, creates job
  - [x] 🟩 `POST /` with payment_token still `pending` + Stripe says unpaid → 402
  - [x] 🟩 `POST /` with payment_token still `pending` + Stripe API error → 402
  - [x] 🟩 `POST /` with already-redeemed token → 402 "invalid or expired"
  - [x] 🟩 `POST /` with nonexistent token → 402
  - [x] 🟩 `POST /` with no payment_token when payment required → 402

- [x] 🟩 **Step 7: Builder bypass test** (`tests/test_payments.py`)
  - [x] 🟩 `POST /` with `BUILDER_MODE_ENV=True` and no payment_token → skips payment, creates job

- [x] 🟩 **Step 8: Full state machine transition audit**
  - [x] 🟩 Test the complete lifecycle: `pending` → `paid` → `redeemed` → done
  - [x] 🟩 Test failure lifecycle: `pending` → `paid` → `redeemed` → `failed_reissued` → `redeemed`
  - [x] 🟩 Double-redeem blocked: two calls, only first succeeds
  - [x] 🟩 Note the redeem-before-job-link gap as inline comment

- [x] 🟩 **Step 9: Manual runbook**
  - [x] 🟩 Written as `MANUAL_RUNBOOK` docstring at bottom of test file covering:
    - Happy path on Railway with Stripe test card `4242 4242 4242 4242`
    - Verify report delivery after payment
    - Webhook verification via Stripe Dashboard event log
    - Local testing option with `stripe listen --forward-to`
    - Failure path + credit reissue verification
    - Double-redemption rejection
    - Checklist summary
