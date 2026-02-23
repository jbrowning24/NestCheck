"""Unit tests for nc_trace.py — request-scoped tracing.

Tests cover: TraceContext lifecycle, stage recording, API call recording,
summary computation, serialization, and thread-local storage.
"""

import time
import threading

import pytest

from nc_trace import (
    TraceContext,
    APICallRecord,
    StageRecord,
    get_trace,
    set_trace,
    clear_trace,
)


# =========================================================================
# TraceContext basics
# =========================================================================

class TestTraceContextInit:
    def test_defaults(self):
        ctx = TraceContext(trace_id="test-1")
        assert ctx.trace_id == "test-1"
        assert ctx.stages == []
        assert ctx.api_calls == []
        assert ctx.model_version == ""
        assert ctx._current_stage == ""
        assert ctx.request_start > 0


# =========================================================================
# Stage lifecycle
# =========================================================================

class TestStageRecording:
    def test_record_stage(self):
        ctx = TraceContext(trace_id="test-1")
        t0 = time.time()
        t1 = t0 + 0.5

        ctx.record_stage("geocode", t0, t1)

        assert len(ctx.stages) == 1
        assert ctx.stages[0].stage_name == "geocode"
        assert ctx.stages[0].elapsed_ms == 500
        assert ctx.stages[0].skipped is False
        assert ctx.stages[0].error_class == ""

    def test_record_skipped_stage(self):
        ctx = TraceContext(trace_id="test-1")
        ctx.record_stage("schools", time.time(), time.time(), skipped=True)

        assert ctx.stages[0].skipped is True

    def test_record_errored_stage(self):
        ctx = TraceContext(trace_id="test-1")
        ctx.record_stage(
            "tier1", time.time(), time.time(),
            error_class="TimeoutError",
            error_message="API timed out",
        )

        assert ctx.stages[0].error_class == "TimeoutError"
        assert ctx.stages[0].error_message == "API timed out"

    def test_start_and_end_stage(self):
        ctx = TraceContext(trace_id="test-1")
        ctx.start_stage("geocode")
        assert ctx._current_stage == "geocode"

        ctx.end_stage()
        assert ctx._current_stage == ""

    def test_api_calls_attributed_to_stage(self):
        ctx = TraceContext(trace_id="test-1")
        ctx.start_stage("geocode")
        ctx.record_api_call("google_maps", "geocode", 100, 200, "OK")
        ctx.record_api_call("google_maps", "place_details", 50, 200, "OK")
        ctx.end_stage()

        t = time.time()
        ctx.record_stage("geocode", t - 0.15, t)

        assert ctx.stages[0].api_calls_made == 2


# =========================================================================
# API call recording
# =========================================================================

class TestApiCallRecording:
    def test_record_api_call(self):
        ctx = TraceContext(trace_id="test-1")
        ctx.start_stage("neighborhood")
        ctx.record_api_call(
            service="google_maps",
            endpoint="places_nearby",
            elapsed_ms=150,
            status_code=200,
            provider_status="OK",
        )

        assert len(ctx.api_calls) == 1
        call = ctx.api_calls[0]
        assert call.service == "google_maps"
        assert call.endpoint == "places_nearby"
        assert call.elapsed_ms == 150
        assert call.status_code == 200
        assert call.provider_status == "OK"
        assert call.stage == "neighborhood"
        assert call.retried is False

    def test_retried_call(self):
        ctx = TraceContext(trace_id="test-1")
        ctx.record_api_call("overpass", "query", 500, 429, "rate_limit", retried=True)

        assert ctx.api_calls[0].retried is True


# =========================================================================
# Summary
# =========================================================================

class TestSummary:
    def test_success_outcome(self):
        ctx = TraceContext(trace_id="test-1")
        t = time.time()
        ctx.record_stage("geocode", t, t + 0.1)
        ctx.record_stage("neighborhood", t + 0.1, t + 0.2)

        s = ctx.summary_dict()
        assert s["trace_id"] == "test-1"
        assert s["final_outcome"] == "success"
        assert s["stages_completed"] == 2
        assert s["stages_skipped"] == 0
        assert s["stages_errored"] == 0
        assert s["total_api_calls"] == 0
        assert s["total_elapsed_ms"] >= 0

    def test_partial_outcome(self):
        ctx = TraceContext(trace_id="test-1")
        t = time.time()
        ctx.record_stage("geocode", t, t + 0.1)
        ctx.record_stage("schools", t, t, skipped=True)

        s = ctx.summary_dict()
        assert s["final_outcome"] == "partial"
        assert s["stages_skipped"] == 1

    def test_error_outcome(self):
        ctx = TraceContext(trace_id="test-1")
        t = time.time()
        ctx.record_stage("geocode", t, t, error_class="ValueError", error_message="bad")

        s = ctx.summary_dict()
        assert s["final_outcome"] == "error"
        assert s["stages_errored"] == 1

    def test_empty_outcome(self):
        ctx = TraceContext(trace_id="test-1")
        s = ctx.summary_dict()
        assert s["final_outcome"] == "empty"

    def test_model_version_included(self):
        ctx = TraceContext(trace_id="test-1")
        ctx.model_version = "v2.1"
        s = ctx.summary_dict()
        assert s["model_version"] == "v2.1"

    def test_model_version_absent_when_empty(self):
        ctx = TraceContext(trace_id="test-1")
        s = ctx.summary_dict()
        assert "model_version" not in s


# =========================================================================
# Serialization helpers
# =========================================================================

class TestSerialization:
    def test_stages_to_list(self):
        ctx = TraceContext(trace_id="test-1")
        t = time.time()
        ctx.record_stage("geocode", t, t + 0.1)
        ctx.record_stage("schools", t, t, skipped=True)

        stages = ctx.stages_to_list()
        assert len(stages) == 2
        assert stages[0]["stage"] == "geocode"
        assert stages[0]["skipped"] is False
        assert stages[0]["error"] is None
        assert stages[1]["skipped"] is True

    def test_api_calls_to_list(self):
        ctx = TraceContext(trace_id="test-1")
        ctx.record_api_call("google_maps", "geocode", 100, 200, "OK")

        calls = ctx.api_calls_to_list()
        assert len(calls) == 1
        assert calls[0]["service"] == "google_maps"
        assert calls[0]["endpoint"] == "geocode"

    def test_full_trace_dict(self):
        ctx = TraceContext(trace_id="test-1")
        t = time.time()
        ctx.record_stage("geocode", t, t + 0.05)
        ctx.record_api_call("google_maps", "geocode", 50, 200, "OK")

        full = ctx.full_trace_dict()
        assert "stages" in full
        assert "api_calls" in full
        assert full["trace_id"] == "test-1"

    def test_errored_stage_serialized(self):
        ctx = TraceContext(trace_id="test-1")
        t = time.time()
        ctx.record_stage("tier1", t, t, error_class="Timeout", error_message="slow")

        stages = ctx.stages_to_list()
        assert stages[0]["error"] == "Timeout: slow"


# =========================================================================
# Thread-local storage
# =========================================================================

class TestThreadLocal:
    def test_set_and_get(self):
        ctx = TraceContext(trace_id="test-tls")
        set_trace(ctx)
        assert get_trace() is ctx

    def test_clear(self):
        set_trace(TraceContext(trace_id="test"))
        clear_trace()
        assert get_trace() is None

    def test_initially_none(self):
        clear_trace()
        assert get_trace() is None

    def test_isolation_between_threads(self):
        """Each thread should have its own trace context."""
        results = {}

        def worker(name):
            ctx = TraceContext(trace_id=name)
            set_trace(ctx)
            time.sleep(0.01)
            results[name] = get_trace().trace_id
            clear_trace()

        t1 = threading.Thread(target=worker, args=("thread-1",))
        t2 = threading.Thread(target=worker, args=("thread-2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results["thread-1"] == "thread-1"
        assert results["thread-2"] == "thread-2"
