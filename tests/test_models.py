"""Unit tests for models.py — DB persistence layer.

Covers: snapshots CRUD, event logging, job queue lifecycle,
overpass/weather cache with TTL, payment operations, and free tier usage.
"""

import json
import time
from datetime import datetime, timezone, timedelta

import pytest

from models import (
    init_db,
    generate_snapshot_id,
    save_snapshot,
    get_snapshot,
    unlock_snapshot,
    increment_view_count,
    get_og_image,
    save_og_image,
    log_event,
    check_return_visit,
    get_event_counts,
    get_recent_events,
    get_recent_snapshots,
    create_job,
    get_job,
    claim_next_job,
    update_job_stage,
    complete_job,
    fail_job,
    cancel_queued_job,
    requeue_stale_running_jobs,
    overpass_cache_key,
    _check_cache_ttl,
    get_overpass_cache,
    set_overpass_cache,
    get_weather_cache,
    set_weather_cache,
    create_payment,
    get_payment_by_session,
    get_payment_by_id,
    update_payment_status,
    redeem_payment,
    update_payment_job_id,
    get_payment_by_job_id,
    hash_email,
    check_free_tier_used,
    record_free_tier_usage,
    delete_free_tier_usage,
    update_free_tier_snapshot,
    _get_db,
    _return_conn,
)


# =========================================================================
# Snapshot ID generation
# =========================================================================

class TestGenerateSnapshotId:
    def test_length(self):
        sid = generate_snapshot_id()
        assert len(sid) == 8

    def test_unique(self):
        ids = {generate_snapshot_id() for _ in range(100)}
        assert len(ids) == 100

    def test_hex_characters(self):
        sid = generate_snapshot_id()
        assert all(c in "0123456789abcdef" for c in sid)


# =========================================================================
# Snapshot CRUD
# =========================================================================

class TestSaveAndGetSnapshot:
    def test_round_trip(self):
        result = {"verdict": "Great", "final_score": 85, "passed_tier1": True}
        sid = save_snapshot("123 Main St", "123 Main Street", result)
        snap = get_snapshot(sid)

        assert snap is not None
        assert snap["address_input"] == "123 Main St"
        assert snap["address_norm"] == "123 Main Street"
        assert snap["verdict"] == "Great"
        assert snap["final_score"] == 85
        assert snap["passed_tier1"] == 1
        assert snap["is_preview"] == 0
        assert snap["view_count"] == 0
        assert snap["result"]["final_score"] == 85

    def test_preview_flag(self):
        result = {"verdict": "OK", "final_score": 50, "passed_tier1": False}
        sid = save_snapshot("1 Elm", "1 Elm St", result, is_preview=True)
        snap = get_snapshot(sid)
        assert snap["is_preview"] == 1

    def test_missing_snapshot_returns_none(self):
        assert get_snapshot("nonexistent") is None

    def test_norm_defaults_to_input(self):
        result = {"verdict": "OK", "final_score": 50}
        sid = save_snapshot("1 Elm", None, result)
        snap = get_snapshot(sid)
        assert snap["address_norm"] == "1 Elm"


class TestUnlockSnapshot:
    def test_unlock_preview(self):
        result = {"verdict": "OK", "final_score": 50}
        sid = save_snapshot("1 Elm", "1 Elm St", result, is_preview=True)

        assert unlock_snapshot(sid) is True
        snap = get_snapshot(sid)
        assert snap["is_preview"] == 0

    def test_unlock_non_preview_is_idempotent(self):
        result = {"verdict": "OK", "final_score": 50}
        sid = save_snapshot("1 Elm", "1 Elm St", result, is_preview=False)
        assert unlock_snapshot(sid) is False

    def test_unlock_twice_returns_false_second_time(self):
        result = {"verdict": "OK", "final_score": 50}
        sid = save_snapshot("1 Elm", "1 Elm St", result, is_preview=True)
        assert unlock_snapshot(sid) is True
        assert unlock_snapshot(sid) is False


class TestIncrementViewCount:
    def test_increments(self):
        result = {"verdict": "OK", "final_score": 50}
        sid = save_snapshot("1 Elm", "1 Elm St", result)

        increment_view_count(sid)
        increment_view_count(sid)
        increment_view_count(sid)

        snap = get_snapshot(sid)
        assert snap["view_count"] == 3


class TestOgImage:
    def test_save_and_retrieve(self):
        result = {"verdict": "OK", "final_score": 50}
        sid = save_snapshot("1 Elm", "1 Elm St", result)

        assert get_og_image(sid) is None

        png = b"\x89PNG\r\n\x1a\nfake"
        save_og_image(sid, png)

        retrieved = get_og_image(sid)
        assert retrieved == png

    def test_missing_snapshot_returns_none(self):
        assert get_og_image("nonexistent") is None


# =========================================================================
# Analytics events
# =========================================================================

class TestLogEvent:
    def test_basic_event(self):
        log_event("snapshot_created", snapshot_id="abc123", visitor_id="v1")
        counts = get_event_counts()
        assert counts.get("snapshot_created") == 1

    def test_event_with_metadata(self):
        log_event("evaluation_error", metadata={"error": "timeout"})
        events = get_recent_events(limit=1)
        assert len(events) == 1
        meta = json.loads(events[0]["metadata"])
        assert meta["error"] == "timeout"

    def test_multiple_event_types(self):
        log_event("snapshot_created")
        log_event("snapshot_created")
        log_event("snapshot_viewed")
        counts = get_event_counts()
        assert counts["snapshot_created"] == 2
        assert counts["snapshot_viewed"] == 1


class TestCheckReturnVisit:
    def test_no_visitor_returns_false(self):
        assert check_return_visit(None) is False
        assert check_return_visit("") is False

    def test_return_visit_detected(self):
        log_event("snapshot_created", visitor_id="v1")
        assert check_return_visit("v1") is True

    def test_different_visitor_not_detected(self):
        log_event("snapshot_created", visitor_id="v1")
        assert check_return_visit("v2") is False


class TestGetRecentSnapshots:
    def test_returns_recent(self):
        # Clean up snapshots from other tests (conftest only clears some tables)
        conn = _get_db()
        conn.execute("DELETE FROM snapshots")
        conn.commit()
        _return_conn(conn)

        result = {"verdict": "OK", "final_score": 50}
        save_snapshot("1 Elm", "1 Elm St", result)
        save_snapshot("2 Oak", "2 Oak Ave", result)

        snaps = get_recent_snapshots(limit=10)
        assert len(snaps) == 2


class TestGetRecentEvents:
    def test_respects_limit(self):
        for i in range(5):
            log_event("test_event", visitor_id=f"v{i}")

        events = get_recent_events(limit=3)
        assert len(events) == 3


# =========================================================================
# Job queue lifecycle
# =========================================================================

class TestCreateAndGetJob:
    def test_create_basic(self):
        job_id = create_job("123 Main St")
        assert len(job_id) == 12

        job = get_job(job_id)
        assert job is not None
        assert job["address"] == "123 Main St"
        assert job["status"] == "queued"
        assert job["visitor_id"] is None

    def test_create_with_all_fields(self):
        job_id = create_job(
            "456 Oak Ave",
            visitor_id="v1",
            request_id="req1",
            place_id="ChIJ123",
            email_hash="abc123",
            persona="commuter",
        )
        job = get_job(job_id)
        assert job["visitor_id"] == "v1"
        assert job["request_id"] == "req1"
        assert job["place_id"] == "ChIJ123"
        assert job["email_hash"] == "abc123"
        assert job["persona"] == "commuter"

    def test_missing_job_returns_none(self):
        assert get_job("nonexistent") is None


class TestClaimNextJob:
    def test_claim_oldest_first(self):
        j1 = create_job("first")
        j2 = create_job("second")

        claimed = claim_next_job()
        assert claimed is not None
        assert claimed["job_id"] == j1
        assert claimed["status"] == "running"
        assert claimed["started_at"] is not None

    def test_claim_skips_running(self):
        j1 = create_job("first")
        j2 = create_job("second")

        claim_next_job()  # claims j1
        claimed = claim_next_job()  # should claim j2
        assert claimed["job_id"] == j2

    def test_no_queued_returns_none(self):
        assert claim_next_job() is None

    def test_claim_returns_none_when_all_claimed(self):
        create_job("only one")
        claim_next_job()
        assert claim_next_job() is None


class TestUpdateJobStage:
    def test_updates_stage(self):
        job_id = create_job("123 Main St")
        claim_next_job()

        update_job_stage(job_id, "geocoding")
        job = get_job(job_id)
        assert job["current_stage"] == "geocoding"

    def test_no_update_if_not_running(self):
        job_id = create_job("123 Main St")
        # job is still queued, not running
        update_job_stage(job_id, "geocoding")
        job = get_job(job_id)
        assert job["current_stage"] is None


class TestCompleteJob:
    def test_marks_done(self):
        job_id = create_job("123 Main St")
        claim_next_job()
        complete_job(job_id, "snap123")

        job = get_job(job_id)
        assert job["status"] == "done"
        assert job["result_snapshot_id"] == "snap123"
        assert job["completed_at"] is not None
        assert job["current_stage"] is None


class TestFailJob:
    def test_marks_failed(self):
        job_id = create_job("123 Main St")
        claim_next_job()
        fail_job(job_id, "API timeout")

        job = get_job(job_id)
        assert job["status"] == "failed"
        assert job["error"] == "API timeout"
        assert job["completed_at"] is not None

    def test_truncates_long_error(self):
        job_id = create_job("123 Main St")
        claim_next_job()
        fail_job(job_id, "x" * 5000)

        job = get_job(job_id)
        assert len(job["error"]) == 2000


class TestCancelQueuedJob:
    def test_cancel_queued(self):
        job_id = create_job("123 Main St")
        assert cancel_queued_job(job_id, "duplicate") is True

        job = get_job(job_id)
        assert job["status"] == "failed"
        assert job["error"] == "duplicate"

    def test_cannot_cancel_running(self):
        job_id = create_job("123 Main St")
        claim_next_job()
        assert cancel_queued_job(job_id, "too late") is False

        job = get_job(job_id)
        assert job["status"] == "running"


class TestRequeueStaleRunningJobs:
    def test_requeues_old_running_job(self):
        job_id = create_job("123 Main St")
        claimed = claim_next_job()

        # Manually backdate started_at to simulate a stale job
        conn = _get_db()
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
        conn.execute(
            "UPDATE evaluation_jobs SET started_at = ? WHERE job_id = ?",
            (old_time, job_id),
        )
        conn.commit()
        _return_conn(conn)

        count = requeue_stale_running_jobs(max_age_seconds=300)
        assert count == 1

        job = get_job(job_id)
        assert job["status"] == "queued"
        assert job["started_at"] is None

    def test_does_not_requeue_recent(self):
        job_id = create_job("123 Main St")
        claim_next_job()

        count = requeue_stale_running_jobs(max_age_seconds=300)
        assert count == 0


# =========================================================================
# Overpass cache
# =========================================================================

class TestOverpassCacheKey:
    def test_deterministic(self):
        q = "[out:json];node(1,2,3,4);out;"
        assert overpass_cache_key(q) == overpass_cache_key(q)

    def test_different_queries_differ(self):
        k1 = overpass_cache_key("query1")
        k2 = overpass_cache_key("query2")
        assert k1 != k2


class TestCheckCacheTtl:
    def test_recent_is_valid(self):
        recent = datetime.now(timezone.utc).isoformat()
        assert _check_cache_ttl(recent, 7) is True

    def test_old_is_expired(self):
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        assert _check_cache_ttl(old, 7) is False

    def test_none_timestamp_assumed_valid(self):
        assert _check_cache_ttl(None, 7) is True

    def test_datetime_object_input(self):
        recent = datetime.now(timezone.utc)
        assert _check_cache_ttl(recent, 7) is True


class TestOverpassCache:
    def test_set_and_get(self):
        set_overpass_cache("key1", '{"elements":[]}')
        result = get_overpass_cache("key1")
        assert result == '{"elements":[]}'

    def test_miss_returns_none(self):
        assert get_overpass_cache("nonexistent") is None

    def test_overwrite(self):
        set_overpass_cache("key1", '{"v":1}')
        set_overpass_cache("key1", '{"v":2}')
        result = get_overpass_cache("key1")
        assert result == '{"v":2}'


class TestWeatherCache:
    def test_set_and_get(self):
        set_weather_cache("41.00,-73.00", '{"annual_avg_high_f":60}')
        result = get_weather_cache("41.00,-73.00")
        assert result == '{"annual_avg_high_f":60}'

    def test_miss_returns_none(self):
        assert get_weather_cache("nonexistent") is None


# =========================================================================
# Payment operations
# =========================================================================

class TestCreateAndGetPayment:
    def test_create_and_lookup_by_session(self):
        create_payment("pay1", "cs_test_123", "v1", "123 Main St")
        p = get_payment_by_session("cs_test_123")
        assert p is not None
        assert p["id"] == "pay1"
        assert p["status"] == "pending"
        assert p["address"] == "123 Main St"

    def test_lookup_by_id(self):
        create_payment("pay2", "cs_test_456", "v1", "456 Oak Ave")
        p = get_payment_by_id("pay2")
        assert p is not None
        assert p["stripe_session_id"] == "cs_test_456"

    def test_missing_payment_returns_none(self):
        assert get_payment_by_session("nonexistent") is None
        assert get_payment_by_id("nonexistent") is None

    def test_create_with_snapshot_id(self):
        create_payment("pay3", "cs_test_789", "v1", "789 Elm", snapshot_id="snap1")
        p = get_payment_by_id("pay3")
        assert p["snapshot_id"] == "snap1"


class TestUpdatePaymentStatus:
    def test_unconditional_update(self):
        create_payment("pay1", "cs1", "v1", "123 Main")
        assert update_payment_status("pay1", "paid") is True

        p = get_payment_by_id("pay1")
        assert p["status"] == "paid"

    def test_conditional_update_succeeds(self):
        create_payment("pay1", "cs1", "v1", "123 Main")
        assert update_payment_status("pay1", "paid", expected_status="pending") is True

    def test_conditional_update_fails_on_mismatch(self):
        create_payment("pay1", "cs1", "v1", "123 Main")
        assert update_payment_status("pay1", "paid", expected_status="redeemed") is False


class TestRedeemPayment:
    def test_redeem_paid(self):
        create_payment("pay1", "cs1", "v1", "123 Main")
        update_payment_status("pay1", "paid")

        assert redeem_payment("pay1", job_id="job1") is True

        p = get_payment_by_id("pay1")
        assert p["status"] == "redeemed"
        assert p["redeemed_at"] is not None
        assert p["job_id"] == "job1"

    def test_cannot_redeem_pending(self):
        create_payment("pay1", "cs1", "v1", "123 Main")
        assert redeem_payment("pay1") is False

    def test_double_redeem_rejected(self):
        create_payment("pay1", "cs1", "v1", "123 Main")
        update_payment_status("pay1", "paid")
        redeem_payment("pay1")
        assert redeem_payment("pay1") is False

    def test_redeem_failed_reissued(self):
        create_payment("pay1", "cs1", "v1", "123 Main")
        update_payment_status("pay1", "failed_reissued")
        assert redeem_payment("pay1", job_id="job2") is True


class TestUpdatePaymentJobId:
    def test_links_job(self):
        create_payment("pay1", "cs1", "v1", "123 Main")
        update_payment_job_id("pay1", "job1")
        p = get_payment_by_id("pay1")
        assert p["job_id"] == "job1"


class TestGetPaymentByJobId:
    def test_lookup(self):
        create_payment("pay1", "cs1", "v1", "123 Main")
        update_payment_job_id("pay1", "job1")
        p = get_payment_by_job_id("job1")
        assert p is not None
        assert p["id"] == "pay1"

    def test_missing_returns_none(self):
        assert get_payment_by_job_id("nonexistent") is None


# =========================================================================
# Free tier usage
# =========================================================================

class TestHashEmail:
    def test_deterministic(self):
        assert hash_email("test@example.com") == hash_email("test@example.com")

    def test_case_insensitive(self):
        assert hash_email("Test@Example.COM") == hash_email("test@example.com")

    def test_strips_whitespace(self):
        assert hash_email("  test@example.com  ") == hash_email("test@example.com")


class TestFreeTierUsage:
    def test_record_and_check(self):
        eh = hash_email("test@example.com")
        assert check_free_tier_used(eh) is False

        assert record_free_tier_usage(eh, "test@example.com", "job1") is True
        assert check_free_tier_used(eh) is True

    def test_duplicate_rejected(self):
        eh = hash_email("test@example.com")
        assert record_free_tier_usage(eh, "test@example.com", "job1") is True
        assert record_free_tier_usage(eh, "test@example.com", "job2") is False

    def test_delete(self):
        eh = hash_email("test@example.com")
        record_free_tier_usage(eh, "test@example.com", "job1")

        assert delete_free_tier_usage("job1") is True
        assert check_free_tier_used(eh) is False

    def test_delete_nonexistent(self):
        assert delete_free_tier_usage("nonexistent") is False

    def test_update_snapshot(self):
        eh = hash_email("test@example.com")
        record_free_tier_usage(eh, "test@example.com", "job1")
        update_free_tier_snapshot(eh, "snap1")

        conn = _get_db()
        row = conn.execute(
            "SELECT snapshot_id FROM free_tier_usage WHERE email_hash = ?", (eh,)
        ).fetchone()
        _return_conn(conn)
        assert row["snapshot_id"] == "snap1"
