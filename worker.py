"""
Background evaluation worker for NestCheck.

Runs property evaluations in a background thread so that POST /
can return a snapshot_id immediately without blocking on the full
evaluation (which takes 60-180s of sequential API calls).

Architecture:
    - In-process queue.Queue (no Redis/Celery needed for v1)
    - Single daemon worker thread consuming jobs
    - Per-job wall-clock timeout (90s default)
    - Per-stage progress written to the DB so /api/snapshot/<id>/status
      can poll and update the UI in real time

Usage (called from app.py at module level):
    from worker import submit_evaluation, start_workers
    start_workers()

    # In a route handler:
    submit_evaluation(snapshot_id, address, api_key, trace_id, visitor_id)
"""

import os
import time
import queue
import logging
import threading
import traceback
from dataclasses import dataclass, field
from typing import Optional, Dict

from nc_trace import TraceContext, set_trace, clear_trace
from models import (
    update_snapshot_status,
    update_snapshot_modules,
    update_snapshot_result,
    log_event,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

JOB_TIMEOUT_S = int(os.environ.get("NESTCHECK_JOB_TIMEOUT", "90"))
NUM_WORKERS = int(os.environ.get("NESTCHECK_WORKERS", "1"))

# ---------------------------------------------------------------------------
# Display-module mapping
# ---------------------------------------------------------------------------
# Maps internal stage names from property_evaluator._timed_stage calls to
# user-visible module groups shown in the snapshot progress UI.

STAGE_TO_MODULE = {
    "geocode": "geocode",
    "bike_score": "neighborhood",
    "neighborhood": "neighborhood",
    "schools": "schools",
    "urban_access": "transit",
    "transit_access": "transit",
    "green_spaces": "green_space",
    "green_escape": "green_space",
    "transit_score": "transit",
    "walk_scores": "transit",
    "tier1_checks": "safety",
    "score_park_access": "scoring",
    "score_third_place": "scoring",
    "score_provisioning": "scoring",
    "score_fitness": "scoring",
    "score_transit_access": "scoring",
}

# Ordered list of display modules for the UI
DISPLAY_MODULES = [
    {"id": "geocode", "label": "Locating address"},
    {"id": "neighborhood", "label": "Scanning neighborhood"},
    {"id": "schools", "label": "Finding schools & childcare"},
    {"id": "green_space", "label": "Evaluating green spaces"},
    {"id": "transit", "label": "Checking transit & walkability"},
    {"id": "safety", "label": "Health & safety checks"},
    {"id": "scoring", "label": "Computing final score"},
]

DISPLAY_MODULE_IDS = [m["id"] for m in DISPLAY_MODULES]


def initial_modules_status():
    """Return the initial modules_status dict (all queued)."""
    return {m["id"]: {"status": "queued", "label": m["label"]} for m in DISPLAY_MODULES}


# ---------------------------------------------------------------------------
# Job definition
# ---------------------------------------------------------------------------

@dataclass
class EvalJob:
    snapshot_id: str
    address: str
    api_key: str
    trace_id: str
    visitor_id: str = ""
    submitted_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Job queue
# ---------------------------------------------------------------------------

_job_queue: queue.Queue = queue.Queue(maxsize=50)


def submit_evaluation(snapshot_id, address, api_key, trace_id, visitor_id=""):
    """Enqueue a background evaluation job. Non-blocking."""
    job = EvalJob(
        snapshot_id=snapshot_id,
        address=address,
        api_key=api_key,
        trace_id=trace_id,
        visitor_id=visitor_id,
    )
    try:
        _job_queue.put_nowait(job)
        logger.info(
            "[worker] Job queued snapshot=%s trace=%s address=%r",
            snapshot_id, trace_id, address,
        )
    except queue.Full:
        logger.error(
            "[worker] Job queue full, cannot enqueue snapshot=%s", snapshot_id
        )
        update_snapshot_status(
            snapshot_id, "failed",
            modules_status=_all_failed("Server busy — evaluation queue is full."),
        )


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

def _all_failed(error_msg):
    """Return modules_status dict with all modules failed."""
    return {
        m["id"]: {"status": "failed", "label": m["label"], "error": error_msg}
        for m in DISPLAY_MODULES
    }


def _run_job(job: EvalJob):
    """Execute a single evaluation job with progress tracking."""
    # Lazy imports to avoid circular deps at module level
    from property_evaluator import PropertyListing, evaluate_property
    from app import result_to_dict, generate_verdict

    snapshot_id = job.snapshot_id
    modules = initial_modules_status()

    logger.info(
        "[worker] Job started snapshot=%s trace=%s address=%r",
        snapshot_id, job.trace_id, job.address,
    )

    # Track which display modules have had at least one stage start
    started_modules = set()
    completed_stages_per_module: Dict[str, int] = {}
    expected_stages_per_module = {
        "geocode": 1,
        "neighborhood": 2,
        "schools": 1,
        "green_space": 2,
        "transit": 4,
        "safety": 1,
        "scoring": 5,
    }

    def on_stage_complete(stage_name, elapsed_ms, error_str):
        """Callback fired by TraceContext after each stage completes."""
        display_mod = STAGE_TO_MODULE.get(stage_name)
        if not display_mod:
            return

        completed_stages_per_module.setdefault(display_mod, 0)
        completed_stages_per_module[display_mod] += 1

        expected = expected_stages_per_module.get(display_mod, 1)
        done_count = completed_stages_per_module[display_mod]

        if error_str:
            # Stage had an error — mark as done (most errors are caught by
            # evaluate_property and the eval continues). Fatal errors like
            # geocode failure will be caught by the outer except block.
            modules[display_mod]["status"] = "done"
            modules[display_mod]["warning"] = error_str
        elif done_count >= expected:
            modules[display_mod]["status"] = "done"
        else:
            modules[display_mod]["status"] = "running"

        modules[display_mod]["elapsed_ms"] = elapsed_ms

        # Mark the next pending module as running
        for mid in DISPLAY_MODULE_IDS:
            if modules[mid]["status"] == "queued":
                # If this is the module right after the one that just completed
                idx_current = DISPLAY_MODULE_IDS.index(display_mod) if display_mod in DISPLAY_MODULE_IDS else -1
                idx_next = DISPLAY_MODULE_IDS.index(mid)
                if idx_next == idx_current + 1:
                    modules[mid]["status"] = "running"
                break

        try:
            update_snapshot_modules(snapshot_id, modules)
        except Exception:
            logger.debug("Failed to update modules for %s", snapshot_id, exc_info=True)

    # Set up trace context
    trace_ctx = TraceContext(trace_id=job.trace_id, on_stage_complete=on_stage_complete)
    set_trace(trace_ctx)

    # Mark job as running
    modules["geocode"]["status"] = "running"
    update_snapshot_status(snapshot_id, "running", modules_status=modules)

    job_start = time.time()
    timed_out = False

    try:
        # Run the evaluation in the current thread (worker thread)
        listing = PropertyListing(address=job.address)
        eval_result = evaluate_property(listing, job.api_key)

        elapsed = time.time() - job_start
        if elapsed > JOB_TIMEOUT_S:
            timed_out = True
            raise TimeoutError(f"Evaluation exceeded {JOB_TIMEOUT_S}s wall clock")

        # Convert to template dict
        result_dict = result_to_dict(eval_result)
        result_dict["verdict"] = generate_verdict(result_dict)

        # Attach trace summary
        trace_summary = trace_ctx.summary_dict()
        result_dict["_trace"] = trace_summary

        # Mark all modules as done
        for mid in DISPLAY_MODULE_IDS:
            if modules[mid]["status"] not in ("done", "failed"):
                modules[mid]["status"] = "done"

        # Persist the full result
        address_norm = result_dict.get("address", job.address)
        update_snapshot_result(snapshot_id, result_dict, address_norm=address_norm)
        update_snapshot_modules(snapshot_id, modules)

        trace_ctx.log_summary()

        logger.info(
            "[worker] Job complete snapshot=%s trace=%s score=%d elapsed=%.1fs",
            snapshot_id, job.trace_id,
            result_dict.get("final_score", 0), elapsed,
        )

        # Log analytics event
        log_event("snapshot_created", snapshot_id=snapshot_id,
                  visitor_id=job.visitor_id,
                  metadata={"address": job.address, "trace_id": job.trace_id})

    except Exception as e:
        elapsed = time.time() - job_start
        trace_ctx.log_summary()

        error_msg = str(e)[:300]
        if timed_out:
            error_msg = f"Evaluation timed out after {JOB_TIMEOUT_S}s"

        logger.error(
            "[worker] Job failed snapshot=%s trace=%s elapsed=%.1fs error=%s",
            snapshot_id, job.trace_id, elapsed, error_msg,
        )
        logger.debug("[worker] Traceback:\n%s", traceback.format_exc())

        # Mark remaining modules as failed/skipped
        for mid in DISPLAY_MODULE_IDS:
            if modules[mid]["status"] in ("queued", "running"):
                modules[mid]["status"] = "failed" if timed_out else "skipped"
                if timed_out:
                    modules[mid]["error"] = "Timed out"

        update_snapshot_status(snapshot_id, "failed", modules_status=modules)

        log_event("evaluation_error", visitor_id=job.visitor_id,
                  metadata={
                      "address": job.address,
                      "error": error_msg,
                      "trace_id": job.trace_id,
                      "snapshot_id": snapshot_id,
                      "trace_summary": trace_ctx.summary_dict(),
                  })

    finally:
        clear_trace()


def _worker_loop():
    """Main worker loop — runs forever in a daemon thread."""
    logger.info("[worker] Background worker started")
    while True:
        try:
            job = _job_queue.get(timeout=5)
        except queue.Empty:
            continue

        try:
            _run_job(job)
        except Exception:
            logger.exception("[worker] Unexpected error in worker loop")
        finally:
            _job_queue.task_done()


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

_started = False


def start_workers(num_workers=None):
    """Start background worker thread(s). Safe to call multiple times."""
    global _started
    if _started:
        return
    _started = True

    n = num_workers or NUM_WORKERS
    for i in range(n):
        t = threading.Thread(target=_worker_loop, name=f"nc-worker-{i}", daemon=True)
        t.start()
        logger.info("[worker] Started worker thread %s", t.name)
