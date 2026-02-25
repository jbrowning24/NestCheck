import os
import io
import csv
import logging
import uuid
import sqlite3
import traceback
from datetime import datetime, timezone
from functools import wraps
from flask import (
    Flask, request, render_template, redirect, url_for,
    make_response, abort, jsonify, g, Response, flash
)
from dotenv import load_dotenv
from nc_trace import TraceContext, get_trace, set_trace, clear_trace
from property_evaluator import (
    PropertyListing, evaluate_property, CheckResult, GoogleMapsClient
)
from models import (
    init_db, save_snapshot, get_snapshot, increment_view_count,
    log_event, check_return_visit, get_event_counts,
    get_recent_events, get_recent_snapshots,
    get_snapshot_by_place_id, is_snapshot_fresh, save_snapshot_for_place,
    get_snapshots_by_ids,
)

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nestcheck-dev-key')
app.config['GOOGLE_MAPS_FRONTEND_API_KEY'] = (
    os.environ.get('GOOGLE_MAPS_FRONTEND_API_KEY') or
    os.environ.get('GOOGLE_MAPS_API_KEY')
)
# Keep templates render-safe even if Flask-WTF is unavailable at runtime.
app.jinja_env.globals.setdefault("csrf_token", lambda: "")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from flask_wtf.csrf import CSRFProtect, generate_csrf
except Exception:
    logger.warning(
        "Flask-WTF not available; CSRF protection disabled and csrf_token() fallback in use."
    )
else:
    CSRFProtect(app)
    app.jinja_env.globals["csrf_token"] = generate_csrf

# ---------------------------------------------------------------------------
# Startup: warn immediately if required config is missing
# ---------------------------------------------------------------------------
if not os.environ.get("GOOGLE_MAPS_API_KEY"):
    logger.warning(
        "GOOGLE_MAPS_API_KEY is not set. "
        "Address evaluations will fail until it is configured. "
        "For local development, copy .env.example to .env and add your key."
    )


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
# Presentation helpers
# ---------------------------------------------------------------------------

_SAFETY_CHECK_NAMES = {"Gas station", "Highway", "High-volume road"}

_CLEAR_HEADLINES = {
    "Gas station": "No gas stations within 500 ft",
    "Highway": "No highways or major parkways nearby",
    "High-volume road": "No high-volume roads nearby",
}

_ISSUE_HEADLINES = {
    "Gas station": "Gas station within proximity threshold",
    "Highway": "Highway or major parkway nearby",
    "High-volume road": "High-volume road nearby",
}


def present_checks(tier1_checks):
    """Convert raw tier1_check dicts into presentation-layer dicts.

    Each check gets category, result_type, proximity_band, headline,
    and explanation fields used by the template to render individual
    items in the Proximity & Environment section.
    """
    presented = []
    for check in tier1_checks:
        name = check["name"]
        result = check["result"]  # "PASS", "FAIL", or "UNKNOWN"
        details = check.get("details", "")

        category = "SAFETY" if name in _SAFETY_CHECK_NAMES else "LIFESTYLE"

        if result == "PASS":
            result_type = "CLEAR"
            proximity_band = "NEUTRAL"
            headline = _CLEAR_HEADLINES.get(name, f"{name} — Clear")
            explanation = None
        elif result == "FAIL":
            result_type = "CONFIRMED_ISSUE"
            proximity_band = "VERY_CLOSE"
            headline = _ISSUE_HEADLINES.get(name, f"{name} — Concern detected")
            explanation = details
        else:
            result_type = "VERIFICATION_NEEDED"
            proximity_band = "NOTABLE"
            headline = f"{name} — Unable to verify"
            explanation = details

        presented.append({
            "name": name,
            "result": result,
            "category": category,
            "result_type": result_type,
            "proximity_band": proximity_band,
            "headline": headline,
            "explanation": explanation,
        })

    return presented


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

    return {
        "primary_transit": primary_transit,
        "major_hub": major_hub,
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

    output["presented_checks"] = present_checks(output["tier1_checks"])
    output["verdict"] = generate_verdict(output)
    return output


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _check_service_config():
    """
    Validate required service configuration.
    Returns (is_ok, missing_keys) tuple.
    """
    missing = []
    if not os.environ.get("GOOGLE_MAPS_API_KEY"):
        missing.append("GOOGLE_MAPS_API_KEY")
    return (len(missing) == 0, missing)


def _wants_json():
    """Return True if the client prefers a JSON response."""
    accept = request.headers.get("Accept", "")
    return "application/json" in accept


def _snapshot_ttl_days():
    """Read SNAPSHOT_TTL_DAYS with safe fallback."""
    raw = os.environ.get("SNAPSHOT_TTL_DAYS", "90")
    try:
        ttl = int(raw)
        if ttl > 0:
            return ttl
    except (TypeError, ValueError):
        pass
    logger.warning("Invalid SNAPSHOT_TTL_DAYS=%r. Falling back to 90.", raw)
    return 90


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    error_detail = None  # builder-mode diagnostic
    address = ""
    snapshot_id = None
    request_id = getattr(g, "request_id", "unknown")

    if request.method == "POST":
        address = request.form.get("address", "").strip()
        logger.info(
            "[%s] POST / address=%r builder=%s",
            request_id, address, g.is_builder,
        )

        if not address:
            error = "Please enter a property address to evaluate."
            if _wants_json():
                return jsonify({"error": error, "request_id": request_id}), 400
            return render_template(
                "index.html", result=result, error=error,
                error_detail=error_detail,
                address=address, snapshot_id=snapshot_id,
                is_builder=g.is_builder, request_id=request_id,
            )

        config_ok, missing_keys = _check_service_config()
        if not config_ok:
            logger.error(
                "[%s] Missing required env vars: %s", request_id, missing_keys
            )
            error = (
                "NestCheck cannot evaluate addresses right now because "
                "required API keys are not configured. "
                "If you are the site operator, check the deployment environment "
                "for: " + ", ".join(missing_keys) + "."
            )
            error_detail = {
                "request_id": request_id,
                "missing_keys": missing_keys,
                "hint": (
                    "For local development: copy .env.example to .env and "
                    "add your keys. For production: set these environment "
                    "variables in your Railway/Render dashboard."
                ),
            }
            log_event("evaluation_error", visitor_id=g.visitor_id,
                      metadata={"address": address,
                                "error": "missing_config",
                                "missing_keys": missing_keys,
                                "request_id": request_id})
            if _wants_json():
                return jsonify({"error": error, "request_id": request_id}), 503
            return render_template(
                "index.html", result=result, error=error,
                error_detail=error_detail,
                address=address, snapshot_id=snapshot_id,
                is_builder=g.is_builder, request_id=request_id,
            )

        # TODO [PACK_LOGIC]: Check evaluation limits here.
        # if not g.is_builder and FEATURE_CONFIG["max_evaluations_per_day"]:
        #     count = get_daily_eval_count(g.visitor_id)
        #     if count >= FEATURE_CONFIG["max_evaluations_per_day"]:
        #         error = "Daily evaluation limit reached."
        #         return render_template(...)

        api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
        ttl_days = _snapshot_ttl_days()
        trace_ctx = TraceContext(trace_id=request_id)
        set_trace(trace_ctx)
        try:
            now_utc = datetime.now(timezone.utc)
            evaluated_at = now_utc.isoformat()
            geocode_details = GoogleMapsClient(api_key).geocode_details(address)
            place_id = geocode_details.get("place_id")
            existing_snapshot = (
                get_snapshot_by_place_id(place_id) if place_id else None
            )

            if existing_snapshot and is_snapshot_fresh(existing_snapshot, ttl_days, now_utc):
                snapshot_id = existing_snapshot["snapshot_id"]
                trace_summary = trace_ctx.summary_dict()
                log_event(
                    "snapshot_reused",
                    snapshot_id=snapshot_id,
                    visitor_id=g.visitor_id,
                    metadata={
                        "address": address,
                        "place_id": place_id,
                        "ttl_days": ttl_days,
                        "request_id": request_id,
                        "trace_id": request_id,
                    },
                )
                trace_ctx.log_summary()
                if _wants_json():
                    return jsonify({
                        "snapshot_id": snapshot_id,
                        "redirect_url": f"/s/{snapshot_id}",
                        "trace_id": request_id,
                        "trace_summary": trace_summary,
                    })
                return redirect(url_for("view_snapshot", snapshot_id=snapshot_id))

            if not place_id:
                logger.warning(
                    "[%s] Geocode result missing place_id for address=%r",
                    request_id, address,
                )

            listing = PropertyListing(address=address)
            eval_result = evaluate_property(
                listing,
                api_key,
                pre_geocode=geocode_details,
            )
            result = result_to_dict(eval_result)

            # Persist snapshot — include trace_id in metadata
            address_norm = (
                geocode_details.get("formatted_address")
                or result.get("address")
                or address
            )
            trace_summary = trace_ctx.summary_dict()
            result["_trace"] = trace_summary
            if place_id:
                try:
                    snapshot_id = save_snapshot_for_place(
                        place_id=place_id,
                        address_input=address,
                        address_norm=address_norm,
                        evaluated_at=evaluated_at,
                        result_dict=result,
                        existing_snapshot_id=(
                            existing_snapshot["snapshot_id"]
                            if existing_snapshot else None
                        ),
                    )
                except sqlite3.IntegrityError:
                    winner = get_snapshot_by_place_id(place_id)
                    if not winner:
                        raise
                    snapshot_id = winner["snapshot_id"]
            else:
                snapshot_id = save_snapshot(
                    address_input=address,
                    address_norm=address_norm,
                    result_dict=result,
                )

            # Log events
            is_return = check_return_visit(g.visitor_id)
            log_event("snapshot_created", snapshot_id=snapshot_id,
                      visitor_id=g.visitor_id,
                      metadata={"address": address,
                                "place_id": place_id,
                                "trace_id": request_id})
            if is_return:
                log_event("return_visit", snapshot_id=snapshot_id,
                          visitor_id=g.visitor_id)

            # Emit the end-of-request summary log line
            trace_ctx.log_summary()

            logger.info(
                "[%s] Snapshot %s created for: %s",
                request_id, snapshot_id, address,
            )

            # Return JSON for fetch-based clients, HTML for traditional form POST
            if _wants_json():
                return jsonify({
                    "snapshot_id": snapshot_id,
                    "redirect_url": f"/s/{snapshot_id}",
                    "trace_id": request_id,
                    "trace_summary": trace_summary,
                })

        except Exception as e:
            trace_ctx.log_summary()
            logger.exception(
                "[%s] Evaluation failed for address: %s", request_id, address
            )
            log_event("evaluation_error", visitor_id=g.visitor_id,
                      metadata={"address": address,
                                "error": str(e),
                                "request_id": request_id,
                                "trace_summary": trace_ctx.summary_dict()})
            error = (
                "Something went wrong while evaluating this address. "
                "Please check the address and try again. "
                "If the problem persists, the address may not be recognized "
                "by Google Maps. (ref: " + request_id + ")"
            )
            error_detail = {
                "request_id": request_id,
                "exception": str(e),
                "traceback": traceback.format_exc(),
            }
            if _wants_json():
                return jsonify({
                    "error": error,
                    "request_id": request_id,
                    "trace_summary": trace_ctx.summary_dict(),
                }), 500
        finally:
            clear_trace()

    return render_template(
        "index.html", result=result, error=error,
        error_detail=error_detail,
        address=address, snapshot_id=snapshot_id,
        is_builder=g.is_builder, request_id=request_id,
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

    # Backfill presented_checks for old snapshots
    result = snapshot["result"]
    if "presented_checks" not in result:
        result["presented_checks"] = present_checks(
            result.get("tier1_checks", [])
        )

    return render_template(
        "snapshot.html",
        snapshot=snapshot,
        result=result,
        snapshot_id=snapshot_id,
        is_builder=g.is_builder,
    )


@app.route("/api/snapshot/<snapshot_id>/json")
def export_snapshot_json(snapshot_id):
    """JSON export of a snapshot evaluation result."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({"error": "Snapshot not found"}), 404

    export = {
        "snapshot_id": snapshot_id,
        "address_input": snapshot["address_input"],
        "address_norm": snapshot["address_norm"],
        "created_at": snapshot["created_at"],
        "verdict": snapshot["verdict"],
        "final_score": snapshot["final_score"],
        "passed_tier1": bool(snapshot["passed_tier1"]),
        "result": snapshot["result"],
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


@app.route("/compare")
def compare():
    raw_ids = (request.args.get("ids") or "").strip()
    if not raw_ids:
        flash("Select at least two addresses", "error")
        return redirect(url_for("index"))

    requested_ids = [part.strip() for part in raw_ids.split(",") if part.strip()]
    deduped_ids = []
    seen = set()
    for snapshot_id in requested_ids:
        if snapshot_id in seen:
            continue
        seen.add(snapshot_id)
        deduped_ids.append(snapshot_id)

    if len(deduped_ids) < 2:
        flash("Select at least two addresses", "error")
        return redirect(url_for("index"))
    if len(deduped_ids) > 4:
        flash("You can compare up to four", "error")
        return redirect(url_for("index"))

    snapshots = get_snapshots_by_ids(deduped_ids)
    if len(snapshots) < 2:
        flash("Could not load enough snapshots", "error")
        return redirect(url_for("index"))

    evaluations = []
    for snapshot in snapshots:
        result = snapshot.get("result", {})
        evaluations.append({
            "snapshot_id": snapshot["snapshot_id"],
            "result": result,
            "address": (
                result.get("address")
                or snapshot.get("address_norm")
                or snapshot.get("address_input")
                or ""
            ),
            "final_score": result.get("final_score", snapshot.get("final_score", 0)),
            "verdict": result.get("verdict", snapshot.get("verdict", "")),
            "score_band": result.get("score_band"),
            "is_preview": bool(snapshot.get("is_preview", 0)),
        })

    top_score = max((e.get("final_score", 0) for e in evaluations), default=0)
    top_score_unique = (
        sum(1 for e in evaluations if e.get("final_score", 0) == top_score) == 1
    )

    return render_template(
        "compare.html",
        evaluations=evaluations,
        evaluation_count=len(evaluations),
        top_score=top_score,
        top_score_unique=top_score_unique,
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


@app.route("/healthz")
def healthz():
    """Lightweight health-check endpoint for monitoring."""
    config_ok, missing = _check_service_config()
    return jsonify({
        "status": "ok" if config_ok else "degraded",
        "missing_keys": missing,
    }), 200 if config_ok else 503


@app.route("/debug/trace/<snapshot_id>")
def debug_trace(snapshot_id):
    """View trace data for a snapshot (safe, no secrets). Builder-only."""
    if not g.is_builder:
        abort(404)

    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({"error": "Snapshot not found"}), 404

    result = snapshot.get("result", {})
    trace_data = result.get("_trace")

    return jsonify({
        "snapshot_id": snapshot_id,
        "address": snapshot.get("address_input"),
        "created_at": snapshot.get("created_at"),
        "trace": trace_data,
    })


@app.route("/debug/eval", methods=["POST"])
def debug_eval():
    """Run an evaluation and return full trace data. Builder-only.

    Accepts JSON: {"address": "123 Main St, City, ST"}
    Returns: full trace with per-stage and per-call timing.
    """
    if not g.is_builder:
        abort(404)

    data = request.get_json(silent=True) or {}
    address = data.get("address", "").strip()
    if not address:
        return jsonify({"error": "address is required"}), 400

    config_ok, missing_keys = _check_service_config()
    if not config_ok:
        return jsonify({"error": "missing config", "missing_keys": missing_keys}), 503

    request_id = getattr(g, "request_id", "unknown")
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    trace_ctx = TraceContext(trace_id=request_id)
    set_trace(trace_ctx)
    try:
        listing = PropertyListing(address=address)
        eval_result = evaluate_property(listing, api_key)
        trace_ctx.log_summary()

        return jsonify({
            "address": address,
            "final_score": eval_result.final_score,
            "passed_tier1": eval_result.passed_tier1,
            "trace": trace_ctx.full_trace_dict(),
        })
    except Exception as e:
        trace_ctx.log_summary()
        return jsonify({
            "address": address,
            "error": str(e),
            "trace": trace_ctx.full_trace_dict(),
        }), 500
    finally:
        clear_trace()


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
