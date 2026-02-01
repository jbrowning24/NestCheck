import os
import logging
import uuid
from functools import wraps
from flask import (
    Flask, request, render_template, redirect, url_for,
    make_response, abort, jsonify, g
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
    """Set builder mode and visitor ID on every request."""
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

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    address = ""
    snapshot_id = None

    if request.method == "POST":
        address = request.form.get("address", "").strip()

        if not address:
            error = "Please enter a property address to evaluate."
            return render_template(
                "index.html", result=result, error=error,
                address=address, snapshot_id=snapshot_id,
                is_builder=g.is_builder,
            )

        api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
        if not api_key:
            error = "Service configuration error. Please contact support."
            logger.error("GOOGLE_MAPS_API_KEY not set")
            return render_template(
                "index.html", result=result, error=error,
                address=address, snapshot_id=snapshot_id,
                is_builder=g.is_builder,
            )

        # TODO [PACK_LOGIC]: Check evaluation limits here.
        # if not g.is_builder and FEATURE_CONFIG["max_evaluations_per_day"]:
        #     count = get_daily_eval_count(g.visitor_id)
        #     if count >= FEATURE_CONFIG["max_evaluations_per_day"]:
        #         error = "Daily evaluation limit reached."
        #         return render_template(...)

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

            logger.info("Snapshot %s created for: %s", snapshot_id, address)

        except Exception as e:
            logger.exception("Evaluation failed for address: %s", address)
            log_event("evaluation_error", visitor_id=g.visitor_id,
                      metadata={"address": address, "error": str(e)})
            error = (
                "Something went wrong while evaluating this address. "
                "Please check the address and try again. "
                "If the problem persists, the address may not be recognized by Google Maps."
            )

    return render_template(
        "index.html", result=result, error=error,
        address=address, snapshot_id=snapshot_id,
        is_builder=g.is_builder,
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
