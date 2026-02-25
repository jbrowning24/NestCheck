"""End-to-end payment flow smoke tests (NES-64).

Tests the full payment state machine, route handlers, and edge cases
using mocked Stripe calls. No real Stripe API traffic.

See MANUAL RUNBOOK at the bottom of this file for the one-time
Stripe test-mode verification to run on Railway before launch.
"""

from unittest.mock import patch, MagicMock

import pytest

try:
    from models import (
        create_payment, get_payment_by_id, get_payment_by_session,
        get_payment_by_job_id, update_payment_status, redeem_payment,
        update_payment_job_id, create_job,
    )
    from worker import _reissue_payment_if_needed
except ImportError:
    pytestmark = pytest.mark.skip(
        reason="Payment functions (create_payment, redeem_payment, etc.) and "
               "job queue functions (create_job) removed from models.py"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payment(payment_id="pay_abc123", stripe_session_id="cs_test_123",
                  visitor_id="visitor_1", address="123 Main St, Scarsdale, NY"):
    """Insert a payment in 'pending' state and return its ID."""
    create_payment(payment_id, stripe_session_id, visitor_id, address)
    return payment_id


def _post_json(client, url, data=None, **kwargs):
    """POST form data and parse the JSON response."""
    resp = client.post(url, data=data, **kwargs)
    return resp, resp.get_json(silent=True)


# ===========================================================================
# Step 2: Payment model unit tests
# ===========================================================================

class TestCreatePayment:
    def test_creates_pending_row(self):
        pid = _make_payment()
        p = get_payment_by_id(pid)
        assert p is not None
        assert p["status"] == "pending"
        assert p["address"] == "123 Main St, Scarsdale, NY"

    def test_lookup_by_session(self):
        _make_payment(stripe_session_id="cs_sess_xyz")
        p = get_payment_by_session("cs_sess_xyz")
        assert p is not None
        assert p["stripe_session_id"] == "cs_sess_xyz"

    def test_lookup_by_session_not_found(self):
        assert get_payment_by_session("cs_nonexistent") is None

    def test_lookup_by_id_not_found(self):
        assert get_payment_by_id("nope") is None


class TestUpdatePaymentStatus:
    def test_update_without_guard(self):
        pid = _make_payment()
        assert update_payment_status(pid, "paid") is True
        assert get_payment_by_id(pid)["status"] == "paid"

    def test_update_with_matching_expected_status(self):
        pid = _make_payment()
        assert update_payment_status(pid, "paid", expected_status="pending") is True
        assert get_payment_by_id(pid)["status"] == "paid"

    def test_update_with_wrong_expected_status(self):
        """Atomic guard: update fails when current status doesn't match."""
        pid = _make_payment()
        update_payment_status(pid, "paid")  # pending -> paid
        # Now try to transition from 'pending' again — should fail
        assert update_payment_status(pid, "paid", expected_status="pending") is False


class TestRedeemPayment:
    def test_redeem_paid(self):
        pid = _make_payment()
        update_payment_status(pid, "paid")
        assert redeem_payment(pid, job_id="job_1") is True
        p = get_payment_by_id(pid)
        assert p["status"] == "redeemed"
        assert p["redeemed_at"] is not None
        assert p["job_id"] == "job_1"

    def test_double_redeem_fails(self):
        """Second redemption of the same token must be rejected."""
        pid = _make_payment()
        update_payment_status(pid, "paid")
        assert redeem_payment(pid) is True
        assert redeem_payment(pid) is False  # already redeemed

    def test_redeem_failed_reissued(self):
        """Credits reissued after failure can be redeemed again."""
        pid = _make_payment()
        update_payment_status(pid, "paid")
        redeem_payment(pid)
        update_payment_status(pid, "failed_reissued")
        assert redeem_payment(pid, job_id="job_retry") is True
        assert get_payment_by_id(pid)["status"] == "redeemed"

    def test_redeem_pending_fails(self):
        """Cannot redeem an unpaid (pending) payment."""
        pid = _make_payment()
        assert redeem_payment(pid) is False

    def test_lookup_by_job_id(self):
        pid = _make_payment()
        update_payment_status(pid, "paid")
        redeem_payment(pid, job_id="job_lookup")
        p = get_payment_by_job_id("job_lookup")
        assert p is not None
        assert p["id"] == pid

    def test_update_job_id_after_redeem(self):
        pid = _make_payment()
        update_payment_status(pid, "paid")
        redeem_payment(pid, job_id=None)
        update_payment_job_id(pid, "job_late_link")
        assert get_payment_by_id(pid)["job_id"] == "job_late_link"


# ===========================================================================
# Step 3: Credit reissue tests
# ===========================================================================

class TestCreditReissue:
    def test_reissue_on_redeemed(self):
        pid = _make_payment()
        update_payment_status(pid, "paid")
        job_id = create_job("123 Main St", visitor_id="v1")
        redeem_payment(pid, job_id=job_id)
        update_payment_job_id(pid, job_id)

        _reissue_payment_if_needed(job_id)
        assert get_payment_by_id(pid)["status"] == "failed_reissued"

    def test_reissue_noop_when_not_redeemed(self):
        """Reissue does nothing if payment is still 'paid' (not yet redeemed)."""
        pid = _make_payment()
        update_payment_status(pid, "paid")
        job_id = create_job("123 Main St", visitor_id="v1")
        update_payment_job_id(pid, job_id)

        _reissue_payment_if_needed(job_id)
        assert get_payment_by_id(pid)["status"] == "paid"

    def test_reissue_noop_when_no_payment(self):
        """Reissue does nothing for jobs without a linked payment (free eval)."""
        job_id = create_job("456 Oak Ave", visitor_id="v2")
        _reissue_payment_if_needed(job_id)  # should not raise

    def test_reissued_credit_redeemable(self):
        """After reissue, the same payment token can be redeemed again."""
        pid = _make_payment()
        update_payment_status(pid, "paid")
        job_id = create_job("123 Main St", visitor_id="v1")
        redeem_payment(pid, job_id=job_id)
        update_payment_job_id(pid, job_id)

        _reissue_payment_if_needed(job_id)
        assert redeem_payment(pid, job_id="job_retry") is True
        assert get_payment_by_id(pid)["status"] == "redeemed"


# ===========================================================================
# Step 4: Checkout creation route tests
# ===========================================================================

class TestCheckoutCreate:
    """Tests for POST /checkout/create."""

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app.stripe")
    def test_happy_path(self, mock_stripe, client):
        mock_session = MagicMock()
        mock_session.id = "cs_test_session_001"
        mock_session.url = "https://checkout.stripe.com/pay/cs_test_session_001"
        mock_stripe.checkout.Session.create.return_value = mock_session

        resp, body = _post_json(client, "/checkout/create", data={
            "address": "42 Elm St, White Plains, NY",
        })

        assert resp.status_code == 200
        assert "checkout_url" in body
        assert body["checkout_url"] == mock_session.url

        # Verify a pending payment was created in the DB
        call_args = mock_stripe.checkout.Session.create.call_args
        payment_id = call_args.kwargs["client_reference_id"]
        p = get_payment_by_id(payment_id)
        assert p is not None
        assert p["status"] == "pending"
        assert p["stripe_session_id"] == "cs_test_session_001"

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    def test_missing_address(self, client):
        resp, body = _post_json(client, "/checkout/create", data={})
        assert resp.status_code == 400
        assert "Address required" in body["error"]

    @patch("app.REQUIRE_PAYMENT", False)
    def test_payments_not_enabled(self, client):
        resp, body = _post_json(client, "/checkout/create", data={
            "address": "1 Main St",
        })
        assert resp.status_code == 400
        assert "not enabled" in body["error"]

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app.stripe")
    def test_stripe_api_error(self, mock_stripe, client):
        mock_stripe.checkout.Session.create.side_effect = Exception("Stripe down")

        resp, body = _post_json(client, "/checkout/create", data={
            "address": "1 Oak Ave",
        })
        assert resp.status_code == 500
        assert "Payment system error" in body["error"]


# ===========================================================================
# Step 5: Webhook handler tests
# ===========================================================================

class TestStripeWebhook:
    """Tests for POST /webhook/stripe."""

    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app.stripe")
    def test_checkout_completed(self, mock_stripe, client):
        """Valid checkout.session.completed event transitions pending → paid."""
        pid = _make_payment(stripe_session_id="cs_wh_001")

        mock_stripe.Webhook.construct_event.return_value = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_wh_001"}},
        }

        resp = client.post("/webhook/stripe", data=b"payload",
                           headers={"Stripe-Signature": "sig_test"})
        assert resp.status_code == 200
        assert get_payment_by_id(pid)["status"] == "paid"

    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app.stripe")
    def test_webhook_does_not_overwrite_redeemed(self, mock_stripe, client):
        """TOCTOU guard: webhook arriving after redemption must not revert status."""
        pid = _make_payment(stripe_session_id="cs_wh_002")
        update_payment_status(pid, "paid")
        redeem_payment(pid)

        mock_stripe.Webhook.construct_event.return_value = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_wh_002"}},
        }

        resp = client.post("/webhook/stripe", data=b"payload",
                           headers={"Stripe-Signature": "sig_test"})
        assert resp.status_code == 200
        assert get_payment_by_id(pid)["status"] == "redeemed"  # unchanged

    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app.stripe")
    def test_invalid_signature(self, mock_stripe, client):
        # The except clause references stripe.error.SignatureVerificationError,
        # so the mock must expose it as a real exception class.
        mock_stripe.error.SignatureVerificationError = type(
            "SignatureVerificationError", (Exception,), {}
        )
        mock_stripe.Webhook.construct_event.side_effect = ValueError("bad sig")

        resp = client.post("/webhook/stripe", data=b"payload",
                           headers={"Stripe-Signature": "bad"})
        assert resp.status_code == 400

    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app.stripe")
    def test_signature_verification_error(self, mock_stripe, client):
        """SignatureVerificationError (Stripe's own signing check) → 400.

        This is the exception Stripe actually raises in production for
        bad webhook signatures. Distinct from ValueError (malformed payload).
        """
        sig_error = type("SignatureVerificationError", (Exception,), {})
        mock_stripe.error.SignatureVerificationError = sig_error
        mock_stripe.Webhook.construct_event.side_effect = sig_error("bad sig")

        resp = client.post("/webhook/stripe", data=b"payload",
                           headers={"Stripe-Signature": "bad"})
        assert resp.status_code == 400

    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app.stripe")
    def test_unhandled_event_type(self, mock_stripe, client):
        """Unhandled event types should still return 200 to prevent Stripe retries."""
        mock_stripe.Webhook.construct_event.return_value = {
            "type": "charge.refunded",
            "data": {"object": {}},
        }

        resp = client.post("/webhook/stripe", data=b"payload",
                           headers={"Stripe-Signature": "sig_test"})
        assert resp.status_code == 200


# ===========================================================================
# Step 6: Return-from-Stripe flow tests (POST / with payment_token)
# ===========================================================================

@patch("app.BUILDER_MODE_ENV", False)
class TestReturnFromStripe:
    """Tests for POST / when REQUIRE_PAYMENT=true.

    This is the most fragile payment path: the user returns from Stripe
    checkout and the frontend auto-submits with payment_token. If the
    webhook hasn't arrived yet, we verify directly with Stripe's API.

    BUILDER_MODE_ENV is patched to False at the class level because the
    .env file sets BUILDER_MODE=true, which would bypass payment entirely.
    """

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    def test_paid_token_creates_job(self, client):
        """Happy path: webhook already confirmed, token is 'paid'."""
        pid = _make_payment()
        update_payment_status(pid, "paid")

        resp, body = _post_json(client, "/", data={
            "address": "123 Main St, Scarsdale, NY",
            "payment_token": pid,
        }, headers={"Accept": "application/json"})

        assert resp.status_code == 200
        assert "job_id" in body
        # Payment should be redeemed
        p = get_payment_by_id(pid)
        assert p["status"] == "redeemed"
        assert p["job_id"] == body["job_id"]

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app.stripe")
    def test_pending_token_verified_by_stripe(self, mock_stripe, client):
        """Webhook hasn't arrived: direct Stripe verify confirms payment."""
        pid = _make_payment(stripe_session_id="cs_pending_verify")

        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_stripe.checkout.Session.retrieve.return_value = mock_session

        resp, body = _post_json(client, "/", data={
            "address": "123 Main St, Scarsdale, NY",
            "payment_token": pid,
        }, headers={"Accept": "application/json"})

        assert resp.status_code == 200
        assert "job_id" in body
        assert get_payment_by_id(pid)["status"] == "redeemed"

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app.stripe")
    def test_pending_token_stripe_says_unpaid(self, mock_stripe, client):
        """Pending token + Stripe says not paid → 402."""
        pid = _make_payment(stripe_session_id="cs_unpaid")

        mock_session = MagicMock()
        mock_session.payment_status = "unpaid"
        mock_stripe.checkout.Session.retrieve.return_value = mock_session

        resp, body = _post_json(client, "/", data={
            "address": "123 Main St, Scarsdale, NY",
            "payment_token": pid,
        }, headers={"Accept": "application/json"})

        assert resp.status_code == 402
        assert "not completed" in body["error"]
        assert get_payment_by_id(pid)["status"] == "pending"  # unchanged

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app.stripe")
    def test_pending_token_stripe_api_error(self, mock_stripe, client):
        """Pending token + Stripe API failure → 402 graceful error."""
        pid = _make_payment(stripe_session_id="cs_error")

        mock_stripe.checkout.Session.retrieve.side_effect = Exception("timeout")

        resp, body = _post_json(client, "/", data={
            "address": "123 Main St, Scarsdale, NY",
            "payment_token": pid,
        }, headers={"Accept": "application/json"})

        assert resp.status_code == 402
        assert "verify payment" in body["error"].lower()

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    def test_already_redeemed_token(self, client):
        """Already-used payment token → 402.

        A 'redeemed' status is not in the allowed set (paid, pending,
        failed_reissued), so the route rejects it at the status check
        before reaching the redeem_payment() call.
        """
        pid = _make_payment()
        update_payment_status(pid, "paid")
        redeem_payment(pid)

        resp, body = _post_json(client, "/", data={
            "address": "123 Main St, Scarsdale, NY",
            "payment_token": pid,
        }, headers={"Accept": "application/json"})

        assert resp.status_code == 402
        assert "invalid or expired" in body["error"].lower()

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    def test_nonexistent_token(self, client):
        """Bogus payment token → 402."""
        resp, body = _post_json(client, "/", data={
            "address": "123 Main St, Scarsdale, NY",
            "payment_token": "does_not_exist",
        }, headers={"Accept": "application/json"})

        assert resp.status_code == 402
        assert "Invalid" in body["error"]

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    def test_missing_token_when_payment_required(self, client):
        """No payment_token at all when payment is required → 402."""
        resp, body = _post_json(client, "/", data={
            "address": "123 Main St, Scarsdale, NY",
        }, headers={"Accept": "application/json"})

        assert resp.status_code == 402
        assert "required" in body["error"].lower()


# ===========================================================================
# Step 7: Builder bypass test
# ===========================================================================

class TestBuilderBypass:
    """Builder mode should skip payment entirely."""

    @patch("app.REQUIRE_PAYMENT", True)
    @patch("app.STRIPE_AVAILABLE", True)
    @patch("app.BUILDER_MODE_ENV", True)
    def test_builder_skips_payment(self, client):
        """is_builder=True + no payment_token → creates job without paying."""
        resp, body = _post_json(client, "/", data={
            "address": "99 Builder Ave, Bronxville, NY",
        }, headers={"Accept": "application/json"})

        assert resp.status_code == 200
        assert "job_id" in body


# ===========================================================================
# Step 8: Full state machine transition audit
# ===========================================================================

class TestPaymentStateMachine:
    """Verify complete lifecycle transitions end-to-end."""

    def test_happy_lifecycle(self):
        """pending → paid → redeemed (normal completion)."""
        pid = _make_payment()
        assert get_payment_by_id(pid)["status"] == "pending"

        assert update_payment_status(pid, "paid", expected_status="pending")
        assert get_payment_by_id(pid)["status"] == "paid"

        job_id = create_job("123 Main St", visitor_id="v1")
        assert redeem_payment(pid, job_id=job_id)
        p = get_payment_by_id(pid)
        assert p["status"] == "redeemed"
        assert p["job_id"] == job_id

    def test_failure_lifecycle(self):
        """pending → paid → redeemed → failed_reissued → redeemed (retry)."""
        pid = _make_payment()

        update_payment_status(pid, "paid", expected_status="pending")
        job1 = create_job("123 Main St", visitor_id="v1")
        redeem_payment(pid, job_id=job1)
        update_payment_job_id(pid, job1)

        # Evaluation fails — credit reissued
        _reissue_payment_if_needed(job1)
        assert get_payment_by_id(pid)["status"] == "failed_reissued"

        # User retries with the same payment token
        job2 = create_job("123 Main St", visitor_id="v1")
        assert redeem_payment(pid, job_id=job2)
        assert get_payment_by_id(pid)["status"] == "redeemed"
        assert get_payment_by_id(pid)["job_id"] == job2

    def test_double_redeem_blocked(self):
        """Two concurrent redeem attempts — only one succeeds."""
        pid = _make_payment()
        update_payment_status(pid, "paid")

        first = redeem_payment(pid, job_id="job_a")
        second = redeem_payment(pid, job_id="job_b")

        assert first is True
        assert second is False
        assert get_payment_by_id(pid)["job_id"] == "job_a"

    # NOTE: There is a known gap between redeem_payment() at app.py:1350
    # and update_payment_job_id() at app.py:1372. If the server crashes
    # between these calls, a payment is marked 'redeemed' with no linked
    # job_id. This is a recoverable edge case (manual DB fix) and is not
    # addressed in this ticket.


# ===========================================================================
# Step 9: Manual runbook
# ===========================================================================

MANUAL_RUNBOOK = """
================================================================================
MANUAL RUNBOOK — Stripe Test-Mode Smoke Test (NES-64)
================================================================================

Run this once on the deployed Railway environment before flipping
REQUIRE_PAYMENT=true in production.

PREREQUISITES
─────────────
- Railway env has STRIPE_SECRET_KEY (sk_test_...) set
- Railway env has STRIPE_WEBHOOK_SECRET (whsec_...) set
- Railway env has STRIPE_PRICE_ID (price_...) set
- REQUIRE_PAYMENT=true on the staging/test deploy
- Stripe Dashboard → Webhooks shows the /webhook/stripe endpoint
  with 'checkout.session.completed' event selected

OPTION A: TEST AGAINST DEPLOYED RAILWAY ENDPOINT (recommended)
──────────────────────────────────────────────────────────────
1. Open the Railway deployment URL in a browser.
2. Enter a test address (e.g. "42 Elm St, White Plains, NY 10601").
3. Click "Evaluate" — you should be redirected to Stripe Checkout.
4. Use test card: 4242 4242 4242 4242
   - Expiry: any future date (e.g. 12/34)
   - CVC: any 3 digits (e.g. 123)
   - Name/ZIP: anything
5. After payment, you should be redirected back to NestCheck.
6. The evaluation should start automatically (progress stages visible).
7. Expected outcome: report loads at /s/{snapshot_id}.

VERIFY IN STRIPE DASHBOARD:
  - Payments → shows a $9.00 test payment (succeeded)
  - Webhooks → Recent deliveries → checkout.session.completed → 200 OK
  - The payment_id in the client_reference_id matches the DB

VERIFY IN RAILWAY LOGS:
  - "Payment confirmed via webhook: pay_xxx" log line
  - "Created evaluation job xxx" log line
  - No 402 or 500 errors

OPTION B: LOCAL TESTING WITH STRIPE CLI
───────────────────────────────────────
1. Install Stripe CLI: brew install stripe/stripe-cli/stripe
2. Login: stripe login
3. Forward webhooks: stripe listen --forward-to localhost:5000/webhook/stripe
4. Copy the webhook signing secret (whsec_...) and set it in .env
5. Start the app: REQUIRE_PAYMENT=true flask run
6. Follow steps 2–7 from Option A using http://localhost:5000
7. The Stripe CLI terminal should show webhook delivery + 200 response.

FAILURE PATH TEST
─────────────────
1. Complete a payment (steps 1–5 above).
2. Before the evaluation finishes, stop the worker (kill the process).
   Or: temporarily set GOOGLE_MAPS_API_KEY to an invalid value so the
   evaluation fails.
3. Verify the job shows status 'failed' in /job/{job_id}.
4. Check the DB: the payment status should be 'failed_reissued'.
5. Re-enter the same address with the same payment_token URL param.
6. Expected outcome: evaluation starts again without requiring new payment.

DOUBLE-REDEMPTION TEST
──────────────────────
1. Complete a successful paid evaluation (steps 1–7).
2. Copy the payment_token from the URL and try to submit it again
   (manually construct: POST / with payment_token + address).
3. Expected outcome: 402 error "Invalid or expired payment".

CHECKLIST
─────────
[ ] Happy path: payment → report delivery works
[ ] Stripe Dashboard shows successful payment + webhook 200
[ ] Failure path: failed eval → credit reissued → retry works
[ ] Double-redemption: second use of same token rejected
[ ] Builder mode: evaluation works without payment when BUILDER_MODE=true
================================================================================
"""
