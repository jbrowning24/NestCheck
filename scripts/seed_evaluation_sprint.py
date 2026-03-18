#!/usr/bin/env python3
"""Batch evaluation runner for the NestCheck seed content sprint.

Reads addresses from data/seed_addresses.json, submits each to the
production NestCheck endpoint, polls for completion, and records results
in data/seed_sprint_state.json (resumable on re-run).

Usage:
    # Run all pending addresses:
    python scripts/seed_evaluation_sprint.py

    # Run against a local dev server:
    python scripts/seed_evaluation_sprint.py --base-url http://localhost:5001

    # Retry only failed addresses:
    python scripts/seed_evaluation_sprint.py --retry-failures

    # Show progress summary without running anything:
    python scripts/seed_evaluation_sprint.py --status

    # Export results to CSV for content planning:
    python scripts/seed_evaluation_sprint.py --export-csv

Environment variables:
    NESTCHECK_URL       Base URL (default: https://nestcheck.app)
    BUILDER_SECRET      Builder mode key (bypasses payment gate)
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"

# --- Paths ---
ADDRESSES_FILE = _DATA_DIR / "seed_addresses.json"
STATE_FILE = _DATA_DIR / "seed_sprint_state.json"
EXPORT_CSV = _DATA_DIR / "seed_sprint_results.csv"

# --- Defaults ---
DEFAULT_BASE_URL = "https://nestcheck.org"
POLL_INTERVAL = 3.0        # seconds between job status polls
POLL_TIMEOUT = 180.0       # max seconds to wait for one evaluation
INTER_EVAL_DELAY = 2.0     # seconds between evaluations (be polite)
MAX_RETRIES_PER_ADDRESS = 2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State management (resumable)
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    """Load sprint state from disk. Returns empty state if file doesn't exist."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"evaluations": {}, "started_at": None, "last_run": None}


def _save_state(state: dict) -> None:
    """Persist sprint state to disk atomically."""
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(STATE_FILE)


def _addr_key(address: str) -> str:
    """Normalize address to a stable dict key."""
    return address.strip().lower()


# ---------------------------------------------------------------------------
# API interaction
# ---------------------------------------------------------------------------

HEALTH_CHECK_RETRIES = 3
HEALTH_CHECK_PAUSE = 60.0     # seconds between health check retries
BATCH_SIZE = 10               # pause every N evaluations
BATCH_PAUSE = 30.0            # seconds to pause between batches


def _check_server_health(base_url: str, session: requests.Session) -> bool:
    """Return True if the server responds to a GET / with 200."""
    try:
        resp = session.get(f"{base_url}/", timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def _wait_for_healthy_server(
    base_url: str, session: requests.Session, state: dict,
) -> bool:
    """Wait for the server to become healthy, retrying up to HEALTH_CHECK_RETRIES.

    Returns True if healthy, False if still unhealthy after all retries (state
    is saved before returning False so progress is not lost).
    """
    for attempt in range(1, HEALTH_CHECK_RETRIES + 1):
        logger.warning(
            "Server unhealthy — pausing %ds before retry (%d/%d)",
            int(HEALTH_CHECK_PAUSE), attempt, HEALTH_CHECK_RETRIES,
        )
        time.sleep(HEALTH_CHECK_PAUSE)
        if _check_server_health(base_url, session):
            logger.info("Server healthy again")
            return True
    logger.error("Server unresponsive — stopping sprint")
    _save_state(state)
    return False


def _create_session(base_url: str, builder_secret: str | None) -> requests.Session:
    """Create a requests session with builder cookie and CSRF token."""
    session = requests.Session()
    session.headers["Accept"] = "application/json"
    session.headers["Referer"] = base_url + "/"

    # Set builder cookie to bypass payment gate
    if builder_secret:
        session.cookies.set("nc_builder", builder_secret, domain=base_url.split("//")[1].split("/")[0].split(":")[0])

    # Fetch CSRF token
    try:
        resp = session.get(f"{base_url}/csrf-token", timeout=10)
        resp.raise_for_status()
        csrf_token = resp.json().get("csrf_token", "")
        if csrf_token:
            session.headers["X-CSRFToken"] = csrf_token
            logger.info("CSRF token acquired")
        else:
            logger.warning("No CSRF token returned — POSTs may fail")
    except Exception as e:
        logger.warning("Failed to fetch CSRF token: %s", e)

    return session


def _submit_evaluation(session: requests.Session, base_url: str, address: str) -> dict:
    """Submit an address for evaluation. Returns {job_id} or {snapshot_id, redirect_url}."""
    resp = session.post(
        f"{base_url}/",
        data={"address": address},
        timeout=30,
        allow_redirects=False,
    )

    # Handle redirect (cached snapshot)
    if resp.status_code in (301, 302):
        location = resp.headers.get("Location", "")
        snapshot_id = location.split("/s/")[-1] if "/s/" in location else None
        if snapshot_id:
            return {"snapshot_id": snapshot_id, "cached": True}

    if resp.status_code == 200:
        try:
            data = resp.json()
            return data
        except (ValueError, KeyError):
            pass

    # CSRF might have expired — try refreshing
    if resp.status_code == 400:
        body = {}
        try:
            body = resp.json()
        except ValueError:
            pass
        if body.get("error_code") == "csrf_expired":
            # Refresh CSRF token
            try:
                csrf_resp = session.get(f"{base_url}/csrf-token", timeout=10)
                csrf_resp.raise_for_status()
                new_token = csrf_resp.json().get("csrf_token", "")
                if new_token:
                    session.headers["X-CSRFToken"] = new_token
                    logger.info("CSRF token refreshed, retrying")
                    return _submit_evaluation(session, base_url, address)
            except Exception:
                pass

    raise RuntimeError(f"POST / returned {resp.status_code}: {resp.text[:200]}")


def _poll_job(session: requests.Session, base_url: str, job_id: str) -> dict:
    """Poll until job completes or times out. Returns final job status dict."""
    start = time.monotonic()
    last_stage = None

    while time.monotonic() - start < POLL_TIMEOUT:
        try:
            resp = session.get(f"{base_url}/job/{job_id}", timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("Poll error for %s: %s", job_id, e)
            time.sleep(POLL_INTERVAL)
            continue

        status = data.get("status")
        stage = data.get("current_stage")

        if stage and stage != last_stage:
            logger.info("  Stage: %s", stage)
            last_stage = stage

        if status == "done":
            return data
        if status == "failed":
            return data

        time.sleep(POLL_INTERVAL)

    return {"status": "timeout", "error": f"Timed out after {POLL_TIMEOUT}s"}


# ---------------------------------------------------------------------------
# Result extraction (from snapshot page)
# ---------------------------------------------------------------------------

def _fetch_snapshot_summary(session: requests.Session, base_url: str, snapshot_id: str) -> dict:
    """Fetch key fields from the snapshot JSON export."""
    try:
        resp = session.get(f"{base_url}/api/snapshot/{snapshot_id}/json", timeout=15)
        resp.raise_for_status()
        data = resp.json()

        result = data.get("result", data)
        return {
            "address": result.get("address", ""),
            "final_score": result.get("final_score"),
            "passed_tier1": result.get("passed_tier1"),
            "verdict": result.get("verdict", ""),
            "score_band": result.get("score_band", {}).get("label", ""),
            "tier1_checks": _summarize_tier1(result.get("tier1_checks", [])),
            "tier2_scores": _summarize_tier2(result.get("tier2_scores", [])),
            "health_hits": _extract_health_hits(result.get("tier1_checks", [])),
        }
    except Exception as e:
        logger.warning("Failed to fetch snapshot %s: %s", snapshot_id, e)
        return {}


def _summarize_tier1(checks: list) -> dict:
    """Count tier1 check results."""
    counts = {"CLEAR": 0, "WARNING_DETECTED": 0, "CONFIRMED_ISSUE": 0}
    for c in checks:
        r = c.get("result", "")
        if r in counts:
            counts[r] += 1
    return counts


def _summarize_tier2(scores: list) -> list:
    """Extract dimension name → score pairs."""
    return [
        {"name": s["name"], "points": s.get("points"), "max": s.get("max", 10)}
        for s in scores
    ]


def _extract_health_hits(checks: list) -> list:
    """Extract non-CLEAR health check findings (the content hooks)."""
    hits = []
    for c in checks:
        if c.get("result") != "CLEAR":
            hits.append({
                "name": c.get("name", ""),
                "result": c.get("result", ""),
                "details": c.get("details", ""),
            })
    return hits


# ---------------------------------------------------------------------------
# Content suitability scoring
# ---------------------------------------------------------------------------

def _rate_content_suitability(summary: dict) -> str:
    """Rate an evaluation's content potential: strong / moderate / routine."""
    health_hits = summary.get("health_hits", [])
    score = summary.get("final_score")
    tier2 = summary.get("tier2_scores", [])

    # Strong: has health proximity hits (the primary content hook)
    if any(h["result"] == "CONFIRMED_ISSUE" for h in health_hits):
        return "strong"

    # Strong: failed tier1 entirely
    if not summary.get("passed_tier1"):
        return "strong"

    # Strong: warnings + interesting score spread
    if health_hits and score is not None:
        return "strong"

    # Moderate: high or low extremes, or provisioning gaps
    if score is not None and (score >= 85 or score <= 35):
        return "moderate"

    # Check for provisioning gaps (high walkability but low grocery/coffee)
    dim_scores = {d["name"]: d.get("points") for d in tier2}
    walk_types = ["Coffee & Social Spots", "Provisioning Access", "Fitness Access"]
    low_dims = [n for n in walk_types if dim_scores.get(n) is not None and dim_scores[n] <= 4]
    if low_dims:
        return "moderate"

    return "routine"


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

def run_sprint(
    base_url: str,
    builder_secret: str | None,
    retry_failures: bool = False,
) -> None:
    """Run the seed evaluation sprint."""
    if not ADDRESSES_FILE.exists():
        logger.error("Address file not found: %s", ADDRESSES_FILE)
        logger.error("Create it first (see data/seed_addresses.json)")
        sys.exit(1)

    with open(ADDRESSES_FILE) as f:
        addresses = json.load(f)

    state = _load_state()
    if not state["started_at"]:
        state["started_at"] = datetime.now(timezone.utc).isoformat()

    session = _create_session(base_url, builder_secret)

    # Determine which addresses to process
    pending = []
    for entry in addresses:
        addr = entry["address"]
        key = _addr_key(addr)
        existing = state["evaluations"].get(key)

        if existing:
            status = existing.get("status")
            if status == "done" and not retry_failures:
                continue  # already completed
            if status == "failed" and not retry_failures:
                continue  # failed but not retrying
            if status == "failed" and retry_failures:
                retries = existing.get("retries", 0)
                if retries >= MAX_RETRIES_PER_ADDRESS:
                    logger.info("Skipping %s — max retries (%d) reached", addr, retries)
                    continue
                pending.append(entry)
            elif status == "done" and retry_failures:
                continue  # don't re-run successes
            else:
                pending.append(entry)  # in-progress or unknown
        else:
            pending.append(entry)

    total = len(addresses)
    done_count = sum(1 for v in state["evaluations"].values() if v.get("status") == "done")
    failed_count = sum(1 for v in state["evaluations"].values() if v.get("status") == "failed")

    logger.info("Sprint status: %d/%d done, %d failed, %d pending",
                done_count, failed_count, len(pending), total)

    if not pending:
        logger.info("Nothing to do. Use --retry-failures to re-run failures.")
        return

    for i, entry in enumerate(pending):
        addr = entry["address"]
        key = _addr_key(addr)
        existing = state["evaluations"].get(key, {})
        retries = existing.get("retries", 0)

        logger.info("[%d/%d] Evaluating: %s", done_count + i + 1, total, addr)

        eval_record = {
            "address": addr,
            "town": entry.get("town", ""),
            "rationale": entry.get("rationale", ""),
            "expected_type": entry.get("expected_type", ""),
            "status": "submitting",
            "retries": retries,
            "last_attempt": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Submit
            submit_result = _submit_evaluation(session, base_url, addr)

            if submit_result.get("snapshot_id"):
                # Cached — already evaluated
                snapshot_id = submit_result["snapshot_id"]
                logger.info("  Cached snapshot: %s", snapshot_id)
                eval_record["status"] = "done"
                eval_record["snapshot_id"] = snapshot_id
                eval_record["cached"] = True
            elif submit_result.get("job_id"):
                # New job — poll for completion
                job_id = submit_result["job_id"]
                logger.info("  Job queued: %s", job_id)
                eval_record["job_id"] = job_id
                eval_record["status"] = "polling"

                job_result = _poll_job(session, base_url, job_id)

                if job_result.get("status") == "done":
                    snapshot_id = job_result["snapshot_id"]
                    logger.info("  Done: /s/%s", snapshot_id)
                    eval_record["status"] = "done"
                    eval_record["snapshot_id"] = snapshot_id
                else:
                    error = job_result.get("error", "Unknown failure")
                    logger.warning("  Failed: %s", error)
                    eval_record["status"] = "failed"
                    eval_record["error"] = error
                    eval_record["retries"] = retries + 1
            else:
                logger.warning("  Unexpected response: %s", submit_result)
                eval_record["status"] = "failed"
                eval_record["error"] = f"Unexpected response: {json.dumps(submit_result)[:200]}"
                eval_record["retries"] = retries + 1

        except Exception as e:
            logger.exception("  Error evaluating %s", addr)
            eval_record["status"] = "failed"
            eval_record["error"] = str(e)[:300]
            eval_record["retries"] = retries + 1

        # Fetch snapshot summary for completed evaluations
        if eval_record["status"] == "done" and eval_record.get("snapshot_id"):
            summary = _fetch_snapshot_summary(session, base_url, eval_record["snapshot_id"])
            if summary:
                eval_record["summary"] = summary
                eval_record["content_rating"] = _rate_content_suitability(summary)
                logger.info("  Score: %s | %s | Content: %s",
                           summary.get("final_score", "N/A"),
                           summary.get("verdict", "N/A"),
                           eval_record["content_rating"])
                if summary.get("health_hits"):
                    for hit in summary["health_hits"]:
                        logger.info("  Health hit: %s — %s", hit["name"], hit["details"][:80])

        # Save state after every evaluation (crash-safe)
        state["evaluations"][key] = eval_record
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)

        # Health check after failures or timeouts
        if eval_record["status"] == "failed":
            if not _check_server_health(base_url, session):
                if not _wait_for_healthy_server(base_url, session, state):
                    return  # state already saved

        # Delay between evaluations
        if i < len(pending) - 1:
            # Batch pause every BATCH_SIZE evaluations
            if (i + 1) % BATCH_SIZE == 0:
                logger.info("Batch pause — sleeping %ds", int(BATCH_PAUSE))
                time.sleep(BATCH_PAUSE)
            else:
                time.sleep(INTER_EVAL_DELAY)

    # Final summary
    done_count = sum(1 for v in state["evaluations"].values() if v.get("status") == "done")
    failed_count = sum(1 for v in state["evaluations"].values() if v.get("status") == "failed")
    strong = sum(1 for v in state["evaluations"].values() if v.get("content_rating") == "strong")
    moderate = sum(1 for v in state["evaluations"].values() if v.get("content_rating") == "moderate")

    logger.info("=" * 60)
    logger.info("Sprint complete: %d/%d done, %d failed", done_count, total, failed_count)
    logger.info("Content ratings: %d strong, %d moderate, %d routine",
                strong, moderate, done_count - strong - moderate)
    logger.info("State saved to: %s", STATE_FILE)


# ---------------------------------------------------------------------------
# Status and export
# ---------------------------------------------------------------------------

def show_status() -> None:
    """Print sprint progress summary."""
    state = _load_state()
    evals = state.get("evaluations", {})

    if not evals:
        print("No evaluations recorded yet.")
        return

    total = len(evals)
    done = [v for v in evals.values() if v.get("status") == "done"]
    failed = [v for v in evals.values() if v.get("status") == "failed"]
    strong = [v for v in done if v.get("content_rating") == "strong"]
    moderate = [v for v in done if v.get("content_rating") == "moderate"]
    routine = [v for v in done if v.get("content_rating") == "routine"]

    print(f"\nSeed Sprint Status")
    print(f"{'=' * 50}")
    print(f"Total addresses:    {total}")
    print(f"Completed:          {len(done)}")
    print(f"Failed:             {len(failed)}")
    print(f"")
    print(f"Content Ratings:")
    print(f"  Strong:           {len(strong)}")
    print(f"  Moderate:         {len(moderate)}")
    print(f"  Routine:          {len(routine)}")

    if strong:
        print(f"\nStrong Content Candidates:")
        print(f"{'-' * 50}")
        for v in strong:
            s = v.get("summary", {})
            addr = s.get("address", v.get("address", ""))
            score = s.get("final_score", "N/A")
            hits = s.get("health_hits", [])
            hit_summary = "; ".join(f"{h['name']}: {h['details'][:60]}" for h in hits[:3])
            print(f"  {addr}")
            print(f"    Score: {score} | Hits: {hit_summary or 'none'}")
            print(f"    /s/{v.get('snapshot_id', '?')}")
            print()

    if failed:
        print(f"\nFailed ({len(failed)}):")
        print(f"{'-' * 50}")
        for v in failed:
            print(f"  {v.get('address', '?')} — {v.get('error', 'unknown')[:80]}")


def export_csv() -> None:
    """Export sprint results to CSV for content planning."""
    state = _load_state()
    evals = state.get("evaluations", {})
    done = [v for v in evals.values() if v.get("status") == "done"]

    if not done:
        print("No completed evaluations to export.")
        return

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(EXPORT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "address", "town", "snapshot_id", "snapshot_url",
            "final_score", "passed_tier1", "verdict", "score_band",
            "content_rating", "health_hits", "expected_type", "rationale",
            "tier1_clear", "tier1_warning", "tier1_issue",
        ])

        for v in sorted(done, key=lambda x: x.get("content_rating", "z")):
            s = v.get("summary", {})
            t1 = s.get("tier1_checks", {})
            hits = s.get("health_hits", [])
            hit_text = "; ".join(
                f"{h['name']}: {h['details'][:80]}" for h in hits
            )

            writer.writerow([
                s.get("address", v.get("address", "")),
                v.get("town", ""),
                v.get("snapshot_id", ""),
                f"https://nestcheck.app/s/{v.get('snapshot_id', '')}",
                s.get("final_score", ""),
                s.get("passed_tier1", ""),
                s.get("verdict", ""),
                s.get("score_band", ""),
                v.get("content_rating", ""),
                hit_text,
                v.get("expected_type", ""),
                v.get("rationale", ""),
                t1.get("CLEAR", 0),
                t1.get("WARNING_DETECTED", 0),
                t1.get("CONFIRMED_ISSUE", 0),
            ])

    print(f"Exported {len(done)} evaluations to {EXPORT_CSV}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="NestCheck seed evaluation sprint runner"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("NESTCHECK_URL", DEFAULT_BASE_URL),
        help="NestCheck base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--builder-secret",
        default=os.environ.get("BUILDER_SECRET"),
        help="Builder mode secret (default: from BUILDER_SECRET env var)",
    )
    parser.add_argument(
        "--retry-failures",
        action="store_true",
        help="Re-run failed evaluations (up to max retries per address)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show sprint progress summary and exit",
    )
    parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Export completed results to CSV and exit",
    )

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.export_csv:
        export_csv()
        return

    if not args.builder_secret:
        logger.error("BUILDER_SECRET is required (env var or --builder-secret)")
        logger.error("Builder mode bypasses the payment gate for batch evaluations.")
        sys.exit(1)

    run_sprint(
        base_url=args.base_url.rstrip("/"),
        builder_secret=args.builder_secret,
        retry_failures=args.retry_failures,
    )


if __name__ == "__main__":
    main()
