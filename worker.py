"""
Background evaluation worker for the async job queue.

Runs in a dedicated thread per gunicorn worker process. Polls the DB for
queued jobs, claims one atomically, runs evaluate_property() with stage
callbacks to update progress, then saves the snapshot and marks the job
done or failed. Supports graceful shutdown via a stop event.
"""

import os
import logging
import threading
import time

from property_evaluator import PropertyListing, evaluate_property
from nc_trace import TraceContext, set_trace, clear_trace
from models import (
    init_db,
    claim_next_job,
    update_job_stage,
    complete_job,
    fail_job,
    save_snapshot,
    log_event,
    check_return_visit,
    requeue_stale_running_jobs,
    get_payment_by_job_id,
    update_payment_status,
    update_free_tier_snapshot,
    delete_free_tier_usage,
)

logger = logging.getLogger(__name__)

# Poll interval when no job is available (seconds)
POLL_INTERVAL = 2.0

# Stop event: set by the main process to signal the worker thread to exit
_stop_event = threading.Event()
_worker_thread = None


def _reissue_payment_if_needed(job_id: str) -> None:
    """If a failed job had a paid evaluation credit, reissue it.

    Transitions the linked payment from 'redeemed' to 'failed_reissued'
    so the user can retry without paying again.

    Swallows all exceptions — losing a reissue is recoverable (manual DB
    fix), but an unhandled exception here would kill the worker thread.
    """
    try:
        payment = get_payment_by_job_id(job_id)
        if payment and payment["status"] == "redeemed":
            update_payment_status(payment["id"], "failed_reissued")
            logger.info(
                "[worker] Reissued credit for failed evaluation: payment %s, job %s",
                payment["id"], job_id,
            )
    except Exception:
        logger.exception("[worker] Failed to reissue payment credit for job %s", job_id)


def _reissue_free_tier_if_needed(job_id: str) -> None:
    """If a failed job used a free tier credit, delete the claim so the user can retry.

    Mirrors _reissue_payment_if_needed for the free tier path.
    Swallows all exceptions for the same reason.
    """
    try:
        if delete_free_tier_usage(job_id):
            logger.info(
                "[worker] Reissued free tier credit for failed evaluation: job %s",
                job_id,
            )
    except Exception:
        logger.exception("[worker] Failed to reissue free tier credit for job %s", job_id)


def _run_job(job_id: str, address: str, visitor_id: str = None, request_id: str = None, place_id: str = None, email_hash: str = None, persona: str = None, email_raw: str = None) -> None:
    """
    Run a single evaluation job: evaluate, save snapshot, complete or fail.
    Updates current_stage in the DB as evaluation progresses.
    """
    # Push Sentry scope with job context so breadcrumbs/errors have tags
    if os.environ.get("SENTRY_DSN"):
        try:
            import sentry_sdk
            with sentry_sdk.push_scope() as scope:
                scope.set_tag("job_id", job_id)
                scope.set_tag("request_id", request_id or "")
                scope.set_tag("address", (address or "")[:200])
                _run_job_impl(job_id, address, visitor_id, request_id, place_id, email_hash, persona, email_raw)
            return
        except Exception:
            raise  # Re-raise so _worker_loop can handle and capture
    _run_job_impl(job_id, address, visitor_id, request_id, place_id, email_hash, persona, email_raw)


def _run_job_impl(job_id: str, address: str, visitor_id: str = None, request_id: str = None, place_id: str = None, email_hash: str = None, persona: str = None, email_raw: str = None) -> None:
    """Inner job execution (called with or without Sentry scope)."""
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        fail_job(job_id, "GOOGLE_MAPS_API_KEY not configured")
        _reissue_payment_if_needed(job_id)
        _reissue_free_tier_if_needed(job_id)
        log_event(
            "evaluation_error",
            visitor_id=visitor_id,
            metadata={
                "address": address,
                "error": "missing_config",
                "request_id": request_id,
            },
        )
        return

    trace_ctx = TraceContext(trace_id=request_id or job_id)
    set_trace(trace_ctx)

    def on_stage(stage_name: str) -> None:
        update_job_stage(job_id, stage_name)

    try:
        listing = PropertyListing(address=address)
        eval_result = evaluate_property(listing, api_key, on_stage=on_stage, place_id=place_id, persona=persona)

        # Serialize result for snapshot (same as app.py). Lazy import to avoid
        # circular dependency (app imports worker for start_worker).
        from app import result_to_dict

        result = result_to_dict(eval_result)
        trace_summary = trace_ctx.summary_dict()
        result["_trace"] = trace_summary
        address_norm = result.get("address", address)

        on_stage("saving")
        # NES-132: free tier jobs (identified by email_hash) produce preview
        # snapshots when payments are enabled. Paid jobs and REQUIRE_PAYMENT=false
        # produce full (unlocked) snapshots.
        # Read env directly to avoid coupling to app module-level state.
        require_payment = os.environ.get("REQUIRE_PAYMENT", "false").lower() == "true"
        is_preview = bool(require_payment and email_hash)

        snapshot_id = save_snapshot(
            address_input=address,
            address_norm=address_norm,
            result_dict=result,
            is_preview=is_preview,
            email_hash=email_hash,
            email_raw=email_raw,
        )
        complete_job(job_id, snapshot_id)
        if email_hash:
            update_free_tier_snapshot(email_hash, snapshot_id)
        is_return = check_return_visit(visitor_id)
        log_event(
            "snapshot_created",
            snapshot_id=snapshot_id,
            visitor_id=visitor_id,
            metadata={"address": address, "trace_id": trace_summary.get("trace_id")},
        )
        if is_return:
            log_event("return_visit", snapshot_id=snapshot_id, visitor_id=visitor_id)
        logger.info("[worker] Job %s completed -> snapshot %s", job_id, snapshot_id)
    except Exception as e:
        logger.exception("[worker] Job %s failed: %s", job_id, e)
        fail_job(job_id, str(e))
        _reissue_payment_if_needed(job_id)
        _reissue_free_tier_if_needed(job_id)
        log_event(
            "evaluation_error",
            visitor_id=visitor_id,
            metadata={
                "address": address,
                "error": str(e),
                "request_id": request_id,
                "trace_summary": trace_ctx.summary_dict(),
            },
        )
    finally:
        trace_ctx.log_summary()
        clear_trace()


def _worker_loop() -> None:
    """Loop: claim next job, run it, repeat until stop event is set."""
    logger.info("[worker] Evaluation worker thread started")
    while not _stop_event.is_set():
        job = claim_next_job()
        if job:
            job_id = job["job_id"]
            address = job["address"]
            visitor_id = job.get("visitor_id")
            request_id = job.get("request_id")
            place_id = job.get("place_id")
            email_hash = job.get("email_hash")
            persona = job.get("persona")
            email_raw = job.get("email_raw")
            logger.info("[worker] Claimed job %s: %r", job_id, address)
            try:
                _run_job(job_id, address, visitor_id=visitor_id, request_id=request_id, place_id=place_id, email_hash=email_hash, persona=persona, email_raw=email_raw)
            except Exception as e:
                logger.exception("[worker] Unhandled error in job %s", job_id)
                if os.environ.get("SENTRY_DSN"):
                    try:
                        import sentry_sdk
                        with sentry_sdk.push_scope() as scope:
                            scope.set_tag("job_id", job_id)
                            scope.set_tag("request_id", request_id or "")
                            scope.set_tag("address", (address or "")[:200])
                            sentry_sdk.capture_exception(e)
                    except Exception:
                        pass
                fail_job(job_id, str(e))
                _reissue_payment_if_needed(job_id)
                _reissue_free_tier_if_needed(job_id)
        else:
            _stop_event.wait(timeout=POLL_INTERVAL)
    logger.info("[worker] Evaluation worker thread stopped")


def start_worker() -> None:
    """
    Start the background worker thread. Safe to call from the main process
    or from a gunicorn post_fork hook. Only one thread is started per process.
    """
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    # Ensure DB tables exist in this process before worker thread starts.
    # Critical for Railway where each deploy starts with empty filesystem.
    init_db()
    try:
        swept = requeue_stale_running_jobs(max_age_seconds=300)
        if swept:
            logger.warning("[worker] Re-queued %d stale running jobs", swept)
    except Exception:
        logger.exception("[worker] Failed to sweep stale running jobs")
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True)
    _worker_thread.start()


def stop_worker() -> None:
    """Signal the worker thread to stop (for tests or graceful shutdown)."""
    _stop_event.set()
