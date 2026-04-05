"""B2B API route handlers."""
import logging
import time
from datetime import datetime, timezone

from flask import g, jsonify, request

from b2b import b2b_bp, limiter
from b2b.auth import require_api_key
from b2b.quota import check_quota, increment_quota
from b2b.sandbox import get_sandbox_snapshot_id
from b2b.schema import build_b2b_response
from models import _get_db, create_job, get_job, get_snapshot

logger = logging.getLogger(__name__)


def _log_usage(key_id: int, address: str, status_code: int,
               response_time_ms: int = None, snapshot_id: str = None) -> None:
    """Write a row to partner_usage_log."""
    conn = _get_db()
    try:
        conn.execute(
            """INSERT INTO partner_usage_log
               (key_id, address, status_code, response_time_ms, snapshot_id)
               VALUES (?, ?, ?, ?, ?)""",
            (key_id, address, status_code, response_time_ms, snapshot_id),
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to write partner usage log")
    finally:
        conn.close()


@b2b_bp.after_request
def add_quota_headers(response):
    """Add quota information headers to every B2B response."""
    if hasattr(g, "partner"):
        _, used, limit = check_quota(g.partner["id"])
        response.headers["X-Quota-Limit"] = str(limit)
        response.headers["X-Quota-Used"] = str(used)
        response.headers["X-Quota-Reset"] = _next_month_start()
    return response


@b2b_bp.route("/evaluate", methods=["POST"])
@require_api_key
@limiter.limit("100/hour", key_func=lambda: str(g.api_key["id"]))
def evaluate():
    """Create a property evaluation job (live) or return sandbox data (test)."""
    start = time.monotonic()
    data = request.get_json(silent=True) or {}
    address = data.get("address", "").strip()

    if not address:
        return jsonify({"error": {
            "code": "invalid_request",
            "message": "Missing required field: address",
            "type": "validation",
        }}), 400

    partner_id = g.partner["id"]
    key_id = g.api_key["id"]

    # Sandbox mode for test keys
    if g.api_key["environment"] == "test":
        snapshot_id = get_sandbox_snapshot_id(address)
        if not snapshot_id:
            return jsonify({"error": {
                "code": "sandbox_not_configured",
                "message": "No sandbox snapshots available. Contact support.",
                "type": "server",
            }}), 503

        snapshot = get_snapshot(snapshot_id)
        if not snapshot:
            return jsonify({"error": {
                "code": "sandbox_not_configured",
                "message": "Sandbox snapshot not found. Contact support.",
                "type": "server",
            }}), 503

        result = snapshot["result"]
        b2b_result = build_b2b_response(result, snapshot_id)
        b2b_result["sandbox"] = True
        b2b_result["sandbox_note"] = (
            "This is sandbox data for integration testing. "
            "Results are pre-computed and may not match the requested address."
        )
        elapsed = int((time.monotonic() - start) * 1000)
        _log_usage(key_id, address, 200, elapsed, snapshot_id)
        return jsonify(b2b_result), 200

    # Live mode — check quota
    allowed, used, limit = check_quota(partner_id)
    if not allowed:
        period_end = _next_month_start()
        elapsed = int((time.monotonic() - start) * 1000)
        _log_usage(key_id, address, 429, elapsed)
        return jsonify({"error": {
            "code": "quota_exceeded",
            "message": f"Monthly quota of {limit} evaluations exceeded. Resets {period_end}.",
            "type": "quota",
        }}), 429

    # Increment quota and create job
    increment_quota(partner_id)
    place_id = data.get("place_id")
    job_id = create_job(address=address, place_id=place_id, partner_id=partner_id)

    elapsed = int((time.monotonic() - start) * 1000)
    _log_usage(key_id, address, 202, elapsed)

    return jsonify({
        "job_id": job_id,
        "status": "queued",
        "poll_url": f"/api/v1/b2b/jobs/{job_id}",
    }), 202


@b2b_bp.route("/jobs/<job_id>", methods=["GET"])
@require_api_key
def job_status(job_id):
    """Poll for evaluation job status. Partners can only see their own jobs."""
    job = get_job(job_id)

    if not job or job.get("partner_id") != g.partner["id"]:
        return jsonify({"error": {
            "code": "not_found",
            "message": "Job not found.",
            "type": "client",
        }}), 404

    resp = {
        "job_id": job_id,
        "status": job["status"],
    }

    if job["current_stage"]:
        resp["stage"] = job["current_stage"]

    if job["status"] == "done" and job["snapshot_id"]:
        snapshot = get_snapshot(job["snapshot_id"])
        if snapshot:
            result = snapshot["result"]
            resp["result"] = build_b2b_response(result, job["snapshot_id"])

    if job["status"] == "failed" and job["error"]:
        resp["error_message"] = job["error"]

    return jsonify(resp), 200


def _next_month_start() -> str:
    """Return ISO date of the first day of next month."""
    now = datetime.now(timezone.utc)
    if now.month == 12:
        return f"{now.year + 1}-01-01"
    return f"{now.year}-{now.month + 1:02d}-01"
