import json
import os
import io
import csv
import logging
import re
import shlex
import subprocess
import sys
import time
import uuid
import sqlite3
import traceback
from datetime import datetime, timezone
from collections import defaultdict
from functools import wraps
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import click
from flask import (
    Flask, request, render_template, redirect, url_for,
    make_response, abort, jsonify, g, Response, flash, session
)
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_login import LoginManager, login_user, logout_user, current_user, login_required
from dotenv import load_dotenv
from markupsafe import escape as _html_escape
from nc_trace import TraceContext, get_trace, set_trace, clear_trace
from property_evaluator import (
    PropertyListing, evaluate_property, CheckResult, GoogleMapsClient,
    get_score_band, proximity_synthesis,
)
from scoring_config import (
    SCORING_MODEL,
    TIER2_NAME_TO_DIMENSION,
    HEALTH_CHECK_CITATIONS,
    CONFIDENCE_VERIFIED, CONFIDENCE_ESTIMATED, CONFIDENCE_SPARSE, CONFIDENCE_NOT_SCORED,
    _LEGACY_CONFIDENCE_MAP,
    WALK_DRIVE_BOTH_THRESHOLD, WALK_DRIVE_ONLY_THRESHOLD,
)
from census import serialize_for_result as _serialize_census
from coverage_config import COVERAGE_MANIFEST, get_section_freshness
from models import (
    _get_db, init_db, save_snapshot, get_snapshot, increment_view_count,
    log_event, check_return_visit, get_event_counts,
    get_recent_events, get_recent_snapshots, get_sitemap_snapshots,
    get_snapshot_by_place_id, is_snapshot_fresh, save_snapshot_for_place,
    get_snapshots_by_ids, update_snapshot_email_sent,
    create_job, get_job,
    get_user_by_id, get_or_create_user, claim_snapshots_for_user,
    get_user_snapshots, update_user_stripe_customer,
    create_payment, get_payment_by_id, get_payment_by_session,
    update_payment_status, redeem_payment, update_payment_job_id,
    hash_email, check_free_tier_available, record_free_tier_usage,
    PAYMENT_PENDING, PAYMENT_PAID, PAYMENT_REDEEMED, PAYMENT_FAILED_REISSUED,
    SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCELED, SUBSCRIPTION_PAST_DUE,
    SUBSCRIPTION_EXPIRED,
    create_subscription, update_subscription_status, is_subscription_active,
    get_active_subscription,
    update_payment_snapshot_id_direct,
    save_feedback, save_inline_feedback, has_inline_feedback,
    get_feedback_digest,
    get_city_snapshots, get_city_stats, get_cities_with_snapshots,
    get_city_name_by_slug,
)

load_dotenv()

app = Flask(__name__)
# Trust Railway's reverse proxy headers so url_for(_external=True) generates https://.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nestcheck-dev-key')
app.config['GOOGLE_MAPS_FRONTEND_API_KEY'] = os.environ.get('GOOGLE_MAPS_FRONTEND_API_KEY')

# Session and remember-me cookie security hardening.
_is_production = app.config['SECRET_KEY'] != 'nestcheck-dev-key'
if not _is_production and os.environ.get("RAILWAY_ENVIRONMENT"):
    raise RuntimeError(
        "SECRET_KEY is using the default dev value in a production environment. "
        "Set the SECRET_KEY environment variable to a secure random string."
    )
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = _is_production
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_SECURE'] = _is_production
# _CANONICAL_DOMAIN is used by _redirect_to_canonical() below to 301-redirect
# non-canonical hosts.  Cookie domain pinning is intentionally omitted — the
# canonical redirect already ensures all traffic (and therefore all cookies)
# goes through the single canonical host.  Setting SESSION_COOKIE_DOMAIN to a
# domain cookie (e.g. ".nestcheck.org") causes dual-cookie conflicts with any
# pre-existing host-only session cookies, breaking login persistence.
_CANONICAL_DOMAIN = os.environ.get("CANONICAL_DOMAIN")  # e.g. "nestcheck.org"
# Keep templates render-safe even if Flask-WTF is unavailable at runtime.
app.jinja_env.globals.setdefault("csrf_token", lambda: "")

# Static asset cache-busting: short git hash computed once at startup.
# Appended to CSS/JS URLs as ?v=<hash> so CDN/browser caches bust on deploy.
import subprocess as _sp
try:
    _ASSET_VERSION = _sp.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        stderr=_sp.DEVNULL, cwd=os.path.dirname(__file__) or "."
    ).decode().strip()
except Exception:
    _ASSET_VERSION = str(int(__import__("time").time()))
app.jinja_env.globals["asset_v"] = _ASSET_VERSION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Warn at startup if critical env vars are missing — visible in Railway deploy logs.
if not os.environ.get("GOOGLE_MAPS_API_KEY"):
    logger.warning("GOOGLE_MAPS_API_KEY is not set — evaluations will fail.")

_csrf = None
try:
    from flask_wtf.csrf import CSRFProtect, generate_csrf
except Exception:
    logger.warning(
        "Flask-WTF not available; CSRF protection disabled and csrf_token() fallback in use."
    )
else:
    _csrf = CSRFProtect(app)
    app.jinja_env.globals["csrf_token"] = generate_csrf

# ---------------------------------------------------------------------------
# Flask-Login setup
# ---------------------------------------------------------------------------

class _FlaskUser:
    """Minimal user wrapper for Flask-Login (not a DB model)."""

    def __init__(self, user_dict: dict):
        self.id = user_dict["id"]
        self.email = user_dict["email"]
        self.name = user_dict.get("name")
        self.picture_url = user_dict.get("picture_url")
        self.stripe_customer_id = user_dict.get("stripe_customer_id")
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False

    def get_id(self) -> str:
        return self.id


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth_login"
login_manager.login_message = "Please sign in to access your reports."
login_manager.login_message_category = "info"


@login_manager.user_loader
def _load_user(user_id: str):
    user_dict = get_user_by_id(user_id)
    return _FlaskUser(user_dict) if user_dict else None


# ---------------------------------------------------------------------------
# Google OAuth via Authlib (optional — app works without it)
# Google OAuth redirect URI is built dynamically from request host via url_for().
# IMPORTANT: Only https://nestcheck.org/auth/callback should be registered in
# Google Cloud Console. Remove any Railway URLs from authorized redirect URIs.
# The CANONICAL_DOMAIN redirect ensures all OAuth flows go through nestcheck.org.
# ---------------------------------------------------------------------------
_GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
_GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
_oauth_enabled = bool(_GOOGLE_CLIENT_ID and _GOOGLE_CLIENT_SECRET)

if _oauth_enabled:
    from authlib.integrations.flask_client import OAuth
    oauth = OAuth(app)
    oauth.register(
        name="google",
        client_id=_GOOGLE_CLIENT_ID,
        client_secret=_GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
else:
    oauth = None
    logger.info(
        "Google OAuth not configured (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET missing). "
        "Sign-in will be unavailable."
    )

# Make oauth_enabled available in all templates for conditional nav rendering.
app.jinja_env.globals["oauth_enabled"] = _oauth_enabled

# ---------------------------------------------------------------------------
# Scoring key context — static band definitions for template rendering
# ---------------------------------------------------------------------------
_BAND_DESCRIPTIONS = {
    "band-exceptional": "Excellent across nearly all dimensions",
    "band-strong": "Good daily fit with minor gaps",
    "band-moderate": "Mixed — some strengths, some limitations",
    "band-limited": "Significant gaps in daily livability",
    "band-poor": "Major limitations across most dimensions",
}


def _build_score_bands_context():
    """Build display-ready band dicts from SCORING_MODEL.score_bands.

    Returns a list of dicts ordered descending by threshold (highest first).
    Each dict has: threshold, upper_bound, label, css_class, description.
    """
    raw = SCORING_MODEL.score_bands  # tuple of ScoreBand, descending
    bands = []
    for i, sb in enumerate(raw):
        bands.append({
            "threshold": sb.threshold,
            "upper_bound": 100 if i == 0 else raw[i - 1].threshold - 1,
            "label": sb.label,
            "css_class": sb.css_class,
            "description": _BAND_DESCRIPTIONS.get(sb.css_class, ""),
        })
    return bands


app.jinja_env.globals["score_bands"] = _build_score_bands_context()

# ---------------------------------------------------------------------------
# Startup: warn immediately if required config is missing
# ---------------------------------------------------------------------------
if not os.environ.get("GOOGLE_MAPS_API_KEY"):
    logger.warning(
        "GOOGLE_MAPS_API_KEY is not set. "
        "Address evaluations will fail until it is configured. "
        "For local development, copy .env.example to .env and add your key."
    )

if not app.config.get("GOOGLE_MAPS_FRONTEND_API_KEY"):
    logger.warning(
        "GOOGLE_MAPS_FRONTEND_API_KEY is not set. "
        "Address autocomplete will be disabled on the landing page. "
        "Set this to a domain-restricted Google Maps API key."
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
BUILDER_SECRET = os.environ.get("BUILDER_SECRET")


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
    if BUILDER_SECRET and req.cookies.get("nc_builder") == BUILDER_SECRET:
        return True
    if BUILDER_SECRET and req.args.get("builder_key") == BUILDER_SECRET:
        return True
    return False


# ---------------------------------------------------------------------------
# Stripe integration (optional — app works without it)
# ---------------------------------------------------------------------------
_STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
_STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
_STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID")
_STRIPE_SUBSCRIPTION_PRICE_ID = os.environ.get("STRIPE_SUBSCRIPTION_PRICE_ID")
REQUIRE_PAYMENT = os.environ.get("REQUIRE_PAYMENT", "").lower() == "true"

try:
    import stripe
    stripe.api_key = _STRIPE_SECRET_KEY
    STRIPE_AVAILABLE = bool(_STRIPE_SECRET_KEY)
except ImportError:
    stripe = None  # type: ignore[assignment]
    STRIPE_AVAILABLE = False

if not STRIPE_AVAILABLE:
    logger.info(
        "Stripe not configured (STRIPE_SECRET_KEY missing or stripe package not installed). "
        "Payment features will be unavailable."
    )

# Make require_payment available in all templates for payment gating.
app.jinja_env.globals["require_payment"] = REQUIRE_PAYMENT


def _get_or_create_stripe_customer(user) -> Optional[str]:
    """Get existing or create new Stripe customer for a logged-in user.

    Returns the Stripe customer ID (cus_xxx), or None on failure.
    Failures are logged but never block checkout — the session will
    proceed without a customer association.
    """
    if not STRIPE_AVAILABLE:
        return None

    # Reuse existing Stripe customer if already linked.
    if user.stripe_customer_id:
        return user.stripe_customer_id

    try:
        customer = stripe.Customer.create(
            email=user.email,
            name=user.name,
            metadata={"nestcheck_user_id": user.id},
        )
        cus_id = customer.id
        update_user_stripe_customer(user.id, cus_id)
        logger.info("Created Stripe customer %s for user %s", cus_id, user.email)
        return cus_id
    except Exception:
        logger.warning("Failed to create Stripe customer for %s", user.email, exc_info=True)
        return None


# Paths exempt from canonical domain redirect (health probes, webhooks).
_CANONICAL_EXEMPT_PATHS = frozenset({
    "/healthz",              # Railway health probes
    "/api/spatial-health",   # Cron service health check
    "/webhook/stripe",       # Stripe webhook (POST, signature-verified)
    "/robots.txt",           # Crawlers
})


@app.before_request
def _redirect_to_canonical():
    """301-redirect non-canonical domains (e.g. Railway URL) to nestcheck.org."""
    if not _CANONICAL_DOMAIN:
        return  # No canonical domain set — skip (local dev, staging)
    if request.path in _CANONICAL_EXEMPT_PATHS:
        return  # Health probes and webhooks must work on any domain
    host = request.host.split(":")[0]  # Strip port if present
    if host != _CANONICAL_DOMAIN:
        target = f"https://{_CANONICAL_DOMAIN}{request.full_path}"
        if target.endswith("?"):
            target = target[:-1]
        return redirect(target, code=301)


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

    # Authenticated user context — available in templates via g.user_email
    g.user_email = current_user.email if current_user.is_authenticated else None
    g.user_name = current_user.name if current_user.is_authenticated else None


# --- Worker thread watchdog ---
# Checks every 30s (on inbound requests) whether the background evaluation
# worker is alive and restarts it if not.  This catches the failure mode where
# gunicorn keeps serving HTTP but the daemon worker thread has crashed.
_worker_watchdog_last_check = 0.0
_WORKER_WATCHDOG_INTERVAL = 30.0  # seconds


@app.before_request
def _worker_watchdog():
    global _worker_watchdog_last_check
    now = time.monotonic()
    if now - _worker_watchdog_last_check < _WORKER_WATCHDOG_INTERVAL:
        return
    _worker_watchdog_last_check = now
    try:
        from worker import ensure_worker_alive
        ensure_worker_alive()
    except Exception:
        logger.exception("Worker watchdog check failed")


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
    if BUILDER_SECRET and request.args.get("builder_key") == BUILDER_SECRET:
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
# Walkability summary (NES-249) — display-time derivation for sidebar widget
# ---------------------------------------------------------------------------

_WALK_CATEGORIES = [
    ("coffee", "Cafes"),
    ("grocery", "Groceries"),
    ("fitness", "Fitness"),
    ("parks", "Parks"),
    ("transit", "Transit"),
]


def _best_walk_time(places):
    """Return the minimum walk_time_min from a list of place dicts.

    Skips placeholder entries (rating is None) and unreachable sentinels
    (walk_time_min >= 9999).  Returns None when no valid time exists.
    """
    valid = [
        p["walk_time_min"]
        for p in (places or [])
        if p.get("rating") is not None and p.get("walk_time_min") is not None
        and p["walk_time_min"] < 9999
    ]
    return min(valid) if valid else None


def _classify_walk(walk_min):
    """Classify a walk time into walkable / borderline / drive_needed."""
    if walk_min is None:
        return "no_data"
    if walk_min <= WALK_DRIVE_BOTH_THRESHOLD:
        return "walkable"
    if walk_min <= WALK_DRIVE_ONLY_THRESHOLD:
        return "borderline"
    return "drive_needed"


def _add_coverage_metadata(output):
    """Add section-level coverage metadata to a result dict (NES-288).

    Extracts state from the formatted address, computes per-section coverage
    tiers, and adds 'coverage' and 'state_name' keys.  Wraps in try/except
    so coverage never breaks an evaluation.
    """
    try:
        from coverage_config import extract_state_from_address, get_section_coverage, get_state_name
        address = output.get("address", "")
        state_code = extract_state_from_address(address)
        output["coverage"] = get_section_coverage(state_code) if state_code else {}
        output["state_name"] = get_state_name(state_code) if state_code else ""
        output["state_code"] = state_code or ""
    except Exception:
        output["coverage"] = {}
        output["state_name"] = ""
        output["state_code"] = ""


def _build_walkability_summary(result):
    """Synthesise a walkability-at-a-glance dict from existing snapshot data.

    Returns None when no category has usable walk-time data (widget hidden).
    """
    np = result.get("neighborhood_places") or {}
    ge = result.get("green_escape") or {}
    ua = result.get("urban_access") or {}

    # --- Extract best walk time per category ---
    raw = {}
    for key in ("coffee", "grocery", "fitness"):
        raw[key] = _best_walk_time(np.get(key))

    # Parks: prefer green_escape.best_daily_park, fall back to neighborhood_places
    bdp = ge.get("best_daily_park") or {}
    park_wt = bdp.get("walk_time_min")
    if park_wt is not None and park_wt < 9999:
        raw["parks"] = park_wt
    else:
        raw["parks"] = _best_walk_time(np.get("parks"))

    # Transit: primary_transit walk time
    pt = ua.get("primary_transit") or {}
    transit_wt = pt.get("walk_time_min")
    raw["transit"] = transit_wt if transit_wt is not None and transit_wt < 9999 else None

    # --- Build category list ---
    categories = []
    for key, label in _WALK_CATEGORIES:
        wt = raw.get(key)
        status = _classify_walk(wt)
        categories.append({
            "key": key,
            "label": label,
            "walk_min": wt,
            "status": status,
        })

    with_data = [c for c in categories if c["status"] != "no_data"]
    if not with_data:
        return None

    walkable = [c for c in with_data if c["status"] == "walkable"]
    not_walkable = [c for c in with_data if c["status"] in ("borderline", "drive_needed")]

    walkable_labels = [c["label"] for c in walkable]
    not_walkable_labels = [c["label"] for c in not_walkable]

    # --- Verdict prose ---
    total = len(with_data)
    wcount = len(walkable)

    if wcount == total and total >= 3:
        verdict = "Most daily needs are within a short walk."
    elif wcount == total:
        verdict = (
            f"{_join_labels(walkable_labels)} "
            f"{'is' if wcount == 1 else 'are'} within walking distance."
        )
    elif wcount == 0:
        verdict = "Daily errands will generally require a car from this address."
    elif wcount >= 3:
        verdict = (
            f"{_join_labels(walkable_labels)} are all within walking distance."
        )
    elif wcount == 1:
        verdict = (
            f"{walkable_labels[0]} is walkable, but "
            f"{_join_labels(not_walkable_labels)} will need a drive."
        )
    else:
        verdict = (
            f"{_join_labels(walkable_labels)} are walkable, but "
            f"{_join_labels(not_walkable_labels)} will need a drive."
        )

    return {
        "categories": categories,
        "verdict": verdict,
        "walkable_count": wcount,
        "total_count": total,
    }


def generate_report_narrative(result_dict):
    """Generate a warm, specific, human-readable summary narrative.

    Synthesizes health screening status, top dimension strengths/weaknesses,
    and concrete place names into a 1-3 sentence summary that reads like a
    friend describing the location.

    Returns HTML string (may contain <strong> tags) or empty string.
    """
    passed = result_dict.get("passed_tier1", False)
    score = result_dict.get("final_score", 0)

    # --- Failed tier 1: lead with the concern, not jargon ---
    if not passed:
        presented = result_dict.get("presented_checks", [])
        issues = [
            pc.get("headline", pc.get("name", ""))
            for pc in presented
            if pc.get("category") == "SAFETY"
            and pc.get("result_type") in ("CONFIRMED_ISSUE", "WARNING_DETECTED")
        ]
        filtered = [i.lower() for i in issues if i]
        if filtered:
            issue_text = _join_labels(filtered, conjunction="and")
            return (
                f"This address has health and safety concerns "
                f"— {issue_text} — that need to be resolved before "
                f"we can score it for daily living."
            )
        return (
            "This address has health and safety concerns that need "
            "attention before we can score it for daily living."
        )

    # --- Passed tier 1: build a warm summary ---
    tier2_list = result_dict.get("tier2_scores", [])
    tier2 = {}
    for s in tier2_list:
        if isinstance(s, dict) and s.get("points") is not None:
            tier2[s.get("name", "")] = s

    neighborhood = result_dict.get("neighborhood_places") or {}
    green_escape = result_dict.get("green_escape") or {}
    urban = result_dict.get("urban_access") or {}

    # Classify dimensions into strong/weak for prose
    strong_dims = []
    weak_dims = []
    for dim_name, label in _DIM_LABELS.items():
        entry = tier2.get(dim_name, {})
        pts = entry.get("points", 0) if isinstance(entry, dict) else 0
        if pts >= 7:
            strong_dims.append({"name": dim_name, "label": label, "score": pts})
        elif pts < 4:
            weak_dims.append({"name": dim_name, "label": label, "score": pts})

    # Find a concrete lead place name from the highest-scoring dimension
    lead_place = None
    if strong_dims:
        strong_dims.sort(key=lambda d: d["score"], reverse=True)
        best_key = _DIM_PLACE_KEYS.get(strong_dims[0]["name"])
        places = neighborhood.get(best_key, []) if best_key else []
        if places and places[0].get("name"):
            lead_place = str(_html_escape(places[0]["name"]))

    # Find the best park name
    best_park_name = None
    bp = green_escape.get("best_daily_park")
    if bp and bp.get("name"):
        best_park_name = str(_html_escape(bp["name"]))

    # Find the nearest transit station
    station_name = None
    pt = urban.get("primary_transit") if urban else None
    if pt and pt.get("name"):
        station_name = str(_html_escape(pt["name"]))

    # Build the narrative sentence(s)
    parts = []

    # -- Opening: health screening passed --
    # -- Body: what's great about this place --
    if score >= 85:
        # Exceptional
        if lead_place:
            parts.append(
                f"This address passed all health and safety checks. "
                f"With <strong>{lead_place}</strong> nearby"
            )
        else:
            parts.append(
                "This address passed all health and safety checks. "
                "Everyday essentials are within easy reach"
            )
        if len(strong_dims) >= 3:
            others = [d["label"] for d in strong_dims[1:3]]
            parts.append(f" and strong access to {_join_labels(others)}")
        parts.append(", this is an <strong>exceptional fit</strong> for daily life.")

    elif score >= 70:
        # Strong
        if lead_place:
            parts.append(
                f"This address passed all health and safety checks. "
                f"<strong>{lead_place}</strong> is close by"
            )
        else:
            parts.append(
                "This address passed all health and safety checks. "
                "Key amenities are within reach"
            )
        if strong_dims:
            labels = [d["label"] for d in strong_dims[:2]]
            parts.append(f", with solid {_join_labels(labels)}")
        parts.append(" — a <strong>strong daily fit</strong>.")

    elif score >= 55:
        # Moderate
        parts.append("This address passed all health and safety checks")
        if lead_place:
            parts.append(f". <strong>{lead_place}</strong> is nearby")
        if weak_dims:
            weak_labels = [d["label"] for d in weak_dims[:2]]
            parts.append(
                f", but {_join_labels(weak_labels)} "
                f"{'is' if len(weak_labels) == 1 else 'are'} "
                f"harder to reach"
            )
        parts.append(". A <strong>solid foundation</strong> with some trade-offs.")

    elif score >= 40:
        # Limited
        parts.append("This address passed health screening")
        if weak_dims:
            weak_labels = [d["label"] for d in weak_dims[:2]]
            parts.append(
                f", but {_join_labels(weak_labels)} "
                f"{'is' if len(weak_labels) == 1 else 'are'} "
                f"limited"
            )
        parts.append(". You'll likely <strong>need a car</strong> for some daily errands.")

    else:
        # Poor
        parts.append("This address passed health screening")
        if weak_dims:
            weak_labels = [d["label"] for d in weak_dims[:3]]
            parts.append(
                f", but {_join_labels(weak_labels)} "
                f"{'is' if len(weak_labels) == 1 else 'are'} "
                f"significantly limited"
            )
        parts.append(". Daily errands will require <strong>driving for most trips</strong>.")

    # -- Optional transit or park callout for mid-range scores --
    if 40 <= score < 85:
        callout = None
        if station_name and score >= 55:
            callout = f" {station_name} station is accessible for commuting."
        elif best_park_name and "Parks & Green Space" not in [d["name"] for d in weak_dims]:
            callout = f" {best_park_name} is a green space worth noting."
        if callout:
            parts.append(callout)

    return "".join(parts)


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
# City / area-page helpers (NES-352)
# ---------------------------------------------------------------------------

_STATE_FULL_NAMES = {
    "NY": "New York", "NJ": "New Jersey", "CT": "Connecticut",
    "MI": "Michigan", "CA": "California", "TX": "Texas",
    "FL": "Florida", "IL": "Illinois",
}


def _city_slug(city_name: str) -> str:
    """Convert city name to URL slug. 'White Plains' -> 'white-plains'."""
    return re.sub(r'[^a-z0-9]+', '-', city_name.lower()).strip('-')


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------

_SAFETY_CHECK_NAMES = {
    "Gas station", "High-traffic road",
    # Legacy names retained for old snapshots:
    "Highway", "High-volume road",
    "Power lines", "Electrical substation", "Cell tower", "Industrial zone",
    "Flood zone",
    # EJScreen block group indicators
    "EJScreen PM2.5", "EJScreen cancer risk", "EJScreen diesel PM",
    "EJScreen lead paint", "EJScreen Superfund", "EJScreen hazardous waste",
    "Superfund (NPL)",
    "TRI facility",
    # Phase 1B spatial dataset checks
    "ust_proximity", "tri_proximity", "hifld_power_lines", "rail_proximity",
    # Health comparison summary check
    "ejscreen_environmental",
}

# Hazard tier hierarchy: Tier 1 = direct proximity hazards (prominent display),
# Tier 2 = area-level environmental indicators (compact display).
# Checks not listed here default to Tier 1.
_TIER_2_CHECKS = {
    "EJScreen PM2.5", "EJScreen cancer risk", "EJScreen diesel PM",
    "EJScreen lead paint", "EJScreen Superfund", "EJScreen hazardous waste",
    "ejscreen_environmental",
}

_CHECK_SOURCE_GROUP = {
    "Gas station": "google_places",
    "High-traffic road": "hpms",
    # Legacy names retained for old snapshots:
    "Highway": "road",
    "High-volume road": "road",
    "Power lines": "environmental",
    "Electrical substation": "environmental",
    "Cell tower": "environmental",
    "Industrial zone": "environmental",
    "Superfund (NPL)": "epa_sems",
    "TRI facility": "epa_tri",
    # EJScreen block group indicators
    "EJScreen PM2.5": "ejscreen",
    "EJScreen cancer risk": "ejscreen",
    "EJScreen diesel PM": "ejscreen",
    "EJScreen lead paint": "ejscreen",
    "EJScreen Superfund": "ejscreen",
    "EJScreen hazardous waste": "ejscreen",
}

_SOURCE_GROUP_LABELS = {
    # Legacy group — only applies to old snapshots with Highway/High-volume road checks
    "road": {
        "label": "Road proximity",
        "checks": ["Highway", "High-volume road"],
        "explanation": "Road-data service temporarily unavailable; please try again shortly",
    },
    "environmental": {
        "label": "Environmental proximity",
        "checks": ["Power lines", "Electrical substation", "Cell tower", "Industrial zone"],
        "explanation": "Environmental data service temporarily unavailable; please try again shortly",
    },
    "epa_sems": {
        "label": "EPA Superfund",
        "checks": ["Superfund (NPL)"],
        "explanation": "Superfund site data not available for this area",
    },
    "epa_tri": {
        "label": "EPA Toxic Release Inventory",
        "checks": ["TRI facility"],
        "explanation": "TRI facility data not available for this area",
    },
    "ejscreen": {
        "label": "EPA EJScreen environmental indicators",
        "checks": [
            "EJScreen PM2.5", "EJScreen cancer risk", "EJScreen diesel PM",
            "EJScreen lead paint", "EJScreen Superfund", "EJScreen hazardous waste",
        ],
        "explanation": "EPA EJScreen data not available for this area",
    },
}

# ---------------------------------------------------------------------------
# Comparison view: structured differential data (NES-207)
# ---------------------------------------------------------------------------

# Canonical health-check row order for the comparison grid.
# Listing checks (W/D, Central air, Size, Bedrooms) excluded — not health.
_COMPARE_HEALTH_CHECKS: List[Tuple[str, str]] = [
    # (check_name, display_label)
    ("Flood zone", "Flood zone"),
    ("Superfund (NPL)", "Superfund"),
    ("TRI facility", "Toxic release"),
    ("ust_proximity", "Underground tanks"),
    ("Gas station", "Gas station"),
    ("hifld_power_lines", "Power lines"),
    ("Power lines", "Power lines"),          # legacy fallback
    ("rail_proximity", "Rail corridor"),
    ("High-traffic road", "High-traffic road"),
    ("Industrial zone", "Industrial zone"),
    ("Electrical substation", "Substation"),
    ("Cell tower", "Cell tower"),
]

# Phase 1B spatial checks that supersede their legacy equivalents.
_SPATIAL_SUPERSEDES: Dict[str, str] = {
    "hifld_power_lines": "Power lines",
}

# EJScreen indicators collapsed into one summary row.
_EJSCREEN_INDICATOR_NAMES = {
    "EJScreen PM2.5", "EJScreen cancer risk", "EJScreen diesel PM",
    "EJScreen lead paint", "EJScreen Superfund", "EJScreen hazardous waste",
}

_CHECK_RESULT_SEVERITY = {"FAIL": 3, "WARNING": 2, "UNKNOWN": 1, "PASS": 0}

# ---------------------------------------------------------------------------
# EJScreen cross-reference: area-level annotations on passing address checks
# (NES-316)
# ---------------------------------------------------------------------------

_EJSCREEN_CROSS_REFS = [
    {
        "address_checks": ["Superfund (NPL)"],
        "ejscreen_field": "PNPL",
        "threshold": 80,
        "template": (
            "Address clear, but this area ranks {pct}th percentile "
            "nationally for Superfund proximity."
        ),
    },
    {
        "address_checks": ["TRI facility", "ust_proximity"],
        "ejscreen_field": "PTSDF",
        "threshold": 80,
        "template": (
            "No facilities in our buffer, but this area ranks {pct}th "
            "percentile nationally for hazardous waste proximity."
        ),
    },
]


def _build_comparison_data(
    evaluations: List[dict],
) -> Tuple[dict, List[dict], List[dict], bool]:
    """Compute structured comparison data for the compare template.

    Returns (health_grid, dimension_rows, key_differences).
    """
    # ── Health flags grid ──────────────────────────────────────────────
    # Build per-evaluation check lookup: {check_name: result_string}
    check_lookups: List[Dict[str, str]] = []
    for ev in evaluations:
        result = ev.get("result", {})
        lookup: Dict[str, str] = {}
        for check in result.get("tier1_checks", []):
            lookup[check["name"]] = check["result"]
        check_lookups.append(lookup)

    # Determine which spatial checks are present so we can skip their
    # legacy equivalents.
    all_check_names: set = set()
    for lookup in check_lookups:
        all_check_names.update(lookup.keys())

    skip_legacy: set = set()
    for spatial_name, legacy_name in _SPATIAL_SUPERSEDES.items():
        if spatial_name in all_check_names:
            skip_legacy.add(legacy_name)

    # Build grid rows — only include if ≥1 address has the check.
    grid_rows: List[dict] = []
    seen_labels: set = set()
    for check_name, display_label in _COMPARE_HEALTH_CHECKS:
        if check_name in skip_legacy:
            continue
        # Avoid duplicate labels (legacy + spatial both labelled "Power lines")
        if display_label in seen_labels:
            continue
        cells = [lookup.get(check_name) for lookup in check_lookups]
        if not any(c is not None for c in cells):
            continue  # no address has this check
        seen_labels.add(display_label)
        grid_rows.append({"label": display_label, "cells": cells})

    # EJScreen summary row — worst-case across 6 indicators per address.
    ej_cells: List[Optional[str]] = []
    any_ej = False
    for lookup in check_lookups:
        ej_results = [
            lookup[name] for name in _EJSCREEN_INDICATOR_NAMES
            if name in lookup
        ]
        if ej_results:
            any_ej = True
            worst = max(ej_results, key=lambda r: _CHECK_RESULT_SEVERITY.get(r, 0))
            ej_cells.append(worst)
        else:
            ej_cells.append(None)
    if any_ej:
        grid_rows.append({"label": "Environmental justice", "cells": ej_cells})

    has_any_issues = any(
        c in ("FAIL", "WARNING")
        for row in grid_rows
        for c in row["cells"]
        if c is not None
    )
    health_grid = {"rows": grid_rows, "has_any_issues": has_any_issues}

    # ── Dimension score comparison ─────────────────────────────────────
    dimension_order = list(TIER2_NAME_TO_DIMENSION.keys())
    dimension_rows: List[dict] = []
    for dim_name in dimension_order:
        display_name = TIER2_NAME_TO_DIMENSION[dim_name]
        scores: List[Optional[int]] = []
        for ev in evaluations:
            result = ev.get("result", {})
            tier2 = result.get("tier2_scores", [])
            matched = next(
                (s for s in tier2 if s["name"] == dim_name), None
            )
            scores.append(matched["points"] if matched else None)

        valid_scores = [s for s in scores if s is not None]
        if valid_scores:
            best_val = max(valid_scores)
            all_tied = len(set(valid_scores)) == 1
            best_index = scores.index(best_val) if not all_tied else None
        else:
            best_index = None
            all_tied = True

        dimension_rows.append({
            "name": display_name,
            "scores": scores,
            "max_score": 10,
            "best_index": best_index,
            "all_tied": all_tied,
        })

    # ── Key differences callout ────────────────────────────────────────
    key_differences: List[dict] = []
    for dim_row in dimension_rows:
        valid = [
            (i, s) for i, s in enumerate(dim_row["scores"])
            if s is not None
        ]
        if len(valid) < 2:
            continue
        high_idx, high_val = max(valid, key=lambda x: x[1])
        low_idx, low_val = min(valid, key=lambda x: x[1])
        gap = high_val - low_val
        if gap >= 2:
            key_differences.append({
                "dimension": dim_row["name"],
                "high": high_val,
                "high_address": evaluations[high_idx].get("address", ""),
                "low": low_val,
                "low_address": evaluations[low_idx].get("address", ""),
                "gap": gap,
            })
    key_differences.sort(key=lambda d: d["gap"], reverse=True)
    key_differences = key_differences[:3]

    has_any_scores = any(
        s is not None
        for dim_row in dimension_rows
        for s in dim_row["scores"]
    )

    return health_grid, dimension_rows, key_differences, has_any_scores


def _short_address(address: str) -> str:
    """Extract street portion from a full address for compact display."""
    return address.split(",")[0].strip() if address else "Address"


_HEALTH_CONCERN_DISPARITY_THRESHOLD = 2


def _dimension_lead_sentence(diff: dict) -> str:
    """Format a dimension lead as a sentence fragment for verdict copy."""
    high_addr = _short_address(diff.get("high_address", ""))
    return (
        f"{high_addr} leads in {diff['dimension']} "
        f"({diff['high']}/10 vs {diff['low']}/10)"
    )


def _build_comparative_verdict(
    evaluations: List[dict],
    health_grid: dict,
    key_differences: List[dict],
    dimension_rows: List[dict],
) -> Optional[dict]:
    """Build a plain-English comparative verdict for the compare view.

    Returns {"headline": str, "body": str} or None if < 2 evaluations.
    Pure function — no side effects.
    """
    if len(evaluations) < 2:
        return None

    num_evals = len(evaluations)

    # ── Per-address health concern counts (FAIL + WARNING in grid) ───
    concern_counts: List[int] = [0] * num_evals
    concern_labels: List[List[str]] = [[] for _ in range(num_evals)]
    for row in health_grid.get("rows", []):
        cells = row.get("cells", [])
        label = row.get("label", "")
        for i, cell in enumerate(cells):
            if cell in ("FAIL", "WARNING"):
                concern_counts[i] += 1
                concern_labels[i].append(label)

    # ── Tier1 pass/fail split ────────────────────────────────────────
    failed_indices: List[int] = []
    passed_indices: List[int] = []
    for i, ev in enumerate(evaluations):
        result = ev.get("result", {})
        if result.get("passed_tier1", True):
            passed_indices.append(i)
        else:
            failed_indices.append(i)

    # ── Score spread ─────────────────────────────────────────────────
    scores = [ev.get("final_score", 0) for ev in evaluations]
    max_score = max(scores)
    min_score = min(scores)
    spread = max_score - min_score
    top_idx = scores.index(max_score)
    top_addr = _short_address(evaluations[top_idx].get("address", ""))

    # ── Branch 1: Tier1 failure split ────────────────────────────────
    if failed_indices:
        if not passed_indices:
            # All failed
            return {
                "headline": "None of these addresses passed baseline health checks.",
                "body": "Consider evaluating other properties. All addresses "
                "in this comparison have unresolved health or safety concerns.",
            }

        failed_addrs = [
            _short_address(evaluations[i].get("address", ""))
            for i in failed_indices
        ]
        passed_addrs = [
            _short_address(evaluations[i].get("address", ""))
            for i in passed_indices
        ]

        # Collect failing check names from all failed addresses
        failing_checks: List[str] = []
        for i in failed_indices:
            result = evaluations[i].get("result", {})
            for check in result.get("tier1_checks", []):
                if check.get("result") == "FAIL" and check.get("required"):
                    name = check.get("name", "")
                    if name and name not in failing_checks:
                        failing_checks.append(name)

        if len(failed_addrs) == 1:
            headline = f"{failed_addrs[0]} did not pass baseline health checks."
        else:
            headline = "Multiple addresses did not pass baseline health checks."

        body_parts = []
        if failing_checks:
            body_parts.append(
                f"Failed checks: {_join_labels(failing_checks[:4])}."
            )
        if len(passed_addrs) == 1:
            body_parts.append(f"{passed_addrs[0]} is the viable option.")
        else:
            body_parts.append(
                f"{_join_labels(passed_addrs)} remain viable options."
            )

        return {"headline": headline, "body": " ".join(body_parts)}

    # ── Branch 2: Health concern disparity ───────────────────────────
    max_concerns = max(concern_counts)
    min_concerns = min(concern_counts)
    if max_concerns - min_concerns >= _HEALTH_CONCERN_DISPARITY_THRESHOLD:
        cleanest_idx = concern_counts.index(min_concerns)
        cleanest_addr = _short_address(
            evaluations[cleanest_idx].get("address", "")
        )

        # Find the address with the most concerns for the body text
        worst_idx = concern_counts.index(max_concerns)
        worst_addr = _short_address(
            evaluations[worst_idx].get("address", "")
        )
        extra_labels = [
            lbl for lbl in concern_labels[worst_idx]
            if lbl not in concern_labels[cleanest_idx]
        ]

        headline = f"{cleanest_addr} has the cleanest health profile."
        if extra_labels:
            label_list = ", ".join(extra_labels[:4])
            body = (
                f"{worst_addr} has {len(extra_labels)} health "
                f"concern{'s' if len(extra_labels) != 1 else ''} "
                f"({label_list}) that {cleanest_addr} does not. "
                "This is the most important difference."
            )
        else:
            body = (
                f"{worst_addr} has more flagged health checks than "
                f"{cleanest_addr}. Review the health grid above for details."
            )

        return {"headline": headline, "body": body}

    # ── Branch 3: Clear winner (spread >= 10) ────────────────────────
    if spread >= 10:
        headline = f"{top_addr} is the stronger choice."
        if key_differences:
            leads = [
                _dimension_lead_sentence(d) for d in key_differences[:2]
            ]
            body = ". ".join(leads) + "."
        else:
            body = (
                f"With an overall score of {max_score} vs {min_score}, "
                f"{top_addr} rates meaningfully higher across the board."
            )
        return {"headline": headline, "body": body}

    # ── Branch 6: All similar (spread <= 3) ──────────────────────────
    if spread <= 3:
        headline = "These addresses are essentially equivalent."
        if key_differences:
            minor = _dimension_lead_sentence(key_differences[0])
            body = f"The only notable difference: {minor}."
        else:
            body = (
                "Scores are within a few points across all dimensions. "
                "Choose based on personal preference or location convenience."
            )
        return {"headline": headline, "body": body}

    # ── Branch 4: Close race (spread <= 5) ───────────────────────────
    if spread <= 5:
        headline = "These addresses are closely matched."
        # Find where each address leads
        leads_by_addr: Dict[int, List[str]] = {}
        for dim_row in dimension_rows:
            if dim_row.get("best_index") is not None and not dim_row.get(
                "all_tied"
            ):
                idx = dim_row["best_index"]
                leads_by_addr.setdefault(idx, []).append(dim_row["name"])

        body_parts = []
        for idx, dims in sorted(leads_by_addr.items()):
            addr = _short_address(evaluations[idx].get("address", ""))
            dim_text = " and ".join(dims[:2])
            body_parts.append(f"{addr} has stronger {dim_text}")

        if body_parts:
            body = "; ".join(body_parts) + "."
        else:
            body = (
                "Scores are very close across all dimensions. "
                "The difference comes down to personal priorities."
            )
        return {"headline": headline, "body": body}

    # ── Branch 5: Middle ground (5 < spread < 10) ────────────────────
    headline = f"{top_addr} has an edge."
    if key_differences:
        leads = [_dimension_lead_sentence(d) for d in key_differences[:2]]
        body = ". ".join(leads) + "."
    else:
        runner_idx = scores.index(min_score)
        runner_addr = _short_address(
            evaluations[runner_idx].get("address", "")
        )
        body = (
            f"Scoring {max_score} overall vs {min_score} for {runner_addr}, "
            f"but the gap is modest enough that personal priorities could tip "
            f"the balance."
        )
    return {"headline": headline, "body": body}


_CLEAR_HEADLINES = {
    "Gas station": "No gas stations nearby",
    "High-traffic road": "No high-traffic roads nearby",
    # Legacy — retained for old snapshots:
    "Highway": "No highways or major parkways nearby",
    "High-volume road": "No high-volume roads nearby",
    "Power lines": "No high-voltage power lines nearby",
    "Electrical substation": "No electrical substations nearby",
    "Cell tower": "No cell towers nearby",
    "Industrial zone": "No industrial sites nearby",
    "Flood zone": "Not in a flood zone",
    "Superfund (NPL)": "Not near a Superfund cleanup site",
    "TRI facility": "No toxic-release facilities within 1 mile",
    # EJScreen block group indicators
    "EJScreen PM2.5": "Air particulate levels are normal for this area",
    "EJScreen cancer risk": "Air toxics cancer risk is normal for this area",
    "EJScreen diesel PM": "Diesel exhaust levels are normal for this area",
    "EJScreen lead paint": "Lead paint risk is low for this area",
    "EJScreen Superfund": "No Superfund site concerns for this area",
    "EJScreen hazardous waste": "No hazardous waste concerns for this area",
    # Phase 1B spatial dataset checks
    "ust_proximity": "No underground fuel tanks nearby",
    "tri_proximity": "No toxic-release facilities within 1 mile",
    "hifld_power_lines": "No high-voltage power lines nearby",
    "rail_proximity": "No active rail lines nearby",
    # Health comparison summary check
    "ejscreen_environmental": "Environmental indicators are within normal ranges",
}

_ISSUE_HEADLINES = {
    "Gas station": "Gas station very close to this address",
    "High-traffic road": "High-traffic road very close by",
    # Legacy — retained for old snapshots:
    "Highway": "Highway or major parkway very close by",
    "High-volume road": "High-volume road very close by",
    "Power lines": "High-voltage power line very close by",
    "Electrical substation": "Electrical substation very close by",
    "Cell tower": "Cell tower very close by",
    "Industrial zone": "Industrial site very close by",
    "Flood zone": "This address is in a high-risk flood zone",
    "Superfund (NPL)": "This address is within a Superfund cleanup site",
    "TRI facility": "Toxic-release facility within 1 mile",
    # EJScreen block group indicators (these only produce WARNING, not FAIL,
    # but registered here for completeness)
    "EJScreen PM2.5": "Elevated air particulate levels in this area",
    "EJScreen cancer risk": "Elevated air toxics cancer risk in this area",
    "EJScreen diesel PM": "Elevated diesel exhaust in this area",
    "EJScreen lead paint": "Elevated lead paint risk in this area",
    "EJScreen Superfund": "Elevated Superfund site proximity in this area",
    "EJScreen hazardous waste": "Elevated hazardous waste proximity in this area",
    # Phase 1B spatial dataset checks
    "ust_proximity": "Underground fuel tank very close by",
    "tri_proximity": "Toxic-release facility within 1 mile",
    "hifld_power_lines": "High-voltage power line very close by",
    "rail_proximity": "Active rail line very close by",
}

_WARNING_HEADLINES = {
    "Gas station": "Gas station in the vicinity",
    "High-traffic road": "High-traffic road in the area",
    "Power lines": "High-voltage power line in the vicinity",
    "Electrical substation": "Electrical substation in the vicinity",
    "Cell tower": "Cell tower in the vicinity",
    "Industrial zone": "Industrial site in the vicinity",
    "Flood zone": "Moderate flood risk in this area",
    "TRI facility": "Toxic-release facility within 1 mile",
    # EJScreen block group indicators
    "EJScreen PM2.5": "Somewhat elevated air particulate levels in this area",
    "EJScreen cancer risk": "Somewhat elevated air toxics cancer risk in this area",
    "EJScreen diesel PM": "Somewhat elevated diesel exhaust in this area",
    "EJScreen lead paint": "Somewhat elevated lead paint risk in this area",
    "EJScreen Superfund": "Somewhat elevated Superfund site proximity in this area",
    "EJScreen hazardous waste": "Somewhat elevated hazardous waste proximity in this area",
    # Phase 1B spatial dataset checks
    "ust_proximity": "Underground fuel tank in the vicinity",
    "tri_proximity": "Toxic-release facility within 1 mile",
    "hifld_power_lines": "High-voltage power line in the vicinity",
    "rail_proximity": "Active rail line in the vicinity",
    # Health comparison summary check
    "ejscreen_environmental": "Some environmental indicators are elevated in this area",
}

# -- Feedback prompt (NES-362) -----------------------------------------------
FEEDBACK_PROMPT_MAX_AGE_DAYS = 30

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
            "This property is within California\u2019s recommended 300-foot setback "
            "between gas stations and sensitive land uses (homes, schools, daycares). "
            "Maryland requires 500 feet. These aren\u2019t arbitrary \u2014 they reflect the "
            "distance at which benzene concentrations from vent pipes are expected to "
            "approach safe thresholds under normal conditions."
        ),
        "exposure": (
            "The exposure is chronic, not acute. You won\u2019t smell benzene at "
            "these concentrations. The health concern is years of low-level chronic "
            "exposure, which is associated with increased leukemia risk and other "
            "blood disorders. This is particularly relevant for young children and "
            "pregnant women."
        ),
    },
    ("Gas station", "WARNING"): {
        "why": (
            "Gas stations emit benzene \u2014 a known human carcinogen "
            "(classified Group 1 by the International Agency for Research on Cancer) "
            "\u2014 from underground storage tank vent pipes and during fueling. "
            "A 2019 Columbia/Johns Hopkins study (Hilpert et al.) measured vent pipe "
            "emissions roughly 10 times higher than California\u2019s regulatory estimates."
        ),
        "regulatory": (
            "This property clears California\u2019s recommended 300-foot setback for "
            "gas stations, but falls within the more conservative 500-foot buffer "
            "recommended by Maryland and supported by Columbia/Johns Hopkins "
            "research on benzene vapor dispersion. Health risk at this distance is "
            "reduced but not eliminated."
        ),
        "exposure": (
            "The exposure is chronic, not acute. You won\u2019t smell benzene at "
            "these concentrations. The concern is years of low-level exposure, "
            "which is associated with increased leukemia risk and other blood "
            "disorders \u2014 particularly relevant for young children and "
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
    # ── High-traffic road (HPMS AADT) ────────────────────────────
    ("High-traffic road", "FAIL"): {
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
            "This check uses actual traffic counts (Annual Average Daily Traffic) "
            "from the FHWA Highway Performance Monitoring System, not road "
            "classification. Research consistently shows that pollutant "
            "concentrations drop substantially within 150\u2013300 meters of roads "
            "carrying 50,000+ vehicles per day and reach background levels by "
            "300 meters. This address falls within that elevated-risk zone."
        ),
    },
    ("High-traffic road", "WARNING"): {
        "why": (
            "A 2010 expert panel convened by the Health Effects Institute found "
            "\u201csufficient\u201d evidence that living near high-traffic roads causes "
            "asthma aggravation in children and cardiovascular effects in adults."
        ),
        "distance": (
            "This address is 150\u2013300 meters from a road carrying 50,000+ "
            "vehicles per day. Pollutant concentrations in this zone are "
            "diminishing but may still be elevated above background levels, "
            "according to CDC and HEI research."
        ),
        "invisible": (
            "This is the kind of proximity risk that doesn\u2019t appear in property "
            "descriptions, photos, or open house tours. You might notice noise on "
            "a site visit, but the air quality impact is invisible and cumulative."
        ),
    },
    ("High-traffic road", "PASS"): {
        "why": (
            "Living within 150\u2013300 meters of roads carrying 50,000+ vehicles "
            "per day exposes residents to elevated levels of fine particulate "
            "matter and nitrogen dioxide. The Health Effects Institute found "
            "sufficient evidence linking this proximity to asthma aggravation "
            "and cardiovascular effects. This check uses actual traffic counts "
            "from the FHWA Highway Performance Monitoring System. This address "
            "is outside the elevated-risk zone."
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
    # ── Superfund (NPL) ──────────────────────────────────────────
    ("Superfund (NPL)", "FAIL"): {
        "why": (
            "EPA Superfund National Priorities List sites have documented "
            "contamination linked to cancer, neurological effects, and birth "
            "defects. Living within the EPA-defined remediation boundary means "
            "ongoing exposure risk from soil, groundwater, or airborne contaminants "
            "that persist even after cleanup efforts."
        ),
        "who": (
            "Children, pregnant women, and anyone with compromised immune systems "
            "face the highest risk. Contaminant effects can be cumulative over "
            "years of residence and may not appear until long after exposure."
        ),
    },
    ("Superfund (NPL)", "PASS"): {
        "why": (
            "EPA Superfund National Priorities List sites contain documented "
            "hazardous contamination. We check whether an address falls inside "
            "the EPA-defined remediation boundary of any NPL site. This address "
            "is outside those boundaries."
        ),
    },
    # ── TRI Facility ─────────────────────────────────────────────
    ("TRI facility", "WARNING"): {
        "why": (
            "EPA Toxic Release Inventory (TRI) facilities manufacture, process, "
            "or otherwise use significant quantities of listed toxic chemicals "
            "and are required to report annual releases to the EPA. Proximity to "
            "these facilities may indicate exposure to toxic air emissions, water "
            "discharges, or contaminated soil."
        ),
        "who": (
            "Children, pregnant women, and older adults face elevated risk from "
            "chronic low-level exposure to toxic chemicals. Effects may include "
            "respiratory illness, neurological impacts, and increased cancer risk "
            "depending on the specific chemicals released."
        ),
        "practical": (
            "Not all TRI facilities pose the same risk \u2014 release quantities, "
            "chemical toxicity, and wind patterns all matter. Check the EPA "
            "Envirofacts database for the specific facility\u2019s release reports "
            "to understand what chemicals are involved and in what quantities."
        ),
    },
    ("TRI facility", "PASS"): {
        "why": (
            "EPA Toxic Release Inventory facilities report annual releases of "
            "listed toxic chemicals to air, water, and land. We check for TRI "
            "facilities within 1 mile of the property. No reporting facilities "
            "were found within that radius."
        ),
    },
    # ── Underground Storage Tanks (Phase 1B) ─────────────────────
    ("ust_proximity", "FAIL"): {
        "why": (
            "Underground storage tanks can leak fuel and chemicals into "
            "surrounding soil and air. Research has found benzene levels "
            "exceeding safety thresholds within 500 feet of tank vent pipes."
        ),
        "regulatory": (
            "Hilpert et al. (2019) at Columbia and Johns Hopkins found that "
            "benzene emissions from underground storage tank vent pipes exceeded "
            "California\u2019s reference exposure level at 160 meters. California "
            "recommends 300-foot setbacks for large fuel stations; Maryland "
            "requires 500 feet. NestCheck flags UST facilities within 500 feet "
            "of your address."
        ),
    },
    ("ust_proximity", "WARNING"): {
        "why": (
            "Underground storage tanks can leak fuel and chemicals into "
            "surrounding soil and air. Research has found benzene levels "
            "exceeding safety thresholds within 500 feet of tank vent pipes."
        ),
        "regulatory": (
            "Hilpert et al. (2019) at Columbia and Johns Hopkins found that "
            "benzene emissions from underground storage tank vent pipes exceeded "
            "California\u2019s reference exposure level at 160 meters. California "
            "recommends 300-foot setbacks for large fuel stations; Maryland "
            "requires 500 feet. NestCheck flags UST facilities within 500 feet "
            "of your address."
        ),
    },
    ("ust_proximity", "PASS"): {
        "why": (
            "Underground storage tanks can leak fuel and chemicals into "
            "surrounding soil and air. Hilpert et al. (2019) found benzene "
            "emissions from vent pipes exceeded California\u2019s reference exposure "
            "level at 160 meters. Several states mandate 300\u2013500 foot setbacks. "
            "This address clears that buffer."
        ),
    },
    # ── Toxic Release Facilities (Phase 1B) ──────────────────────
    ("tri_proximity", "WARNING"): {
        "why": (
            "EPA Toxics Release Inventory facilities report chemical releases "
            "to air, water, and land. Proximity to these facilities may indicate "
            "elevated exposure to industrial pollutants."
        ),
        "regulatory": (
            "The EPA Toxics Release Inventory tracks releases of more than 800 "
            "chemicals from approximately 21,000 facilities nationwide. Risk "
            "varies significantly by chemical type and release volume. NestCheck "
            "flags TRI facilities within 1 mile as a prompt for further "
            "investigation."
        ),
    },
    ("tri_proximity", "PASS"): {
        "why": (
            "EPA Toxics Release Inventory facilities report chemical releases "
            "to air, water, and land. The TRI tracks more than 800 chemicals "
            "from approximately 21,000 facilities nationwide. This address has "
            "no TRI facilities within 1 mile."
        ),
    },
    # ── High-Voltage Power Lines / HIFLD (Phase 1B) ──────────────
    ("hifld_power_lines", "WARNING"): {
        "why": (
            "High-voltage transmission lines produce electromagnetic fields "
            "that decline with distance. The International Agency for Research "
            "on Cancer classifies EMF as a possible carcinogen, with elevated "
            "risk observed within 200 feet of lines."
        ),
        "regulatory": (
            "The International Agency for Research on Cancer (IARC) classified "
            "extremely low frequency electromagnetic fields as Group 2B "
            "(possibly carcinogenic) in 2002, based on a consistent "
            "approximately 2x increase in childhood leukemia risk at exposures "
            "above 0.3\u20130.4 microtesla. EMF from typical transmission lines "
            "drops to approximately 0.18 microtesla at 200 feet. The evidence "
            "is moderate and contested \u2014 no biophysical mechanism has been "
            "established."
        ),
    },
    ("hifld_power_lines", "PASS"): {
        "why": (
            "High-voltage transmission lines produce electromagnetic fields "
            "classified as \u201cpossibly carcinogenic\u201d by IARC. EMF intensity drops "
            "rapidly with distance, reaching typical background levels by about "
            "200 feet from the line. This address is outside that proximity zone."
        ),
    },
    # ── Rail Corridor (Phase 1B) ─────────────────────────────────
    ("rail_proximity", "WARNING"): {
        "why": (
            "Freight rail corridors produce noise and vibration that affect "
            "nearby residents. Rail lines also carry hazardous materials, "
            "presenting a low-probability but high-consequence risk."
        ),
        "regulatory": (
            "The Federal Railroad Administration and Bureau of Transportation "
            "Statistics document noise and vibration impacts from rail "
            "corridors. Freight rail lines carry hazardous materials under "
            "Department of Transportation regulations. NestCheck flags rail "
            "corridors within approximately 1,000 feet of your address."
        ),
    },
    ("rail_proximity", "PASS"): {
        "why": (
            "Rail corridors produce noise, vibration, and carry hazardous "
            "materials. The Federal Railroad Administration documents these "
            "impacts on nearby residents. This address has no rail corridors "
            "within 1,000 feet."
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
            # Show nearest distance when the check explicitly opted in
            explanation = details if check.get("show_detail") else None
        elif result == "FAIL":
            result_type = "CONFIRMED_ISSUE"
            proximity_band = "VERY_CLOSE"
            headline = _ISSUE_HEADLINES.get(name, f"{name} — Concern detected")
            explanation = details
        elif result == "WARNING":
            result_type = "WARNING_DETECTED"
            proximity_band = "NOTABLE"
            # UST-only gas station caution: no Places-confirmed station
            if (name == "Gas station"
                    and "no operating gas station was confirmed" in details):
                headline = "Unverified fuel facility nearby"
            else:
                headline = _WARNING_HEADLINES.get(
                    name, f"{name} — Warning detected"
                )
            explanation = details
        else:
            result_type = "VERIFICATION_NEEDED"
            proximity_band = "NOTABLE"
            headline = f"{name} \u2014 could not be verified"
            # Show the service-level message if it's user-friendly,
            # otherwise provide a generic fallback.
            if details and not details.startswith("Error checking:"):
                explanation = details
            else:
                explanation = (
                    "The data source for this check was temporarily "
                    "unavailable. You can use the satellite link below "
                    "to check manually."
                )

        # Build expanded context for progressive disclosure
        health_context = _build_health_context(name, result, details, value)

        # Attach citation links for "Why we check this" expandable
        citations = HEALTH_CHECK_CITATIONS.get(name, [])

        hazard_tier = 2 if name in _TIER_2_CHECKS else 1

        presented.append({
            "name": name,
            "result": result,
            "category": category,
            "result_type": result_type,
            "proximity_band": proximity_band,
            "headline": headline,
            "explanation": explanation,
            "health_context": health_context,
            "citations": citations,
            "hazard_tier": hazard_tier,
        })

    # --- Collapse groups where ALL checks are VERIFICATION_NEEDED ---
    groups = defaultdict(list)
    for item in presented:
        sg = _CHECK_SOURCE_GROUP.get(item["name"])
        if sg:
            groups[sg].append(item)

    collapsed = []
    collapsed_groups = set()
    for item in presented:
        sg = _CHECK_SOURCE_GROUP.get(item["name"])
        if sg and sg in _SOURCE_GROUP_LABELS:
            group_items = groups[sg]
            all_unverified = all(i["result_type"] == "VERIFICATION_NEEDED" for i in group_items)
            if all_unverified:
                if sg not in collapsed_groups:
                    collapsed_groups.add(sg)
                    meta = _SOURCE_GROUP_LABELS[sg]
                    # Inherit tier from grouped checks (all same tier)
                    group_tier = group_items[0].get("hazard_tier", 1)
                    collapsed.append({
                        "name": meta["label"],
                        "result": "UNKNOWN",
                        "category": "SAFETY",
                        "result_type": "VERIFICATION_NEEDED",
                        "proximity_band": "NOTABLE",
                        "headline": f"{meta['label']} \u2014 could not be verified",
                        "explanation": meta["explanation"],
                        "is_grouped": True,
                        "grouped_checks": meta["checks"],
                        "hazard_tier": group_tier,
                    })
                continue
        collapsed.append(item)

    return collapsed


def suppress_unknown_safety_checks(presented_checks):
    """Remove VERIFICATION_NEEDED safety checks from the presented list.

    Returns (filtered_list, suppressed_count).  Listing-specific UNKNOWN
    checks (LIFESTYLE category) are kept — they represent missing listing
    data, not missing database coverage.
    """
    filtered = []
    suppressed = 0
    for pc in presented_checks:
        if pc.get("result_type") == "VERIFICATION_NEEDED" and pc.get("category") == "SAFETY":
            suppressed += 1
        else:
            filtered.append(pc)
    return filtered, suppressed


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
            "place_id": p.place_id,
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
            "osm_amenity_tags": p.osm_amenity_tags,
        }

    nearby = []
    for s in evaluation.nearby_green_spaces:
        nearby.append({
            "name": s.name,
            "place_id": s.place_id,
            "rating": s.rating,
            "user_ratings_total": s.user_ratings_total,
            "walk_time_min": s.walk_time_min,
            "drive_time_min": s.drive_time_min,
            "daily_walk_value": s.daily_walk_value,
            "criteria_status": s.criteria_status,
            "criteria_reasons": s.criteria_reasons,
            "osm_amenity_tags": s.osm_amenity_tags,
        })

    return {
        "best_daily_park": best_park,
        "nearby_green_spaces": nearby,
        "total_green_space_count": len(nearby),
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
            "wheelchair_accessible_entrance": pt.wheelchair_accessible_entrance,
            "elevator_available": pt.elevator_available,
            "ada_accessibility_note": pt.ada_accessibility_note,
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


# NES-210: Legacy dimension name migration for old snapshots.
# Maps internal Tier2Score names that were renamed to their current
# user-facing equivalents.  Applied during snapshot deserialization so
# templates always see the current name.
_LEGACY_DIMENSION_NAMES = {
    "Third Place": "Coffee & Social Spots",
}


def _migrate_dimension_names(result: dict) -> dict:
    """Remap legacy dimension names in a deserialized snapshot result dict.

    Mutates tier2_scores and dimension_summaries in-place (caller should
    shallow-copy the result dict first if mutation is undesirable).
    """
    for score in result.get("tier2_scores", []):
        old = score.get("name", "")
        if old in _LEGACY_DIMENSION_NAMES:
            score["name"] = _LEGACY_DIMENSION_NAMES[old]
    for dim in result.get("dimension_summaries", []):
        old = dim.get("name", "")
        if old in _LEGACY_DIMENSION_NAMES:
            dim["name"] = _LEGACY_DIMENSION_NAMES[old]
    return result


def _migrate_item_confidence(item: dict, details_field: str) -> None:
    """Remap a single item's legacy confidence value in-place."""
    old_conf = item.get("data_confidence")
    if old_conf and old_conf in _LEGACY_CONFIDENCE_MAP:
        details = item.get(details_field, "")
        if old_conf == "LOW" and "benefit of the doubt" in details:
            item["data_confidence"] = CONFIDENCE_NOT_SCORED
        else:
            item["data_confidence"] = _LEGACY_CONFIDENCE_MAP[old_conf]


def _migrate_confidence_tiers(result: dict) -> dict:
    """Remap legacy HIGH/MEDIUM/LOW confidence values to Phase 3 tiers.

    Mutates tier2_scores and dimension_summaries in-place (caller should
    shallow-copy the result dict first if mutation is undesirable).

    Special case: if a dimension has data_confidence="LOW" and its details
    contain "benefit of the doubt", it was a road noise fallback that should
    now be "not_scored" instead of "estimated".
    """
    for score in result.get("tier2_scores", []):
        _migrate_item_confidence(score, "details")
    for dim in result.get("dimension_summaries", []):
        _migrate_item_confidence(dim, "summary")
    # Migrate aggregate summary level too
    summary = result.get("data_confidence_summary")
    if summary and summary.get("level") in _LEGACY_CONFIDENCE_MAP:
        summary["level"] = _LEGACY_CONFIDENCE_MAP[summary["level"]]
    return result


def _backfill_dimension_bands(result: dict) -> None:
    """Ensure every dimension summary has a ``band`` dict.

    Legacy snapshots stored before the band field was introduced will have
    ``None`` for ``band``.  This fills it in-place from score/max_score.
    """
    for dim in result.get("dimension_summaries", []):
        if "band" not in dim:
            dim["band"] = _dim_band(dim.get("score"), dim.get("max_score", 10))


def _compute_show_numeric_score(dimension_summaries: list) -> bool:
    """Decide whether the verdict gauge should display the numeric score.

    Returns True when all scored dimensions have confidence of 'verified'
    or 'estimated'.  Returns False when any dimension is 'sparse' (thin
    data that shouldn't be presented as a precise number).

    not_scored dimensions are excluded from the check — they already
    carry their own "Not scored" badge and don't imply overall data
    quality issues in the same way sparse does.

    Assumes _migrate_confidence_tiers() has already run — do not add
    legacy tier names here; a mismatch should surface visibly.

    None means the dimension predates confidence tracking; treated as OK
    so old snapshots still show their scores.
    """
    _OK_TIERS = {CONFIDENCE_VERIFIED, CONFIDENCE_ESTIMATED, None}
    for dim in dimension_summaries:
        conf = dim.get("data_confidence")
        if conf == CONFIDENCE_NOT_SCORED:
            continue  # excluded from this check
        if conf not in _OK_TIERS:
            return False
    return True


# Per-dimension band classification (Phase 1 anatomy).
# Thresholds on a 0-10 scale — distinct from composite ScoreBand (0-100).
_DIM_BANDS = (
    (8, "strong", "dim-band--strong", "Strong"),
    (5, "moderate", "dim-band--moderate", "Moderate"),
    (0, "limited", "dim-band--limited", "Limited"),
)


def _dim_band(score, max_score):
    """Classify a single dimension score into a band dict for templates."""
    if score is None or max_score is None or max_score == 0:
        return {"key": "not_scored", "css": "dim-band--not-scored", "label": "Not scored"}
    for threshold, key, css, label in _DIM_BANDS:
        if score >= threshold:
            return {"key": key, "css": css, "label": label}
    return {"key": "limited", "css": "dim-band--limited", "label": "Limited"}


def _prepare_snapshot_for_display(result):
    """Run the full migration/backfill pipeline on a snapshot result dict.

    Mutates *result* in-place.  Callers should pass a shallow copy
    (``{**snapshot["result"]}``) to avoid corrupting stored snapshot dicts.

    This is the single source of truth for display-time preparation —
    used by view_snapshot(), export_snapshot_json(), export_snapshot_csv(),
    and the curated-list route.
    """
    # Backfill presented_checks for old snapshots.
    if "presented_checks" not in result:
        result["presented_checks"] = present_checks(
            result.get("tier1_checks", [])
        )

    # Backfill structured_summary for old snapshots.
    if "structured_summary" not in result:
        result["structured_summary"] = generate_structured_summary(
            result.get("presented_checks", [])
        )

    # NES-196: Suppress UNKNOWN spatial checks at presentation layer.
    filtered_checks, _ = (
        suppress_unknown_safety_checks(result.get("presented_checks", []))
    )
    result["presented_checks"] = filtered_checks

    # NES-241: Backfill hazard_tier.  Rebuild each dict to avoid mutating
    # shared references from the stored snapshot.
    result["presented_checks"] = [
        {**pc, "hazard_tier": 2 if pc.get("name") in _TIER_2_CHECKS else 1}
        if "hazard_tier" not in pc else pc
        for pc in result.get("presented_checks", [])
    ]

    # NES-316: Cross-reference EJScreen area indicators on passing checks.
    _ejscreen = result.get("ejscreen_profile")
    if _ejscreen:
        for xref in _EJSCREEN_CROSS_REFS:
            pct = _ejscreen.get(xref["ejscreen_field"])
            if pct is None or pct < xref["threshold"]:
                continue
            for pc in result["presented_checks"]:
                if (pc.get("name") in xref["address_checks"]
                        and pc.get("result_type") == "CLEAR"):
                    pc["area_context_annotation"] = xref["template"].format(
                        pct=int(pct)
                    )

    # NES-210: Migrate legacy dimension names (on the shallow copy).
    _migrate_dimension_names(result)
    _migrate_confidence_tiers(result)
    _backfill_dimension_bands(result)

    # Backfill total green space count for old snapshots.
    _ge = result.get("green_escape") or {}
    if _ge and "total_green_space_count" not in _ge:
        _ge = dict(_ge)
        _ge["total_green_space_count"] = len(
            _ge.get("nearby_green_spaces", [])
        )
        result["green_escape"] = _ge

    # Backfill neighborhood summary for old snapshots.
    if "neighborhood_summary" not in result:
        _np = result.get("neighborhood_places") or {}
        result["neighborhood_summary"] = {
            "coffee_count": len(_np.get("coffee", [])),
            "grocery_count": len(_np.get("grocery", [])),
            "fitness_count": len(_np.get("fitness", [])),
            "parks_count": len(_np.get("parks", [])),
        }

    # Phase B2: Backfill show_numeric_score for old snapshots.
    if "show_numeric_score" not in result:
        result["show_numeric_score"] = _compute_show_numeric_score(
            result.get("dimension_summaries", [])
        )

    # NES-239: Backfill summary_narrative for old snapshots.
    if "summary_narrative" not in result:
        result["summary_narrative"] = generate_report_narrative(result)

    # NES-249: Walkability summary for sidebar widget (display-time only).
    result["walkability_summary"] = _build_walkability_summary(result)

    # NES-288: Backfill coverage metadata (display-time only).
    _add_coverage_metadata(result)

    # NES-345: Data freshness indicators (display-time only).
    result["section_freshness"] = get_section_freshness()


# NES-315: Tier2Score.name → user-facing category label for annotations.
# Only dimensions that participate in access-mode annotations are listed.
_ANNOTATION_CATEGORY_LABELS = {
    "Fitness access": "fitness",
    "Coffee & Social Spots": "coffee shops",
    "Provisioning": "grocery",
    "Primary Green Escape": "parks",
}


def result_to_dict(result):
    """Convert EvaluationResult to template-friendly dict."""
    _ge = _serialize_green_escape(result.green_escape_evaluation)
    if _ge and result.canopy_cover:
        _ge["canopy_cover"] = result.canopy_cover
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
        "green_escape": _ge,
        "transit_score": result.transit_score,
        "passed_tier1": result.passed_tier1,
        "tier1_checks": [
            {
                "name": c.name,
                "result": c.result.value,
                "details": c.details,
                "required": c.required,
                "value": c.value,
                "show_detail": c.show_detail,
            }
            for c in result.tier1_checks
        ],
        "tier2_score": result.tier2_total,
        "tier2_max": result.tier2_max,
        "tier2_normalized": result.tier2_normalized,
        "tier2_scores": [
            {
                "name": s.name, "points": s.points, "max": s.max_points,
                "details": s.details,
                # NES-189: per-dimension data confidence
                "data_confidence": getattr(s, "data_confidence", None),
                "data_confidence_note": getattr(s, "data_confidence_note", None),
                "suppressed_reason": getattr(s, "suppressed_reason", None),
            }
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

    # Neighborhood places — already plain dicts, pass through as-is
    output["neighborhood_places"] = result.neighborhood_places if result.neighborhood_places else None

    # Category summary counts for section summary row
    _np = output.get("neighborhood_places") or {}
    output["neighborhood_summary"] = {
        "coffee_count": len(_np.get("coffee", [])),
        "grocery_count": len(_np.get("grocery", [])),
        "fitness_count": len(_np.get("fitness", [])),
        "parks_count": len(_np.get("parks", [])),
    }

    # Road noise assessment (NES-193)
    rna = result.road_noise_assessment
    if rna is not None:
        output["road_noise"] = {
            "worst_road_name": rna.worst_road_name,
            "worst_road_ref": rna.worst_road_ref,
            "worst_road_type": rna.worst_road_type,
            "worst_road_lanes": rna.worst_road_lanes,
            "distance_ft": rna.distance_ft,
            "estimated_dba": rna.estimated_dba,
            "severity": rna.severity.value,
            "severity_label": rna.severity_label,
            "methodology_note": rna.methodology_note,
            "all_roads_assessed": rna.all_roads_assessed,
        }
    else:
        output["road_noise"] = None

    # EJScreen block group environmental profile (NES-EJScreen)
    output["ejscreen_profile"] = result.ejscreen_profile

    # School district identification + NYSED performance (NES-206)
    sd = getattr(result, "school_district", None)
    if sd is not None:
        output["school_district"] = {
            "district_name": sd.district_name,
            "geoid": sd.geoid,
            "grade_range": sd.grade_range,
            "graduation_rate_pct": float(sd.graduation_rate_pct) if sd.graduation_rate_pct is not None else None,
            "ela_proficiency_pct": float(sd.ela_proficiency_pct) if sd.ela_proficiency_pct is not None else None,
            "math_proficiency_pct": float(sd.math_proficiency_pct) if sd.math_proficiency_pct is not None else None,
            "chronic_absenteeism_pct": float(sd.chronic_absenteeism_pct) if sd.chronic_absenteeism_pct is not None else None,
            "pupil_expenditure": float(sd.pupil_expenditure) if sd.pupil_expenditure is not None else None,
            "source_year": sd.source_year,
        }
    else:
        output["school_district"] = None

    # Nearby individual schools from NCES (NES-216)
    ns_list = getattr(result, "nearby_schools", None)
    if ns_list is not None:
        output["nearby_schools"] = [
            {
                "name": s.name,
                "ncessch": s.ncessch,
                "level": s.level,
                "grades": s.grades,
                "distance_feet": float(s.distance_feet),
                "distance_miles": float(s.distance_miles),
                "enrollment": int(s.enrollment) if s.enrollment is not None else None,
                "frl_pct": float(s.frl_pct) if s.frl_pct is not None else None,
                "is_charter": s.is_charter,
                "leaid": s.leaid,
            }
            for s in ns_list
        ]
    else:
        output["nearby_schools"] = None

    # City-level demographics from Census ACS (NES-257)
    output["demographics"] = _serialize_census(
        getattr(result, "demographics", None)
    )

    # Walk quality — MAPS-Mini pipeline (NES-192)
    wq = getattr(result, "walk_quality", None)
    if wq is not None:
        output["walk_quality"] = {
            "walk_quality_score": wq.walk_quality_score,
            "walk_quality_rating": wq.walk_quality_rating,
            "feature_scores": [
                {
                    "feature": fs.feature,
                    "score": fs.score,
                    "weight": fs.weight,
                    "detail": fs.detail,
                    "source": fs.source,
                }
                for fs in wq.feature_scores
            ],
            "sample_points_total": wq.sample_points_total,
            "sample_points_with_coverage": wq.sample_points_with_coverage,
            "avg_greenery_pct": wq.avg_greenery_pct,
            "avg_brightness": wq.avg_brightness,
            "infrastructure": {
                "crosswalk_count": wq.infrastructure.crosswalk_count,
                "streetlight_count": wq.infrastructure.streetlight_count,
                "curb_cut_count": wq.infrastructure.curb_cut_count,
                "ped_signal_count": wq.infrastructure.ped_signal_count,
                "bench_count": wq.infrastructure.bench_count,
                "total_features": wq.infrastructure.total_features,
            } if wq.infrastructure else None,
            "data_confidence": wq.data_confidence,
            "data_confidence_note": wq.data_confidence_note,
            "gsv_available": wq.gsv_available,
            "methodology_note": wq.methodology_note,
            "walk_score_comparison": wq.walk_score_comparison,
        }
    else:
        output["walk_quality"] = None

    output["presented_checks"] = present_checks(output["tier1_checks"])
    output["structured_summary"] = generate_structured_summary(output["presented_checks"])
    output["verdict"] = generate_verdict(output)

    # Score band for verdict card colour treatment
    output["score_band"] = get_score_band(output["final_score"])

    # Dimension summaries — derived from tier2_scores for the verdict card
    # breakdown.  Each entry carries the confidence indicator (NES-189).
    # NES-315: merge access-mode annotation data from dimension_details_data.
    _dd_all = getattr(result, "dimension_details_data", {})
    output["dimension_summaries"] = []
    for s in output.get("tier2_scores", []):
        _dim_name = s["name"]
        _dd = _dd_all.get(_dim_name, {})
        _entry = {
            "name": _dim_name,
            "score": s["points"],
            "max_score": s["max"],
            "summary": s["details"],
            "data_confidence": s.get("data_confidence"),
            "data_confidence_note": s.get("data_confidence_note"),
            "suppressed_reason": s.get("suppressed_reason"),
            "band": _dim_band(s["points"], s["max"]),
            # NES-315: access-mode annotation fields
            "access_mode": _dd.get("access_mode"),
            "walk_time_min": _dd.get("walk_time_min"),
            "drive_time_min": _dd.get("drive_time_min"),
            "venue_name": _dd.get("venue_name"),
            "category_label": _ANNOTATION_CATEGORY_LABELS.get(_dim_name),
        }
        output["dimension_summaries"].append(_entry)

    # Aggregate data confidence (weakest-link across scorable dimensions).
    # Only populated when tier2_scores exist (i.e. passed tier 1).
    # not_scored dimensions are excluded from the aggregate — they already
    # carry their own "Not scored" badge.
    # Single pass: classify each dimension's confidence for the aggregate.
    _confidence_levels = []
    _limited_dims = []
    _sparse_dims = []
    _not_scored_dims = []
    for s in output.get("tier2_scores", []):
        conf = s.get("data_confidence")
        if conf == CONFIDENCE_NOT_SCORED:
            _not_scored_dims.append(s["name"])
        elif conf == CONFIDENCE_SPARSE:
            _confidence_levels.append(conf)
            _sparse_dims.append(s["name"])
            _limited_dims.append(s["name"])
        elif conf == CONFIDENCE_ESTIMATED:
            _confidence_levels.append(conf)
            _limited_dims.append(s["name"])
        elif conf:
            _confidence_levels.append(conf)
    if _confidence_levels:
        _has_sparse = CONFIDENCE_SPARSE in _confidence_levels
        _has_estimated = CONFIDENCE_ESTIMATED in _confidence_levels
        if _has_sparse:
            _weakest = CONFIDENCE_SPARSE
        elif _has_estimated:
            _weakest = CONFIDENCE_ESTIMATED
        else:
            _weakest = CONFIDENCE_VERIFIED
        output["data_confidence_summary"] = {
            "level": _weakest,
            "note": (
                "Some dimensions have very limited data"
                if _weakest == CONFIDENCE_SPARSE
                else "Some dimensions have limited data coverage"
                if _weakest == CONFIDENCE_ESTIMATED
                else "All dimensions have strong data coverage"
            ),
            "limited_dimensions": _limited_dims,
            "sparse_dimensions": _sparse_dims,
            "not_scored_dimensions": _not_scored_dims,
        }
    # Section-level narrative insights (NES-191)
    output["insights"] = generate_insights(output)

    # Cap score band when insight layer says car-dependent — a location
    # where "most everyday amenities will likely require driving" cannot
    # be labelled "Strong Daily Fit" or "Exceptional Daily Fit".
    if output["insights"].get("_car_dependent") and output["score_band"]["css_class"] in (
        "band-strong", "band-exceptional",
    ):
        output["score_band"] = get_score_band(55)  # → "Moderate — Some Trade-offs"

    # NES-239: Warm, specific summary narrative for report header
    output["summary_narrative"] = generate_report_narrative(output)

    # Count unresolved safety checks for CTA conditioning (Phase 4)
    output["unknown_check_count"] = sum(
        1 for c in output.get("tier1_checks", [])
        if c.get("result") == "UNKNOWN"
    )

    # Phase B2: Determine whether to show numeric score in verdict gauge.
    # Show the number only when all scored dimensions have sufficient data
    # quality (verified or estimated). Any sparse dimension hides the number.
    output["show_numeric_score"] = _compute_show_numeric_score(
        output.get("dimension_summaries", [])
    )

    # NES-288: Section-level coverage badges based on state data availability.
    # Display-time derivation — no evaluator changes needed.
    _add_coverage_metadata(output)

    return output


# ---------------------------------------------------------------------------
# Insight Generators — pure functions: dict → string | None (NES-191)
# ---------------------------------------------------------------------------

# Dimension labels used in insight text (matches template copy)
_DIM_LABELS = {
    "Coffee & Social Spots": "cafés and social spots",
    "Daily Essentials": "grocery stores",
    "Fitness & Recreation": "gyms and fitness options",
    "Parks & Green Space": "parks and green spaces",
}

_DIM_PLACE_KEYS = {
    "Coffee & Social Spots": "coffee",
    "Daily Essentials": "grocery",
    "Fitness & Recreation": "fitness",
    "Parks & Green Space": "parks",
}


def _nearest_walk_time(places):
    """Return the minimum walk_time_min from a list of place dicts, or None."""
    if not places:
        return None
    times = [p.get("walk_time_min") for p in places if p.get("walk_time_min") is not None]
    return min(times) if times else None


def _join_labels(labels, conjunction="and"):
    """Join a list of labels with Oxford comma formatting."""
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} {conjunction} {labels[1]}"
    return ", ".join(labels[:-1]) + f", {conjunction} {labels[-1]}"


def _insight_neighborhood(neighborhood, tier2):
    """Generate a narrative insight for the Your Neighborhood section.

    Classifies dimensions into strong (>=7), middling (4-6), and weak (<4)
    buckets, then selects a prose template.

    Returns a dict with:
      - text: str | None — the insight prose
      - car_dependent: bool — True when all 4 neighbourhood dimensions < 4
    """
    if not neighborhood or not tier2:
        return {"text": None, "car_dependent": False}

    # Build per-dimension info: {dim_name: {score, label, place_key, places}}
    dims = []
    for dim_name, label in _DIM_LABELS.items():
        score_entry = tier2.get(dim_name, {})
        score = score_entry.get("points", 0) if isinstance(score_entry, dict) else 0
        place_key = _DIM_PLACE_KEYS[dim_name]
        places = neighborhood.get(place_key, [])
        dims.append({
            "name": dim_name,
            "label": label,
            "score": score,
            "places": places,
            "place_key": place_key,
        })

    if not dims:
        return {"text": None, "car_dependent": False}

    # Classify
    strong = [d for d in dims if d["score"] >= 7]
    middling = [d for d in dims if 4 <= d["score"] < 7]
    weak = [d for d in dims if d["score"] < 4]

    # Sort each bucket by score descending
    strong.sort(key=lambda d: d["score"], reverse=True)
    middling.sort(key=lambda d: d["score"], reverse=True)
    weak.sort(key=lambda d: d["score"], reverse=True)

    # Get the lead place name from the highest-scoring dimension
    all_sorted = sorted(dims, key=lambda d: d["score"], reverse=True)
    lead = all_sorted[0]
    lead_place_name = None
    if lead["places"]:
        lead_place_name = lead["places"][0].get("name")

    # Branch: all strong (4 dims >= 7)
    if len(strong) == 4:
        lead_label = lead["label"]
        others = [d["label"] for d in strong if d["name"] != lead["name"]]
        parts = []
        if lead_place_name:
            parts.append(f"{lead_place_name} is just a short walk away")
        else:
            parts.append(f"This area excels at {lead_label}")
        parts.append(f" \u2014 and {_join_labels(others)} are all within easy reach too.")
        return {"text": "".join(parts), "car_dependent": False}

    # Branch: all weak (all < 4) — car-dependent location
    if len(weak) == 4:
        # Check if any places exist at all
        any_places = any(d["places"] for d in weak)
        if not any_places:
            return {"text": "We didn't find everyday amenities like grocery stores, coffee shops, or gyms nearby. You'll likely need a car for most errands.", "car_dependent": True}
        # Places exist but are far
        return {"text": "Grocery stores, coffee shops, and other everyday spots exist in the area but are a significant drive away. Plan on needing a car for most errands.", "car_dependent": True}

    # Branch: all middling (all 4-6)
    if len(middling) == 4:
        labels = [d["label"] for d in middling]
        lead_name = lead_place_name or "Everyday amenities"
        return {"text": f"{lead_name} and other essentials are all within reach \u2014 {_join_labels(labels)} are accessible, though none are exceptional.", "car_dependent": False}

    # Branch: mixed — has both strong and weak
    if strong and weak:
        # Lead from strongest
        lead_label = lead["label"]
        lead_sentence = ""
        if lead_place_name:
            lead_sentence = f"{lead_place_name} ({lead_label}) is a standout nearby."
        else:
            lead_sentence = f"This area scores well for {lead_label}."

        # Others (strong + middling, excluding lead)
        other_strong = [d for d in strong if d["name"] != lead["name"]]
        all_other_labels = [d["label"] for d in other_strong + middling]

        # Weakness sentence
        weak_labels = [d["label"] for d in weak]
        any_weak_places = any(d["places"] for d in weak)

        weakness = ""
        if not any_weak_places:
            weakness = f" However, {_join_labels(weak_labels)} are harder to come by in this area."
        else:
            weakness = f" However, {_join_labels(weak_labels)} will take more effort to reach."

        return {"text": lead_sentence + weakness, "car_dependent": False}

    # Branch: has strong dims, rest are middling (no weak)
    if strong and middling and not weak:
        lead_label = lead["label"]
        others = [d["label"] for d in dims if d["name"] != lead["name"]]
        if lead_place_name:
            return {"text": f"{lead_place_name} ({lead_label}) is a standout nearby, and {_join_labels(others)} are all within reach too.", "car_dependent": False}
        return {"text": f"This area excels at {lead_label}, and {_join_labels(others)} are all within reach too.", "car_dependent": False}

    # Branch: no strong, middling + weak
    if not strong and middling and weak:
        lead_label = lead["label"]
        weak_labels = [d["label"] for d in weak]
        any_weak_places = any(d["places"] for d in weak)

        lead_sentence = ""
        if lead_place_name:
            lead_sentence = f"{lead_place_name} ({lead_label}) is the closest option."
        else:
            lead_sentence = f"{lead_label.capitalize()} are the most accessible here."

        weakness = ""
        if not any_weak_places:
            weakness = f" But {_join_labels(weak_labels)} are harder to come by nearby."
        else:
            weakness = f" But {_join_labels(weak_labels)} will take more effort to reach."

        return {"text": lead_sentence + weakness, "car_dependent": False}

    return {"text": None, "car_dependent": False}


def _insight_getting_around(urban, transit, walk_scores, freq_label, tier2):
    """Generate a narrative insight for the Getting Around section."""
    score = 0
    if tier2:
        entry = tier2.get("Getting Around", {})
        score = entry.get("points", 0) if isinstance(entry, dict) else 0

    has_rail = urban and urban.get("primary_transit") and urban["primary_transit"].get("name")
    has_bus = transit and transit.get("primary_stop")

    if not has_rail and not has_bus:
        if urban is not None:
            return "Public transit is limited here. You'll likely need a car for most trips."
        return None

    parts = []

    if has_rail:
        station = urban["primary_transit"]["name"]
        walk_min = urban["primary_transit"].get("walk_time_min")
        drive_min = urban["primary_transit"].get("drive_time_min")
        parking = urban["primary_transit"].get("parking_available")

        # Determine if this is a drive-accessible station (walk is impractical
        # but driving is quick).  Used to shape prose so we don't imply the
        # commuter would walk 45 minutes.
        is_drive_accessible = (
            walk_min is not None
            and drive_min is not None
            and walk_min > 20
            and drive_min <= 20
        )

        if score >= 7:
            # Strong rail
            if is_drive_accessible:
                parts.append(f"{station} station is a {drive_min}-minute drive")
                if parking:
                    parts.append(" with parking available")
            else:
                parts.append(f"{station} station is {walk_min} minutes on foot")
            if freq_label:
                parts.append(f", with {freq_label.lower()} service")
            parts.append(".")

            hub = urban.get("major_hub")
            if hub and hub.get("name") and hub.get("travel_time_min"):
                parts.append(f" {hub['name']} is about {hub['travel_time_min']} minutes away.")

        elif score >= 4:
            # Moderate rail
            parts.append(f"{station} is the nearest station")
            if is_drive_accessible:
                parts.append(f" ({drive_min} minutes by car")
                if parking:
                    parts.append(", parking available")
                parts.append(")")
            elif walk_min:
                parts.append(f" ({walk_min} minutes on foot)")
            if freq_label:
                parts.append(f", but service runs at {freq_label.lower()} frequency")
            parts.append(". Having a backup way to get around is a good idea.")

        else:
            # Weak rail
            parts.append(f"The nearest transit is {station}")
            if walk_min:
                parts.append(f" ({walk_min} minutes away)")
            parts.append(". You'll likely need a car for most trips.")

    elif has_bus:
        stop = transit["primary_stop"]
        walk_min = transit.get("walk_minutes")
        freq = transit.get("frequency_bucket", "")

        parts.append(f"The nearest bus stop is {stop}")
        if walk_min:
            parts.append(f" ({walk_min} minutes on foot)")
        if freq:
            parts.append(f", with {freq.lower()} frequency")
        parts.append(".")

        if score < 4:
            parts.append(" You'll likely need a car or rideshare for most trips.")

    result = "".join(parts)

    # Add walk description for moderate+ scores
    if walk_scores and score >= 4:
        walk_desc = walk_scores.get("walk_description")
        if walk_desc:
            result += f" Walk Score rates this area as \"{walk_desc}.\""

    # Add bike note for high bike scores
    if walk_scores and walk_scores.get("bike_score") and walk_scores["bike_score"] >= 60:
        result += " Biking is also a good option here."

    return result


def _insight_parks(green_escape, tier2):
    """Generate a narrative insight for the Parks & Green Space section."""
    if not green_escape:
        return None

    best_park = green_escape.get("best_daily_park")
    if not best_park or not best_park.get("name"):
        return "We didn't find any parks or named green spaces within walking distance of this address."

    name = best_park["name"]
    walk_min = best_park.get("walk_time_min")
    score = 0
    if tier2:
        entry = tier2.get("Parks & Green Space", {})
        score = entry.get("points", 0) if isinstance(entry, dict) else 0

    nearby = green_escape.get("nearby_green_spaces", [])

    # OSM enrichment details
    osm_enriched = best_park.get("osm_enriched", False)
    area_sqm = best_park.get("osm_area_sqm", 0) if osm_enriched else 0
    has_trail = best_park.get("osm_has_trail", False) if osm_enriched else False
    path_count = best_park.get("osm_path_count", 0) if osm_enriched else 0

    parts = []

    # Branch: strong + close (score >= 7 and walk <= 15)
    if score >= 7 and walk_min is not None and walk_min <= 15:
        parts.append(f"{name} is just {walk_min} minutes on foot \u2014 close enough for a morning run or afternoon walk")

        # OSM enrichment
        osm_details = []
        if area_sqm and area_sqm >= 20_234:  # ~5 acres
            acres = int(area_sqm / 4047 + 0.5)
            osm_details.append(f"{acres} acres")
        if has_trail:
            osm_details.append("trails")
        if path_count >= 3:
            osm_details.append(f"{path_count} paths")

        if osm_details:
            parts.append(f", with {_join_labels(osm_details)}")

        parts.append(".")

    # Branch: good park but far (score < 7 and walk > 20)
    elif score < 7 and walk_min is not None and walk_min > 20:
        parts.append(f"{name} is {walk_min} minutes away \u2014 more of a weekend destination than a daily routine.")

    # Branch: moderate (score >= 4)
    elif score >= 4:
        parts.append(f"{name} is ")
        if walk_min is not None:
            parts.append(f"{walk_min} minutes away, ")
        parts.append(f"a solid option for regular visits.")

        # OSM enrichment
        osm_details = []
        if area_sqm and area_sqm >= 20_234:
            acres = int(area_sqm / 4047 + 0.5)
            osm_details.append(f"{acres} acres")
        if has_trail:
            osm_details.append("trails")
        if path_count >= 3:
            osm_details.append(f"{path_count} paths")

        if osm_details:
            parts[-1] = parts[-1].rstrip(".")
            parts.append(f", with {_join_labels(osm_details)}.")

    # Branch: weak (score < 4)
    else:
        parts.append(f"Green space is limited nearby \u2014 {name} is the closest option")
        if walk_min is not None:
            parts.append(f" at {walk_min} minutes")
        parts.append(".")

    # Nearby green spaces notation
    if nearby:
        if len(nearby) == 1:
            parts.append(f" There's also another green space nearby.")
        else:
            parts.append(f" There are {len(nearby)} other green spaces nearby.")

    return "".join(parts)


def _weather_context(weather):
    """Generate weather context sentences from trigger flags and monthly data."""
    if not weather:
        return None

    triggers = weather.get("triggers", [])
    if not triggers:
        return None

    monthly = weather.get("monthly", [])
    sentences = []

    has_snow = "snow" in triggers
    has_freezing = "freezing" in triggers
    has_heat = "extreme_heat" in triggers
    has_rain = "rain" in triggers

    month_names = {1: "January", 2: "February", 3: "March", 4: "April",
                   5: "May", 6: "June", 7: "July", 8: "August",
                   9: "September", 10: "October", 11: "November", 12: "December"}

    def _month_range(month_numbers):
        """Find contiguous month range, handling Dec-Jan wrap-around."""
        if not month_numbers:
            return None, None
        nums = sorted(set(month_numbers))
        # Check for winter wrap-around (has both Dec and Jan/Feb/Mar)
        if 12 in nums and any(m <= 3 for m in nums):
            # Wrap: start from December, end at last spring month
            winter = [m for m in nums if m >= 10] + [m for m in nums if m <= 5]
            return month_names[winter[0]], month_names[winter[-1]]
        return month_names[nums[0]], month_names[nums[-1]]

    # Snow + freezing combined
    if has_snow and has_freezing:
        snow_months = [m["month"] for m in monthly if m.get("avg_snowfall_in", 0) > 1.0]
        if snow_months:
            first, last = _month_range(snow_months)
            sentences.append(
                f"Expect snow and freezing temperatures from {first} through {last}"
            )
        else:
            sentences.append("Expect snow and freezing temperatures in winter")
    elif has_snow:
        snow_months = [m["month"] for m in monthly if m.get("avg_snowfall_in", 0) > 1.0]
        if snow_months:
            first, last = _month_range(snow_months)
            sentences.append(
                f"Notable snow from {first} through {last}"
            )
        else:
            sentences.append("Notable snow in winter months")
    elif has_freezing:
        sentences.append("Freezing temperatures are common in winter")

    # Extreme heat
    if has_heat:
        heat_month_nums = [m["month"] for m in monthly if m.get("avg_high_f", 0) >= 90]
        if heat_month_nums:
            first, last = _month_range(heat_month_nums)
            sentences.append(
                f"Summers are hot, with highs above 90\u00b0F from {first} through {last}"
            )
        else:
            sentences.append("Summers can be extremely hot")

    # Rain (only if snow is NOT present)
    if has_rain and not has_snow:
        sentences.append("Frequent rain year-round")

    # Cap at 2 sentences
    sentences = sentences[:2]

    if not sentences:
        return None

    return ". ".join(sentences) + "."


def _insight_community_profile(demographics, result_dict):
    """Generate a narrative insight for the Community Profile section.

    Uses city/place-level Census ACS data (NES-257).  Factual framing
    only — no characterizations of desirability (Fair Housing guardrail).
    """
    if not demographics:
        return None

    place_name = demographics.get("place_name", "") or "This area"
    population = demographics.get("population", 0)
    total_households = demographics.get("total_households", 0)
    median_income = demographics.get("median_household_income")
    median_age = demographics.get("median_age")
    renter_pct = demographics.get("renter_pct", 0)
    owner_pct = demographics.get("owner_pct", 0)

    sentences = []

    # Population + households
    if population and total_households:
        sentences.append(
            f"{place_name} has a population of {population:,} "
            f"across {total_households:,} households"
        )

    # Median household income
    if median_income is not None:
        sentences.append(
            f"The median household income is ${median_income:,}"
        )

    # Tenure
    if owner_pct or renter_pct:
        if renter_pct >= owner_pct:
            sentences.append(
                f"Housing is majority renter-occupied ({renter_pct:.0f}%)"
            )
        else:
            sentences.append(
                f"Housing is majority owner-occupied ({owner_pct:.0f}%)"
            )

    # Median age
    if median_age is not None:
        sentences.append(f"The median age is {median_age:.1f}")

    if not sentences:
        return None

    return ". ".join(sentences) + "."


def generate_insights(result_dict):
    """Orchestrate all section-level narrative insights.

    Returns a dict with keys matching template section names:
    - your_neighborhood
    - getting_around
    - parks
    - proximity
    - community_profile
    """
    neighborhood = result_dict.get("neighborhood_places")
    tier2_list = result_dict.get("tier2_scores", [])

    # Build tier2 lookup: {name: {points, max, ...}}
    tier2 = {}
    for s in tier2_list:
        if isinstance(s, dict):
            tier2[s.get("name", "")] = s

    green_escape = result_dict.get("green_escape")
    urban_access = result_dict.get("urban_access")
    transit_access = result_dict.get("transit_access")
    walk_scores = result_dict.get("walk_scores")
    freq_label = result_dict.get("frequency_label", "")
    presented_checks = result_dict.get("presented_checks", [])
    demographics = result_dict.get("demographics")

    neighborhood_insight = _insight_neighborhood(neighborhood, tier2)

    return {
        "your_neighborhood": neighborhood_insight["text"],
        "getting_around": _insight_getting_around(
            urban_access, transit_access, walk_scores, freq_label, tier2,
        ),
        "parks": _insight_parks(green_escape, tier2),
        "proximity": proximity_synthesis(presented_checks),
        "community_profile": _insight_community_profile(demographics, result_dict),
        "_car_dependent": neighborhood_insight["car_dependent"],
    }


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


# ---------------------------------------------------------------------------
# Curated list pages (NES-293)
# ---------------------------------------------------------------------------

_LISTS_DIR = os.path.join(os.path.dirname(__file__), "data", "lists")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _load_list_config(slug, config_dir=None):
    """Load a curated list config by slug. Returns dict or None."""
    if not slug or not _SLUG_RE.fullmatch(slug):
        return None
    config_dir = config_dir or _LISTS_DIR
    path = os.path.join(config_dir, f"{slug}.json")
    try:
        with open(path) as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _get_all_list_slugs(config_dir=None):
    """Return list of slugs from all published config files (excludes _-prefixed)."""
    config_dir = config_dir or _LISTS_DIR
    slugs = []
    try:
        for fname in os.listdir(config_dir):
            if fname.endswith(".json") and not fname.startswith("_"):
                slugs.append(fname[:-5])  # strip .json
    except OSError:
        pass
    return slugs


@app.route("/lists/<slug>")
def view_list(slug):
    """Serve a curated list page from JSON config."""
    config = _load_list_config(slug)
    if not config:
        abort(404)

    # Hydrate each entry with its snapshot data
    hydrated_entries = []
    for entry in config.get("entries", []):
        snapshot = get_snapshot(entry.get("snapshot_id"))
        if not snapshot:
            logger.warning("List %s: snapshot %s not found, skipping",
                           slug, entry.get("snapshot_id"))
            continue
        result = {**snapshot["result"]}
        _prepare_snapshot_for_display(result)
        hydrated_entries.append({
            "snapshot_id": entry["snapshot_id"],
            "narrative": entry.get("narrative", ""),
            "result": result,
        })

    # Resolve related list titles for cross-linking
    related_lists = []
    for related_slug in config.get("related_lists", []):
        related_config = _load_list_config(related_slug)
        if related_config:
            related_lists.append({
                "slug": related_slug,
                "title": related_config["title"],
            })

    return render_template(
        "list.html",
        config=config,
        entries=hydrated_entries,
        related_lists=related_lists,
    )


# ---------------------------------------------------------------------------
# State area pages (NES-344)
# ---------------------------------------------------------------------------

@app.route("/state/<state_slug>")
def view_state(state_slug):
    """State-level area page listing evaluated cities (NES-344)."""
    state_upper = state_slug.upper()
    state_name = _STATE_FULL_NAMES.get(state_upper)
    if not state_name:
        abort(404)

    # Cities with enough evaluations for their own page
    all_cities = get_cities_with_snapshots(min_count=3)
    state_cities = [c for c in all_cities if c["state_abbr"] == state_upper]
    for c in state_cities:
        c["slug"] = _city_slug(c["city"])

    # Coverage tier from manifest
    manifest = COVERAGE_MANIFEST.get(state_upper, {})
    has_education = manifest.get("STATE_EDUCATION") == "active"
    coverage_tier = "Full evaluation" if has_education else "Health check only"

    breadcrumbs = [
        {"name": "Home", "url": "/"},
        {"name": state_name, "url": None},
    ]

    return render_template(
        "state.html",
        state_name=state_name,
        state_abbr=state_upper,
        state_cities=state_cities,
        coverage_tier=coverage_tier,
        breadcrumbs=breadcrumbs,
    )


# ---------------------------------------------------------------------------
# City area page (NES-352)
# ---------------------------------------------------------------------------

@app.route("/city/<state>/<city_slug>")
def view_city(state, city_slug):
    """City-level area page aggregating evaluations (NES-352)."""
    state_upper = state.upper()
    state_name = _STATE_FULL_NAMES.get(state_upper)
    if not state_name:
        abort(404)

    city_name = get_city_name_by_slug(state_upper, city_slug)
    if not city_name:
        abort(404)

    snapshots = get_city_snapshots(state_upper, city_name)
    if len(snapshots) < 3:
        abort(404)

    for snap in snapshots:
        snap["score_band"] = get_score_band(snap["final_score"])
        snap["tier1_passed"] = bool(snap["passed_tier1"])

    stats = get_city_stats(state_upper, city_name)
    stats["health_pass_rate"] = (
        round(stats["health_pass_count"] / stats["eval_count"] * 100)
        if stats["eval_count"] > 0 else 0
    )

    # Compute dimension averages from result_json (NES-352 spec requirement).
    # Also cache the first full snapshot for Census lookup below.
    dim_totals = {}
    dim_counts = {}
    first_full_snap = None
    for snap in snapshots:
        full = get_snapshot(snap["snapshot_id"])
        if not full:
            continue
        if first_full_snap is None:
            first_full_snap = full
        result = {**full["result"]}
        _prepare_snapshot_for_display(result)
        tier2 = result.get("tier2_scores") or []
        for t2 in tier2:
            name = t2.get("name", "")
            pts = t2.get("points")
            if pts is not None and name:
                dim_totals[name] = dim_totals.get(name, 0) + pts
                dim_counts[name] = dim_counts.get(name, 0) + 1

    dimension_averages = []
    for name in dim_totals:
        avg = round(dim_totals[name] / dim_counts[name])
        dimension_averages.append({
            "name": name,
            "avg_score": avg,
            "max": 10,
        })
    # Sort by name for consistent display
    dimension_averages.sort(key=lambda d: d["name"])
    stats["dimension_averages"] = dimension_averages

    demographics = None
    try:
        first_snap = first_full_snap
        if first_snap:
            result = first_snap.get("result", {})
            coords = result.get("coordinates", {})
            lat, lng = coords.get("lat"), coords.get("lng")
            if lat and lng:
                from census import get_demographics
                demo_obj = get_demographics(lat, lng)
                if demo_obj:
                    demo_dict = _serialize_census(demo_obj)
                    if demo_dict and demo_dict.get("place_name") == city_name:
                        demographics = demo_dict
    except Exception:
        logger.warning("Census lookup failed for city page %s/%s", state, city_slug)

    breadcrumbs = [
        {"name": "Home", "url": "/"},
        {"name": state_name, "url": f"/state/{state_upper.lower()}"},
        {"name": city_name, "url": None},
    ]

    return render_template(
        "city.html",
        city_name=city_name,
        state_abbr=state_upper,
        state_name=state_name,
        snapshots=snapshots,
        stats=stats,
        demographics=demographics,
        breadcrumbs=breadcrumbs,
    )


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    error_detail = None  # builder-mode diagnostic
    address = ""
    snapshot_id = None
    request_id = getattr(g, "request_id", "unknown")
    featured_cities = []

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

        # ----- Payment / free-tier gate -----
        payment_token = request.form.get("payment_token", "").strip() or None
        _payment_id_for_job = None  # set if a paid token is being redeemed
        email_h = hash_email(email) if email else None
        _is_subscriber = email and is_subscription_active(email)

        if not g.is_builder:
            if REQUIRE_PAYMENT and payment_token:
                # PAID PATH: validate & redeem payment token
                payment = get_payment_by_id(payment_token)
                if not payment:
                    if _wants_json():
                        return jsonify({"error": "Invalid payment token"}), 402
                    error = "Invalid payment token."
                    return render_template(
                        "index.html", result=result, error=error,
                        error_detail=error_detail, address=address,
                        snapshot_id=snapshot_id,
                        is_builder=g.is_builder, request_id=request_id,
                    )

                pstatus = payment["status"]
                if pstatus == PAYMENT_PENDING:
                    # Webhook hasn't arrived yet — verify directly with Stripe
                    try:
                        session_obj = stripe.checkout.Session.retrieve(
                            payment["stripe_session_id"]
                        )
                        if session_obj.payment_status == "paid":
                            update_payment_status(
                                payment_token, PAYMENT_PAID, expected_status=PAYMENT_PENDING,
                            )
                            pstatus = PAYMENT_PAID
                        else:
                            if _wants_json():
                                return jsonify({"error": "Payment not completed"}), 402
                            error = "Payment not completed."
                            return render_template(
                                "index.html", result=result, error=error,
                                error_detail=error_detail, address=address,
                                snapshot_id=snapshot_id,
                                is_builder=g.is_builder, request_id=request_id,
                            )
                    except Exception:
                        logger.exception(
                            "[%s] Failed to verify payment %s with Stripe",
                            request_id, payment_token,
                        )
                        if _wants_json():
                            return jsonify({"error": "Unable to verify payment status"}), 402
                        error = "Unable to verify payment status."
                        return render_template(
                            "index.html", result=result, error=error,
                            error_detail=error_detail, address=address,
                            snapshot_id=snapshot_id,
                            is_builder=g.is_builder, request_id=request_id,
                        )

                if pstatus in (PAYMENT_PAID, PAYMENT_FAILED_REISSUED):
                    if not redeem_payment(payment_token):
                        if _wants_json():
                            return jsonify({"error": "Invalid or expired payment"}), 402
                        error = "Invalid or expired payment."
                        return render_template(
                            "index.html", result=result, error=error,
                            error_detail=error_detail, address=address,
                            snapshot_id=snapshot_id,
                            is_builder=g.is_builder, request_id=request_id,
                        )
                    _payment_id_for_job = payment_token
                else:
                    if _wants_json():
                        return jsonify({"error": "Invalid or expired payment"}), 402
                    error = "Invalid or expired payment."
                    return render_template(
                        "index.html", result=result, error=error,
                        error_detail=error_detail, address=address,
                        snapshot_id=snapshot_id,
                        is_builder=g.is_builder, request_id=request_id,
                    )

            elif REQUIRE_PAYMENT and not payment_token:
                # No payment token — must be a free tier attempt or missing payment
                if not email:
                    if _wants_json():
                        return jsonify({"error": "Email or payment required"}), 402
                    error = "Email or payment required."
                    return render_template(
                        "index.html", result=result, error=error,
                        error_detail=error_detail, address=address,
                        snapshot_id=snapshot_id,
                        is_builder=g.is_builder, request_id=request_id,
                    )
                if not _is_subscriber and not check_free_tier_available(email_h):
                    if _wants_json():
                        return jsonify({"error": "free_tier_exhausted"}), 402
                    error = "Free evaluation already used for this email."
                    return render_template(
                        "index.html", result=result, error=error,
                        error_detail=error_detail, address=address,
                        snapshot_id=snapshot_id,
                        is_builder=g.is_builder, request_id=request_id,
                    )

            else:
                # REQUIRE_PAYMENT=false — free tier still applies when email given
                if email:
                    if not _is_subscriber and not check_free_tier_available(email_h):
                        if _wants_json():
                            return jsonify({"error": "free_tier_exhausted"}), 402
                        error = "Free evaluation already used for this email."
                        return render_template(
                            "index.html", result=result, error=error,
                            error_detail=error_detail, address=address,
                            snapshot_id=snapshot_id,
                            is_builder=g.is_builder, request_id=request_id,
                        )

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
                # Send report email on cached snapshot reuse (never blocks redirect)
                if email:
                    try:
                        from email_service import send_report_email

                        if send_report_email(email, snapshot_id, address):
                            update_snapshot_email_sent(snapshot_id)
                            log_event(
                                "email_sent",
                                snapshot_id=snapshot_id,
                                visitor_id=g.visitor_id,
                                metadata={"address": address},
                            )
                        else:
                            log_event(
                                "email_failed",
                                snapshot_id=snapshot_id,
                                visitor_id=g.visitor_id,
                                metadata={"address": address},
                            )
                    except Exception:
                        logger.exception(
                            "[%s] Email send failed for cached snapshot %s",
                            request_id, snapshot_id,
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
        job_id = create_job(
            address=address,
            visitor_id=g.visitor_id,
            request_id=request_id,
            place_id=place_id,
            email_hash=email_h,
            email_raw=email,
            user_id=current_user.id if current_user.is_authenticated else None,
        )
        logger.info("[%s] Job %s queued for address=%r", request_id, job_id, address)

        # Link payment token to job (paid path)
        if _payment_id_for_job:
            update_payment_job_id(_payment_id_for_job, job_id)

        # Record free tier usage (unpaid path with email, skip for subscribers)
        if not _payment_id_for_job and not g.is_builder and email and not _is_subscriber:
            record_free_tier_usage(email_h, email)

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

    # NES-344: featured cities for homepage
    try:
        featured_cities = get_cities_with_snapshots(min_count=3)
        featured_cities.sort(key=lambda c: c["snapshot_count"], reverse=True)
        featured_cities = featured_cities[:5]
        for c in featured_cities:
            c["slug"] = _city_slug(c["city"])
    except Exception:
        logger.warning("Failed to load featured cities for homepage")
        featured_cities = []

    return render_template(
        "index.html", result=result, error=error,
        error_detail=error_detail,
        address=address, snapshot_id=snapshot_id,
        job_id=None,
        is_builder=g.is_builder, request_id=request_id,
        featured_cities=featured_cities,
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


@app.route("/feedback/<snapshot_id>")
def feedback_survey(snapshot_id):
    """Render the detailed feedback survey for a snapshot."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        abort(404)

    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)

    graded_dims = [d for d in result.get("dimension_summaries", [])
                   if d.get("score") is not None
                   and d.get("data_confidence") != "not_scored"]

    return render_template("feedback.html",
                           snapshot=snapshot,
                           result=result,
                           graded_dims=graded_dims)


def _check_full_access(snapshot_id: str, user_email: str | None = None) -> bool:
    """Check if a snapshot should render with full detail.

    Priority: builder > dev mode > payment (job join) >
    payment (direct snapshot_id) > active sub > past sub.
    """
    if getattr(g, "is_builder", False):
        return True
    if not REQUIRE_PAYMENT:
        return True
    conn = _get_db()
    try:
        # Payment via job join (upfront purchase flow)
        row = conn.execute(
            "SELECT 1 FROM payments p JOIN evaluation_jobs j ON p.job_id = j.job_id "
            "WHERE j.snapshot_id = ? AND p.status = ?",
            (snapshot_id, PAYMENT_REDEEMED),
        ).fetchone()
        if row:
            return True
        # Payment via direct snapshot_id (unlock-existing-report flow)
        row = conn.execute(
            "SELECT 1 FROM payments WHERE snapshot_id = ? AND status = ?",
            (snapshot_id, PAYMENT_REDEEMED),
        ).fetchone()
        if row:
            return True
        if user_email:
            # Active subscription
            row = conn.execute(
                "SELECT 1 FROM subscriptions "
                "WHERE user_email = ? AND status IN (?, ?, ?) "
                "AND period_end > datetime('now') LIMIT 1",
                (user_email, SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCELED,
                 SUBSCRIPTION_PAST_DUE),
            ).fetchone()
            if row:
                return True
            # Past subscription covering this snapshot's creation time
            row = conn.execute(
                "SELECT 1 FROM subscriptions s "
                "JOIN snapshots snap ON snap.snapshot_id = ? "
                "WHERE s.user_email = ? "
                "AND snap.evaluated_at BETWEEN s.period_start AND s.period_end",
                (snapshot_id, user_email),
            ).fetchone()
            if row:
                return True
    finally:
        conn.close()
    return False


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

    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)

    # Payment redemption on snapshot view (NES-327)
    payment_token = request.args.get("payment_token")
    if payment_token and REQUIRE_PAYMENT:
        payment = get_payment_by_id(payment_token)
        if payment and payment["status"] in (PAYMENT_PENDING, PAYMENT_PAID):
            if payment["status"] == PAYMENT_PENDING and STRIPE_AVAILABLE:
                try:
                    session = stripe.checkout.Session.retrieve(payment["stripe_session_id"])
                    if session.payment_status == "paid":
                        update_payment_status(payment_token, PAYMENT_PAID, expected_status=PAYMENT_PENDING)
                except Exception:
                    logger.warning("Stripe session check failed for %s", payment_token)
            redeem_payment(payment_token)
            # Link payment to this snapshot (unlock-existing-report flow)
            update_payment_snapshot_id_direct(payment_token, snapshot_id)

    # Content gating (NES-327)
    user_email = None
    try:
        if current_user.is_authenticated:
            user_email = current_user.email
    except Exception:
        pass
    is_full_access = _check_full_access(snapshot_id, user_email=user_email)

    if not is_full_access:
        result = {**result}
        result["dimension_summaries"] = [
            {k: v for k, v in dim.items() if k in ("name", "points", "band")}
            for dim in result.get("dimension_summaries", [])
        ]
        result["neighborhood_places"] = {}
        result.pop("walkability_summary", None)
        result.pop("green_escape", None)
        result.pop("urban_access", None)
        result.pop("census_demographics", None)
        result.pop("school_district", None)

    # NES-257: demographics is not backfilled — old snapshots simply lack the
    # key and the template hides the section when result.demographics is
    # None/absent.  Live re-fetch would be possible but is deliberately
    # avoided to keep view_snapshot() side-effect-free.

    # NES-344: city page link + breadcrumbs
    city_page_url = None
    city_name_for_link = None
    snap_city = snapshot.get("city")
    snap_state = snapshot.get("state_abbr")
    if snap_city and snap_state:
        _city_stats = get_city_stats(snap_state, snap_city)
        if _city_stats and _city_stats.get("eval_count", 0) >= 3:
            city_page_url = f"/city/{snap_state.lower()}/{_city_slug(snap_city)}"
            city_name_for_link = snap_city
            state_full = _STATE_FULL_NAMES.get(snap_state, snap_state)
            result["breadcrumbs"] = [
                {"name": state_full, "url": f"/state/{snap_state.lower()}"},
                {"name": snap_city, "url": city_page_url},
            ]

    # NES-362: show feedback prompt for recent snapshots only
    show_feedback_prompt = False
    evaluated_at_str = snapshot.get("evaluated_at")
    if evaluated_at_str:
        try:
            evaluated_at = datetime.fromisoformat(evaluated_at_str)
            age_days = (datetime.now(timezone.utc) - evaluated_at).days
            show_feedback_prompt = age_days <= FEEDBACK_PROMPT_MAX_AGE_DAYS
        except (ValueError, TypeError):
            pass

    return render_template(
        "snapshot.html",
        snapshot=snapshot,
        result=result,
        snapshot_id=snapshot_id,
        is_builder=g.is_builder,
        is_full_access=is_full_access,
        show_feedback_prompt=show_feedback_prompt,
        city_page_url=city_page_url,
        city_name_for_link=city_name_for_link,
    )


@app.route("/widget/badge/<snapshot_id>.svg")
def widget_badge(snapshot_id):
    """Embeddable SVG badge — returns self-contained SVG for <img> embedding (NES-348)."""
    snapshot = get_snapshot(snapshot_id)

    # Fallback: missing or expired snapshot → generic "Evaluate on NestCheck" badge
    is_fresh = False
    if snapshot:
        is_fresh = is_snapshot_fresh(
            snapshot, _snapshot_ttl_days(), datetime.now(timezone.utc)
        )

    style = request.args.get("style", "banner")
    if style not in ("banner", "square"):
        style = "banner"

    if not snapshot or not is_fresh:
        resp = make_response(render_template(
            "widget_badge_fallback.svg",
            style=style,
        ))
        resp.headers["Content-Type"] = "image/svg+xml"
        resp.headers["Content-Security-Policy"] = "frame-ancestors *"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)

    checks = result.get("presented_checks", [])
    clear_count = sum(1 for c in checks if c.get("result_type") == "CLEAR")
    concern_count = sum(
        1 for c in checks
        if c.get("result_type") in ("CONFIRMED_ISSUE", "WARNING_DETECTED")
    )

    score = result.get("final_score") or 0
    band = get_score_band(score)

    # Map css_class to hex color (same mapping as widget_card.html)
    band_colors = {
        "band-exceptional": "#16A34A",
        "band-strong": "#65A30D",
        "band-moderate": "#D97706",
        "band-limited": "#EA580C",
        "band-concerning": "#DC2626",
    }
    band_color = band_colors.get(band["css_class"], "#DC2626")

    resp = make_response(render_template(
        "widget_badge.svg",
        snapshot_id=snapshot_id,
        score=score,
        band_label=band["label"],
        band_color=band_color,
        clear_count=clear_count,
        concern_count=concern_count,
        style=style,
    ))
    resp.headers["Content-Type"] = "image/svg+xml"
    resp.headers["Content-Security-Policy"] = "frame-ancestors *"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/widget/card/<snapshot_id>")
def widget_card(snapshot_id):
    """Embeddable score card widget — returns complete HTML for iframe."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        abort(404)

    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)

    # Health summary counts
    checks = result.get("presented_checks", [])
    clear_count = sum(
        1 for c in checks if c.get("result_type") == "CLEAR"
    )
    concern_count = sum(
        1 for c in checks
        if c.get("result_type") in ("CONFIRMED_ISSUE", "WARNING_DETECTED")
    )

    # Score band
    score = result.get("final_score") or 0
    band = get_score_band(score)

    # Configurable dimensions via query params
    width = request.args.get("w", 300, type=int)
    height = request.args.get("h", 200, type=int)

    resp = make_response(render_template(
        "widget_card.html",
        snapshot_id=snapshot_id,
        address=result.get("address", snapshot.get("address_norm", "")),
        score=score,
        band_label=band["label"],
        band_css_class=band["css_class"],
        clear_count=clear_count,
        concern_count=concern_count,
        width=width,
        height=height,
    ))
    resp.headers["Content-Security-Policy"] = "frame-ancestors *"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/api/v1/widget-data/<snapshot_id>")
def api_widget_data(snapshot_id):
    """Widget data API — returns JSON for programmatic access (NES-343)."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        resp = jsonify({"error": "Snapshot not found"})
        resp.status_code = 404
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)

    checks = result.get("presented_checks", [])
    clear_count = sum(1 for c in checks if c.get("result_type") == "CLEAR")
    concern_count = sum(
        1 for c in checks
        if c.get("result_type") in ("CONFIRMED_ISSUE", "WARNING_DETECTED")
    )

    score = result.get("final_score") or 0
    band = get_score_band(score)

    if concern_count == 0:
        health_summary = f"{clear_count} clear"
    else:
        concern_word = "concern" if concern_count == 1 else "concerns"
        health_summary = f"{clear_count} clear / {concern_count} {concern_word}"

    report_url = request.host_url.rstrip("/") + "/s/" + snapshot_id

    resp = jsonify({
        "score": score,
        "band": band["label"],
        "address": result.get("address", snapshot.get("address_norm", "")),
        "health_summary": health_summary,
        "clear_count": clear_count,
        "concern_count": concern_count,
        "report_url": report_url,
    })
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@app.route("/api/snapshot/<snapshot_id>/json")
def export_snapshot_json(snapshot_id):
    """JSON export of a snapshot evaluation result."""
    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({"error": "Snapshot not found"}), 404

    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)
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

    result = {**snapshot["result"]}
    _prepare_snapshot_for_display(result)
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
    writer.writerow(["category", "points", "max", "details", "data_confidence", "data_confidence_note"])
    for score in result.get("tier2_scores", []):
        writer.writerow([
            score.get("name", ""),
            score.get("points", ""),
            score.get("max", ""),
            score.get("details", ""),
            score.get("data_confidence", ""),
            score.get("data_confidence_note", ""),
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


@app.route("/compare", methods=["GET", "POST"])
def compare():
    # --- POST: instant health comparison via spatial checks ---
    if request.method == "POST":
        addresses_raw = request.form.getlist("address[]")
        addresses = [a.strip() for a in addresses_raw if a.strip()]

        if len(addresses) < 2:
            flash("Please enter at least 2 addresses to compare.", "error")
            return redirect(url_for("compare"))
        if len(addresses) > 5:
            addresses = addresses[:5]

        api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
        if not api_key:
            flash("Google Maps API key not configured.", "error")
            return redirect(url_for("compare"))

        from health_compare import compare_addresses
        comparison = compare_addresses(addresses, api_key)

        if not comparison.get("spatial_available"):
            flash(
                "Spatial data is still loading. Please try again in a few minutes.",
                "warning",
            )
            return redirect(url_for("compare"))

        # Serialize Tier1Check instances → dicts for present_checks()
        for result in comparison["results"]:
            if result.get("checks"):
                serialized = []
                for check in result["checks"]:
                    serialized.append({
                        "name": check.name,
                        "result": check.result.value if hasattr(check.result, "value") else check.result,
                        "details": check.details,
                        "value": check.value,
                        "required": getattr(check, "required", True),
                        "show_detail": getattr(check, "show_detail", False),
                    })
                result["presented_checks"] = present_checks(serialized)

        return render_template(
            "compare_health.html",
            comparison=comparison,
            addresses=addresses,
        )

    # --- GET: snapshot-based comparison (existing) or empty form ---
    raw_ids = (request.args.get("ids") or "").strip()
    if not raw_ids:
        # No snapshot IDs — show the health comparison form
        return render_template(
            "compare_health.html",
            comparison=None,
            addresses=[],
        )

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
    missing_count = len(deduped_ids) - len(snapshots)
    if missing_count > 0:
        logger.warning(
            "Compare: %d of %d snapshot IDs not found (stale localStorage?)",
            missing_count, len(deduped_ids),
        )
    if len(snapshots) < 2:
        flash(
            "Some saved addresses are no longer available. "
            "Please re-evaluate them and add to comparison again.",
            "error",
        )
        return redirect(url_for("index"))

    evaluations = []
    for snapshot in snapshots:
        result = {**snapshot.get("result", {})}
        # NES-210: Migrate legacy dimension names for old snapshots
        _migrate_dimension_names(result)
        _migrate_confidence_tiers(result)
        _backfill_dimension_bands(result)
        if "show_numeric_score" not in result:
            result["show_numeric_score"] = _compute_show_numeric_score(
                result.get("dimension_summaries", [])
            )
        if "summary_narrative" not in result:
            result["summary_narrative"] = generate_report_narrative(result)
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

    health_grid, dimension_rows, key_differences, has_any_scores = (
        _build_comparison_data(evaluations)
    )

    verdict = _build_comparative_verdict(
        evaluations, health_grid, key_differences, dimension_rows,
    )

    return render_template(
        "compare.html",
        evaluations=evaluations,
        evaluation_count=len(evaluations),
        top_score=top_score,
        top_score_unique=top_score_unique,
        health_grid=health_grid,
        dimension_rows=dimension_rows,
        key_differences=key_differences,
        has_any_scores=has_any_scores,
        verdict=verdict,
    )


@app.route("/api/snapshots/check", methods=["POST"])
def check_snapshots():
    """Validate which snapshot IDs still exist in the database.

    Accepts JSON body: {"ids": ["abc", "def", ...]}
    Returns: {"valid": ["abc"], "invalid": ["def"]}
    """
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    if not isinstance(ids, list) or len(ids) > 10:
        return jsonify({"error": "ids must be a list of up to 10 strings"}), 400
    ids = [str(i).strip() for i in ids if isinstance(i, str) and i.strip()]
    if not ids:
        return jsonify({"valid": [], "invalid": []})

    found_ids = check_snapshots_exist(ids)
    return jsonify({
        "valid": [i for i in ids if i in found_ids],
        "invalid": [i for i in ids if i not in found_ids],
    })


@app.route("/api/snapshots/<snapshot_id>/fresh")
def api_snapshot_fresh(snapshot_id):
    """Check if a snapshot exists and is fresh. No API calls — pure SQLite."""
    try:
        snapshot = get_snapshot(snapshot_id)
        if not snapshot:
            return jsonify({"exists": False, "fresh": False})
        ttl_days = _snapshot_ttl_days()
        now_utc = datetime.now(timezone.utc)
        fresh = is_snapshot_fresh(snapshot, ttl_days, now_utc)
        return jsonify({
            "exists": True,
            "fresh": fresh,
            "snapshot_id": snapshot_id,
        })
    except Exception:
        return jsonify({"exists": False, "fresh": False})


@app.route("/api/feedback", methods=["POST"])
def api_submit_feedback():
    """Accept inline feedback for a snapshot (NES-362)."""
    data = request.get_json(silent=True) or {}

    snapshot_id = data.get("snapshot_id")
    if not snapshot_id:
        return jsonify({"error": "snapshot_id is required"}), 400

    told = data.get("told_something_new")
    if told not in (0, 1, True, False):
        return jsonify({"error": "told_something_new must be 0 or 1"}), 400
    told = int(told)

    free_text = data.get("free_text")
    if free_text and len(free_text) > 1000:
        return jsonify({"error": "free_text must be 1000 characters or fewer"}), 400

    feedback_type = data.get("feedback_type", "inline_reaction")

    user_id = None
    if current_user.is_authenticated:
        user_id = current_user.id
    visitor_id = request.cookies.get("nestcheck_vid")

    if not user_id and not visitor_id:
        return jsonify({"error": "No identity available"}), 400

    snapshot = get_snapshot(snapshot_id)
    if not snapshot:
        return jsonify({"error": "Snapshot not found"}), 404

    saved = save_inline_feedback(snapshot_id, user_id, visitor_id,
                                 feedback_type, told, free_text)
    if not saved:
        return jsonify({"status": "duplicate"}), 200

    return jsonify({"status": "ok"}), 201

@app.route("/api/feedback/<snapshot_id>/status")
def api_feedback_status(snapshot_id):
    """Check if the current user/visitor already submitted feedback (NES-362)."""
    user_id = None
    if current_user.is_authenticated:
        user_id = current_user.id
    visitor_id = request.cookies.get("nestcheck_vid")

    submitted = has_inline_feedback(snapshot_id, user_id, visitor_id)
    return jsonify({"submitted": submitted})


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


@app.route("/api/feedback", methods=["POST"])
def submit_feedback():
    """Save user feedback from the detailed survey page."""
    data = request.get_json(silent=True) or {}

    snapshot_id = (data.get("snapshot_id") or "").strip()
    feedback_type = (data.get("feedback_type") or "").strip()
    response_json_str = data.get("response_json")

    if not snapshot_id or not feedback_type:
        return jsonify({"success": False, "error": "snapshot_id and feedback_type are required"}), 400

    if not response_json_str:
        return jsonify({"success": False, "error": "response_json is required"}), 400

    try:
        json.loads(response_json_str)
    except (json.JSONDecodeError, TypeError):
        return jsonify({"success": False, "error": "response_json must be valid JSON"}), 400

    snapshot = get_snapshot(snapshot_id)
    address_norm = snapshot.get("address_norm") if snapshot else None

    save_feedback(
        snapshot_id=snapshot_id,
        feedback_type=feedback_type,
        response_json=response_json_str,
        address_norm=address_norm,
        visitor_id=g.visitor_id,
    )

    log_event("feedback_submitted", snapshot_id=snapshot_id,
              visitor_id=g.visitor_id,
              metadata={"feedback_type": feedback_type})

    return jsonify({"success": True})


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
    feedback_digest = get_feedback_digest()

    return render_template(
        "builder_dashboard.html",
        counts=counts,
        recent_events=recent_events,
        recent_snapshots=recent_snapshots,
        feedback=feedback_digest,
    )


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


@app.route("/vote-state", methods=["POST"])
def vote_state():
    """Handle anonymous state demand vote from homepage form."""
    state = (request.form.get("state") or "").strip().upper()
    if not state:
        flash("Please select a state.", "error")
        return redirect("/#help-us-expand")

    from models import record_state_vote, _US_STATES

    # Only allow votes for states we don't fully support yet
    _SUPPORTED_STATES = {"NY", "NJ", "CT", "MI"}
    if state not in _US_STATES or state in _SUPPORTED_STATES:
        flash("That state is already supported! Enter any address to get a report.", "error")
        return redirect("/#help-us-expand")

    record_state_vote(state)
    flash("Thanks for voting! Your input helps us prioritize.", "success")
    return redirect("/#help-us-expand")


# ---------------------------------------------------------------------------
# Stripe Checkout routes
# ---------------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    """Liveness probe for Railway — always 200 once Flask is accepting connections.

    Reports config status in the body for monitoring, but never blocks
    deployment with a non-200 response.  Missing env vars are an operational
    concern, not a reason to fail the healthcheck and take the site down.
    """
    config_ok, missing = _check_service_config()
    return jsonify({
        "status": "ok" if config_ok else "degraded",
        "missing_keys": missing,
    }), 200


@app.route("/api/spatial-health")
def api_spatial_health():
    """Check spatial.db health on the production volume.

    Authenticated via Bearer token matching SPATIAL_HEALTH_TOKEN env var.
    Returns 404 when the env var is unset (endpoint disabled).
    """
    import hmac

    expected_token = os.environ.get("SPATIAL_HEALTH_TOKEN")
    if not expected_token:
        abort(404)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "missing or malformed Authorization header"}), 401
    provided = auth[len("Bearer "):]
    if not hmac.compare_digest(provided, expected_token):
        return jsonify({"error": "invalid token"}), 401

    try:
        from scripts.spatial_health_check import check_health
        from spatial_data import _spatial_db_path

        statuses = check_health(_spatial_db_path())
        unhealthy = [s for s in statuses if not s.healthy]
        checked_at = datetime.now(timezone.utc).isoformat()

        payload = {
            "status": "healthy" if not unhealthy else "unhealthy",
            "checked_at": checked_at,
            "summary": {
                "total": len(statuses),
                "healthy": len(statuses) - len(unhealthy),
                "unhealthy": len(unhealthy),
            },
            "tables": [
                {
                    "table_name": s.table_name,
                    "exists": s.exists,
                    "row_count": s.row_count,
                    "baseline_count": s.baseline_count,
                    "ingested_at": s.ingested_at,
                    "age_days": round(s.age_days, 1) if s.age_days is not None else None,
                    "staleness_threshold_days": s.staleness_threshold_days,
                    "healthy": s.healthy,
                    "issues": s.issues,
                }
                for s in statuses
            ],
        }
        return jsonify(payload), 200 if not unhealthy else 503
    except Exception as exc:
        logger.exception("spatial-health endpoint error")
        return jsonify({"error": type(exc).__name__}), 500


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
# Flask CLI — Ingestion management
# ---------------------------------------------------------------------------
# Run via:   flask ingest -d sems -d fema -d ust
# Railway:   railway run flask ingest -d sems -d fema
# List all:  flask ingest --list
#
# Each dataset maps to scripts/ingest_{name}.py. The CLI builds per-script
# arguments from the generic options below, passing only those the script
# supports. Scripts run as subprocesses — no import gymnastics needed.
# DB path: RAILWAY_VOLUME_MOUNT_PATH/spatial.db (prod) or data/spatial.db (local).

# Registry: dataset name → (script filename, set of supported CLI flags).
# Flags use the Click parameter names from the command below.
INGEST_REGISTRY = {
    "ust":         ("ingest_ust.py",         {"state", "limit", "verify"}),
    "tri":         ("ingest_tri.py",         {"state", "limit", "verify"}),
    "sems":        ("ingest_sems.py",        {"state", "limit", "verify"}),
    "hpms":        ("ingest_hpms.py",        {"state", "states", "limit", "dry_run", "verify"}),
    "fema":        ("ingest_fema.py",        {"metro", "metros", "states", "bbox", "limit", "verify"}),
    "hifld":       ("ingest_hifld.py",       {"limit", "verify"}),
    "fra":         ("ingest_fra.py",         {"limit", "us_only", "verify"}),
    "ejscreen":    ("ingest_ejscreen.py",    {"state", "limit", "verify"}),
    "walkability": ("ingest_walkability.py", {"state", "limit", "verify"}),
    "nlcd":        ("ingest_nlcd.py",        {"state", "limit", "verify"}),
    "parkserve":   ("ingest_parkserve.py",   {"state", "limit", "verify"}),
    "tiger":       ("ingest_tiger.py",       {"state", "county", "bbox", "limit", "verify"}),
    "census_acs":  ("ingest_census_acs.py",  {"state", "limit", "verify"}),
}


def _build_script_args(dataset, opts):
    """
    Build CLI args for a dataset's ingest script.

    Only passes flags the script actually supports (per INGEST_REGISTRY).
    Value options (--state NY) are skipped when the value is empty/zero.
    Boolean flags (--verify) are skipped when False.
    """
    _, supported = INGEST_REGISTRY[dataset]
    args = []

    # Value options: (registry key, CLI flag, value)
    value_opts = [
        ("state",  "--state",  opts.get("state", "")),
        ("states", "--states", opts.get("states", "")),
        ("limit",  "--limit",  str(opts.get("limit", 0)) if opts.get("limit") else ""),
        ("metro",  "--metro",  opts.get("metro", "")),
        ("bbox",   "--bbox",   opts.get("bbox", "")),
        ("county", "--county", opts.get("county", "")),
    ]
    for key, flag, value in value_opts:
        if key in supported and value:
            args.extend([flag, value])

    # Boolean flags: (registry key, CLI flag, is_set)
    bool_opts = [
        ("verify",  "--verify",  opts.get("verify", False)),
        ("us_only", "--us-only", opts.get("us_only", False)),
        ("dry_run", "--dry-run", opts.get("dry_run", False)),
        ("metros",  "--metros",  opts.get("metros", False)),
    ]
    for key, flag, is_set in bool_opts:
        if key in supported and is_set:
            args.append(flag)

    return args


def _register_ingest_command():
    """Register the `flask ingest` CLI command. Invoked at module load."""

    @app.cli.command("ingest")
    @click.option(
        "--dataset", "-d", "datasets", multiple=True,
        help=(
            "Dataset(s) to ingest. Repeat for batch: -d sems -d fema -d ust. "
            f"Available: {', '.join(sorted(INGEST_REGISTRY))}."
        ),
    )
    @click.option("--list", "list_datasets", is_flag=True,
                  help="List all available datasets and exit.")
    @click.option("--state", "-s", default="",
                  help="Filter to single state (e.g., NY, CA, or FIPS code depending on dataset).")
    @click.option("--states", default="",
                  help="HPMS: comma-separated states (e.g., NY,CA,IL). Default: all 52.")
    @click.option("--metro", "-m", default="",
                  help="FEMA: predefined metro bbox (nyc, sf, chicago, la, seattle, detroit).")
    @click.option("--metros", is_flag=True,
                  help="FEMA: ingest all metros matching --states (or all TARGET_STATES).")
    @click.option("--bbox", default="",
                  help="Bounding box: lng_min,lat_min,lng_max,lat_max (FEMA, TIGER).")
    @click.option("--county", default="",
                  help="TIGER: county FIPS code (e.g., 061 for Manhattan). Requires --state.")
    @click.option("--limit", "-l", type=int, default=0,
                  help="Max records or pages per dataset (0 = no limit).")
    @click.option("--verify", "-v", is_flag=True,
                  help="Run verification query after each dataset.")
    @click.option("--us-only", "us_only", is_flag=True,
                  help="FRA: filter to US rail lines only.")
    @click.option("--dry-run", "dry_run", is_flag=True,
                  help="HPMS: probe services without writing to DB.")
    def ingest_command(datasets, list_datasets, state, states, metro, metros, bbox,
                       county, limit, verify, us_only, dry_run):
        """Ingest spatial datasets into spatial.db."""

        # --list: show registry and exit
        if list_datasets:
            click.echo("Available datasets:")
            for name in sorted(INGEST_REGISTRY):
                script, supported = INGEST_REGISTRY[name]
                flags = ", ".join(f"--{f.replace('_', '-')}" for f in sorted(supported))
                click.echo(f"  {name:<14} {script:<28} [{flags}]")
            return

        if not datasets:
            click.echo("No datasets specified. Use -d <name> or --list.", err=True)
            sys.exit(1)

        # Validate all dataset names upfront
        for name in datasets:
            if name not in INGEST_REGISTRY:
                click.echo(
                    f"Unknown dataset: {name}. "
                    f"Available: {', '.join(sorted(INGEST_REGISTRY))}",
                    err=True,
                )
                sys.exit(1)

        # Collect options into a dict for _build_script_args
        opts = dict(
            state=state, states=states, metro=metro, metros=metros, bbox=bbox,
            county=county, limit=limit, verify=verify,
            us_only=us_only, dry_run=dry_run,
        )

        project_root = os.path.dirname(os.path.abspath(__file__))
        scripts_dir = os.path.join(project_root, "scripts")
        succeeded = []
        failed = []

        for name in datasets:
            script_file, _ = INGEST_REGISTRY[name]
            script_path = os.path.join(scripts_dir, script_file)

            if not os.path.exists(script_path):
                click.echo(f"Script not found: {script_path}", err=True)
                sys.exit(1)

            cmd = [sys.executable, script_path] + _build_script_args(name, opts)
            click.echo(f"[{name}] Running: {shlex.join(cmd)}")

            result = subprocess.run(cmd, cwd=project_root)
            if result.returncode != 0:
                click.echo(f"[{name}] FAILED (exit {result.returncode})", err=True)
                failed.append(name)
                continue
            click.echo(f"[{name}] Done.")
            succeeded.append(name)

        # Summary
        click.echo(f"\nIngestion complete: {len(succeeded)} succeeded, {len(failed)} failed.")
        if failed:
            click.echo(f"Failed: {', '.join(failed)}", err=True)
            sys.exit(1)


_register_ingest_command()


# ---------------------------------------------------------------------------
# Stripe checkout & webhook routes
# ---------------------------------------------------------------------------

@app.route("/checkout/create", methods=["POST"])
def checkout_create():
    """Create a Stripe Checkout Session and return the checkout URL."""
    if not REQUIRE_PAYMENT:
        return jsonify({"error": "Payments not enabled"}), 400
    if not STRIPE_AVAILABLE:
        return jsonify({"error": "Payment system not configured"}), 503

    data = request.get_json(silent=True) or {}
    tier = data.get("tier", request.form.get("tier", "single"))
    snapshot_id = data.get("snapshot_id", request.form.get("snapshot_id", "")).strip() or None

    payment_id = uuid.uuid4().hex
    base_url = request.url_root.rstrip("/")
    try:
        if tier == "subscription":
            if not _STRIPE_SUBSCRIPTION_PRICE_ID:
                return jsonify({"error": "Subscription pricing not configured"}), 503
            email_for_checkout = data.get("email", request.form.get("email", "")).strip()
            if not email_for_checkout:
                return jsonify({"error": "Email required for subscription"}), 400
            session_kwargs = {
                "mode": "subscription",
                "line_items": [{"price": _STRIPE_SUBSCRIPTION_PRICE_ID, "quantity": 1}],
                "success_url": f"{base_url}/my-reports?subscription=active",
                "cancel_url": f"{base_url}/pricing",
                "client_reference_id": payment_id,
            }
            address = ""
        else:
            # Single-payment flow
            address = data.get("address", request.form.get("address", "")).strip()
            if not address:
                return jsonify({"error": "Address required"}), 400

            place_id = data.get("place_id", request.form.get("place_id", "")).strip() or ""
            email_for_checkout = data.get("email", request.form.get("email", "")).strip() or ""

            if snapshot_id:
                success_url = f"{base_url}/s/{snapshot_id}?payment_token={payment_id}"
            else:
                success_url = (
                    f"{base_url}/?payment_token={payment_id}"
                    f"&address={quote(address, safe='')}"
                    f"&place_id={quote(place_id, safe='')}"
                    f"&email={quote(email_for_checkout, safe='')}"
                )

            session_kwargs = {
                "mode": "payment",
                "line_items": [{"price": _STRIPE_PRICE_ID, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": f"{base_url}/",
                "client_reference_id": payment_id,
            }

        # Wire Stripe Customer for logged-in users so payments are
        # associated with their account for receipts and history.
        if current_user.is_authenticated:
            cus_id = _get_or_create_stripe_customer(current_user)
            if cus_id:
                session_kwargs["customer"] = cus_id
            else:
                # Customer creation failed — fall back to pre-filling email
                session_kwargs["customer_email"] = current_user.email

        checkout_session = stripe.checkout.Session.create(**session_kwargs)

        create_payment(
            payment_id,
            stripe_session_id=checkout_session.id,
            visitor_id=g.visitor_id,
            address=address,
            snapshot_id=snapshot_id,
        )
        return jsonify({"checkout_url": checkout_session.url, "payment_id": payment_id})
    except Exception:
        logger.exception("Stripe checkout session creation failed")
        return jsonify({"error": "Payment system error"}), 500


def _resolve_email_from_stripe_customer(customer_id: str) -> str | None:
    """Look up email for a Stripe customer: local DB first, then Stripe API."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT email FROM users WHERE stripe_customer_id = ?",
            (customer_id,),
        ).fetchone()
        if row:
            return row[0]
    finally:
        conn.close()
    if STRIPE_AVAILABLE:
        try:
            customer = stripe.Customer.retrieve(customer_id)
            return customer.get("email")
        except Exception:
            logger.warning("Failed to retrieve Stripe customer %s", customer_id)
    return None


def _handle_subscription_event(sub_obj: dict, event_type: str) -> None:
    """Handle subscription lifecycle events from Stripe webhooks."""
    if event_type == "created":
        email = _resolve_email_from_stripe_customer(sub_obj["customer"])
        if not email:
            logger.warning("No email for subscription %s — skipping", sub_obj["id"])
            return
        create_subscription(
            subscription_id=uuid.uuid4().hex,
            user_email=email,
            stripe_subscription_id=sub_obj["id"],
            stripe_customer_id=sub_obj["customer"],
            period_start=datetime.utcfromtimestamp(sub_obj["current_period_start"]).isoformat(),
            period_end=datetime.utcfromtimestamp(sub_obj["current_period_end"]).isoformat(),
        )
    elif event_type == "updated":
        status = SUBSCRIPTION_ACTIVE
        if sub_obj.get("cancel_at_period_end"):
            status = SUBSCRIPTION_CANCELED
        update_subscription_status(
            sub_obj["id"],
            status,
            period_start=datetime.utcfromtimestamp(sub_obj["current_period_start"]).isoformat(),
            period_end=datetime.utcfromtimestamp(sub_obj["current_period_end"]).isoformat(),
        )
    elif event_type == "deleted":
        update_subscription_status(sub_obj["id"], SUBSCRIPTION_EXPIRED)


@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhook events (no CSRF — Stripe signs the payload)."""
    if not STRIPE_AVAILABLE:
        return jsonify({"error": "Stripe not configured"}), 400

    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, _STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except Exception as exc:
        # stripe.error.SignatureVerificationError in stripe <6,
        # stripe.SignatureVerificationError in stripe >=6.
        if "SignatureVerification" in type(exc).__name__:
            return jsonify({"error": "Invalid signature"}), 400
        raise

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        stripe_session_id = session_obj["id"]
        payment = get_payment_by_session(stripe_session_id)
        if payment:
            update_payment_status(
                payment["id"], PAYMENT_PAID, expected_status=PAYMENT_PENDING,
            )
            logger.info("Webhook: payment %s → paid", payment["id"])
    elif event["type"] == "customer.subscription.created":
        _handle_subscription_event(event["data"]["object"], "created")
    elif event["type"] == "customer.subscription.updated":
        _handle_subscription_event(event["data"]["object"], "updated")
    elif event["type"] == "customer.subscription.deleted":
        _handle_subscription_event(event["data"]["object"], "deleted")
    elif event["type"] == "invoice.payment_failed":
        inv_obj = event["data"]["object"]
        sub_id = inv_obj.get("subscription")
        if sub_id:
            update_subscription_status(sub_id, SUBSCRIPTION_PAST_DUE)
            logger.warning("Webhook: subscription %s → past_due (payment failed)", sub_id)

    return jsonify({"status": "ok"}), 200


# Exempt the Stripe webhook from CSRF — it uses Stripe signature verification.
if _csrf is not None:
    _csrf.exempt(stripe_webhook)


# ---------------------------------------------------------------------------
# Authentication routes (Google OAuth)
# ---------------------------------------------------------------------------

@app.route("/auth/login")
def auth_login():
    """Redirect to Google OAuth consent screen."""
    if not _oauth_enabled:
        flash("Sign-in is not configured.", "warning")
        return redirect("/")
    # Clear the entire session to force a fresh Set-Cookie on this response.
    # This prevents dual-cookie conflicts: if the browser holds a stale
    # session cookie (from an earlier visit or different path), it sends
    # BOTH the stale and the new one.  Flask reads only the first (stale)
    # cookie, which lacks the OAuth state — causing silent login failures.
    # The fresh Set-Cookie overwrites the stale one (same name, path, domain).
    session.clear()
    session["auth_next"] = request.args.get("next", "/")
    redirect_uri = url_for("auth_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/callback")
def auth_callback():
    """Handle Google OAuth callback — create/find user and log in."""
    if not _oauth_enabled:
        flash("Sign-in is not configured.", "warning")
        return redirect("/")
    # Log incoming callback state for diagnostics — helps identify session
    # loss (state key missing) vs token exchange errors.
    callback_state = request.args.get("state", "<missing>")
    session_state_keys = [k for k in session.keys() if k.startswith("_state_google_")]
    cookie_header = request.headers.get('Cookie', '')
    logger.info(
        "OAuth callback: state=%s..., session_state_keys=%d, session_size_approx=%d, cookie_header_len=%d",
        callback_state[:16], len(session_state_keys), len(str(dict(session))),
        len(cookie_header),
    )
    try:
        token = oauth.google.authorize_access_token()
    except Exception as e:
        logger.exception("OAuth callback failed: %s: %s", type(e).__name__, e)
        session.clear()
        flash("Sign-in failed. Please try again.", "error")
        return redirect("/")

    userinfo = token.get("userinfo", {})
    email = userinfo.get("email")
    if not email:
        flash("Could not retrieve your email from Google.", "error")
        return redirect("/")

    name = userinfo.get("name")
    picture = userinfo.get("picture")
    google_sub = userinfo.get("sub")

    user_dict, created = get_or_create_user(
        email=email, name=name, picture_url=picture, google_sub=google_sub
    )

    # Claim any unclaimed snapshots matching the user's email — on every login,
    # not just the first, so snapshots created between logins are picked up.
    claimed = claim_snapshots_for_user(user_dict["id"], email)
    if claimed:
        logger.info("Auto-claimed %d snapshot(s) for user %s", claimed, email)

    login_user(_FlaskUser(user_dict), remember=True)
    next_url = session.pop("auth_next", "/")
    # Prevent open redirect: only allow relative paths on this host.
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    return redirect(next_url)


@app.route("/auth/logout")
def auth_logout():
    """Log out and redirect to home."""
    logout_user()
    return redirect("/")


# ---------------------------------------------------------------------------
# My Reports (authenticated)
# ---------------------------------------------------------------------------

@app.route("/my-reports")
@login_required
def my_reports():
    """Show the current user's evaluation history."""
    snapshots = get_user_snapshots(current_user.id)
    return render_template(
        "my_reports.html",
        authenticated=True,
        email=current_user.email,
        snapshots=snapshots,
    )


# ---------------------------------------------------------------------------
# SEO: robots.txt and sitemap
# ---------------------------------------------------------------------------

@app.route("/robots.txt")
def robots_txt():
    """Serve robots.txt to guide search engine crawlers."""
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /s/\n"
        "Allow: /pricing\n"
        "Allow: /compare\n"
        "Disallow: /api/\n"
        "Disallow: /job/\n"
        "Disallow: /debug/\n"
        "Disallow: /builder/\n"
        "Disallow: /auth/\n"
        "\n"
        "Sitemap: " + request.url_root.rstrip("/") + "/sitemap.xml\n"
    )
    return app.response_class(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    """Dynamic XML sitemap including static pages and recent evaluations."""
    base = request.url_root.rstrip("/")

    # Static pages with manually assigned priorities
    static_pages = [
        {"loc": base + "/", "priority": "1.0", "changefreq": "daily"},
        {"loc": base + "/pricing", "priority": "0.7", "changefreq": "monthly"},
        {"loc": base + "/compare", "priority": "0.6", "changefreq": "monthly"},
        {"loc": base + "/privacy", "priority": "0.2", "changefreq": "yearly"},
        {"loc": base + "/terms", "priority": "0.2", "changefreq": "yearly"},
    ]

    # Evaluation snapshots — only those that passed health checks
    snapshots = get_sitemap_snapshots(limit=2000)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for page in static_pages:
        lines.append("  <url>")
        lines.append(f"    <loc>{_html_escape(page['loc'])}</loc>")
        lines.append(f"    <changefreq>{page['changefreq']}</changefreq>")
        lines.append(f"    <priority>{page['priority']}</priority>")
        lines.append("  </url>")

    # Curated list pages (NES-293)
    for list_slug in _get_all_list_slugs():
        loc = f"{base}/lists/{_html_escape(list_slug)}"
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append("    <changefreq>monthly</changefreq>")
        lines.append("    <priority>0.7</priority>")
        lines.append("  </url>")

    # City pages (NES-352)
    city_list = []
    try:
        city_list = get_cities_with_snapshots(min_count=3)
        for city_row in city_list:
            slug = _city_slug(city_row["city"])
            st = city_row["state_abbr"].lower()
            lines.append("  <url>")
            lines.append(f"    <loc>{base}/city/{st}/{slug}</loc>")
            lines.append("    <changefreq>weekly</changefreq>")
            lines.append("    <priority>0.6</priority>")
            lines.append("  </url>")
    except Exception:
        logger.warning("Failed to add city pages to sitemap")

    # State pages (NES-344) — only states with evaluated cities
    try:
        states_with_cities = {c["state_abbr"] for c in city_list}
        for st_abbr in sorted(states_with_cities):
            st_slug = _html_escape(st_abbr.lower())
            lines.append("  <url>")
            lines.append(f"    <loc>{base}/state/{st_slug}</loc>")
            lines.append("    <changefreq>weekly</changefreq>")
            lines.append("    <priority>0.6</priority>")
            lines.append("  </url>")
    except Exception:
        logger.warning("Failed to add state pages to sitemap")

    for snap in snapshots:
        loc = f"{base}/s/{_html_escape(snap['snapshot_id'])}"
        lastmod = snap["created_at"][:10] if snap.get("created_at") else ""
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        if lastmod:
            lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append("    <changefreq>never</changefreq>")
        lines.append("    <priority>0.5</priority>")
        lines.append("  </url>")

    lines.append("</urlset>")

    return app.response_class(
        "\n".join(lines),
        mimetype="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ---------------------------------------------------------------------------
# SEO: OG image serving
# ---------------------------------------------------------------------------

@app.route("/og/<snapshot_id>.png")
def serve_og_image(snapshot_id):
    """Serve the pre-generated OG image for a snapshot.

    Falls back to the static default image for old snapshots that
    were created before OG image generation was wired in.
    """
    from models import get_og_image
    image_data = get_og_image(snapshot_id)
    if not image_data:
        return redirect(url_for("static", filename="images/og-default.png"))
    return app.response_class(
        image_data,
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ---------------------------------------------------------------------------
# CSRF token refresh endpoint
# ---------------------------------------------------------------------------

@app.route('/csrf-token', methods=['GET'])
def csrf_token_endpoint():
    """Return a fresh CSRF token for long-lived pages."""
    try:
        from flask_wtf.csrf import generate_csrf
        return jsonify({"csrf_token": generate_csrf()})
    except Exception:
        return jsonify({"csrf_token": ""})


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(400)
def bad_request(e):
    msg = getattr(e, "description", "Bad request")
    if _wants_json():
        resp = {"error": msg}
        if "csrf" in msg.lower():
            resp["error_code"] = "csrf_expired"
        return jsonify(resp), 400
    return render_template("404.html"), 400


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_error(e):
    if _wants_json():
        return jsonify({"error": "Internal server error. Please try again."}), 500
    return render_template("404.html"), 500


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
