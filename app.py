import os
import io
import csv
import logging
import uuid
import traceback
from functools import wraps
import requests
from flask import (
    Flask, request, render_template, redirect, url_for,
    make_response, abort, jsonify, g, Response
)
from dotenv import load_dotenv
from property_evaluator import (
    PropertyListing, evaluate_property, CheckResult
)
from urban_access import urban_access_result_to_dict
from models import (
    init_db, save_snapshot, get_snapshot, increment_view_count,
    log_event, check_return_visit, get_event_counts,
    get_recent_events, get_recent_snapshots,
)

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nestcheck-dev-key')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup: one-time env diagnostics (always runs, even when key IS present)
# ---------------------------------------------------------------------------
_startup_key = os.environ.get("GOOGLE_MAPS_API_KEY")
_startup_builder = os.environ.get("BUILDER_MODE", "")
logger.info(
    "ENV CHECK: GOOGLE_MAPS_API_KEY present=%s length=%d",
    _startup_key is not None,
    len(_startup_key) if _startup_key else 0,
)
logger.info(
    "ENV CHECK: BUILDER_MODE=%r effective=%s",
    _startup_builder,
    _startup_builder.lower() == "true",
)
if not _startup_key:
    logger.warning(
        "GOOGLE_MAPS_API_KEY is not set. "
        "Real evaluations will fail. "
        "If BUILDER_MODE=true, demo evaluations will still work."
    )
del _startup_key, _startup_builder


# ---------------------------------------------------------------------------
# Request ID middleware — every request gets a unique ID for tracing
# ---------------------------------------------------------------------------
def _generate_request_id():
    return uuid.uuid4().hex[:10]

# ---------------------------------------------------------------------------
# Feature config — togglable for future pack logic
# ---------------------------------------------------------------------------
# TODO [PACK_LOGIC]: When introducing paid packs, move these to a per-user
# config that checks entitlements. Metrics to justify: >=100 snapshots/week
# with >=15% share rate and >=10% return-visit rate.
FEATURE_CONFIG = {
    "max_evaluations_per_day": None,   # None = unlimited (free phase)
    "enrichments_enabled": True,       # all enrichments on
    "share_enabled": True,             # sharing always on
    # TODO [PACK_LOGIC]: Add keys like "pdf_export", "saved_dashboard",
    # "comparison_mode" here when packs ship.
}

# ---------------------------------------------------------------------------
# Builder mode
# ---------------------------------------------------------------------------
BUILDER_MODE_ENV = os.environ.get("BUILDER_MODE", "").lower() == "true"
BUILDER_SECRET = os.environ.get(
    "BUILDER_SECRET", "nestcheck-builder-2024"
)


def _is_builder(req):
    """
    Check if current request is in builder mode.

    Enabled if:
      1. BUILDER_MODE=true env var is set, OR
      2. A signed cookie 'nc_builder' matches the secret, OR
      3. Query param ?builder_key=<secret> is present (sets cookie for session)
    """
    if BUILDER_MODE_ENV:
        return True
    if req.cookies.get("nc_builder") == BUILDER_SECRET:
        return True
    if req.args.get("builder_key") == BUILDER_SECRET:
        return True
    return False


@app.before_request
def _set_request_context():
    """Set builder mode, visitor ID, and request ID on every request."""
    g.request_id = _generate_request_id()
    g.is_builder = _is_builder(request)

    # Visitor ID: anonymous, cookie-based, for return-visit tracking
    g.visitor_id = request.cookies.get("nc_vid")
    if not g.visitor_id:
        g.visitor_id = uuid.uuid4().hex[:12]
        g.set_visitor_cookie = True
    else:
        g.set_visitor_cookie = False


@app.after_request
def _after_request(response):
    """Set cookies after request if needed."""
    # Set visitor ID cookie (1 year)
    if getattr(g, "set_visitor_cookie", False):
        response.set_cookie(
            "nc_vid", g.visitor_id,
            max_age=365 * 24 * 3600, httponly=True, samesite="Lax"
        )

    # Set builder cookie if activated via query param
    if request.args.get("builder_key") == BUILDER_SECRET:
        response.set_cookie(
            "nc_builder", BUILDER_SECRET,
            max_age=90 * 24 * 3600, httponly=True, samesite="Lax"
        )

    return response


# ---------------------------------------------------------------------------
# Verdict generation
# ---------------------------------------------------------------------------

def generate_verdict(result_dict):
    """Generate a one-line verdict based on the evaluation result."""
    score = result_dict.get("final_score", 0)
    passed = result_dict.get("passed_tier1", False)

    if not passed:
        return "Does not meet baseline requirements"

    if score >= 85:
        return "Exceptional daily-life match"
    elif score >= 70:
        return "Strong daily-life match"
    elif score >= 55:
        return "Solid foundation with trade-offs"
    elif score >= 40:
        return "Compromised walkability — car likely needed"
    else:
        return "Significant daily-life gaps"


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_green_escape(evaluation):
    """Serialize GreenEscapeEvaluation to template dict."""
    if not evaluation:
        return None

    best_park = None
    if evaluation.best_daily_park:
        p = evaluation.best_daily_park
        best_park = {
            "name": p.name,
            "rating": p.rating,
            "user_ratings_total": p.user_ratings_total,
            "walk_time_min": p.walk_time_min,
            "types_display": p.types_display,
            "daily_walk_value": p.daily_walk_value,
            "criteria_status": p.criteria_status,
            "criteria_reasons": p.criteria_reasons,
            "subscores": [
                {
                    "name": s.name,
                    "score": s.score,
                    "max_score": s.max_score,
                    "reason": s.reason,
                    "is_estimate": s.is_estimate,
                }
                for s in p.subscores
            ],
            "reasons": p.reasons,
            "osm_enriched": p.osm_enriched,
            "osm_area_sqm": p.osm_area_sqm,
            "osm_path_count": p.osm_path_count,
            "osm_has_trail": p.osm_has_trail,
            "osm_nature_tags": p.osm_nature_tags,
        }

    nearby = []
    for s in evaluation.nearby_green_spaces:
        nearby.append({
            "name": s.name,
            "rating": s.rating,
            "user_ratings_total": s.user_ratings_total,
            "walk_time_min": s.walk_time_min,
            "daily_walk_value": s.daily_walk_value,
            "criteria_status": s.criteria_status,
            "criteria_reasons": s.criteria_reasons,
        })

    return {
        "best_daily_park": best_park,
        "nearby_green_spaces": nearby,
        "green_escape_score_0_10": evaluation.green_escape_score_0_10,
        "messages": evaluation.messages,
        "criteria": evaluation.criteria,
    }


def _serialize_urban_access(urban_access):
    """Serialize UrbanAccessProfile to template dict."""
    if not urban_access:
        return None

    primary_transit = None
    if urban_access.primary_transit:
        pt = urban_access.primary_transit
        primary_transit = {
            "name": pt.name,
            "mode": pt.mode,
            "walk_time_min": pt.walk_time_min,
            "drive_time_min": pt.drive_time_min,
            "parking_available": pt.parking_available,
            "frequency_class": pt.frequency_class,
        }

    major_hub = None
    if urban_access.major_hub:
        mh = urban_access.major_hub
        major_hub = {
            "name": mh.name,
            "travel_time_min": mh.travel_time_min,
            "transit_mode": mh.transit_mode,
            "route_summary": mh.route_summary,
        }

    # Engine result (primary hub commute + reachability hubs)
    engine = None
    if urban_access.engine_result:
        engine = urban_access_result_to_dict(urban_access.engine_result)

    return {
        "primary_transit": primary_transit,
        "major_hub": major_hub,
        "engine": engine,
    }


def result_to_dict(result):
    """Convert EvaluationResult to template-friendly dict."""
    output = {
        "address": result.listing.address,
        "coordinates": {"lat": result.lat, "lng": result.lng},
        "walk_scores": result.walk_scores,
        "child_schooling_snapshot": {
            "childcare": [
                {
                    "name": p.name,
                    "rating": p.rating,
                    "user_ratings_total": p.user_ratings_total,
                    "walk_time_min": p.walk_time_min,
                    "website": p.website,
                }
                for p in (result.child_schooling_snapshot.childcare if result.child_schooling_snapshot else [])
            ],
            "schools_by_level": {
                level: (
                    {
                        "name": place.name,
                        "rating": place.rating,
                        "user_ratings_total": place.user_ratings_total,
                        "walk_time_min": place.walk_time_min,
                        "website": place.website,
                        "level": place.level,
                    }
                    if place else None
                )
                for level, place in (
                    result.child_schooling_snapshot.schools_by_level.items()
                    if result.child_schooling_snapshot else {}
                )
            },
        },
        "urban_access": _serialize_urban_access(result.urban_access),
        "transit_access": {
            "primary_stop": result.transit_access.primary_stop,
            "walk_minutes": result.transit_access.walk_minutes,
            "mode": result.transit_access.mode,
            "frequency_bucket": result.transit_access.frequency_bucket,
            "score_0_10": result.transit_access.score_0_10,
            "reasons": result.transit_access.reasons,
        } if result.transit_access else None,
        "green_escape": _serialize_green_escape(result.green_escape_evaluation),
        "transit_score": result.transit_score,
        "passed_tier1": result.passed_tier1,
        "tier1_checks": [
            {
                "name": c.name,
                "result": c.result.value,
                "details": c.details,
                "required": c.required,
            }
            for c in result.tier1_checks
        ],
        "tier2_score": result.tier2_total,
        "tier2_max": result.tier2_max,
        "tier2_normalized": result.tier2_normalized,
        "tier2_scores": [
            {"name": s.name, "points": s.points, "max": s.max_points, "details": s.details}
            for s in result.tier2_scores
        ],
        "tier3_bonus": result.tier3_total,
        "tier3_bonuses": [
            {"name": b.name, "points": b.points, "details": b.details}
            for b in result.tier3_bonuses
        ],
        "tier3_bonus_reasons": result.tier3_bonus_reasons,
        "final_score": result.final_score,
        "percentile_top": result.percentile_top,
        "percentile_label": result.percentile_label,
    }

    output["verdict"] = generate_verdict(output)
    return output


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _diagnose_api_key(request_id="unknown"):
    """
    Diagnose the state of GOOGLE_MAPS_API_KEY at request time.

    Reads the env var *fresh* every call (never cached) so that hot-reloads
    or late-set env vars are picked up immediately.

    Returns dict:
        present  – True if the var exists in os.environ (even if empty)
        usable   – True if the var is non-empty (can be sent to Google)
        length   – len(value) if present, else 0
        redacted – first 8 chars + "…" for log safety
    """
    raw = os.environ.get("GOOGLE_MAPS_API_KEY")
    diag = {
        "present": raw is not None,
        "usable": bool(raw and raw.strip()),
        "length": len(raw) if raw else 0,
        "redacted": (raw[:8] + "...") if raw and len(raw) > 8 else repr(raw),
    }
    logger.info(
        "[%s] API key diagnostic: present=%s usable=%s length=%d redacted=%s",
        request_id, diag["present"], diag["usable"], diag["length"],
        diag["redacted"],
    )
    return diag


def _classify_evaluation_error(exc):
    """
    Map an evaluation exception to a user-friendly (category, message) tuple.

    Categories:
        key_rejected  – key present but Google refused it (REQUEST_DENIED)
        quota_exceeded – OVER_QUERY_LIMIT
        network_error – connection / DNS failure
        timeout       – request timeout
        bad_address   – geocoding returned no results
        unknown       – everything else
    """
    msg = str(exc)

    if "REQUEST_DENIED" in msg:
        return (
            "key_rejected",
            "The Google Maps API key was rejected. "
            "This usually means the key is invalid, IP-restricted, or the "
            "required APIs (Geocoding, Places, Distance Matrix) are not "
            "enabled on the Google Cloud project.",
        )
    if "OVER_QUERY_LIMIT" in msg:
        return (
            "quota_exceeded",
            "Google Maps API quota exceeded. "
            "Evaluations will resume when the quota resets or is increased.",
        )
    if isinstance(exc, requests.exceptions.ConnectionError):
        return (
            "network_error",
            "Could not reach the Google Maps API. "
            "This may be a temporary network issue — please try again.",
        )
    if isinstance(exc, requests.exceptions.Timeout):
        return (
            "timeout",
            "The Google Maps API did not respond in time. Please try again.",
        )
    if "Geocoding failed" in msg and "ZERO_RESULTS" in msg:
        return (
            "bad_address",
            "Google Maps could not find this address. "
            "Please check the address and try again.",
        )
    return (
        "unknown",
        "Something went wrong while evaluating this address. "
        "Please check the address and try again.",
    )


def _generate_demo_result(address):
    """
    Return a template-ready result dict with clearly-labelled demo data.

    Used in BUILDER_MODE when the API key is unavailable so the full
    UI → snapshot → share → export flow can be tested end-to-end.
    """
    return {
        "address": address,
        "coordinates": {"lat": 40.9176, "lng": -73.8551},
        "walk_scores": {
            "walk_score": 72,
            "walk_description": "Very Walkable",
            "transit_score": 58,
            "transit_description": "Good Transit",
            "bike_score": 45,
            "bike_description": "Bikeable",
        },
        "child_schooling_snapshot": {
            "childcare": [],
            "schools_by_level": {},
        },
        "urban_access": None,
        "transit_access": None,
        "green_escape": None,
        "transit_score": 58,
        "passed_tier1": True,
        "tier1_checks": [
            {"name": "Highway buffer", "result": "PASS",
             "details": "Demo — no live data", "required": True},
            {"name": "Gas station buffer", "result": "PASS",
             "details": "Demo — no live data", "required": True},
            {"name": "High-volume road buffer", "result": "PASS",
             "details": "Demo — no live data", "required": True},
        ],
        "tier2_score": 42,
        "tier2_max": 60,
        "tier2_normalized": 70,
        "tier2_scores": [
            {"name": "Park & Green Access", "points": 7, "max": 10,
             "details": "Demo score"},
            {"name": "Third-Place Access", "points": 8, "max": 10,
             "details": "Demo score"},
            {"name": "Provisioning Access", "points": 7, "max": 10,
             "details": "Demo score"},
            {"name": "Fitness Access", "points": 6, "max": 10,
             "details": "Demo score"},
            {"name": "Transit Access", "points": 7, "max": 10,
             "details": "Demo score"},
            {"name": "Cost", "points": 7, "max": 10,
             "details": "Demo score"},
        ],
        "tier3_bonus": 5,
        "tier3_bonuses": [
            {"name": "Demo bonus", "points": 5, "details": "Illustrative"},
        ],
        "tier3_bonus_reasons": [],
        "final_score": 75,
        "percentile_top": 30,
        "percentile_label": "~top 30% nationally for families",
        "verdict": "Strong daily-life match (demo)",
        "_demo_mode": True,
        "_demo_notice": (
            "This evaluation used demo data because the Google Maps "
            "API key is not available. Scores are illustrative only."
        ),
    }


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    error_detail = None  # builder-mode diagnostic
    address = ""
    snapshot_id = None
    is_demo = False
    request_id = getattr(g, "request_id", "unknown")

    if request.method == "POST":
        address = request.form.get("address", "").strip()
        logger.info(
            "[%s] POST / address=%r builder=%s",
            request_id, address, g.is_builder,
        )

        if not address:
            error = "Please enter a property address to evaluate."
            return render_template(
                "index.html", result=result, error=error,
                error_detail=error_detail,
                address=address, snapshot_id=snapshot_id,
                is_builder=g.is_builder, request_id=request_id,
                is_demo=is_demo,
            )

        # --- Diagnose API key at request time (never cached) ---
        key_diag = _diagnose_api_key(request_id)

        if not key_diag["usable"]:
            logger.warning(
                "[%s] GOOGLE_MAPS_API_KEY not usable "
                "(present=%s, length=%d). builder=%s → %s",
                request_id, key_diag["present"], key_diag["length"],
                g.is_builder,
                "DEMO_EVAL" if g.is_builder else "BLOCK",
            )

            # ----- BUILDER MODE: demo evaluation -----
            if g.is_builder:
                result = _generate_demo_result(address)
                is_demo = True

                snapshot_id = save_snapshot(
                    address_input=address,
                    address_norm=address,
                    result_dict=result,
                )
                log_event("snapshot_created", snapshot_id=snapshot_id,
                          visitor_id=g.visitor_id,
                          metadata={"address": address, "demo": True})
                logger.info(
                    "[%s] Demo snapshot %s created for: %s",
                    request_id, snapshot_id, address,
                )
            else:
                # ----- NON-BUILDER: actionable error -----
                error = (
                    "NestCheck cannot evaluate addresses right now because "
                    "required API keys are not configured. "
                    "If you are the site operator, check the deployment "
                    "environment for: GOOGLE_MAPS_API_KEY."
                )
                error_detail = {
                    "request_id": request_id,
                    "missing_keys": ["GOOGLE_MAPS_API_KEY"],
                    "key_diagnostic": {
                        "present": key_diag["present"],
                        "usable": key_diag["usable"],
                        "length": key_diag["length"],
                    },
                    "hint": (
                        "For local development: copy .env.example to .env "
                        "and add your key. For production: set the env var "
                        "in your Railway/Render dashboard, then redeploy."
                    ),
                }
                log_event("evaluation_error", visitor_id=g.visitor_id,
                          metadata={"address": address,
                                    "error": "missing_config",
                                    "missing_keys": ["GOOGLE_MAPS_API_KEY"],
                                    "request_id": request_id})
                return render_template(
                    "index.html", result=result, error=error,
                    error_detail=error_detail,
                    address=address, snapshot_id=snapshot_id,
                    is_builder=g.is_builder, request_id=request_id,
                    is_demo=is_demo,
                )

        # --- API key is available: run real evaluation ---
        if not is_demo:
            # TODO [PACK_LOGIC]: Check evaluation limits here.

            api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
            try:
                listing = PropertyListing(address=address)
                eval_result = evaluate_property(listing, api_key)
                result = result_to_dict(eval_result)

                # Persist snapshot
                address_norm = result.get("address", address)
                snapshot_id = save_snapshot(address_input=address,
                                            address_norm=address_norm,
                                            result_dict=result)

                # Log events
                is_return = check_return_visit(g.visitor_id)
                log_event("snapshot_created", snapshot_id=snapshot_id,
                          visitor_id=g.visitor_id,
                          metadata={"address": address})
                if is_return:
                    log_event("return_visit", snapshot_id=snapshot_id,
                              visitor_id=g.visitor_id)

                logger.info(
                    "[%s] Snapshot %s created for: %s",
                    request_id, snapshot_id, address,
                )

            except Exception as e:
                category, user_message = _classify_evaluation_error(e)
                logger.exception(
                    "[%s] Evaluation failed (category=%s) for address: %s",
                    request_id, category, address,
                )
                log_event("evaluation_error", visitor_id=g.visitor_id,
                          metadata={"address": address,
                                    "error": str(e),
                                    "category": category,
                                    "request_id": request_id})
                error = user_message + " (ref: " + request_id + ")"
                error_detail = {
                    "request_id": request_id,
                    "category": category,
                    "exception": str(e),
                    "traceback": traceback.format_exc(),
                    "key_diagnostic": {
                        "present": key_diag["present"],
                        "usable": key_diag["usable"],
                        "length": key_diag["length"],
                    },
                }

    return render_template(
        "index.html", result=result, error=error,
        error_detail=error_detail,
        address=address, snapshot_id=snapshot_id,
        is_builder=g.is_builder, request_id=request_id,
        is_demo=is_demo,
    )


@app.route("/s/<snapshot_id>")
def view_snapshot(snapshot_id):
    """Public, read-only snapshot page. No auth required."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        abort(404)

    # Track view
    increment_view_count(snapshot_id)
    log_event("snapshot_viewed", snapshot_id=snapshot_id,
              visitor_id=g.visitor_id)

    return render_template(
        "snapshot.html",
        snapshot=snapshot,
        result=snapshot["result"],
        snapshot_id=snapshot_id,
        is_builder=g.is_builder,
    )


@app.route("/api/snapshot/<snapshot_id>/json")
def export_snapshot_json(snapshot_id):
    """JSON export of a snapshot evaluation result."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({"error": "Snapshot not found"}), 404

    result_data = snapshot["result"]
    export = {
        "snapshot_id": snapshot_id,
        "address_input": snapshot["address_input"],
        "address_norm": snapshot["address_norm"],
        "created_at": snapshot["created_at"],
        "verdict": snapshot["verdict"],
        "final_score": snapshot["final_score"],
        "passed_tier1": bool(snapshot["passed_tier1"]),
        "demo": bool(result_data.get("_demo_mode")),
        "result": result_data,
    }
    return jsonify(export)


@app.route("/api/snapshot/<snapshot_id>/csv")
def export_snapshot_csv(snapshot_id):
    """CSV export of a snapshot — flattened key scores."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({"error": "Snapshot not found"}), 404

    result = snapshot["result"]
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "snapshot_id", "address", "created_at", "verdict",
        "final_score", "passed_tier1",
        "tier2_score", "tier2_max", "tier2_normalized", "tier3_bonus",
    ])
    writer.writerow([
        snapshot_id,
        result.get("address", snapshot["address_input"]),
        snapshot["created_at"],
        snapshot["verdict"],
        result.get("final_score", ""),
        result.get("passed_tier1", ""),
        result.get("tier2_score", ""),
        result.get("tier2_max", ""),
        result.get("tier2_normalized", ""),
        result.get("tier3_bonus", ""),
    ])

    # Tier 2 scores breakdown
    writer.writerow([])
    writer.writerow(["category", "points", "max", "details"])
    for score in result.get("tier2_scores", []):
        writer.writerow([
            score.get("name", ""),
            score.get("points", ""),
            score.get("max", ""),
            score.get("details", ""),
        ])

    # Tier 1 checks
    writer.writerow([])
    writer.writerow(["check_name", "result", "details", "required"])
    for check in result.get("tier1_checks", []):
        writer.writerow([
            check.get("name", ""),
            check.get("result", ""),
            check.get("details", ""),
            check.get("required", ""),
        ])

    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=nestcheck-{snapshot_id}.csv"
        },
    )


@app.route("/api/event", methods=["POST"])
def track_event():
    """Lightweight client-side event tracking endpoint."""
    data = request.get_json(silent=True) or {}
    event_type = data.get("event_type")
    sid = data.get("snapshot_id")

    allowed_events = {"snapshot_shared"}
    if event_type not in allowed_events:
        return jsonify({"ok": False}), 400

    log_event(event_type, snapshot_id=sid, visitor_id=g.visitor_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Builder-only routes
# ---------------------------------------------------------------------------

@app.route("/builder/dashboard")
def builder_dashboard():
    """Builder-only analytics dashboard."""
    if not g.is_builder:
        abort(404)

    counts = get_event_counts()
    recent_events = get_recent_events(limit=50)
    recent_snapshots = get_recent_snapshots(limit=20)

    return render_template(
        "builder_dashboard.html",
        counts=counts,
        recent_events=recent_events,
        recent_snapshots=recent_snapshots,
    )


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


# ---------------------------------------------------------------------------
# Health-check endpoint
# ---------------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    """
    Internal health-check — returns JSON config diagnostic.

    Hit this after a deploy to confirm env vars are loaded:
        curl https://yourapp/healthz
    """
    request_id = getattr(g, "request_id", "unknown")
    raw_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    diag = {
        "api_key_present": raw_key is not None,
        "api_key_usable": bool(raw_key and raw_key.strip()),
        "api_key_length": len(raw_key) if raw_key else 0,
        "builder_mode_effective": g.is_builder,
        "request_id": request_id,
    }
    logger.info("[%s] /healthz → %s", request_id, diag)
    return jsonify(diag)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

# Initialize database on import (safe to call repeatedly)
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
