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
from scoring_config import PERSONA_PRESETS, DEFAULT_PERSONA
from models import (
    init_db, save_snapshot, get_snapshot, increment_view_count,
    log_event, check_return_visit, get_event_counts,
    get_recent_events, get_recent_snapshots,
    get_snapshot_by_place_id, is_snapshot_fresh, save_snapshot_for_place,
    get_snapshots_by_ids, update_snapshot_email_sent,
    create_job, get_job,
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


def generate_structured_summary(presented_checks):
    """Build a human-readable summary of why an address failed tier 1.

    Returns a string like "This address has 2 health & safety concerns that
    prevent full scoring: gas station proximity and high-volume road proximity."
    Returns empty string if there are no issues.
    """
    if not presented_checks:
        return ""

    safety_issues = [
        pc for pc in presented_checks
        if pc.get("category") == "SAFETY"
        and pc.get("result_type") in ("CONFIRMED_ISSUE", "WARNING_DETECTED")
    ]
    if not safety_issues:
        return ""

    issue_names = [pc.get("headline", pc.get("name", "Unknown check")) for pc in safety_issues]

    count = len(issue_names)
    concern_word = "concern" if count == 1 else "concerns"
    verb = "prevents" if count == 1 else "prevent"
    names_str = issue_names[0] if count == 1 else (
        ", ".join(issue_names[:-1]) + " and " + issue_names[-1]
    )

    return (
        f"This address has {count} health & safety {concern_word} "
        f"that {verb} full scoring: {names_str}."
    )


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------

_SAFETY_CHECK_NAMES = {
    "Gas station", "Highway", "High-volume road",
    "Power lines", "Electrical substation", "Cell tower", "Industrial zone",
}

_CLEAR_HEADLINES = {
    "Gas station": "No gas stations within 500 ft",
    "Highway": "No highways or major parkways nearby",
    "High-volume road": "No high-volume roads nearby",
    "Power lines": "No high-voltage transmission lines within 200 ft",
    "Electrical substation": "No electrical substations within 300 ft",
    "Cell tower": "No cell towers within 500 ft",
    "Industrial zone": "No industrial-zoned land within 500 ft",
}

_ISSUE_HEADLINES = {
    "Gas station": "Gas station within proximity threshold",
    "Highway": "Highway or major parkway nearby",
    "High-volume road": "High-volume road nearby",
    "Power lines": "High-voltage transmission line detected nearby",
    "Electrical substation": "Electrical substation detected nearby",
    "Cell tower": "Cell tower detected nearby",
    "Industrial zone": "Industrial-zoned land detected nearby",
}

_WARNING_HEADLINES = {
    "Power lines": "High-voltage transmission line detected nearby",
    "Electrical substation": "Electrical substation detected nearby",
    "Cell tower": "Cell tower detected nearby",
    "Industrial zone": "Industrial-zoned land detected nearby",
}

# ---------------------------------------------------------------------------
# Health-check context copy — expanded "why we check this" content
# ---------------------------------------------------------------------------
# Keys: (check_name, result_category) where result_category is one of:
#   "FAIL", "WARNING", "PASS"
# Each value is a dict with structured paragraphs for progressive disclosure.
# Dynamic data (distances, names) is injected at render time via .format().

_HEALTH_CONTEXT = {
    # ── Gas Station ──────────────────────────────────────────────
    ("Gas station", "FAIL"): {
        "why": (
            "Gas stations emit benzene \u2014 a known human carcinogen "
            "(classified Group 1 by the International Agency for Research on Cancer) "
            "\u2014 from underground storage tank vent pipes and during fueling. "
            "A 2019 study by researchers at Columbia and Johns Hopkins (Hilpert et al.) "
            "measured vent pipe emissions at a Midwest station and found them roughly "
            "10 times higher than the estimates California uses to set safety "
            "regulations. At that station, California\u2019s benzene reference exposure "
            "level was exceeded at a distance of 160 meters."
        ),
        "regulatory": (
            "California recommends 300-foot setbacks between gas stations and "
            "sensitive land uses (homes, schools, daycares). Maryland requires "
            "500 feet. These aren\u2019t arbitrary \u2014 they reflect the distance at "
            "which benzene concentrations from vent pipes are expected to approach "
            "safe thresholds under normal conditions."
        ),
        "exposure": (
            "The exposure is chronic, not acute. You won\u2019t smell benzene at "
            "these concentrations. The health concern is years of low-level chronic "
            "exposure, which is associated with increased leukemia risk and other "
            "blood disorders. This is particularly relevant for young children and "
            "pregnant women."
        ),
    },
    ("Gas station", "PASS"): {
        "why": (
            "Gas stations emit benzene, a known carcinogen, from underground "
            "storage tank vent pipes. Research from Columbia and Johns Hopkins "
            "found vent pipe emissions significantly higher than previously "
            "estimated, with California\u2019s benzene safety threshold exceeded "
            "at 160 meters. Several states mandate 300\u2013500 foot setbacks "
            "between gas stations and residences. This address clears that buffer."
        ),
    },
    # ── Highway ──────────────────────────────────────────────────
    ("Highway", "FAIL"): {
        "why": (
            "A 2010 expert panel convened by the Health Effects Institute reviewed "
            "decades of research and found \u201csufficient\u201d evidence that living near "
            "high-traffic roads causes asthma aggravation in children and is "
            "associated with cardiovascular mortality in adults. The CDC has "
            "documented that roughly 11 million Americans live within 150 meters "
            "of a major highway \u2014 a zone where traffic-related air pollution "
            "(fine particulate matter, nitrogen dioxide, ultrafine particles) "
            "remains significantly elevated above background levels."
        ),
        "who": (
            "Children, older adults, and anyone with pre-existing respiratory or "
            "cardiovascular conditions face the highest risk. Children breathe "
            "faster and spend more time outdoors, increasing their cumulative "
            "exposure. The effects are not immediate \u2014 they compound over months "
            "and years of residence."
        ),
        "distance": (
            "Peer-reviewed research consistently shows that traffic-related "
            "pollutant concentrations drop substantially within 150\u2013300 meters "
            "of a high-traffic road and typically reach background levels by "
            "300 meters. This address falls within that elevated-risk zone."
        ),
    },
    ("Highway", "PASS"): {
        "why": (
            "Living within 150\u2013300 meters of high-traffic roads exposes "
            "residents to elevated levels of fine particulate matter and "
            "nitrogen dioxide. The Health Effects Institute found sufficient "
            "evidence linking this proximity to asthma aggravation and "
            "cardiovascular effects. This address is outside that "
            "elevated-risk zone."
        ),
    },
    # ── High-volume road ─────────────────────────────────────────
    ("High-volume road", "FAIL"): {
        "why": (
            "A 2010 expert panel convened by the Health Effects Institute reviewed "
            "decades of research and found \u201csufficient\u201d evidence that living near "
            "high-traffic roads causes asthma aggravation in children and is "
            "associated with cardiovascular mortality in adults."
        ),
        "who": (
            "Children, older adults, and anyone with pre-existing respiratory or "
            "cardiovascular conditions face the highest risk. Children breathe "
            "faster and spend more time outdoors, increasing their cumulative "
            "exposure. The effects compound over months and years of residence."
        ),
        "distance": (
            "Traffic-related pollutant concentrations drop substantially within "
            "150\u2013300 meters of a high-traffic road and typically reach background "
            "levels by 300 meters. This address falls within that elevated-risk zone."
        ),
        "invisible": (
            "This is the kind of proximity risk that doesn\u2019t appear in property "
            "descriptions, photos, or open house tours. You might notice noise on "
            "a site visit, but the air quality impact is invisible and cumulative."
        ),
    },
    ("High-volume road", "PASS"): {
        "why": (
            "Living within 150\u2013300 meters of high-traffic roads exposes "
            "residents to elevated levels of fine particulate matter and nitrogen "
            "dioxide. The Health Effects Institute found sufficient evidence "
            "linking this proximity to asthma aggravation and cardiovascular "
            "effects. This address is outside that elevated-risk zone."
        ),
    },
    # ── Power lines ──────────────────────────────────────────────
    ("Power lines", "WARNING"): {
        "why": (
            "High-voltage transmission lines generate electromagnetic fields "
            "(EMF). In 2002, the International Agency for Research on Cancer "
            "classified extremely low-frequency EMF as \u201cpossibly carcinogenic\u201d "
            "(Group 2B), based on a consistent finding of approximately double "
            "the childhood leukemia risk at exposures above 0.3\u20130.4 microtesla. "
            "EMF strength drops rapidly with distance: roughly 20 microtesla "
            "directly beneath high-voltage lines, dropping to about 0.7 "
            "microtesla at 100 feet and 0.18 microtesla at 200 feet."
        ),
        "nuance": (
            "The scientific evidence here is moderate and contested. The "
            "epidemiological association with childhood leukemia is consistent "
            "across studies, but no biophysical mechanism has been confirmed, and "
            "many health agencies consider the evidence insufficient to establish "
            "causation. We include this as a warning \u2014 something to be aware of "
            "\u2014 rather than a disqualifier."
        ),
    },
    ("Power lines", "PASS"): {
        "why": (
            "High-voltage power lines generate electromagnetic fields classified "
            "as \u201cpossibly carcinogenic\u201d by the International Agency for Research "
            "on Cancer. EMF intensity drops rapidly with distance, reaching "
            "typical background levels by about 200 feet from the line. This "
            "address is outside that proximity zone."
        ),
    },
    # ── Electrical substation ────────────────────────────────────
    ("Electrical substation", "WARNING"): {
        "why": (
            "Electrical substations generate localized electromagnetic fields and "
            "can produce persistent low-frequency noise (the \u201chum\u201d from "
            "transformers). EMF levels near substations can be comparable to those "
            "beneath transmission lines and diminish with similar distance profiles."
        ),
    },
    ("Electrical substation", "PASS"): {
        "why": (
            "Electrical substations generate localized electromagnetic fields and "
            "can produce persistent low-frequency noise (the \u201chum\u201d from "
            "transformers). EMF levels near substations can be comparable to those "
            "beneath transmission lines and diminish with similar distance "
            "profiles. This address is well outside the elevated-EMF zone."
        ),
    },
    # ── Cell tower ───────────────────────────────────────────────
    ("Cell tower", "WARNING"): {
        "why": (
            "The International Agency for Research on Cancer classified "
            "radiofrequency electromagnetic fields as \u201cpossibly carcinogenic\u201d "
            "(Group 2B) in 2011. However, ground-level RF exposure from cell "
            "towers is typically hundreds to thousands of times below the limits "
            "set by the FCC. The primary concerns at close range are more "
            "practical: potential property value perception and visual impact."
        ),
        "nuance": (
            "The scientific evidence for health effects from cell tower RF "
            "exposure at residential distances is substantially weaker than for "
            "the other hazards we evaluate. We include it because proximity to "
            "cell infrastructure is information some buyers and renters want, but "
            "we do not weight it as a health disqualifier."
        ),
    },
    ("Cell tower", "PASS"): {
        "why": (
            "While health evidence for cell tower RF exposure is limited, "
            "proximity to cell infrastructure is a factor in property perception "
            "and visual impact. We check using the FCC\u2019s Antenna Structure "
            "Registration database, noting that smaller installations may not be "
            "captured."
        ),
    },
    # ── Industrial zone ──────────────────────────────────────────
    ("Industrial zone", "WARNING"): {
        "why": (
            "Industrial zoning permits land uses that may include manufacturing, "
            "warehousing, waste processing, and chemical storage. Proximity to "
            "industrial zones can mean elevated noise levels, truck traffic, and "
            "potential exposure to airborne pollutants \u2014 even when specific "
            "facilities haven\u2019t triggered an EPA reporting threshold."
        ),
        "practical": (
            "The current occupant of an industrial-zoned parcel might be benign "
            "(a self-storage facility, a light manufacturing workshop). But zoning "
            "tells you what\u2019s permitted, not just what\u2019s there today. An empty "
            "industrial lot next door could become a distribution center "
            "generating 24/7 truck traffic without any zoning change required."
        ),
    },
    ("Industrial zone", "PASS"): {
        "why": (
            "Industrial zoning permits land uses including manufacturing, "
            "warehousing, and chemical storage that can generate noise, truck "
            "traffic, and airborne pollutants. Proximity also matters for future "
            "development \u2014 industrial zoning determines what could be built, not "
            "just what\u2019s there today. This address has sufficient buffer from "
            "industrial-zoned parcels."
        ),
    },
}


def _build_health_context(name, result, details, value):
    """Build the expanded health-context paragraphs for a single check.

    Returns a list of paragraph strings ready for template rendering,
    or None if no context copy is available for this check.
    """
    # Map result strings to the keys used in _HEALTH_CONTEXT
    if result in ("PASS",):
        ctx_key = "PASS"
    elif result in ("FAIL",):
        ctx_key = "FAIL"
    elif result in ("WARNING",):
        ctx_key = "WARNING"
    else:
        return None

    template = _HEALTH_CONTEXT.get((name, ctx_key))
    if not template:
        return None

    # Return paragraphs in a stable order
    paragraphs = []
    for key in ("why", "regulatory", "exposure", "who", "distance",
                "invisible", "nuance", "practical"):
        if key in template:
            paragraphs.append(template[key])

    return paragraphs if paragraphs else None


def present_checks(tier1_checks):
    """Convert raw tier1_check dicts into presentation-layer dicts.

    Each check gets category, result_type, proximity_band, headline,
    explanation, and health_context fields used by the template to render
    individual items in the Proximity & Environment section.
    """
    presented = []
    for check in tier1_checks:
        name = check["name"]
        result = check["result"]  # "PASS", "FAIL", "WARNING", or "UNKNOWN"
        details = check.get("details", "")
        value = check.get("value")

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
        elif result == "WARNING":
            result_type = "WARNING_DETECTED"
            proximity_band = "NOTABLE"
            headline = _WARNING_HEADLINES.get(name, f"{name} — Warning detected")
            explanation = details
        else:
            result_type = "VERIFICATION_NEEDED"
            proximity_band = "NOTABLE"
            headline = f"{name} — Unable to verify automatically"
            # Show the service-level message if it's user-friendly,
            # otherwise provide a generic fallback.
            if details and not details.startswith("Error checking:"):
                explanation = details
            else:
                explanation = (
                    "The external data source for this check was "
                    "temporarily unavailable. Use the satellite link "
                    "below to verify manually."
                )

        # Build expanded context for progressive disclosure
        health_context = _build_health_context(name, result, details, value)

        presented.append({
            "name": name,
            "result": result,
            "category": category,
            "result_type": result_type,
            "proximity_band": proximity_band,
            "headline": headline,
            "explanation": explanation,
            "health_context": health_context,
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
            "drive_time_min": p.drive_time_min,
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
            "drive_time_min": s.drive_time_min,
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
                "value": c.value,
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

    # Persona / scoring lens (NES-133)
    if result.persona is not None:
        output["persona"] = {
            "key": result.persona.key,
            "label": result.persona.label,
            "description": result.persona.description,
            "weights": dict(result.persona.weights),
        }

    # Neighborhood places — already plain dicts, pass through as-is
    output["neighborhood_places"] = result.neighborhood_places if result.neighborhood_places else None

    output["presented_checks"] = present_checks(output["tier1_checks"])
    output["structured_summary"] = generate_structured_summary(output["presented_checks"])
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
        email = request.form.get("email", "").strip() or None
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

        # Check for a fresh cached snapshot before queuing a job.
        api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
        ttl_days = _snapshot_ttl_days()
        try:
            now_utc = datetime.now(timezone.utc)
            geocode_details = GoogleMapsClient(api_key).geocode_details(address)
            place_id = geocode_details.get("place_id")
            existing_snapshot = (
                get_snapshot_by_place_id(place_id) if place_id else None
            )

            if existing_snapshot and is_snapshot_fresh(existing_snapshot, ttl_days, now_utc):
                snapshot_id = existing_snapshot["snapshot_id"]
                log_event(
                    "snapshot_reused",
                    snapshot_id=snapshot_id,
                    visitor_id=g.visitor_id,
                    metadata={
                        "address": address,
                        "place_id": place_id,
                        "ttl_days": ttl_days,
                        "request_id": request_id,
                    },
                )
                if _wants_json():
                    return jsonify({
                        "snapshot_id": snapshot_id,
                        "redirect_url": f"/s/{snapshot_id}",
                    })
                return redirect(url_for("view_snapshot", snapshot_id=snapshot_id))
        except Exception:
            # Geocode/cache check failed — continue to queue the job anyway.
            # The worker will re-geocode from scratch.
            place_id = None
            logger.warning(
                "[%s] Pre-geocode failed; queuing job without place_id",
                request_id, exc_info=True,
            )

        # Queue the evaluation as an async job so the response returns
        # immediately. The frontend polls GET /job/<job_id> for progress.
        persona = request.form.get("persona", "").strip() or None
        job_id = create_job(
            address=address,
            visitor_id=g.visitor_id,
            request_id=request_id,
            place_id=place_id,
            persona=persona,
            email_raw=email,
        )
        logger.info("[%s] Job %s queued for address=%r", request_id, job_id, address)

        if _wants_json():
            return jsonify({"job_id": job_id})

        # Non-JS fallback: render the page with the job_id so inline
        # script can start polling.
        return render_template(
            "index.html", result=None, error=None,
            error_detail=None, address=address,
            snapshot_id=None, job_id=job_id,
            is_builder=g.is_builder, request_id=request_id,
        )

    return render_template(
        "index.html", result=result, error=error,
        error_detail=error_detail,
        address=address, snapshot_id=snapshot_id,
        job_id=None,
        is_builder=g.is_builder, request_id=request_id,
    )


@app.route("/job/<job_id>")
def job_status(job_id):
    """Poll endpoint for async evaluation jobs.

    Returns JSON: {status, current_stage?, snapshot_id?, error?}
    """
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    resp = {"status": job["status"]}
    if job["current_stage"]:
        resp["current_stage"] = job["current_stage"]
    if job["snapshot_id"]:
        resp["snapshot_id"] = job["snapshot_id"]
    if job["error"]:
        resp["error"] = job["error"]
    return jsonify(resp)


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

    # Backfill structured_summary for old snapshots
    if "structured_summary" not in result:
        result["structured_summary"] = generate_structured_summary(
            result.get("presented_checks", [])
        )

    # Backfill persona for old snapshots (NES-133)
    if "persona" not in result:
        _bp = PERSONA_PRESETS[DEFAULT_PERSONA]
        result["persona"] = {
            "key": _bp.key,
            "label": _bp.label,
            "description": _bp.description,
            "weights": dict(_bp.weights),
        }

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

    result = snapshot["result"]
    if not g.is_builder:
        result = {k: v for k, v in result.items() if k != "_trace"}

    export = {
        "snapshot_id": snapshot_id,
        "address_input": snapshot["address_input"],
        "address_norm": snapshot["address_norm"],
        "created_at": snapshot["created_at"],
        "verdict": snapshot["verdict"],
        "final_score": snapshot["final_score"],
        "passed_tier1": bool(snapshot["passed_tier1"]),
        "result": result,
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
    # Start background evaluation worker for dev server.
    # In production, gunicorn_config.py post_fork handles this.
    from worker import start_worker
    start_worker()
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
