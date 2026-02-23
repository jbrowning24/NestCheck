import os
import sys
import io
import csv
import logging
import uuid
import secrets
import traceback
from functools import wraps
from urllib.parse import quote as _stdlib_quote
from flask import (
    Flask, request, render_template, redirect, url_for,
    make_response, abort, jsonify, g, Response
)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from nc_trace import TraceContext, get_trace, set_trace, clear_trace
from property_evaluator import (
    PropertyListing, evaluate_property, CheckResult, Tier1Check,
    present_checks, get_score_band, proximity_synthesis,
)
from models import (
    init_db, save_snapshot, get_snapshot, increment_view_count,
    unlock_snapshot,
    log_event, check_return_visit, get_event_counts,
    get_recent_events, get_recent_snapshots,
    create_job, get_job, cancel_queued_job,
    create_payment, get_payment_by_session, get_payment_by_id,
    update_payment_status, redeem_payment,
    hash_email, check_free_tier_used, record_free_tier_usage,
)
from weather import serialize_for_result as _serialize_weather

def _quote_param(s: str) -> str:
    """URL-encode a string for use as a query parameter value.

    Uses safe='' so everything is encoded — including / and # which the
    stdlib default leaves alone.  This prevents addresses like
    "123 Main St #4B" from breaking the round-trip through Stripe's
    success redirect URL.
    """
    return _stdlib_quote(s, safe="")


# ---------------------------------------------------------------------------
# Stripe (optional — app starts without it for local dev without payments)
# ---------------------------------------------------------------------------
try:
    import stripe
    STRIPE_AVAILABLE = True
except ImportError:
    stripe = None  # type: ignore[assignment]
    STRIPE_AVAILABLE = False

load_dotenv()

# ---------------------------------------------------------------------------
# Sentry error tracking — gated on SENTRY_DSN; silent when unset (local dev)
# ---------------------------------------------------------------------------
_sentry_dsn = os.environ.get("SENTRY_DSN")
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    import requests.exceptions

    def _sentry_before_send(event, hint):
        """Demote expected failures to breadcrumbs; only unexpected errors become Sentry events."""
        exc_info = hint.get("exc_info")
        if exc_info:
            exc_type, exc_value, _ = exc_info
            msg = str(exc_value) if exc_value else ""
            # Geocoding failed for bad address (ZERO_RESULTS, etc.)
            if exc_type is ValueError and "Geocoding failed" in msg:
                sentry_sdk.add_breadcrumb(
                    category="geocoding",
                    message=msg,
                    level="warning",
                )
                return None
            # Overpass timeouts / request failures
            if exc_type is not None and issubclass(exc_type, requests.exceptions.RequestException):
                sentry_sdk.add_breadcrumb(
                    category="overpass",
                    message=msg,
                    level="warning",
                )
                return None
            # Rate limit 429 from non-requests HTTP clients (requests 429s
            # already caught above as RequestException subclass)
            if hasattr(exc_value, "response") and getattr(exc_value.response, "status_code", None) == 429:
                sentry_sdk.add_breadcrumb(
                    category="rate_limit",
                    message=msg or "HTTP 429",
                    level="warning",
                )
                return None
        return event

    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.0,
        release=os.environ.get("RAILWAY_GIT_COMMIT_SHA"),
        environment=os.environ.get("RAILWAY_ENVIRONMENT", "production"),
        before_send=_sentry_before_send,
    )

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nestcheck-dev-key')
app.config['GOOGLE_MAPS_FRONTEND_API_KEY'] = os.environ.get('GOOGLE_MAPS_FRONTEND_API_KEY')
if (not app.config['SECRET_KEY'] or app.config['SECRET_KEY'] == 'nestcheck-dev-key') and os.environ.get('FLASK_DEBUG') != '1':
    print("FATAL: SECRET_KEY is not set. Refusing to start with insecure default.", file=sys.stderr)
    print("Set SECRET_KEY in your environment or .env file.", file=sys.stderr)
    sys.exit(1)

# Proxy fix — Railway (and most PaaS) run behind a reverse proxy that sets
# X-Forwarded-For.  ProxyFix rewrites request.remote_addr to the real
# client IP so both Flask-Limiter and logging see the correct address.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

# CSRF protection — validates X-CSRFToken header on all POST requests.
# Token is rendered into a <meta> tag in templates; JS reads it and sends
# as a header on every fetch() call.
csrf = CSRFProtect(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiting — protects cost-sensitive endpoints from abuse.
# In-memory storage is per-process (with 2 gunicorn workers the effective
# limit is ~2x nominal).  Upgrade to Redis if precision is needed later.
# ---------------------------------------------------------------------------
RATE_LIMIT_DEFAULT = os.environ.get("RATE_LIMIT_DEFAULT", "60/minute")
RATE_LIMIT_EVAL = os.environ.get("RATE_LIMIT_EVAL", "10/hour")

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[RATE_LIMIT_DEFAULT],
    storage_uri="memory://",
)
logging.getLogger("flask-limiter").setLevel(logging.WARNING)


@limiter.request_filter
def _builder_bypass():
    """Exempt builder-mode requests from all rate limits."""
    return _is_builder(request)

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
# Stripe / payment config
# ---------------------------------------------------------------------------
REQUIRE_PAYMENT = os.environ.get("REQUIRE_PAYMENT", "false").lower() == "true"

LANDING_PREVIEW_SNAPSHOT_ID = os.environ.get("LANDING_PREVIEW_SNAPSHOT_ID")
if STRIPE_AVAILABLE:
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")

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
    # Set visitor ID cookie (1 year) — only if user has accepted cookies
    has_consent = request.cookies.get("nc_cookie_consent") == "1"
    if getattr(g, "set_visitor_cookie", False) and has_consent:
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

def generate_structured_summary(presented_checks: list) -> str:
    """Generate a structured summary sentence from presented checks.

    Only counts SAFETY-category checks. LIFESTYLE checks (listing details)
    are excluded from the summary since they are no longer displayed.

    Examples:
        "1 confirmed concern · 1 item we couldn't verify"
        "All safety checks passed"
        "2 confirmed concerns"
    """
    safety = [c for c in presented_checks if c.get("category") == "SAFETY"]

    confirmed = [c for c in safety if c["result_type"] == "CONFIRMED_ISSUE"]
    verification = [c for c in safety if c["result_type"] == "VERIFICATION_NEEDED"]

    parts = []
    if confirmed:
        n = len(confirmed)
        parts.append(f"{n} confirmed concern{'s' if n != 1 else ''}")
    if verification:
        n = len(verification)
        parts.append(f"{n} item{'s' if n != 1 else ''} we couldn't verify")

    if not parts:
        return "All safety checks passed"

    return " · ".join(parts)




def generate_verdict(result_dict):
    """Generate a one-line verdict based on the evaluation result."""
    score = result_dict.get("final_score", 0)
    band_info = get_score_band(score)
    verdict = band_info["label"]

    # Append proximity concern suffix when tier1 checks failed
    if not result_dict.get("passed_tier1", False):
        presented = result_dict.get("presented_checks", [])
        has_confirmed = any(
            pc.get("result_type") == "CONFIRMED_ISSUE"
            for pc in presented
        )
        if has_confirmed:
            verdict += " — has proximity concerns"

    return verdict


def generate_dimension_summaries(result_dict: dict) -> list:
    """Generate plain-English summaries for each scoring dimension.

    Reads from the serialized result dict so it works for both new
    evaluations and old snapshots (with graceful fallbacks).
    """
    # Build a lookup: tier2 dimension name → {points, max}
    tier2 = {
        s["name"]: {"points": s["points"], "max": s["max"]}
        for s in result_dict.get("tier2_scores", [])
    }

    neighborhood = result_dict.get("neighborhood_places") or {}
    green = result_dict.get("green_escape") or {}
    urban = result_dict.get("urban_access") or {}
    transit = result_dict.get("transit_access") or {}

    summaries = []

    # ── Parks & Green Space ──────────────────────────────────────
    best_park = green.get("best_daily_park")
    if best_park and best_park.get("name"):
        park_summary = f"{best_park['name']} — {best_park.get('walk_time_min', '?')} min walk"
    else:
        park_summary = "No parks found within walking distance"
    t2 = tier2.get("Parks & Green Space", {})
    summaries.append({
        "name": "Parks & Green Space",
        "summary": park_summary,
        "score": t2.get("points", 0),
        "max_score": t2.get("max", 10),
    })

    # ── Coffee & Social Spots ────────────────────────────────────
    coffee_places = neighborhood.get("coffee") or []
    walkable_coffee = [p for p in coffee_places if (p.get("walk_time_min") or 99) <= 20]
    if walkable_coffee:
        nearest = min(p.get("walk_time_min", 99) for p in walkable_coffee)
        coffee_summary = f"{len(walkable_coffee)} options within walking distance · nearest {nearest} min"
    else:
        coffee_summary = "No cafés or social spots found nearby"
    t2 = tier2.get("Coffee & Social Spots", {})
    summaries.append({
        "name": "Coffee & Social Spots",
        "summary": coffee_summary,
        "score": t2.get("points", 0),
        "max_score": t2.get("max", 10),
    })

    # ── Daily Essentials ─────────────────────────────────────────
    grocery_places = neighborhood.get("grocery") or []
    walkable_grocery = [p for p in grocery_places if (p.get("walk_time_min") or 99) <= 20]
    if walkable_grocery:
        nearest = min(p.get("walk_time_min", 99) for p in walkable_grocery)
        grocery_summary = f"{len(walkable_grocery)} stores within walking distance · nearest {nearest} min"
    else:
        grocery_summary = "No grocery stores found nearby"
    t2 = tier2.get("Daily Essentials", {})
    summaries.append({
        "name": "Daily Essentials",
        "summary": grocery_summary,
        "score": t2.get("points", 0),
        "max_score": t2.get("max", 10),
    })

    # ── Fitness & Recreation ─────────────────────────────────────
    fitness_places = neighborhood.get("fitness") or []
    walkable_fitness = [p for p in fitness_places if (p.get("walk_time_min") or 99) <= 20]
    if walkable_fitness:
        nearest = min(p.get("walk_time_min", 99) for p in walkable_fitness)
        fitness_summary = f"{len(walkable_fitness)} options within walking distance · nearest {nearest} min"
    else:
        fitness_summary = "No fitness options found nearby"
    t2 = tier2.get("Fitness & Recreation", {})
    summaries.append({
        "name": "Fitness & Recreation",
        "summary": fitness_summary,
        "score": t2.get("points", 0),
        "max_score": t2.get("max", 10),
    })

    # ── Getting Around ───────────────────────────────────────────
    freq = result_dict.get("frequency_label") or ""
    primary = urban.get("primary_transit")
    if primary and primary.get("name"):
        transit_summary = f"{primary['name']} — {primary.get('walk_time_min', '?')} min walk"
        if freq:
            transit_summary += f" · {freq}"
    elif transit.get("primary_stop"):
        transit_summary = f"{transit['primary_stop']} — {transit.get('walk_minutes', '?')} min walk"
        if freq:
            transit_summary += f" · {freq}"
    else:
        transit_summary = "No public transit found nearby"
    t2 = tier2.get("Getting Around", {})
    summaries.append({
        "name": "Getting Around",
        "summary": transit_summary,
        "score": t2.get("points", 0),
        "max_score": t2.get("max", 10),
    })

    return summaries


# ---------------------------------------------------------------------------
# Insight generation — plain-English takeaways per report section
# ---------------------------------------------------------------------------

def _tier2_lookup(result_dict: dict) -> dict:
    """Build a tier2 dimension name -> {points, max} lookup."""
    return {
        s["name"]: {"points": s["points"], "max": s["max"]}
        for s in result_dict.get("tier2_scores", [])
    }


def _nearest_walk_time(places: list) -> int | None:
    """Return the shortest walk_time_min from a list of place dicts, or None."""
    times = [p.get("walk_time_min") for p in places if p.get("walk_time_min") is not None]
    return min(times) if times else None


def _join_labels(items: list[str], conjunction: str = "and") -> str:
    """Join a list of strings with commas and a final conjunction.

    Examples:
        ["cafés"]                         → "cafés"
        ["cafés", "grocery stores"]       → "cafés and grocery stores"
        ["cafés", "grocery stores", "gyms"] → "cafés, grocery stores, and gyms"
    """
    if len(items) <= 2:
        return f" {conjunction} ".join(items)
    return f", ".join(items[:-1]) + f", {conjunction} " + items[-1]


def _insight_neighborhood(neighborhood: dict, tier2: dict) -> str | None:
    """Generate a plain-English insight for the Your Neighborhood section.

    Synthesizes across all four neighborhood categories: coffee, grocery,
    fitness, and parks.
    """
    if not neighborhood:
        return None

    # Gather per-dimension data
    dims = {
        "coffee": {
            "label": "café and social spot",
            "label_plural": "cafés and social spots",
            "places": neighborhood.get("coffee") or [],
            "score": tier2.get("Coffee & Social Spots", {}).get("points", 0),
        },
        "grocery": {
            "label": "grocery",
            "label_plural": "grocery stores",
            "places": neighborhood.get("grocery") or [],
            "score": tier2.get("Daily Essentials", {}).get("points", 0),
        },
        "fitness": {
            "label": "gym or fitness",
            "label_plural": "gyms and fitness options",
            "places": neighborhood.get("fitness") or [],
            "score": tier2.get("Fitness & Recreation", {}).get("points", 0),
        },
        "parks": {
            "label": "parks",
            "label_plural": "parks and green spaces",
            "places": neighborhood.get("parks") or [],
            "score": tier2.get("Parks & Green Space", {}).get("points", 0),
        },
    }

    # Classify each dimension
    strong = []   # score >= 7
    middling = [] # 4-6
    weak = []     # < 4

    for key, d in dims.items():
        d["nearest_time"] = _nearest_walk_time(d["places"])
        d["nearest_name"] = d["places"][0]["name"] if d["places"] else None
        d["key"] = key
        if d["score"] >= 7:
            strong.append(d)
        elif d["score"] >= 4:
            middling.append(d)
        else:
            weak.append(d)

    # Sort strong by score desc so we lead with the best
    strong.sort(key=lambda d: -d["score"])

    # All strong
    if len(strong) == len(dims):
        lead = strong[0]
        also_clause = _join_labels([d["label_plural"] for d in strong[1:]])
        return (
            f"You have solid options for everyday errands on foot — "
            f"{lead['nearest_name']} is {lead['nearest_time']} min away, "
            f"with {also_clause} also within walking distance."
        )

    # All weak
    if len(weak) == len(dims):
        # Distinguish "nothing found" from "found but far"
        has_any = any(d["places"] for d in weak)
        all_labels = _join_labels([d["label_plural"] for d in weak], "or")
        if not has_any:
            return (
                f"We didn't find {all_labels} "
                f"within reach of this address."
            )
        all_labels_and = _join_labels([d["label_plural"] for d in weak])
        return (
            f"Everyday errands would likely mean driving — "
            f"{all_labels_and} are all a fair distance from this address."
        )

    # Mixed: at least one strong and at least one weak
    if strong and weak:
        lead = strong[0]
        # Defensive: exclude lead from weak in case classification changes
        other_weak = [d for d in weak if d is not lead]
        worst = other_weak[0] if other_weak else None
        if not worst:
            return None
        # Lead with strength
        parts = [
            f"{lead['nearest_name']} is just {lead['nearest_time']} min on foot"
        ]
        if len(strong) > 1:
            other = strong[1]
            parts[0] += f", and {other['label']} options are also close by"

        # Hedge on weakness
        if not worst["places"]:
            weakness = f"we didn't find any {worst['label_plural']} nearby"
        else:
            weakness = (
                f"the nearest {worst['label']} option is "
                f"{worst['nearest_time']} minutes away"
            )

        return f"{parts[0]}. On the other hand, {weakness}."

    # Strong dims with rest middling (no weak)
    if strong and not weak:
        lead = strong[0]
        # Exclude lead; include any remaining strong dims + all middling
        rest = list(strong[1:]) + list(middling)
        other_clause = _join_labels([d["label_plural"] for d in rest])
        return (
            f"The {lead['label']} scene is a bright spot here, with "
            f"{lead['nearest_name']} {lead['nearest_time']} min on foot. "
            f"{other_clause.capitalize()} are reasonable but not as close."
        )

    # No strong, mix of middling and weak
    if not strong and weak:
        ok = middling[0] if middling else None
        # Defensive: exclude ok from weak in case classification changes
        other_weak = [d for d in weak if d is not ok]
        worst = other_weak[0] if other_weak else None
        if ok and worst:
            if not worst["places"]:
                weakness = f"we didn't find any {worst['label_plural']} nearby"
            else:
                weakness = (
                    f"{worst['label']} options are more of a trek at "
                    f"{worst['nearest_time']} minutes"
                )
            return (
                f"{ok['nearest_name']} is {ok['nearest_time']} min away for "
                f"{ok['label_plural']}, but {weakness}."
            )
        return None

    # All middling — nothing exceptional, nothing terrible
    if len(middling) == len(dims):
        all_labels = _join_labels([d["label_plural"] for d in middling])
        return (
            f"You have options for {all_labels} within reach, though "
            f"none are especially close. A short walk or bike ride covers "
            f"the basics."
        )

    return None


def _insight_getting_around(
    urban: dict | None,
    transit: dict | None,
    walk_scores: dict | None,
    freq_label: str,
    tier2: dict,
    weather: dict | None = None,
) -> str | None:
    """Generate a plain-English insight for the Getting Around section."""
    # If we have no transit data at all, return None rather than guessing.
    # This avoids false "transit is limited" on old snapshots that simply
    # didn't store transit fields.
    has_data = (
        urban is not None
        or transit is not None
    )
    if not has_data:
        return None

    score = tier2.get("Getting Around", {}).get("points", 0)
    primary = (urban or {}).get("primary_transit")
    hub = (urban or {}).get("major_hub")
    ws = walk_scores or {}

    parts = []

    # Rail station path
    if primary and primary.get("name"):
        station = primary["name"]
        walk_min = primary.get("walk_time_min", "?")

        if score >= 7:
            part = f"{station} is {walk_min} minutes on foot"
            if freq_label:
                part += f" with {freq_label.lower()}"
            parts.append(part)
            if hub and hub.get("travel_time_min"):
                parts.append(
                    f"You have a direct line into {hub['name']} — "
                    f"about {hub['travel_time_min']} minutes door to door"
                )
        elif score >= 4:
            part = f"{station} is {walk_min} minutes on foot"
            if freq_label:
                part += f", but service runs at {freq_label.lower()}"
            parts.append(part)
            parts.append(
                "For regular commuting, factor in wait times or have a "
                "backup option"
            )
        else:
            parts.append(
                f"The nearest transit option is {station}, "
                f"{walk_min} minutes on foot"
            )
            if freq_label:
                parts[-1] += f" with {freq_label.lower()}"
            parts.append(
                "Getting around would likely mean driving for most trips"
            )

    # Bus-only fallback
    elif transit and transit.get("primary_stop"):
        stop = transit["primary_stop"]
        walk_min = transit.get("walk_minutes")
        freq_bucket = transit.get("frequency_bucket", "")

        part = f"The nearest transit is the {stop} bus stop"
        if walk_min is not None:
            part += f", {walk_min} minutes on foot"
        if freq_bucket:
            part += f" with {freq_bucket.lower()} frequency service"
        parts.append(part)

        if score < 4:
            parts.append(
                "Bus service alone is unlikely to cover daily commuting "
                "needs — plan on driving or rideshare for most trips"
            )

    # No transit at all
    else:
        parts.append(
            "Transit options are limited here. Getting around would "
            "likely mean driving or rideshare for most trips"
        )

    # Bike note
    if ws.get("bike_score") is not None and ws["bike_score"] >= 70:
        parts.append(
            "Biking is a practical option — the area scores well for "
            "bike infrastructure"
        )

    # Walk Score description
    if ws.get("walk_description"):
        desc = ws["walk_description"]
        # Only add if it provides real info (not "Car-Dependent" when
        # we already said driving is needed)
        if score >= 4:
            parts.append(f"The area is rated \"{desc}\" for walkability")

    # Weather context — append 0-2 sentences when climate materially
    # affects the walkability/transit story (NES-32).
    weather_sentence = _weather_context(weather)
    if weather_sentence:
        parts.append(weather_sentence)

    if not parts:
        return None

    return ". ".join(parts) + "."


# Month name lookup for weather context sentences
_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _snow_months(monthly: list[dict]) -> str:
    """Identify the contiguous winter months with meaningful snowfall.

    Returns a human-readable range like "December through March".
    """
    snow_months = [
        m["month"] for m in monthly
        if m.get("avg_snowfall_in", 0) >= 1.0
    ]
    if not snow_months:
        return "winter"

    # Winter-centered sort: July=0 … June=11.  This keeps winter months
    # (Oct–Mar) contiguous so first/last gives the correct range.
    ordered = sorted(snow_months, key=lambda m: (m - 7) % 12)
    return f"{_MONTH_NAMES[ordered[0]]} through {_MONTH_NAMES[ordered[-1]]}"


def _hot_months(monthly: list[dict]) -> str:
    """Identify months where average highs exceed 90 deg F."""
    hot = [
        m["month"] for m in monthly
        if m.get("avg_high_f", 0) >= 90
    ]
    if not hot:
        return "summer"
    return f"{_MONTH_NAMES[hot[0]]} through {_MONTH_NAMES[hot[-1]]}"


def _weather_context(weather: dict | None) -> str | None:
    """Generate 0-1 weather context sentences for the Getting Around insight.

    Only produces output when climate thresholds are triggered.  Returns
    None for mild climates.  Combines related triggers (snow + freezing)
    into a single natural sentence to avoid redundancy.
    """
    if not weather:
        return None

    triggers = weather.get("triggers") or []
    if not triggers:
        return None

    monthly = weather.get("monthly") or []
    sentences = []

    # Snow and freezing often co-occur — combine into one sentence
    has_snow = "snow" in triggers
    has_freezing = "freezing" in triggers

    if has_snow and has_freezing:
        period = _snow_months(monthly)
        sentences.append(
            f"This area gets significant snow and freezing temperatures "
            f"in winter \u2014 expect that commute to feel longer from {period}"
        )
    elif has_snow:
        period = _snow_months(monthly)
        sentences.append(
            f"This area gets notable snow in winter \u2014 plan for that "
            f"walk to feel longer from {period}"
        )
    elif has_freezing:
        sentences.append(
            "Winters here bring extended freezing temperatures \u2014 "
            "factor in icy conditions for outdoor commuting"
        )

    # Extreme heat — independent of snow/cold
    if "extreme_heat" in triggers:
        period = _hot_months(monthly)
        sentences.append(
            f"Summers are hot \u2014 outdoor walks will be uncomfortable "
            f"from {period}"
        )

    # Frequent rain — only if no snow trigger (avoid "it snows AND rains")
    if "rain" in triggers and not has_snow:
        sentences.append(
            "This area sees frequent rain year-round \u2014 keep that in "
            "mind for daily walks and transit waits"
        )

    if not sentences:
        return None

    # Return at most 2 sentences, joined naturally
    return ". ".join(sentences[:2])


def _insight_parks(green_escape: dict | None, tier2: dict) -> str | None:
    """Generate a plain-English insight for the Parks & Green Space section."""
    if not green_escape:
        return None

    score = tier2.get("Parks & Green Space", {}).get("points", 0)
    best = green_escape.get("best_daily_park")
    nearby = green_escape.get("nearby_green_spaces") or []

    if not best or not best.get("name"):
        return "No parks or green spaces were found within walking distance of this address."

    name = best["name"]
    walk_min = best.get("walk_time_min")

    # Build nature feature fragments from OSM data
    nature_bits = []
    if best.get("osm_enriched"):
        if best.get("osm_area_sqm"):
            acres = best["osm_area_sqm"] / 4047
            if acres >= 5:
                nature_bits.append(f"roughly {acres:.0f} acres")
        if best.get("osm_has_trail"):
            nature_bits.append("trails")
        elif best.get("osm_path_count") and best["osm_path_count"] >= 3:
            nature_bits.append(f"{best['osm_path_count']} paths")

    nature_phrase = ""
    if nature_bits:
        nature_phrase = f" — {', '.join(nature_bits)}"

    nearby_note = ""
    if len(nearby) >= 2:
        nearby_note = f" {len(nearby)} other green spaces nearby give you options too."
    elif len(nearby) == 1:
        nearby_note = " There's another green space nearby as well."

    # Strong: close and high-scoring
    if score >= 7 and walk_min is not None and walk_min <= 15:
        return (
            f"{name} is {walk_min} minutes on foot{nature_phrase}. "
            f"It's the kind of park where you can go for a run, bring "
            f"kids to play, or walk the dog.{nearby_note}"
        )

    # Good park but far — only for parks that didn't score high
    if score < 7 and walk_min is not None and walk_min > 20:
        return (
            f"{name} is well-rated and offers real green space"
            f"{nature_phrase}, but at {walk_min} minutes on foot it's "
            f"more of a weekend destination than a daily stop."
            f"{nearby_note}"
        )

    # Moderate: decent park at moderate distance
    if score >= 4:
        time_desc = f"{walk_min} minutes on foot" if walk_min else "a moderate walk"
        return (
            f"{name} is {time_desc}{nature_phrase}. "
            f"Close enough for regular visits, especially on weekends."
            f"{nearby_note}"
        )

    # Weak: park exists but scored low
    time_clause = f" at {walk_min} minutes" if walk_min is not None else " nearby"
    return (
        f"Green space is limited near this address. The closest option "
        f"is {name}{time_clause} — more of a small park than "
        f"a place for a long walk or active outdoor time."
    )


def generate_insights(result_dict: dict) -> dict:
    """Generate plain-English insights for report sections.

    Reads from the serialized result dict so it works for both new
    evaluations and old snapshots (with graceful fallbacks).

    Returns a dict with keys: your_neighborhood, getting_around, parks,
    proximity.  Each value is a string or None.
    """
    tier2 = _tier2_lookup(result_dict)
    neighborhood = result_dict.get("neighborhood_places") or {}
    urban = result_dict.get("urban_access")
    transit = result_dict.get("transit_access")
    walk_scores = result_dict.get("walk_scores")
    freq_label = result_dict.get("frequency_label") or ""
    green_escape = result_dict.get("green_escape")
    presented = result_dict.get("presented_checks") or []
    weather = result_dict.get("weather")

    return {
        "your_neighborhood": _insight_neighborhood(neighborhood, tier2),
        "getting_around": _insight_getting_around(
            urban, transit, walk_scores, freq_label, tier2, weather,
        ),
        "parks": _insight_parks(green_escape, tier2),
        "proximity": proximity_synthesis(presented),
    }


def _backfill_result(result):
    """Apply standard backfills to a snapshot result dict. Mutates in place."""
    if "score_band" not in result or isinstance(result["score_band"], str):
        result["score_band"] = get_score_band(result.get("final_score", 0))
    if "dimension_summaries" not in result:
        result["dimension_summaries"] = generate_dimension_summaries(result)

    _needs_presented = (
        "presented_checks" not in result
        or any(
            "proximity_band" not in pc
            for pc in (result.get("presented_checks") or [])
            if pc.get("category") == "SAFETY"
        )
    )
    if _needs_presented and result.get("tier1_checks"):
        tier1_objs = [
            Tier1Check(
                name=c["name"],
                result=CheckResult(c["result"]),
                details=c.get("details", ""),
                required=c.get("required", True),
            )
            for c in result["tier1_checks"]
        ]
        result["presented_checks"] = present_checks(tier1_objs)
    if "structured_summary" not in result and result.get("presented_checks"):
        result["structured_summary"] = generate_structured_summary(
            result["presented_checks"]
        )

    if "insights" not in result:
        result["insights"] = generate_insights(result)


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


def _serialize_road_noise(assessment):
    """Serialize RoadNoiseAssessment to template dict.

    Returns None when assessment is absent (old snapshots / Overpass failure),
    which the template uses to hide the card.
    """
    if not assessment:
        return None
    return {
        "worst_road_name": assessment.worst_road_name,
        "worst_road_ref": assessment.worst_road_ref,
        "worst_road_type": assessment.worst_road_type,
        "worst_road_lanes": assessment.worst_road_lanes,
        "distance_ft": assessment.distance_ft,
        "estimated_dba": assessment.estimated_dba,
        "severity": assessment.severity.value if hasattr(assessment.severity, "value") else assessment.severity,
        "severity_label": assessment.severity_label,
        "methodology_note": assessment.methodology_note,
        "all_roads_assessed": assessment.all_roads_assessed,
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
            "lat": pt.lat,
            "lng": pt.lng,
            "walk_time_min": pt.walk_time_min,
            "drive_time_min": pt.drive_time_min,
            "parking_available": pt.parking_available,
            "wheelchair_accessible_entrance": pt.wheelchair_accessible_entrance,
            "elevator_available": pt.elevator_available,
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
        # Unified frequency label — prefer smart heuristic bucket,
        # fall back to review-count frequency_class.
        "frequency_label": (
            f"{result.transit_access.frequency_bucket} frequency"
            if result.transit_access and result.transit_access.frequency_bucket
            else (
                result.urban_access.primary_transit.frequency_class
                if result.urban_access and result.urban_access.primary_transit
                   and result.urban_access.primary_transit.frequency_class
                else ""
            )
        ),
        "green_escape": _serialize_green_escape(result.green_escape_evaluation),
        "road_noise": _serialize_road_noise(
            getattr(result, "road_noise_assessment", None)
        ),
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
        "model_version": getattr(result, "model_version", ""),
    }

    # Neighborhood places — already plain dicts, pass through as-is
    output["neighborhood_places"] = result.neighborhood_places if result.neighborhood_places else None

    # Base64-encoded neighborhood map PNG
    output["neighborhood_map"] = result.neighborhood_map_b64

    # Emergency services — informational, not scored (NES-50).
    # Three states: None = lookup failed (section hidden), [] = searched
    # but found nothing ("none found" message), [...] = found stations.
    # Key absent on old snapshots → section hidden via `is defined` guard.
    output["emergency_services"] = (
        [
            {
                "name": s.name,
                "type": s.service_type,
                "drive_time_min": s.drive_time_min,
                "lat": s.lat,
                "lng": s.lng,
            }
            for s in result.emergency_services
        ]
        if result.emergency_services is not None
        else None
    )

    # Nearby libraries — informational, not scored (NES-106).
    # Same three-state convention as emergency_services.
    output["nearby_libraries"] = (
        [
            {
                "name": lib.name,
                "distance_ft": lib.distance_ft,
                "est_walk_min": lib.est_walk_min,
                "lat": lib.lat,
                "lng": lib.lng,
            }
            for lib in result.nearby_libraries
        ]
        if result.nearby_libraries is not None
        else None
    )
    output["library_count"] = result.library_count

    # Weather climate normals — informational context for insights (NES-32).
    output["weather"] = _serialize_weather(
        getattr(result, "weather_summary", None)
    )

    # Presentation layer for the new results UI
    output["presented_checks"] = present_checks(result.tier1_checks)
    output["show_score"] = True
    output["structured_summary"] = generate_structured_summary(
        output["presented_checks"]
    )

    output["verdict"] = generate_verdict(output)
    output["score_band"] = get_score_band(result.final_score)
    output["dimension_summaries"] = generate_dimension_summaries(output)
    output["insights"] = generate_insights(output)
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


@app.route("/", methods=["GET", "POST"])
@limiter.limit(RATE_LIMIT_EVAL, methods=["POST"])
def index():
    print(f"INDEX ROUTE: LANDING_PREVIEW_SNAPSHOT_ID={LANDING_PREVIEW_SNAPSHOT_ID!r}")
    result = None
    error = None
    error_detail = None  # builder-mode diagnostic
    address = ""
    snapshot_id = None
    request_id = getattr(g, "request_id", "unknown")

    preview_result = None
    preview_snapshot_id = None
    if result is None and LANDING_PREVIEW_SNAPSHOT_ID:
        try:
            print(f"INDEX_PREVIEW: about to call get_snapshot({LANDING_PREVIEW_SNAPSHOT_ID!r})")
            snap = get_snapshot(LANDING_PREVIEW_SNAPSHOT_ID)
            print(f"PREVIEW LOAD: snap={snap is not None}, has_result={snap.get('result') is not None if snap else 'N/A'}, preview_result={preview_result is not None}")
            if snap and snap.get("result"):
                _backfill_result(snap["result"])
                preview_result = snap["result"]
                preview_snapshot_id = LANDING_PREVIEW_SNAPSHOT_ID
        except Exception:
            logger.exception("Failed to load landing preview snapshot")

    # Temporary debug: diagnose landing preview loading
    snap_status = (snap is not None) if "snap" in dir() else "not reached"
    logger.info(
        "Landing preview: env=%s, snap=%s, result=%s",
        LANDING_PREVIEW_SNAPSHOT_ID,
        snap_status,
        preview_result is not None,
    )

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
                preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
                is_builder=g.is_builder, request_id=request_id,
                require_payment=REQUIRE_PAYMENT,
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
                    "variables in your Railway dashboard."
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
                preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
                is_builder=g.is_builder, request_id=request_id,
                require_payment=REQUIRE_PAYMENT,
            )

        # TODO [PACK_LOGIC]: Check evaluation limits here.
        # if not g.is_builder and FEATURE_CONFIG["max_evaluations_per_day"]:
        #     count = get_daily_eval_count(g.visitor_id)
        #     if count >= FEATURE_CONFIG["max_evaluations_per_day"]:
        #         error = "Daily evaluation limit reached."
        #         return render_template(...)

        # ---------------------------------------------------------------
        # Free tier gate — one free evaluation per email (NES-120)
        # Checked before the payment gate so eligible users skip Stripe.
        # ---------------------------------------------------------------
        email = ""
        email_h = None       # set if email provided and valid
        free_tier_used = False  # True when this request is using the free tier

        if REQUIRE_PAYMENT and not g.is_builder:
            payment_token = request.form.get("payment_token", "").strip()
            email = request.form.get("email", "").strip()

            if not payment_token and email:
                # Minimal server-side email format check
                if "@" not in email or "." not in email.split("@")[-1]:
                    if _wants_json():
                        return jsonify({
                            "error": "Please enter a valid email address.",
                            "request_id": request_id,
                        }), 400
                    error = "Please enter a valid email address."
                    return render_template(
                        "index.html", result=result, error=error,
                        error_detail=error_detail,
                        address=address, snapshot_id=snapshot_id,
                        preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
                        is_builder=g.is_builder, request_id=request_id,
                        require_payment=REQUIRE_PAYMENT,
                    )

                # Free tier path: check if this email already claimed
                email_h = hash_email(email)
                if check_free_tier_used(email_h):
                    log_event(
                        "free_tier_exhausted", visitor_id=g.visitor_id,
                        metadata={"email_hash": email_h[:12], "address": address},
                    )
                    if _wants_json():
                        return jsonify({
                            "error": "free_tier_exhausted",
                            "request_id": request_id,
                        }), 403
                    error = "You've already used your free evaluation."
                    return render_template(
                        "index.html", result=result, error=error,
                        error_detail=error_detail,
                        address=address, snapshot_id=snapshot_id,
                        preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
                        is_builder=g.is_builder, request_id=request_id,
                        require_payment=REQUIRE_PAYMENT,
                    )
                free_tier_used = True
                logger.info(
                    "[%s] Free tier claim for email_hash=%s",
                    request_id, email_h[:12],
                )

        # ---------------------------------------------------------------
        # Payment gate — only enforced when REQUIRE_PAYMENT=true
        # and the request is NOT using the free tier
        # ---------------------------------------------------------------
        payment = None  # set if a valid payment is redeemed
        if REQUIRE_PAYMENT and not g.is_builder and not free_tier_used:
            payment_token = request.form.get("payment_token", "").strip()
            if not payment_token:
                if _wants_json():
                    return jsonify({
                        "error": "Payment required",
                        "requires_payment": True,
                        "request_id": request_id,
                    }), 402
                error = "Payment is required before running an evaluation."
                return render_template(
                    "index.html", result=result, error=error,
                    error_detail=error_detail,
                    address=address, snapshot_id=snapshot_id,
                    preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
                    is_builder=g.is_builder, request_id=request_id,
                    require_payment=REQUIRE_PAYMENT,
                )

            payment = get_payment_by_id(payment_token)
            if not payment or payment["status"] not in ("paid", "pending", "failed_reissued"):
                if _wants_json():
                    return jsonify({
                        "error": "Invalid or expired payment",
                        "requires_payment": True,
                        "request_id": request_id,
                    }), 402
                error = "Invalid or expired payment token."
                return render_template(
                    "index.html", result=result, error=error,
                    error_detail=error_detail,
                    address=address, snapshot_id=snapshot_id,
                    preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
                    is_builder=g.is_builder, request_id=request_id,
                    require_payment=REQUIRE_PAYMENT,
                )

            # If status is still 'pending', verify with Stripe directly
            # (success redirect can arrive before the webhook)
            if payment["status"] == "pending" and STRIPE_AVAILABLE:
                try:
                    session = stripe.checkout.Session.retrieve(
                        payment["stripe_session_id"]
                    )
                    if session.payment_status == "paid":
                        update_payment_status(payment["id"], "paid")
                    else:
                        if _wants_json():
                            return jsonify({
                                "error": "Payment not completed",
                                "requires_payment": True,
                                "request_id": request_id,
                            }), 402
                        error = "Payment has not been completed yet."
                        return render_template(
                            "index.html", result=result, error=error,
                            error_detail=error_detail,
                            address=address, snapshot_id=snapshot_id,
                            preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
                            is_builder=g.is_builder, request_id=request_id,
                            require_payment=REQUIRE_PAYMENT,
                        )
                except Exception as e:
                    logger.error(
                        "[%s] Stripe session verify failed: %s",
                        request_id, e,
                    )
                    if _wants_json():
                        return jsonify({
                            "error": "Could not verify payment",
                            "requires_payment": True,
                            "request_id": request_id,
                        }), 402
                    error = "Could not verify payment status. Please try again."
                    return render_template(
                        "index.html", result=result, error=error,
                        error_detail=error_detail,
                        address=address, snapshot_id=snapshot_id,
                        preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
                        is_builder=g.is_builder, request_id=request_id,
                        require_payment=REQUIRE_PAYMENT,
                    )
            elif payment["status"] == "pending":
                if _wants_json():
                    return jsonify({
                        "error": "Payment not completed",
                        "requires_payment": True,
                        "request_id": request_id,
                    }), 402
                error = "Payment has not been completed yet."
                return render_template(
                    "index.html", result=result, error=error,
                    error_detail=error_detail,
                    address=address, snapshot_id=snapshot_id,
                    preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
                    is_builder=g.is_builder, request_id=request_id,
                    require_payment=REQUIRE_PAYMENT,
                )

        # Async queue: create job first so redeem_payment can link atomically.
        # A job with no payment is harmless; a redeemed payment with no job is a lost credit.
        place_id = request.form.get('place_id', '').strip() or None
        job_id = create_job(
            address, visitor_id=g.visitor_id, request_id=request_id,
            place_id=place_id, email_hash=email_h,
        )
        logger.info("[%s] Created evaluation job %s for: %s", request_id, job_id, address)

        # Record free tier usage atomically — if a concurrent request with
        # the same email won the INSERT race, cancel this job.
        if free_tier_used:
            if not record_free_tier_usage(email_h, email, job_id):
                cancel_queued_job(job_id, "free_tier_race_lost")
                if _wants_json():
                    return jsonify({
                        "error": "free_tier_exhausted",
                        "request_id": request_id,
                    }), 403
                error = "You've already used your free evaluation."
                return render_template(
                    "index.html", result=result, error=error,
                    error_detail=error_detail,
                    address=address, snapshot_id=snapshot_id,
                    preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
                    is_builder=g.is_builder, request_id=request_id,
                    require_payment=REQUIRE_PAYMENT,
                )
            log_event(
                "free_tier_claimed", visitor_id=g.visitor_id,
                metadata={"email_hash": email_h[:12], "address": address, "job_id": job_id},
            )

        if payment is not None:
            # Redeem the credit (paid -> redeemed) with job_id set atomically
            if not redeem_payment(payment["id"], job_id=job_id):
                # Mark orphaned job as failed so the worker won't run a
                # free evaluation.  Use cancel_queued_job to avoid clobbering
                # a job the worker may have already claimed.
                cancel_queued_job(job_id, "payment_already_used")
                if _wants_json():
                    return jsonify({
                        "error": "Payment already used",
                        "requires_payment": True,
                        "request_id": request_id,
                    }), 402
                error = "This payment has already been used for an evaluation."
                return render_template(
                    "index.html", result=result, error=error,
                    error_detail=error_detail,
                    address=address, snapshot_id=snapshot_id,
                    preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
                    is_builder=g.is_builder, request_id=request_id,
                    require_payment=REQUIRE_PAYMENT,
                )

        if _wants_json():
            return jsonify({"job_id": job_id})
        # Non-JS form POST: redirect to index with job_id so the page can poll
        return redirect(url_for("index", job_id=job_id))

    # Optional: when redirected with ?job_id= after form POST, frontend will poll
    job_id = request.args.get("job_id")

    return render_template(
        "index.html", result=result, error=error,
        error_detail=error_detail,
        address=address, snapshot_id=snapshot_id,
        job_id=job_id,
        preview_result=preview_result, preview_snapshot_id=preview_snapshot_id,
        is_builder=g.is_builder, request_id=request_id,
        require_payment=REQUIRE_PAYMENT,
    )


@app.route("/job/<job_id>")
@limiter.exempt
def job_status(job_id):
    """
    Polling endpoint for async evaluation. Returns JSON:
    {status, current_stage, snapshot_id?, error?}
    status: queued | running | done | failed
    """
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    payload = {
        "status": job["status"],
        "current_stage": job["current_stage"],
    }
    if job.get("result_snapshot_id"):
        payload["snapshot_id"] = job["result_snapshot_id"]
    if job.get("error"):
        payload["error"] = job["error"]
    return jsonify(payload)


@app.route("/s/<snapshot_id>")
def view_snapshot(snapshot_id):
    """Public, read-only snapshot page. No auth required.

    NES-132: Preview snapshots show only health/safety checks + road noise.
    Unlock via payment_token query param (return from Stripe checkout).
    """
    print(f"VIEW_SNAPSHOT: looking for {snapshot_id!r}")
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        abort(404)

    # ── NES-132: Preview unlock via payment_token ──
    payment_token = request.args.get("payment_token", "").strip()
    is_preview = bool(snapshot.get("is_preview"))
    payment_pending = False

    if payment_token and is_preview:
        payment = get_payment_by_id(payment_token)
        # Verify the payment is linked to THIS snapshot (prevents using
        # someone else's payment_token to unlock a different snapshot).
        if (payment
                and payment["status"] in ("paid", "redeemed")
                and payment.get("snapshot_id") == snapshot_id):
            unlock_snapshot(snapshot_id)
            is_preview = False
            log_event("preview_unlocked", snapshot_id=snapshot_id,
                      visitor_id=g.visitor_id,
                      metadata={"payment_id": payment_token})
            # Redirect to clean URL (strip payment_token)
            return redirect(url_for("view_snapshot", snapshot_id=snapshot_id))
        elif (payment
                and payment["status"] == "pending"
                and payment.get("snapshot_id") == snapshot_id):
            # Stripe webhook hasn't fired yet — template will show
            # "Payment processing..." with auto-refresh polling.
            payment_pending = True

    # Builder bypass — always show full report
    if g.is_builder:
        is_preview = False

    # Track view — skip during payment-pending polling to avoid inflating count
    if not payment_pending:
        increment_view_count(snapshot_id)
        log_event("snapshot_viewed", snapshot_id=snapshot_id,
                  visitor_id=g.visitor_id)

    result = snapshot["result"]
    _backfill_result(result)

    return render_template(
        "snapshot.html",
        snapshot=snapshot,
        result=result,
        snapshot_id=snapshot_id,
        is_builder=g.is_builder,
        is_preview=is_preview,
        payment_pending=payment_pending,
    )


@app.route("/api/snapshot/<snapshot_id>/status")
def snapshot_status(snapshot_id):
    """Lightweight status check for preview unlock polling (NES-132).

    Returns {unlocked: true/false} without loading the full result_json.
    Used by payment-pending polling to avoid full page reloads that inflate
    view_count and waste bandwidth.
    """
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({"error": "Snapshot not found"}), 404
    return jsonify({"unlocked": not bool(snapshot.get("is_preview"))})


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


@app.route("/api/event", methods=["POST"])
@limiter.limit("30/minute")
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
    return render_template("pricing.html", require_payment=REQUIRE_PAYMENT)


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


# ---------------------------------------------------------------------------
# Stripe Checkout — create a checkout session for one evaluation
# ---------------------------------------------------------------------------

@app.route("/checkout/create", methods=["POST"])
@limiter.limit("5/minute")
def create_checkout():
    """Create a Stripe Checkout session for one evaluation.

    Price is defined by STRIPE_PRICE_ID in Stripe dashboard.
    Expects form data with 'address'. Returns JSON with 'checkout_url'.
    The payment_id is embedded in the success_url so the frontend can
    pass it back to POST / after payment completes.

    NES-132: Also supports preview unlock flow — when 'snapshot_id' is
    provided, the checkout unlocks an existing preview snapshot instead
    of creating a new evaluation.
    """
    if not REQUIRE_PAYMENT or not STRIPE_AVAILABLE:
        return jsonify({"error": "Payments not enabled"}), 400

    # NES-132: Preview unlock flow — snapshot_id provided
    unlock_snapshot_id = request.form.get("snapshot_id", "").strip() or None

    if unlock_snapshot_id:
        snapshot = get_snapshot(unlock_snapshot_id)
        if not snapshot or not snapshot.get("is_preview"):
            return jsonify({"error": "Invalid snapshot for unlock"}), 400
        address = snapshot["address_input"]
    else:
        address = request.form.get("address", "").strip()
        if not address:
            return jsonify({"error": "Address required"}), 400

    place_id = request.form.get("place_id", "").strip() or None
    visitor_id = getattr(g, "visitor_id", "unknown")
    payment_id = secrets.token_hex(8)

    if unlock_snapshot_id:
        # Unlock flow: return to snapshot page after payment
        success_url = (
            url_for("view_snapshot", snapshot_id=unlock_snapshot_id, _external=True)
            + f"?payment_token={payment_id}"
        )
        cancel_url = url_for("view_snapshot", snapshot_id=unlock_snapshot_id, _external=True)
    else:
        # New eval flow: return to index (existing behavior)
        success_url = (
            url_for("index", _external=True)
            + f"?payment_token={payment_id}&address={_quote_param(address)}"
        )
        if place_id:
            success_url += f"&place_id={_quote_param(place_id)}"
        cancel_url = url_for("index", _external=True)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": STRIPE_PRICE_ID,
                "quantity": 1,
            }],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=payment_id,
            metadata={"address": address, "visitor_id": visitor_id},
        )
    except Exception as e:
        logger.error("Stripe checkout creation failed: %s", e)
        return jsonify({"error": "Payment system error"}), 500

    create_payment(payment_id, session.id, visitor_id, address,
                   snapshot_id=unlock_snapshot_id)
    log_event(
        "checkout_created",
        visitor_id=visitor_id,
        metadata={"payment_id": payment_id, "address": address,
                   "snapshot_id": unlock_snapshot_id},
    )
    return jsonify({"checkout_url": session.url})


# ---------------------------------------------------------------------------
# Stripe Webhook — server-to-server payment confirmation
# ---------------------------------------------------------------------------

@app.route("/webhook/stripe", methods=["POST"])
@limiter.exempt
@csrf.exempt  # Server-to-server; Stripe signs payloads with its own webhook secret.
def stripe_webhook():
    """Receive Stripe webhook events (e.g. checkout.session.completed).

    This endpoint is called by Stripe's servers, NOT the user's browser.
    It must NOT require the nc_vid cookie or any visitor identification.
    Always returns 200 to acknowledge receipt, except on verification failure.
    """
    if not STRIPE_AVAILABLE:
        return "", 400

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.warning("Stripe webhook verification failed: %s", e)
        return "", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        stripe_session_id = session["id"]
        payment = get_payment_by_session(stripe_session_id)
        if payment and payment["status"] == "pending":
            # Atomic: only transitions pending -> paid. If POST / already
            # verified and redeemed this payment, the WHERE guard prevents
            # overwriting 'redeemed' back to 'paid' (TOCTOU race).
            updated = update_payment_status(payment["id"], "paid", expected_status="pending")
            if updated:
                logger.info("Payment confirmed via webhook: %s", payment["id"])
                # NES-132: Auto-unlock preview snapshot if this payment is
                # for a preview unlock (snapshot_id set at checkout creation).
                if payment.get("snapshot_id"):
                    unlock_snapshot(payment["snapshot_id"])
                    log_event("preview_unlocked_webhook",
                              snapshot_id=payment["snapshot_id"],
                              metadata={"payment_id": payment["id"]})

    # Always return 200 to acknowledge receipt — even for event types we don't handle
    return "", 200


@app.route("/robots.txt")
@limiter.exempt
def robots_txt():
    """Serve robots.txt with crawler rules and sitemap location."""
    sitemap_url = request.host_url.rstrip("/") + "/sitemap.xml"
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "Disallow: /checkout/\n"
        "Disallow: /webhook/\n"
        "Disallow: /job/\n"
        "Disallow: /api/\n"
        "Disallow: /debug/\n"
        "Disallow: /builder/\n"
        "Disallow: /healthz\n"
        "\n"
        f"Sitemap: {sitemap_url}\n"
    )
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
@limiter.exempt
def sitemap_xml():
    """Generate sitemap.xml with static pages.

    Snapshots are intentionally excluded — they are share-by-link only
    and including them would make evaluated addresses publicly discoverable.
    """
    base = request.host_url.rstrip("/")

    static_pages = ["/", "/pricing", "/privacy", "/terms"]
    urls = []
    for path in static_pages:
        urls.append(f"  <url><loc>{base}{path}</loc></url>")

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n"
        '</urlset>\n'
    )
    return Response(xml, mimetype="application/xml")


@app.route("/healthz")
@limiter.exempt
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
@limiter.exempt
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

@app.errorhandler(429)
def rate_limit_exceeded(e):
    if _wants_json():
        return jsonify({
            "error": "Too many requests. Please wait and try again.",
        }), 429
    return render_template("429.html"), 429


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_error(e):
    return render_template("500.html"), 500


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

# Initialize database on import (safe to call repeatedly)
init_db()

if __name__ == "__main__":
    # Development: start the async evaluation worker thread in this process
    from worker import start_worker
    start_worker()
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
if os.environ.get("FLASK_RUN_FROM_CLI") == "true" and os.environ.get("START_WORKER") != "1":
    logger.warning(
        "WARNING: No background worker running. Jobs will not process. "
        "Use gunicorn or set START_WORKER=1."
    )
elif os.environ.get("START_WORKER") == "1":
    try:
        from worker import start_worker
        start_worker()
    except Exception:
        logger.exception("Failed to start background worker via START_WORKER=1")
