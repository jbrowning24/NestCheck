"""
Request-scoped tracing for NestCheck evaluation debugging.

Provides a thread-local TraceContext that records:
  - Per-stage timing (stage_name, start/end, elapsed_ms, api_calls, errors)
  - Per-outbound-call timing (service, endpoint, elapsed_ms, status, provider status)
  - End-of-request summary (total_elapsed, total_api_calls, outcome)

Usage:
    from nc_trace import TraceContext, get_trace, set_trace, clear_trace

    # In the request handler (app.py):
    ctx = TraceContext(trace_id=request_id)
    set_trace(ctx)
    ...
    ctx.log_summary()
    clear_trace()

    # In API clients (automatically via _traced_get helpers):
    trace = get_trace()
    if trace:
        trace.record_api_call(...)
"""

import time
import threading
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


# =============================================================================
# Data classes for trace records
# =============================================================================

@dataclass
class APICallRecord:
    """One outbound HTTP call (Google Maps, Overpass, WalkScore, etc.)."""
    service: str          # "google_maps" | "overpass" | "walkscore" | "website"
    endpoint: str         # "geocode", "places_nearby", etc.
    elapsed_ms: int
    status_code: int
    provider_status: str = ""   # e.g. Google "OK", "ZERO_RESULTS"
    retried: bool = False
    stage: str = ""             # which evaluation stage was running


@dataclass
class StageRecord:
    """One evaluation stage (geocode, neighborhood, schools, tier1, etc.)."""
    stage_name: str
    start_ts: float = 0.0
    end_ts: float = 0.0
    elapsed_ms: int = 0
    api_calls_made: int = 0
    skipped: bool = False
    error_class: str = ""
    error_message: str = ""


# =============================================================================
# Trace context
# =============================================================================

@dataclass
class TraceContext:
    """Accumulates timing data for a single evaluation request."""
    trace_id: str
    request_start: float = field(default_factory=time.time)
    stages: List[StageRecord] = field(default_factory=list)
    api_calls: List[APICallRecord] = field(default_factory=list)
    model_version: str = ""
    _current_stage: str = ""

    # ------------------------------------------------------------------
    # Stage lifecycle
    # ------------------------------------------------------------------

    def start_stage(self, name: str):
        self._current_stage = name

    def end_stage(self):
        self._current_stage = ""

    def record_stage(
        self,
        stage_name: str,
        start_ts: float,
        end_ts: float,
        skipped: bool = False,
        error_class: str = "",
        error_message: str = "",
    ):
        api_in_stage = sum(1 for c in self.api_calls if c.stage == stage_name)
        rec = StageRecord(
            stage_name=stage_name,
            start_ts=start_ts,
            end_ts=end_ts,
            elapsed_ms=int((end_ts - start_ts) * 1000),
            api_calls_made=api_in_stage,
            skipped=skipped,
            error_class=error_class,
            error_message=error_message,
        )
        self.stages.append(rec)

        status = "SKIP" if skipped else ("ERR" if error_class else "OK")
        err_info = f" err={error_class}: {error_message}" if error_class else ""
        logger.info(
            "  [stage] trace=%s %s %s %dms api_calls=%d%s",
            self.trace_id,
            stage_name,
            status,
            rec.elapsed_ms,
            api_in_stage,
            err_info,
        )

    # ------------------------------------------------------------------
    # API call recording
    # ------------------------------------------------------------------

    def record_api_call(
        self,
        service: str,
        endpoint: str,
        elapsed_ms: int,
        status_code: int,
        provider_status: str = "",
        retried: bool = False,
    ):
        rec = APICallRecord(
            service=service,
            endpoint=endpoint,
            elapsed_ms=elapsed_ms,
            status_code=status_code,
            provider_status=provider_status,
            retried=retried,
            stage=self._current_stage,
        )
        self.api_calls.append(rec)
        logger.info(
            "  [api] trace=%s stage=%s svc=%s ep=%s ms=%d http=%d provider=%s",
            self.trace_id,
            self._current_stage or "-",
            service,
            endpoint,
            elapsed_ms,
            status_code,
            provider_status,
        )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    # Maximum per-call records persisted in summary_dict to prevent bloat.
    MAX_CALL_RECORDS = 500

    def summary_dict(self) -> Dict[str, Any]:
        """Return a summary dict suitable for logging and JSON responses.

        Includes a ``calls`` array with per-call records (capped at
        MAX_CALL_RECORDS) so API cost regressions can be debugged from
        saved snapshots without access to stdout logs.
        """
        total_elapsed = int((time.time() - self.request_start) * 1000)
        completed = [s for s in self.stages if not s.skipped and not s.error_class]
        skipped = [s for s in self.stages if s.skipped]
        errored = [s for s in self.stages if s.error_class and not s.skipped]

        if errored and not completed:
            outcome = "error"
        elif not completed and not errored:
            outcome = "empty"
        elif skipped or errored:
            outcome = "partial"
        else:
            outcome = "success"

        calls = [
            {
                "service": c.service,
                "endpoint": c.endpoint,
                "stage": c.stage,
                "elapsed_ms": c.elapsed_ms,
                "status_code": c.status_code,
            }
            for c in self.api_calls[:self.MAX_CALL_RECORDS]
        ]

        result = {
            "trace_id": self.trace_id,
            "total_elapsed_ms": total_elapsed,
            "total_api_calls": len(self.api_calls),
            "stages_completed": len(completed),
            "stages_skipped": len(skipped),
            "stages_errored": len(errored),
            "final_outcome": outcome,
            "calls": calls,
        }
        if self.model_version:
            result["model_version"] = self.model_version
        return result

    def log_summary(self):
        """Emit a single structured summary log line."""
        s = self.summary_dict()
        logger.info(
            "[trace-summary] trace=%s total_ms=%d api_calls=%d "
            "completed=%d skipped=%d errored=%d outcome=%s",
            s["trace_id"],
            s["total_elapsed_ms"],
            s["total_api_calls"],
            s["stages_completed"],
            s["stages_skipped"],
            s["stages_errored"],
            s["final_outcome"],
        )

    # ------------------------------------------------------------------
    # Serialisation helpers (for /debug endpoint and response metadata)
    # ------------------------------------------------------------------

    def stages_to_list(self) -> List[Dict[str, Any]]:
        return [
            {
                "stage": s.stage_name,
                "elapsed_ms": s.elapsed_ms,
                "api_calls": s.api_calls_made,
                "skipped": s.skipped,
                "error": (
                    f"{s.error_class}: {s.error_message}"
                    if s.error_class else None
                ),
            }
            for s in self.stages
        ]

    def api_calls_to_list(self) -> List[Dict[str, Any]]:
        return [
            {
                "service": c.service,
                "endpoint": c.endpoint,
                "elapsed_ms": c.elapsed_ms,
                "status_code": c.status_code,
                "provider_status": c.provider_status,
                "retried": c.retried,
                "stage": c.stage,
            }
            for c in self.api_calls
        ]

    def full_trace_dict(self) -> Dict[str, Any]:
        """Complete trace data for debug output."""
        summary = self.summary_dict()
        summary["stages"] = self.stages_to_list()
        summary["api_calls"] = self.api_calls_to_list()
        return summary


# =============================================================================
# Thread-local storage
# =============================================================================

_trace_local = threading.local()


def get_trace() -> Optional[TraceContext]:
    """Get the current request's trace context, or None."""
    return getattr(_trace_local, "ctx", None)


def set_trace(ctx: Optional[TraceContext]):
    """Set the trace context for the current thread."""
    _trace_local.ctx = ctx


def clear_trace():
    """Clear the current trace context."""
    _trace_local.ctx = None
