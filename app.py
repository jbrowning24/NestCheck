import os
import logging
from flask import Flask, request, render_template
from dotenv import load_dotenv
from property_evaluator import (
    PropertyListing, evaluate_property, CheckResult
)

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'nestcheck-dev-key')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


def result_to_dict(result):
    """Convert EvaluationResult to template-friendly dict."""
    output = {
        "address": result.listing.address,
        "coordinates": {"lat": result.lat, "lng": result.lng},
        "walk_scores": result.walk_scores,
        "neighborhood_snapshot": [
            {
                "category": p.category,
                "name": p.name,
                "rating": p.rating,
                "walk_time_min": p.walk_time_min,
                "place_type": p.place_type
            }
            for p in (result.neighborhood_snapshot.places if result.neighborhood_snapshot else [])
        ],
        "child_schooling_snapshot": {
            "childcare": [
                {
                    "name": p.name,
                    "rating": p.rating,
                    "user_ratings_total": p.user_ratings_total,
                    "walk_time_min": p.walk_time_min,
                    "website": p.website
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
            }
        },
        "urban_access": {
            "primary_transit": {
                "name": result.urban_access.primary_transit.name,
                "mode": result.urban_access.primary_transit.mode,
                "lat": result.urban_access.primary_transit.lat,
                "lng": result.urban_access.primary_transit.lng,
                "walk_time_min": result.urban_access.primary_transit.walk_time_min,
                "drive_time_min": result.urban_access.primary_transit.drive_time_min,
                "parking_available": result.urban_access.primary_transit.parking_available,
                "user_ratings_total": result.urban_access.primary_transit.user_ratings_total,
                "frequency_class": result.urban_access.primary_transit.frequency_class,
            } if result.urban_access and result.urban_access.primary_transit else None,
            "major_hub": {
                "name": result.urban_access.major_hub.name,
                "travel_time_min": result.urban_access.major_hub.travel_time_min,
                "transit_mode": result.urban_access.major_hub.transit_mode,
                "route_summary": result.urban_access.major_hub.route_summary,
            } if result.urban_access and result.urban_access.major_hub else None,
        },
        "green_space_evaluation": {
            "green_escape": {
                "name": result.green_space_evaluation.green_escape.name,
                "rating": result.green_space_evaluation.green_escape.rating,
                "user_ratings_total": result.green_space_evaluation.green_escape.user_ratings_total,
                "walk_time_min": result.green_space_evaluation.green_escape.walk_time_min,
                "types": result.green_space_evaluation.green_escape.types,
                "types_display": result.green_space_evaluation.green_escape.types_display,
            } if result.green_space_evaluation and result.green_space_evaluation.green_escape else None,
            "green_escape_message": (
                result.green_space_evaluation.green_escape_message
                if result.green_space_evaluation else None
            ),
            "green_spaces": [
                {
                    "name": space.name,
                    "rating": space.rating,
                    "user_ratings_total": space.user_ratings_total,
                    "walk_time_min": space.walk_time_min,
                    "types": space.types,
                    "types_display": space.types_display,
                }
                for space in (result.green_space_evaluation.green_spaces if result.green_space_evaluation else [])
            ],
            "other_green_spaces": [
                {
                    "name": space.name,
                    "rating": space.rating,
                    "user_ratings_total": space.user_ratings_total,
                    "walk_time_min": space.walk_time_min,
                    "types": space.types,
                    "types_display": space.types_display,
                }
                for space in (result.green_space_evaluation.other_green_spaces if result.green_space_evaluation else [])
            ],
            "green_spaces_message": (
                result.green_space_evaluation.green_spaces_message
                if result.green_space_evaluation else None
            ),
        },
        "transit_score": result.transit_score,
        "bike_score": result.bike_score,
        "bike_rating": result.bike_rating,
        "bike_metadata": result.bike_metadata,
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


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None
    address = ""

    if request.method == "POST":
        address = request.form.get("address", "").strip()

        if not address:
            error = "Please enter a property address to evaluate."
            return render_template("index.html", result=result, error=error, address=address)

        api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
        if not api_key:
            error = "Service configuration error. Please contact support."
            logger.error("GOOGLE_MAPS_API_KEY not set")
            return render_template("index.html", result=result, error=error, address=address)

        try:
            listing = PropertyListing(address=address)
            eval_result = evaluate_property(listing, api_key)
            result = result_to_dict(eval_result)
        except Exception as e:
            logger.exception("Evaluation failed for address: %s", address)
            error = (
                "Something went wrong while evaluating this address. "
                "Please check the address and try again. "
                "If the problem persists, the address may not be recognized by Google Maps."
            )

    return render_template("index.html", result=result, error=error, address=address)


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
