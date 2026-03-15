"""
Reference address regression tests (NES-89+).

Tests that scoring functions produce outputs within the expected_range
defined in tests/fixtures/reference_addresses.json, using synthetic inputs
derived from address notes.

Structure:
  Part 1: Synthetic inputs keyed by "address_id:dimension"
  Part 2: Parametrized dimension-level score tests
  Part 3: Band classification tests (composite score)
  Part 4: Spot-check specific curve values
"""

import json
from pathlib import Path

import pytest

from scoring_config import (
    SCORING_MODEL,
    apply_piecewise,
    apply_quality_multiplier,
)
from property_evaluator import (
    get_score_band,
    compute_transit_score,
    compute_composite_score,
)
from green_space import compute_park_score

# ---------------------------------------------------------------------------
# Load reference data
# ---------------------------------------------------------------------------
_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reference_addresses.json"

with open(_FIXTURE_PATH) as f:
    _REF_DATA = json.load(f)

_ADDRESSES = _REF_DATA["addresses"]


# ---------------------------------------------------------------------------
# Part 1: Synthetic inputs
#
# Each entry is keyed by "{address_id}:{dimension}".
# Value is a dict of synthetic parameters derived from the fixture notes.
#
# Coffee/grocery: walk_time_min, rating, reviews
# Fitness: walk_time_min, rating, reviews
# Parks: walk_time_min, park_acres, rating, reviews, name, + optional OSM
# Transit: walk_time_min, frequency_bucket, hub_travel_time_min, drive_time_min
# ---------------------------------------------------------------------------

SYNTHETIC_INPUTS = {
    # ── ref-001: Brooklyn 7th Ave (Park Slope) ──────────────────────────
    "ref-001:parks": {"walk_time_min": 4, "park_acres": 585.0, "rating": 4.8, "reviews": 5000, "name": "Prospect Park", "osm_has_trail": True, "osm_nature_tags": ["natural=wood", "leisure=park"]},
    "ref-001:coffee": {"walk_time_min": 5, "rating": 4.5, "reviews": 500},
    "ref-001:grocery": {"walk_time_min": 8, "rating": 4.3, "reviews": 300},
    "ref-001:fitness": {"walk_time_min": 8, "rating": 4.5, "reviews": 200},
    "ref-001:transit": {"walk_time_min": 5, "frequency_bucket": "High", "hub_travel_time_min": 25},
    "ref-001:road_noise": {"dba": 55},

    # ── ref-002: Astoria Steinway St ────────────────────────────────────
    "ref-002:parks": {"walk_time_min": 17, "park_acres": 60.0, "rating": 4.7, "reviews": 3000, "name": "Astoria Park", "osm_has_trail": True},
    "ref-002:coffee": {"walk_time_min": 6, "rating": 4.4, "reviews": 350},
    "ref-002:grocery": {"walk_time_min": 7, "rating": 4.2, "reviews": 250},
    "ref-002:fitness": {"walk_time_min": 10, "rating": 4.3, "reviews": 150},
    "ref-002:transit": {"walk_time_min": 5, "frequency_bucket": "High", "hub_travel_time_min": 30},
    "ref-002:road_noise": {"dba": 62},

    # ── ref-003: Upper East Side 1060 Park Ave ──────────────────────────
    "ref-003:parks": {"walk_time_min": 5, "park_acres": 843.0, "rating": 4.8, "reviews": 10000, "name": "Central Park", "osm_has_trail": True, "osm_nature_tags": ["natural=wood", "water=lake", "leisure=park"]},
    "ref-003:coffee": {"walk_time_min": 5, "rating": 4.5, "reviews": 400},
    "ref-003:grocery": {"walk_time_min": 7, "rating": 4.4, "reviews": 500},
    "ref-003:fitness": {"walk_time_min": 8, "rating": 4.5, "reviews": 300},
    "ref-003:transit": {"walk_time_min": 5, "frequency_bucket": "High", "hub_travel_time_min": 15},
    "ref-003:road_noise": {"dba": 52},

    # ── ref-004: Hoboken River St ───────────────────────────────────────
    "ref-004:parks": {"walk_time_min": 8, "park_acres": 3.0, "rating": 4.5, "reviews": 500, "name": "Pier A Park"},
    "ref-004:coffee": {"walk_time_min": 6, "rating": 4.4, "reviews": 300},
    "ref-004:grocery": {"walk_time_min": 8, "rating": 4.2, "reviews": 250},
    "ref-004:fitness": {"walk_time_min": 10, "rating": 4.3, "reviews": 100},
    "ref-004:transit": {"walk_time_min": 13, "frequency_bucket": "Medium", "hub_travel_time_min": 40},
    "ref-004:road_noise": {"dba": 58},

    # ── ref-005: Tarrytown Main St ──────────────────────────────────────
    "ref-005:parks": {"walk_time_min": 10, "park_acres": 3.0, "rating": 4.3, "reviews": 100, "name": "Pierson Park"},
    "ref-005:coffee": {"walk_time_min": 10, "rating": 4.3, "reviews": 150},
    "ref-005:grocery": {"walk_time_min": 18, "rating": 4.0, "reviews": 100},
    "ref-005:fitness": {"walk_time_min": 25, "rating": 3.8, "reviews": 30},
    "ref-005:transit": {"walk_time_min": 15, "frequency_bucket": "Low", "hub_travel_time_min": 65},
    "ref-005:road_noise": {"dba": 55},

    # ── ref-006: Yonkers S Broadway ─────────────────────────────────────
    "ref-006:parks": {"walk_time_min": 25, "rating": 3.5, "reviews": 30, "name": "small park"},
    "ref-006:coffee": {"walk_time_min": 15, "rating": 4.0, "reviews": 80},
    "ref-006:grocery": {"walk_time_min": 15, "rating": 3.8, "reviews": 80},
    "ref-006:fitness": {"walk_time_min": 20, "rating": 3.8, "reviews": 20},
    "ref-006:transit": {"walk_time_min": 18, "frequency_bucket": "Low", "hub_travel_time_min": 55},
    "ref-006:road_noise": {"dba": 65},

    # ── ref-007: White Plains Mamaroneck Ave ────────────────────────────
    "ref-007:parks": {"walk_time_min": 10, "park_acres": 4.0, "rating": 4.2, "reviews": 80, "name": "Battle Hill Park"},
    "ref-007:coffee": {"walk_time_min": 10, "rating": 4.2, "reviews": 120},
    "ref-007:grocery": {"walk_time_min": 12, "rating": 4.1, "reviews": 200},
    "ref-007:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 50},
    "ref-007:transit": {"walk_time_min": 10, "frequency_bucket": "Low", "hub_travel_time_min": 50},
    "ref-007:road_noise": {"dba": 62},

    # ── ref-008: Bronx Exterior St (highway-adjacent) ───────────────────
    "ref-008:parks": {"walk_time_min": 10, "park_acres": 28.0, "rating": 4.4, "reviews": 1000, "name": "Macombs Dam Park"},
    "ref-008:coffee": {"walk_time_min": 25, "rating": 3.9, "reviews": 40},
    "ref-008:grocery": {"walk_time_min": 25, "rating": 3.8, "reviews": 50},
    "ref-008:fitness": {"walk_time_min": 25, "rating": 3.7, "reviews": 15},
    "ref-008:transit": {"walk_time_min": 5, "frequency_bucket": "High", "hub_travel_time_min": 20},
    "ref-008:road_noise": {"dba": 78},

    # ── ref-009: Bronx E Tremont (gas station) ──────────────────────────
    "ref-009:parks": {"walk_time_min": 14, "park_acres": 127.0, "rating": 4.5, "reviews": 2000, "name": "Crotona Park"},
    "ref-009:coffee": {"walk_time_min": 20, "rating": 3.9, "reviews": 50},
    "ref-009:grocery": {"walk_time_min": 12, "rating": 4.0, "reviews": 100},
    "ref-009:fitness": {"walk_time_min": 25, "rating": 3.7, "reviews": 15},
    "ref-009:transit": {"walk_time_min": 12, "frequency_bucket": "Medium", "hub_travel_time_min": 50},
    "ref-009:road_noise": {"dba": 65},

    # ── ref-010: Seattle Capitol Hill 1505 Broadway ─────────────────────
    "ref-010:parks": {"walk_time_min": 5, "park_acres": 7.5, "rating": 4.5, "reviews": 2000, "name": "Cal Anderson Park"},
    "ref-010:coffee": {"walk_time_min": 5, "rating": 4.6, "reviews": 400},
    "ref-010:grocery": {"walk_time_min": 8, "rating": 4.3, "reviews": 300},
    "ref-010:fitness": {"walk_time_min": 10, "rating": 4.3, "reviews": 200},
    "ref-010:transit": {"walk_time_min": 5, "frequency_bucket": "High", "hub_travel_time_min": 25},
    "ref-010:road_noise": {"dba": 60},

    # ── ref-011: Seattle Fremont ────────────────────────────────────────
    "ref-011:parks": {"walk_time_min": 11, "park_acres": 20.0, "rating": 4.6, "reviews": 3000, "name": "Gas Works Park"},
    "ref-011:coffee": {"walk_time_min": 7, "rating": 4.4, "reviews": 300},
    "ref-011:grocery": {"walk_time_min": 8, "rating": 4.3, "reviews": 250},
    "ref-011:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 60},
    "ref-011:transit": {"walk_time_min": 12, "frequency_bucket": "Medium", "hub_travel_time_min": 50},
    "ref-011:road_noise": {"dba": 58},

    # ── ref-012: Seattle Ballard residential fringe ─────────────────────
    "ref-012:parks": {"walk_time_min": 22, "park_acres": 88.0, "rating": 4.6, "reviews": 5000, "name": "Golden Gardens Park", "osm_nature_tags": ["natural=beach"]},
    "ref-012:coffee": {"walk_time_min": 13, "rating": 4.3, "reviews": 200},
    "ref-012:grocery": {"walk_time_min": 12, "rating": 4.2, "reviews": 250},
    "ref-012:fitness": {"walk_time_min": 13, "rating": 4.0, "reviews": 50},
    "ref-012:transit": {"walk_time_min": 12, "frequency_bucket": "Low", "hub_travel_time_min": 55},
    "ref-012:road_noise": {"dba": 55},

    # ── ref-013: Seattle U-District ─────────────────────────────────────
    "ref-013:parks": {"walk_time_min": 12, "park_acres": 58.0, "rating": 4.6, "reviews": 2000, "name": "Ravenna Park", "osm_has_trail": True, "osm_nature_tags": ["natural=wood"]},
    "ref-013:coffee": {"walk_time_min": 5, "rating": 4.3, "reviews": 250},
    "ref-013:grocery": {"walk_time_min": 7, "rating": 4.2, "reviews": 200},
    "ref-013:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 60},
    "ref-013:transit": {"walk_time_min": 5, "frequency_bucket": "High", "hub_travel_time_min": 25},
    "ref-013:road_noise": {"dba": 58},

    # ── ref-014: Renton ─────────────────────────────────────────────────
    "ref-014:parks": {"walk_time_min": 15, "park_acres": 57.0, "rating": 4.5, "reviews": 2000, "name": "Gene Coulon Memorial Beach Park"},
    "ref-014:coffee": {"walk_time_min": 20, "rating": 4.0, "reviews": 60},
    "ref-014:grocery": {"walk_time_min": 12, "rating": 4.0, "reviews": 150},
    "ref-014:fitness": {"walk_time_min": 25, "rating": 3.8, "reviews": 30},
    "ref-014:transit": {"walk_time_min": 20, "frequency_bucket": "Low", "hub_travel_time_min": 80},
    "ref-014:road_noise": {"dba": 62},

    # ── ref-015: Seattle Beacon Hill ────────────────────────────────────
    "ref-015:parks": {"walk_time_min": 10, "park_acres": 48.0, "rating": 4.6, "reviews": 1500, "name": "Jefferson Park", "osm_has_trail": True},
    "ref-015:coffee": {"walk_time_min": 12, "rating": 4.2, "reviews": 100},
    "ref-015:grocery": {"walk_time_min": 12, "rating": 4.0, "reviews": 150},
    "ref-015:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 50},
    "ref-015:transit": {"walk_time_min": 10, "frequency_bucket": "Medium", "hub_travel_time_min": 40},
    "ref-015:road_noise": {"dba": 55},

    # ── ref-016: DC Georgia Ave NW (Petworth) ───────────────────────────
    "ref-016:parks": {"walk_time_min": 10, "park_acres": 5.0, "rating": 4.2, "reviews": 200, "name": "Grant Circle Park"},
    "ref-016:coffee": {"walk_time_min": 10, "rating": 4.2, "reviews": 120},
    "ref-016:grocery": {"walk_time_min": 12, "rating": 4.0, "reviews": 150},
    "ref-016:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 50},
    "ref-016:transit": {"walk_time_min": 10, "frequency_bucket": "Medium", "hub_travel_time_min": 50},
    "ref-016:road_noise": {"dba": 62},

    # ── ref-017: DC Dupont Circle ───────────────────────────────────────
    "ref-017:parks": {"walk_time_min": 18, "park_acres": 1754.0, "rating": 4.7, "reviews": 5000, "name": "Rock Creek Park"},
    "ref-017:coffee": {"walk_time_min": 4, "rating": 4.5, "reviews": 500},
    "ref-017:grocery": {"walk_time_min": 8, "rating": 4.3, "reviews": 400},
    "ref-017:fitness": {"walk_time_min": 8, "rating": 4.5, "reviews": 300},
    "ref-017:transit": {"walk_time_min": 5, "frequency_bucket": "High", "hub_travel_time_min": 15},
    "ref-017:road_noise": {"dba": 58},

    # ── ref-018: Arlington Wilson Blvd ──────────────────────────────────
    "ref-018:parks": {"walk_time_min": 10, "park_acres": 3.0, "rating": 4.3, "reviews": 100, "name": "Courthouse Park"},
    "ref-018:coffee": {"walk_time_min": 5, "rating": 4.4, "reviews": 350},
    "ref-018:grocery": {"walk_time_min": 7, "rating": 4.3, "reviews": 300},
    "ref-018:fitness": {"walk_time_min": 8, "rating": 4.4, "reviews": 200},
    "ref-018:transit": {"walk_time_min": 8, "frequency_bucket": "High", "hub_travel_time_min": 25},
    "ref-018:road_noise": {"dba": 60},

    # ── ref-019: DC 14th St NW ──────────────────────────────────────────
    "ref-019:parks": {"walk_time_min": 10, "park_acres": 12.0, "rating": 4.6, "reviews": 3000, "name": "Meridian Hill Park"},
    "ref-019:coffee": {"walk_time_min": 5, "rating": 4.5, "reviews": 400},
    "ref-019:grocery": {"walk_time_min": 7, "rating": 4.3, "reviews": 350},
    "ref-019:fitness": {"walk_time_min": 10, "rating": 4.3, "reviews": 150},
    "ref-019:transit": {"walk_time_min": 5, "frequency_bucket": "High", "hub_travel_time_min": 20},
    "ref-019:road_noise": {"dba": 62},

    # ── ref-020: Tysons VA ──────────────────────────────────────────────
    "ref-020:parks": {"walk_time_min": 40, "rating": 3.5, "reviews": 20, "name": "office park landscaping"},
    "ref-020:coffee": {"walk_time_min": 35, "rating": 4.0, "reviews": 100},
    "ref-020:grocery": {"walk_time_min": 30, "rating": 4.0, "reviews": 200},
    "ref-020:fitness": {"walk_time_min": 25, "rating": 4.0, "reviews": 50},
    "ref-020:transit": {"walk_time_min": 12, "frequency_bucket": "Low", "hub_travel_time_min": 60},
    "ref-020:road_noise": {"dba": 65},

    # ── ref-021: DC Georgia Ave NW (upper) ──────────────────────────────
    "ref-021:parks": {"walk_time_min": 10, "park_acres": 3.0, "rating": 4.0, "reviews": 60, "name": "Fort Stevens Park"},
    "ref-021:coffee": {"walk_time_min": 18, "rating": 4.0, "reviews": 60},
    "ref-021:grocery": {"walk_time_min": 12, "rating": 4.0, "reviews": 100},
    "ref-021:fitness": {"walk_time_min": 25, "rating": 3.7, "reviews": 15},
    "ref-021:transit": {"walk_time_min": 18, "frequency_bucket": "Medium", "hub_travel_time_min": 45},
    "ref-021:road_noise": {"dba": 62},

    # ── ref-022: Plano TX ───────────────────────────────────────────────
    "ref-022:parks": {"walk_time_min": 40, "rating": 4.0, "reviews": 50, "name": "neighborhood park"},
    "ref-022:coffee": {"walk_time_min": 45, "rating": 4.0, "reviews": 100},
    "ref-022:grocery": {"walk_time_min": 45, "rating": 4.0, "reviews": 200},
    "ref-022:fitness": {"walk_time_min": 40, "rating": 4.0, "reviews": 50},
    "ref-022:transit": {"walk_time_min": 45, "frequency_bucket": "Very low", "hub_travel_time_min": None},
    "ref-022:road_noise": {"dba": 58},

    # ── ref-023: Santa Monica ───────────────────────────────────────────
    "ref-023:parks": {"walk_time_min": 8, "park_acres": 6.0, "rating": 4.6, "reviews": 3000, "name": "Tongva Park"},
    "ref-023:coffee": {"walk_time_min": 5, "rating": 4.5, "reviews": 400},
    "ref-023:grocery": {"walk_time_min": 8, "rating": 4.3, "reviews": 300},
    "ref-023:fitness": {"walk_time_min": 8, "rating": 4.5, "reviews": 250},
    "ref-023:transit": {"walk_time_min": 12, "frequency_bucket": "Low", "hub_travel_time_min": 50},
    "ref-023:road_noise": {"dba": 60},

    # ── ref-024: Glendale CA ────────────────────────────────────────────
    "ref-024:parks": {"walk_time_min": 30, "rating": 3.8, "reviews": 40, "name": "small city park"},
    "ref-024:coffee": {"walk_time_min": 12, "rating": 4.2, "reviews": 120},
    "ref-024:grocery": {"walk_time_min": 12, "rating": 4.1, "reviews": 150},
    "ref-024:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 50},
    "ref-024:transit": {"walk_time_min": 25, "frequency_bucket": "Low", "hub_travel_time_min": 80},
    "ref-024:road_noise": {"dba": 62},

    # ── ref-025: Austin Mueller ─────────────────────────────────────────
    "ref-025:parks": {"walk_time_min": 8, "park_acres": 30.0, "rating": 4.5, "reviews": 1000, "name": "Mueller Lake Park", "osm_nature_tags": ["leisure=park"]},
    "ref-025:coffee": {"walk_time_min": 12, "rating": 4.3, "reviews": 150},
    "ref-025:grocery": {"walk_time_min": 10, "rating": 4.2, "reviews": 200},
    "ref-025:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 50},
    "ref-025:transit": {"walk_time_min": 15, "frequency_bucket": "Low", "hub_travel_time_min": 80},
    "ref-025:road_noise": {"dba": 55},

    # ── ref-026: Mesa AZ ────────────────────────────────────────────────
    "ref-026:parks": {"walk_time_min": 35, "rating": 3.8, "reviews": 30, "name": "Riverview Park"},
    "ref-026:coffee": {"walk_time_min": 45, "rating": 3.8, "reviews": 50},
    "ref-026:grocery": {"walk_time_min": 45, "rating": 3.8, "reviews": 100},
    "ref-026:fitness": {"walk_time_min": 40, "rating": 3.8, "reviews": 30},
    "ref-026:transit": {"walk_time_min": 30, "frequency_bucket": "Very low", "hub_travel_time_min": None},
    "ref-026:road_noise": {"dba": 62},

    # ── ref-027: Portland Alberta St ────────────────────────────────────
    "ref-027:parks": {"walk_time_min": 7, "park_acres": 16.0, "rating": 4.4, "reviews": 500, "name": "Alberta Park"},
    "ref-027:coffee": {"walk_time_min": 5, "rating": 4.5, "reviews": 350},
    "ref-027:grocery": {"walk_time_min": 10, "rating": 4.2, "reviews": 200},
    "ref-027:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 60},
    "ref-027:transit": {"walk_time_min": 12, "frequency_bucket": "Low", "hub_travel_time_min": 55},
    "ref-027:road_noise": {"dba": 58},

    # ── ref-028: Denver E Colfax ────────────────────────────────────────
    "ref-028:parks": {"walk_time_min": 18, "park_acres": 330.0, "rating": 4.5, "reviews": 3000, "name": "City Park"},
    "ref-028:coffee": {"walk_time_min": 25, "rating": 3.9, "reviews": 40},
    "ref-028:grocery": {"walk_time_min": 20, "rating": 3.8, "reviews": 60},
    "ref-028:fitness": {"walk_time_min": 25, "rating": 3.7, "reviews": 15},
    "ref-028:transit": {"walk_time_min": 15, "frequency_bucket": "Medium", "hub_travel_time_min": 80},
    "ref-028:road_noise": {"dba": 68},

    # ── ref-029: Miami Brickell ─────────────────────────────────────────
    "ref-029:parks": {"walk_time_min": 10, "park_acres": 2.0, "rating": 4.3, "reviews": 300, "name": "Brickell Key Park"},
    "ref-029:coffee": {"walk_time_min": 5, "rating": 4.4, "reviews": 350},
    "ref-029:grocery": {"walk_time_min": 7, "rating": 4.3, "reviews": 300},
    "ref-029:fitness": {"walk_time_min": 8, "rating": 4.5, "reviews": 250},
    "ref-029:transit": {"walk_time_min": 10, "frequency_bucket": "Medium", "hub_travel_time_min": 50},
    "ref-029:road_noise": {"dba": 62},

    # ── ref-030: Houston Galleria ───────────────────────────────────────
    "ref-030:parks": {"walk_time_min": 25, "park_acres": 1.0, "rating": 4.2, "reviews": 3000, "name": "Gerald Hines Waterwall Park"},
    "ref-030:coffee": {"walk_time_min": 30, "rating": 4.0, "reviews": 100},
    "ref-030:grocery": {"walk_time_min": 25, "rating": 4.0, "reviews": 150},
    "ref-030:fitness": {"walk_time_min": 25, "rating": 4.0, "reviews": 80},
    "ref-030:transit": {"walk_time_min": 20, "frequency_bucket": "Low", "hub_travel_time_min": 90},
    "ref-030:road_noise": {"dba": 65},
}


# ---------------------------------------------------------------------------
# Helpers: compute a raw score from synthetic inputs using config curves
# ---------------------------------------------------------------------------

def _score_coffee(inputs: dict) -> float:
    """Compute raw coffee score from walk_time_min via piecewise curve.

    Note: This tests only the walk-time curve. Production also applies
    two ceilings (category diversity + quality ceiling) that depend on
    the full place list — not testable from synthetic scalar inputs.
    """
    raw = apply_piecewise(SCORING_MODEL.coffee.knots, inputs["walk_time_min"])
    return int(max(SCORING_MODEL.coffee.floor, raw) + 0.5)


def _score_grocery(inputs: dict) -> float:
    """Compute raw grocery score from walk_time_min via piecewise curve."""
    raw = apply_piecewise(SCORING_MODEL.grocery.knots, inputs["walk_time_min"])
    return int(max(SCORING_MODEL.grocery.floor, raw) + 0.5)


def _score_fitness(inputs: dict) -> float:
    """Compute fitness score = distance_curve(walk_time) * quality_multiplier(rating)."""
    base = apply_piecewise(SCORING_MODEL.fitness.knots, inputs["walk_time_min"])
    mult = apply_quality_multiplier(
        SCORING_MODEL.fitness.quality_multipliers, inputs["rating"],
    )
    return int(max(SCORING_MODEL.fitness.floor, base * mult) + 0.5)


def _score_road_noise(inputs: dict) -> float:
    """Compute road noise score from dba via piecewise curve."""
    raw = apply_piecewise(SCORING_MODEL.road_noise.knots, inputs["dba"])
    return int(max(SCORING_MODEL.road_noise.floor, raw) + 0.5)


def _score_parks(inputs: dict) -> float:
    """Compute park Daily Walk Value via compute_park_score()."""
    return int(compute_park_score(
        walk_time_min=inputs["walk_time_min"],
        rating=inputs.get("rating"),
        reviews=inputs.get("reviews", 0),
        name=inputs.get("name", ""),
        types=inputs.get("types", []),
        park_acres=inputs.get("park_acres"),
        osm_area_sqm=inputs.get("osm_area_sqm"),
        osm_path_count=inputs.get("osm_path_count", 0),
        osm_has_trail=inputs.get("osm_has_trail", False),
        osm_nature_tags=inputs.get("osm_nature_tags"),
    ) + 0.5)


def _score_transit(inputs: dict) -> int:
    """Compute transit score via compute_transit_score()."""
    return compute_transit_score(
        walk_time_min=inputs["walk_time_min"],
        frequency_bucket=inputs["frequency_bucket"],
        hub_travel_time_min=inputs.get("hub_travel_time_min"),
        drive_time_min=inputs.get("drive_time_min"),
    )


_DIMENSION_SCORERS = {
    "coffee": _score_coffee,
    "grocery": _score_grocery,
    "fitness": _score_fitness,
    "parks": _score_parks,
    "transit": _score_transit,
    "road_noise": _score_road_noise,
}


# ---------------------------------------------------------------------------
# Part 2: Build parametrized test cases
# ---------------------------------------------------------------------------

def _build_dimension_test_cases():
    """Yield (address_id, address_label, dimension, expected_lo, expected_hi, inputs)."""
    for addr in _ADDRESSES:
        addr_id = addr["id"]
        addr_label = f"{addr['city']}_{addr_id}"
        for dim_name, dim_data in addr.get("dimensions", {}).items():
            key = f"{addr_id}:{dim_name}"
            expected = dim_data.get("expected_range")
            if expected is None:
                continue
            lo, hi = expected
            inputs = SYNTHETIC_INPUTS.get(key)
            yield addr_id, addr_label, dim_name, lo, hi, inputs


_DIMENSION_CASES = list(_build_dimension_test_cases())


@pytest.mark.parametrize(
    "addr_id, addr_label, dimension, expected_lo, expected_hi, inputs",
    _DIMENSION_CASES,
    ids=[f"{c[0]}-{c[2]}" for c in _DIMENSION_CASES],
)
def test_dimension_score_in_range(
    addr_id, addr_label, dimension, expected_lo, expected_hi, inputs,
):
    """Assert that the scoring function output falls within expected_range."""
    if inputs is None:
        pytest.skip(f"No synthetic inputs for {addr_id}:{dimension}")

    scorer = _DIMENSION_SCORERS.get(dimension)
    if scorer is None:
        pytest.skip(f"No scorer registered for dimension '{dimension}'")

    score = scorer(inputs)

    assert expected_lo <= score <= expected_hi, (
        f"{addr_label}:{dimension} — score {score:.1f} outside "
        f"expected [{expected_lo}, {expected_hi}]"
    )


# ---------------------------------------------------------------------------
# Part 3: Band classification tests
#
# Uses compute_composite_score() + get_score_band() to test that the
# composite of all dimension scores lands in the expected band.
# Road noise is not in the reference fixture — excluded from composite
# (treated as not_scored).
# ---------------------------------------------------------------------------

def _build_band_test_cases():
    """Yield (addr_id, city, expected_band) for addresses with expected_band."""
    for addr in _ADDRESSES:
        band = addr.get("expected_band")
        if band is not None:
            yield addr["id"], addr["city"], band


_BAND_CASES = list(_build_band_test_cases())


@pytest.mark.parametrize(
    "addr_id, city, expected_band",
    _BAND_CASES,
    ids=[f"{c[0]}-band" for c in _BAND_CASES],
)
def test_band_classification(addr_id, city, expected_band):
    """Assert that composite score from midpoint expected_ranges lands in the expected band.

    Uses the midpoint of each dimension's expected_range from the fixture
    (not the synthetic inputs, which test individual scorer accuracy).
    This validates the compute_composite_score + get_score_band pipeline.
    """
    addr = next(a for a in _ADDRESSES if a["id"] == addr_id)
    dims = addr.get("dimensions", {})

    dim_tuples = []
    for dim_name in ("parks", "coffee", "grocery", "fitness", "transit"):
        dim_data = dims.get(dim_name, {})
        expected_range = dim_data.get("expected_range")
        if expected_range is None:
            dim_tuples.append((None, 10, "not_scored"))
            continue
        lo, hi = expected_range
        midpoint = int((lo + hi) / 2 + 0.5)
        dim_tuples.append((midpoint, 10, None))

    # Road noise is not in the fixture dimensions but is a 6th production
    # dimension.  Use the synthetic road_noise input if available.
    rn_key = f"{addr_id}:road_noise"
    rn_inputs = SYNTHETIC_INPUTS.get(rn_key)
    if rn_inputs:
        rn_score = _score_road_noise(rn_inputs)
        dim_tuples.append((rn_score, 10, None))
    else:
        dim_tuples.append((None, 10, "not_scored"))

    composite = compute_composite_score(dim_tuples)
    band = get_score_band(composite)

    assert band["label"] == expected_band, (
        f"{city} ({addr_id}) — composite {composite}, "
        f"got band '{band['label']}', expected '{expected_band}'"
    )


# ---------------------------------------------------------------------------
# Part 4: Spot-check specific curve values to catch step→smooth regressions
# ---------------------------------------------------------------------------

class TestCurveSpotChecks:
    """Verify specific curve outputs at values that were cliff edges
    under the old step function, confirming smooth behavior."""

    def test_coffee_at_16_smooth(self):
        """16 min was 10→7 cliff under old step. Smooth should be ~7.6."""
        score = apply_piecewise(SCORING_MODEL.coffee.knots, 16)
        assert 7.0 <= score <= 8.5

    def test_coffee_at_21_smooth(self):
        """21 min was 7→4 cliff under old step. Smooth should be ~5.8."""
        score = apply_piecewise(SCORING_MODEL.coffee.knots, 21)
        assert 5.0 <= score <= 6.5

    def test_grocery_at_15_smooth(self):
        """15 min was full 10 under old step. Smooth is 8.0."""
        score = apply_piecewise(SCORING_MODEL.grocery.knots, 15)
        assert 7.5 <= score <= 8.5

    def test_fitness_low_rating_gets_score(self):
        """3.7★ gym at 10 min was 0 under old step. Smooth gives 6.0."""
        score = _score_fitness({"walk_time_min": 10, "rating": 3.7})
        assert 5.0 <= score <= 7.0

    def test_fitness_4star_at_20_smooth(self):
        """4.0★ gym at 20 min was exactly 6 under old step.
        Smooth: base=6.0 × mult=0.8 = 4.8."""
        score = _score_fitness({"walk_time_min": 20, "rating": 4.0})
        assert 4.0 <= score <= 6.0
