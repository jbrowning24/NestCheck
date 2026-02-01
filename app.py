import os
import io
import csv
import json
import uuid
import sqlite3
import logging
import hashlib
import hmac
import base64
import zlib
from datetime import datetime, timezone

from flask import (
    Flask, request, render_template, redirect, url_for,
    jsonify, abort, Response,
)
from dotenv import load_dotenv
from property_evaluator import (
    PropertyListing, evaluate_property, CheckResult
)
from urban_access import urban_access_result_to_dict

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nestcheck-dev-key')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persistence — SQLite (file on container; ephemeral across redeploys)
# Falls back to stateless token-based share links if DB is unavailable.
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("NESTCHECK_DB_PATH", "evaluations.db")


def _get_db():
    """Return a SQLite connection (created per-request)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    """Create the evaluations table if it doesn't exist."""
    try:
        conn = _get_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS evaluations (
                id          TEXT PRIMARY KEY,
                address     TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        return True
    except Exception:
        logger.exception("Could not initialise SQLite database")
        return False


DB_AVAILABLE = _init_db()


def _save_evaluation(evaluation_id, address, result_dict):
    """Persist an evaluation. Returns True on success."""
    if not DB_AVAILABLE:
        return False
    try:
        conn = _get_db()
        conn.execute(
            "INSERT OR REPLACE INTO evaluations (id, address, result_json, created_at) VALUES (?, ?, ?, ?)",
            (evaluation_id, address, json.dumps(result_dict), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        logger.exception("Failed to save evaluation %s", evaluation_id)
        return False


def _load_evaluation(evaluation_id):
    """Load an evaluation by id. Returns (address, result_dict, created_at) or None."""
    if not DB_AVAILABLE:
        return None
    try:
        conn = _get_db()
        row = conn.execute("SELECT address, result_json, created_at FROM evaluations WHERE id = ?", (evaluation_id,)).fetchone()
        conn.close()
        if row:
            return row["address"], json.loads(row["result_json"]), row["created_at"]
    except Exception:
        logger.exception("Failed to load evaluation %s", evaluation_id)
    return None

# ---------------------------------------------------------------------------
# Stateless share tokens (fallback when SQLite isn't reliable)
# Encode the result dict as a compressed+signed URL-safe token.
# ---------------------------------------------------------------------------
_SIGN_KEY = app.config['SECRET_KEY'].encode()


def _make_token(result_dict):
    """Compress + sign a result dict into a URL-safe token."""
    payload = zlib.compress(json.dumps(result_dict, separators=(',', ':')).encode(), level=9)
    b64 = base64.urlsafe_b64encode(payload).decode()
    sig = hmac.new(_SIGN_KEY, payload, hashlib.sha256).hexdigest()[:16]
    return f"{sig}.{b64}"


def _decode_token(token):
    """Verify and decompress a stateless token. Returns dict or None."""
    try:
        sig, b64 = token.split(".", 1)
        payload = base64.urlsafe_b64decode(b64)
        expected = hmac.new(_SIGN_KEY, payload, hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        return json.loads(zlib.decompress(payload))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Serialisers (unchanged logic, cleaned up from old app.py)
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

    engine = None
    if urban_access.engine_result:
        engine = urban_access_result_to_dict(urban_access.engine_result)

    return {
        "primary_transit": primary_transit,
        "major_hub": major_hub,
        "engine": engine,
    }


def result_to_dict(result):
    """Convert EvaluationResult to a serialisable dict."""
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
# CSV helper
# ---------------------------------------------------------------------------

def _result_to_csv(result_dict):
    """Flatten a result dict into a downloadable CSV string."""
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header row
    writer.writerow(["Section", "Name", "Value", "Details"])

    # Summary
    writer.writerow(["Summary", "Address", result_dict.get("address", ""), ""])
    writer.writerow(["Summary", "Final Score", result_dict.get("final_score", ""), ""])
    writer.writerow(["Summary", "Verdict", result_dict.get("verdict", ""), ""])
    writer.writerow(["Summary", "Passed Tier 1", result_dict.get("passed_tier1", ""), ""])

    # Tier 1 checks
    for c in result_dict.get("tier1_checks", []):
        writer.writerow(["Health & Safety", c.get("name", ""), c.get("result", ""), c.get("details", "")])

    # Tier 2 scores
    for s in result_dict.get("tier2_scores", []):
        writer.writerow(["Score Breakdown", s.get("name", ""), f'{s.get("points", "")}/{s.get("max", "")}', s.get("details", "")])

    # Tier 3 bonuses
    for b in result_dict.get("tier3_bonuses", []):
        writer.writerow(["Bonus", b.get("name", ""), f'+{b.get("points", "")}', b.get("details", "")])

    # Walk scores
    ws = result_dict.get("walk_scores") or {}
    if ws:
        for key in ("walk_score", "transit_score", "bike_score"):
            val = ws.get(key)
            if val is not None:
                writer.writerow(["Walk Scores", key.replace("_", " ").title(), val, ws.get(key.replace("score", "description"), "")])

    return buf.getvalue()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/evaluate", methods=["POST"])
def evaluate():
    """Run evaluation, persist results, redirect to results page."""
    address = request.form.get("address", "").strip()

    if not address:
        return render_template("index.html", error="Please enter a property address to evaluate.")

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        error = (
            "Google Maps API key is not configured. "
            "The server administrator needs to set the GOOGLE_MAPS_API_KEY environment variable."
        )
        logger.error("GOOGLE_MAPS_API_KEY not set")
        return render_template("index.html", error=error, address=address)

    try:
        listing = PropertyListing(address=address)
        eval_result = evaluate_property(listing, api_key)
        result_dict = result_to_dict(eval_result)
    except Exception:
        logger.exception("Evaluation failed for address: %s", address)
        error = (
            "Something went wrong while evaluating this address. "
            "Please check the address and try again. "
            "If the problem persists, the address may not be recognized by Google Maps."
        )
        return render_template("index.html", error=error, address=address)

    # Persist
    evaluation_id = uuid.uuid4().hex[:12]
    saved = _save_evaluation(evaluation_id, address, result_dict)

    if saved:
        return redirect(url_for("view_evaluation", evaluation_id=evaluation_id))

    # Fallback: stateless token redirect
    token = _make_token(result_dict)
    return redirect(url_for("view_evaluation", evaluation_id="t") + f"?d={token}")


@app.route("/e/<evaluation_id>")
def view_evaluation(evaluation_id):
    """Render the results page for a saved evaluation."""
    result_dict = None
    address = None
    created_at = None
    share_url = request.url

    # Stateless token mode
    if evaluation_id == "t":
        token = request.args.get("d")
        if token:
            result_dict = _decode_token(token)
        if not result_dict:
            abort(404)
        address = result_dict.get("address", "")
        created_at = datetime.now(timezone.utc).isoformat()
    else:
        loaded = _load_evaluation(evaluation_id)
        if not loaded:
            abort(404)
        address, result_dict, created_at = loaded

    return render_template(
        "results.html",
        result=result_dict,
        address=address,
        evaluation_id=evaluation_id,
        created_at=created_at,
        share_url=share_url,
    )


@app.route("/e/<evaluation_id>.json")
def evaluation_json(evaluation_id):
    """Return evaluation results as JSON."""
    result_dict = None

    if evaluation_id == "t":
        token = request.args.get("d")
        if token:
            result_dict = _decode_token(token)
    else:
        loaded = _load_evaluation(evaluation_id)
        if loaded:
            _, result_dict, _ = loaded

    if not result_dict:
        abort(404)

    return jsonify({
        "evaluation_id": evaluation_id,
        "data": result_dict,
    })


@app.route("/e/<evaluation_id>.csv")
def evaluation_csv(evaluation_id):
    """Return evaluation results as CSV download."""
    result_dict = None

    if evaluation_id == "t":
        token = request.args.get("d")
        if token:
            result_dict = _decode_token(token)
    else:
        loaded = _load_evaluation(evaluation_id)
        if loaded:
            _, result_dict, _ = loaded

    if not result_dict:
        abort(404)

    csv_data = _result_to_csv(result_dict)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=nestcheck-{evaluation_id}.csv"},
    )


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


# ---------------------------------------------------------------------------
# Optional email delivery (only visible if SMTP env vars are set)
# ---------------------------------------------------------------------------

def _smtp_configured():
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


@app.route("/e/<evaluation_id>/email", methods=["POST"])
def email_results(evaluation_id):
    """Send evaluation results via email (requires SMTP_* env vars)."""
    if not _smtp_configured():
        abort(404)

    import smtplib
    from email.mime.text import MIMEText

    recipient = request.form.get("email", "").strip()
    if not recipient:
        return jsonify({"error": "Email address required"}), 400

    loaded = _load_evaluation(evaluation_id)
    if not loaded:
        abort(404)
    address, result_dict, _ = loaded

    body = (
        f"NestCheck Results for {address}\n"
        f"Score: {result_dict.get('final_score', 'N/A')} / 100\n"
        f"Verdict: {result_dict.get('verdict', '')}\n\n"
        f"View full results: {request.host_url}e/{evaluation_id}\n"
    )

    msg = MIMEText(body)
    msg["Subject"] = f"NestCheck Results: {address}"
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = recipient

    try:
        host = os.environ["SMTP_HOST"]
        port = int(os.environ.get("SMTP_PORT", "587"))
        user = os.environ.get("SMTP_USER", "")
        password = os.environ.get("SMTP_PASSWORD", "")

        with smtplib.SMTP(host, port) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        return jsonify({"ok": True})
    except Exception:
        logger.exception("Failed to send email for evaluation %s", evaluation_id)
        return jsonify({"error": "Failed to send email. Please try again."}), 500


# ---------------------------------------------------------------------------
# Template context
# ---------------------------------------------------------------------------

@app.context_processor
def inject_globals():
    return {
        "smtp_configured": _smtp_configured(),
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
