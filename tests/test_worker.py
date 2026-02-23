"""Unit tests for worker.py — background evaluation worker.

Tests cover: payment reissue logic, free tier reissue, job execution flow,
worker loop lifecycle, and error handling paths.
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from models import (
    init_db,
    create_job,
    get_job,
    claim_next_job,
    create_payment,
    update_payment_status,
    redeem_payment,
    get_payment_by_id,
    record_free_tier_usage,
    hash_email,
    check_free_tier_used,
)
from worker import (
    _reissue_payment_if_needed,
    _reissue_free_tier_if_needed,
    _run_job_impl,
    start_worker,
    stop_worker,
    _stop_event,
)


# =========================================================================
# Payment reissue
# =========================================================================

class TestReissuePaymentIfNeeded:
    def test_reissues_redeemed_payment(self):
        job_id = create_job("123 Main St")
        create_payment("pay1", "cs1", "v1", "123 Main St")
        update_payment_status("pay1", "paid")
        redeem_payment("pay1", job_id=job_id)

        _reissue_payment_if_needed(job_id)

        p = get_payment_by_id("pay1")
        assert p["status"] == "failed_reissued"

    def test_no_payment_is_noop(self):
        job_id = create_job("123 Main St")
        # Should not raise
        _reissue_payment_if_needed(job_id)

    def test_pending_payment_not_reissued(self):
        job_id = create_job("123 Main St")
        create_payment("pay1", "cs1", "v1", "123 Main St")
        from models import update_payment_job_id
        update_payment_job_id("pay1", job_id)

        _reissue_payment_if_needed(job_id)

        p = get_payment_by_id("pay1")
        assert p["status"] == "pending"  # unchanged


# =========================================================================
# Free tier reissue
# =========================================================================

class TestReissueFreeTierIfNeeded:
    def test_deletes_free_tier_claim(self):
        eh = hash_email("test@example.com")
        job_id = create_job("123 Main St")
        record_free_tier_usage(eh, "test@example.com", job_id)

        _reissue_free_tier_if_needed(job_id)

        assert check_free_tier_used(eh) is False

    def test_no_free_tier_is_noop(self):
        job_id = create_job("123 Main St")
        # Should not raise
        _reissue_free_tier_if_needed(job_id)


# =========================================================================
# _run_job_impl
# =========================================================================

class TestRunJobImpl:
    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}, clear=False)
    def test_missing_api_key_fails_job(self):
        """When GOOGLE_MAPS_API_KEY is not set, the job should be failed."""
        # Remove the key entirely
        env = os.environ.copy()
        env.pop("GOOGLE_MAPS_API_KEY", None)

        with patch.dict(os.environ, env, clear=True):
            job_id = create_job("123 Main St")
            claim_next_job()

            _run_job_impl(job_id, "123 Main St", visitor_id="v1")

            job = get_job(job_id)
            assert job["status"] == "failed"
            assert "GOOGLE_MAPS_API_KEY" in job["error"]

    @patch("app.result_to_dict")
    @patch("worker.evaluate_property")
    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key", "REQUIRE_PAYMENT": "false"}, clear=False)
    def test_successful_evaluation(self, mock_evaluate, mock_result_to_dict):
        """A successful evaluation should complete the job and save a snapshot."""
        mock_evaluate.return_value = MagicMock()
        mock_result_to_dict.return_value = {
            "verdict": "Good",
            "final_score": 75,
            "passed_tier1": True,
            "address": "123 Main Street",
        }

        job_id = create_job("123 Main St", visitor_id="v1")
        claim_next_job()

        _run_job_impl(job_id, "123 Main St", visitor_id="v1")

        job = get_job(job_id)
        assert job["status"] == "done"
        assert job["result_snapshot_id"] is not None

    @patch("worker.evaluate_property", side_effect=Exception("API error"))
    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False)
    def test_evaluation_exception_fails_job(self, mock_evaluate):
        """An exception during evaluation should fail the job."""
        job_id = create_job("123 Main St", visitor_id="v1")
        claim_next_job()

        _run_job_impl(job_id, "123 Main St", visitor_id="v1")

        job = get_job(job_id)
        assert job["status"] == "failed"
        assert "API error" in job["error"]

    @patch("worker.evaluate_property", side_effect=Exception("boom"))
    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key"}, clear=False)
    def test_failed_job_reissues_payment(self, mock_evaluate):
        """A failed evaluation should reissue the payment credit."""
        job_id = create_job("123 Main St")
        create_payment("pay1", "cs1", "v1", "123 Main St")
        update_payment_status("pay1", "paid")
        redeem_payment("pay1", job_id=job_id)

        claim_next_job()
        _run_job_impl(job_id, "123 Main St")

        p = get_payment_by_id("pay1")
        assert p["status"] == "failed_reissued"

    @patch("app.result_to_dict")
    @patch("worker.evaluate_property")
    @patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-key", "REQUIRE_PAYMENT": "true"}, clear=False)
    def test_free_tier_creates_preview(self, mock_evaluate, mock_result_to_dict):
        """Free tier jobs with REQUIRE_PAYMENT=true should create preview snapshots."""
        mock_evaluate.return_value = MagicMock()
        mock_result_to_dict.return_value = {
            "verdict": "OK",
            "final_score": 60,
            "passed_tier1": True,
            "address": "123 Main St",
        }

        eh = hash_email("user@test.com")
        job_id = create_job("123 Main St", email_hash=eh)
        claim_next_job()

        _run_job_impl(job_id, "123 Main St", email_hash=eh)

        job = get_job(job_id)
        assert job["status"] == "done"

        from models import get_snapshot
        snap = get_snapshot(job["result_snapshot_id"])
        assert snap["is_preview"] == 1


# =========================================================================
# Worker lifecycle
# =========================================================================

class TestWorkerLifecycle:
    def test_start_and_stop(self):
        """Worker thread should start and stop cleanly."""
        start_worker()
        import worker
        assert worker._worker_thread is not None
        assert worker._worker_thread.is_alive()

        stop_worker()
        worker._worker_thread.join(timeout=5)
        assert not worker._worker_thread.is_alive()

    def test_start_idempotent(self):
        """Calling start_worker twice should not create a second thread."""
        start_worker()
        import worker
        t1 = worker._worker_thread

        start_worker()
        t2 = worker._worker_thread
        assert t1 is t2

        stop_worker()
        worker._worker_thread.join(timeout=5)
