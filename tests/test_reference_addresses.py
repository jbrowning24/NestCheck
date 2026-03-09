"""
Reference address regression tests (NES-89+).

Tests that scoring functions produce outputs within the expected_range
defined in tests/fixtures/reference_addresses.json, using synthetic inputs
derived from address notes.

Structure:
  Part 1: Synthetic inputs keyed by "address_id:dimension"
  Part 2: Parametrized dimension-level score tests
  Part 3: Band classification tests (composite score)
  Part 4: Skips are explicit with reasons
"""

import json
import math
from pathlib import Path

import pytest

from scoring_config import (
    SCORING_MODEL,
    apply_piecewise,
    apply_quality_multiplier,
)
from property_evaluator import get_score_band

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
# Value is a dict of synthetic parameters, or None if notes lack enough
# detail to construct inputs.
#
# Coffee/grocery inputs: walk_time_min, plus optional ceiling params.
# Fitness inputs: walk_time_min, rating.
# Parks/transit: complex API-dependent — marked None unless notes are very
#   specific.
# ---------------------------------------------------------------------------

SYNTHETIC_INPUTS = {
    # ── ref-001: Brooklyn 7th Ave (Park Slope) ──────────────────────────
    "ref-001:parks": None,  # requires GreenEscapeEvaluation (complex API object)
    "ref-001:coffee": {"walk_time_min": 5, "rating": 4.5, "reviews": 500},
    "ref-001:grocery": {"walk_time_min": 8, "rating": 4.3, "reviews": 300},
    "ref-001:fitness": {"walk_time_min": 8, "rating": 4.5, "reviews": 200},
    "ref-001:transit": None,  # composite: walk_to_stop + frequency + hub_travel

    # ── ref-002: Astoria Steinway St ────────────────────────────────────
    "ref-002:parks": None,
    "ref-002:coffee": {"walk_time_min": 6, "rating": 4.4, "reviews": 350},
    "ref-002:grocery": {"walk_time_min": 7, "rating": 4.2, "reviews": 250},
    "ref-002:fitness": {"walk_time_min": 10, "rating": 4.3, "reviews": 150},
    "ref-002:transit": None,

    # ── ref-003: Upper East Side 1060 Park Ave ──────────────────────────
    "ref-003:parks": None,
    "ref-003:coffee": {"walk_time_min": 5, "rating": 4.5, "reviews": 400},
    "ref-003:grocery": {"walk_time_min": 7, "rating": 4.4, "reviews": 500},
    "ref-003:fitness": {"walk_time_min": 8, "rating": 4.5, "reviews": 300},
    "ref-003:transit": None,

    # ── ref-004: Hoboken River St ───────────────────────────────────────
    "ref-004:parks": None,
    "ref-004:coffee": {"walk_time_min": 6, "rating": 4.4, "reviews": 300},
    "ref-004:grocery": {"walk_time_min": 8, "rating": 4.2, "reviews": 250},
    "ref-004:fitness": {"walk_time_min": 10, "rating": 4.3, "reviews": 100},
    "ref-004:transit": None,

    # ── ref-005: Tarrytown Main St ──────────────────────────────────────
    "ref-005:parks": None,
    "ref-005:coffee": {"walk_time_min": 10, "rating": 4.3, "reviews": 150},
    "ref-005:grocery": {"walk_time_min": 18, "rating": 4.0, "reviews": 100},
    "ref-005:fitness": {"walk_time_min": 25, "rating": 3.8, "reviews": 30},
    "ref-005:transit": None,

    # ── ref-006: Yonkers S Broadway ─────────────────────────────────────
    "ref-006:parks": None,
    "ref-006:coffee": {"walk_time_min": 15, "rating": 4.0, "reviews": 80},
    "ref-006:grocery": {"walk_time_min": 15, "rating": 3.8, "reviews": 80},
    "ref-006:fitness": {"walk_time_min": 20, "rating": 3.8, "reviews": 20},
    "ref-006:transit": None,

    # ── ref-007: White Plains Mamaroneck Ave ────────────────────────────
    "ref-007:parks": None,
    "ref-007:coffee": {"walk_time_min": 10, "rating": 4.2, "reviews": 120},
    "ref-007:grocery": {"walk_time_min": 12, "rating": 4.1, "reviews": 200},
    "ref-007:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 50},
    "ref-007:transit": None,

    # ── ref-008: Bronx Exterior St (highway-adjacent) ───────────────────
    "ref-008:parks": None,
    "ref-008:coffee": {"walk_time_min": 25, "rating": 3.9, "reviews": 40},
    "ref-008:grocery": {"walk_time_min": 25, "rating": 3.8, "reviews": 50},
    "ref-008:fitness": {"walk_time_min": 25, "rating": 3.7, "reviews": 15},
    "ref-008:transit": None,

    # ── ref-009: Bronx E Tremont (gas station) ──────────────────────────
    "ref-009:parks": None,
    "ref-009:coffee": {"walk_time_min": 20, "rating": 3.9, "reviews": 50},
    "ref-009:grocery": {"walk_time_min": 12, "rating": 4.0, "reviews": 100},
    "ref-009:fitness": {"walk_time_min": 25, "rating": 3.7, "reviews": 15},
    "ref-009:transit": None,

    # ── ref-010: Seattle Capitol Hill 1505 Broadway ─────────────────────
    "ref-010:parks": None,
    "ref-010:coffee": {"walk_time_min": 5, "rating": 4.6, "reviews": 400},
    "ref-010:grocery": {"walk_time_min": 8, "rating": 4.3, "reviews": 300},
    "ref-010:fitness": {"walk_time_min": 10, "rating": 4.3, "reviews": 200},
    "ref-010:transit": None,

    # ── ref-011: Seattle Fremont ────────────────────────────────────────
    "ref-011:parks": None,
    "ref-011:coffee": {"walk_time_min": 7, "rating": 4.4, "reviews": 300},
    "ref-011:grocery": {"walk_time_min": 8, "rating": 4.3, "reviews": 250},
    "ref-011:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 60},
    "ref-011:transit": None,

    # ── ref-012: Seattle Ballard residential fringe ─────────────────────
    "ref-012:parks": None,
    "ref-012:coffee": {"walk_time_min": 13, "rating": 4.3, "reviews": 200},
    "ref-012:grocery": {"walk_time_min": 12, "rating": 4.2, "reviews": 250},
    "ref-012:fitness": {"walk_time_min": 13, "rating": 4.0, "reviews": 50},
    "ref-012:transit": None,

    # ── ref-013: Seattle U-District ─────────────────────────────────────
    "ref-013:parks": None,
    "ref-013:coffee": {"walk_time_min": 5, "rating": 4.3, "reviews": 250},
    "ref-013:grocery": {"walk_time_min": 7, "rating": 4.2, "reviews": 200},
    "ref-013:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 60},
    "ref-013:transit": None,

    # ── ref-014: Renton ─────────────────────────────────────────────────
    "ref-014:parks": None,
    "ref-014:coffee": {"walk_time_min": 20, "rating": 4.0, "reviews": 60},
    "ref-014:grocery": {"walk_time_min": 12, "rating": 4.0, "reviews": 150},
    "ref-014:fitness": {"walk_time_min": 25, "rating": 3.8, "reviews": 30},
    "ref-014:transit": None,

    # ── ref-015: Seattle Beacon Hill ────────────────────────────────────
    "ref-015:parks": None,
    "ref-015:coffee": {"walk_time_min": 12, "rating": 4.2, "reviews": 100},
    "ref-015:grocery": {"walk_time_min": 12, "rating": 4.0, "reviews": 150},
    "ref-015:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 50},
    "ref-015:transit": None,

    # ── ref-016: DC Georgia Ave NW (Petworth) ───────────────────────────
    "ref-016:parks": None,
    "ref-016:coffee": {"walk_time_min": 10, "rating": 4.2, "reviews": 120},
    "ref-016:grocery": {"walk_time_min": 12, "rating": 4.0, "reviews": 150},
    "ref-016:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 50},
    "ref-016:transit": None,

    # ── ref-017: DC Dupont Circle ───────────────────────────────────────
    "ref-017:parks": None,
    "ref-017:coffee": {"walk_time_min": 4, "rating": 4.5, "reviews": 500},
    "ref-017:grocery": {"walk_time_min": 8, "rating": 4.3, "reviews": 400},
    "ref-017:fitness": {"walk_time_min": 8, "rating": 4.5, "reviews": 300},
    "ref-017:transit": None,

    # ── ref-018: Arlington Wilson Blvd ──────────────────────────────────
    "ref-018:parks": None,
    "ref-018:coffee": {"walk_time_min": 5, "rating": 4.4, "reviews": 350},
    "ref-018:grocery": {"walk_time_min": 7, "rating": 4.3, "reviews": 300},
    "ref-018:fitness": {"walk_time_min": 8, "rating": 4.4, "reviews": 200},
    "ref-018:transit": None,

    # ── ref-019: DC 14th St NW ──────────────────────────────────────────
    "ref-019:parks": None,
    "ref-019:coffee": {"walk_time_min": 5, "rating": 4.5, "reviews": 400},
    "ref-019:grocery": {"walk_time_min": 7, "rating": 4.3, "reviews": 350},
    "ref-019:fitness": {"walk_time_min": 10, "rating": 4.3, "reviews": 150},
    "ref-019:transit": None,

    # ── ref-020: Tysons VA ──────────────────────────────────────────────
    "ref-020:parks": None,
    "ref-020:coffee": {"walk_time_min": 35, "rating": 4.0, "reviews": 100},
    "ref-020:grocery": {"walk_time_min": 30, "rating": 4.0, "reviews": 200},
    "ref-020:fitness": {"walk_time_min": 25, "rating": 4.0, "reviews": 50},
    "ref-020:transit": None,

    # ── ref-021: DC Georgia Ave NW (upper) ──────────────────────────────
    "ref-021:parks": None,
    "ref-021:coffee": {"walk_time_min": 18, "rating": 4.0, "reviews": 60},
    "ref-021:grocery": {"walk_time_min": 12, "rating": 4.0, "reviews": 100},
    "ref-021:fitness": {"walk_time_min": 25, "rating": 3.7, "reviews": 15},
    "ref-021:transit": None,

    # ── ref-022: Plano TX ───────────────────────────────────────────────
    "ref-022:parks": None,
    "ref-022:coffee": {"walk_time_min": 45, "rating": 4.0, "reviews": 100},
    "ref-022:grocery": {"walk_time_min": 45, "rating": 4.0, "reviews": 200},
    "ref-022:fitness": {"walk_time_min": 40, "rating": 4.0, "reviews": 50},
    "ref-022:transit": None,

    # ── ref-023: Santa Monica ───────────────────────────────────────────
    "ref-023:parks": None,
    "ref-023:coffee": {"walk_time_min": 5, "rating": 4.5, "reviews": 400},
    "ref-023:grocery": {"walk_time_min": 8, "rating": 4.3, "reviews": 300},
    "ref-023:fitness": {"walk_time_min": 8, "rating": 4.5, "reviews": 250},
    "ref-023:transit": None,

    # ── ref-024: Glendale CA ────────────────────────────────────────────
    "ref-024:parks": None,
    "ref-024:coffee": {"walk_time_min": 12, "rating": 4.2, "reviews": 120},
    "ref-024:grocery": {"walk_time_min": 12, "rating": 4.1, "reviews": 150},
    "ref-024:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 50},
    "ref-024:transit": None,

    # ── ref-025: Austin Mueller ─────────────────────────────────────────
    "ref-025:parks": None,
    "ref-025:coffee": {"walk_time_min": 12, "rating": 4.3, "reviews": 150},
    "ref-025:grocery": {"walk_time_min": 10, "rating": 4.2, "reviews": 200},
    "ref-025:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 50},
    "ref-025:transit": None,

    # ── ref-026: Mesa AZ ────────────────────────────────────────────────
    "ref-026:parks": None,
    "ref-026:coffee": {"walk_time_min": 45, "rating": 3.8, "reviews": 50},
    "ref-026:grocery": {"walk_time_min": 45, "rating": 3.8, "reviews": 100},
    "ref-026:fitness": {"walk_time_min": 40, "rating": 3.8, "reviews": 30},
    "ref-026:transit": None,

    # ── ref-027: Portland Alberta St ────────────────────────────────────
    "ref-027:parks": None,
    "ref-027:coffee": {"walk_time_min": 5, "rating": 4.5, "reviews": 350},
    "ref-027:grocery": {"walk_time_min": 10, "rating": 4.2, "reviews": 200},
    "ref-027:fitness": {"walk_time_min": 15, "rating": 4.0, "reviews": 60},
    "ref-027:transit": None,

    # ── ref-028: Denver E Colfax ────────────────────────────────────────
    "ref-028:parks": None,
    "ref-028:coffee": {"walk_time_min": 25, "rating": 3.9, "reviews": 40},
    "ref-028:grocery": {"walk_time_min": 20, "rating": 3.8, "reviews": 60},
    "ref-028:fitness": {"walk_time_min": 25, "rating": 3.7, "reviews": 15},
    "ref-028:transit": None,

    # ── ref-029: Miami Brickell ─────────────────────────────────────────
    "ref-029:parks": None,
    "ref-029:coffee": {"walk_time_min": 5, "rating": 4.4, "reviews": 350},
    "ref-029:grocery": {"walk_time_min": 7, "rating": 4.3, "reviews": 300},
    "ref-029:fitness": {"walk_time_min": 8, "rating": 4.5, "reviews": 250},
    "ref-029:transit": None,

    # ── ref-030: Houston Galleria ───────────────────────────────────────
    "ref-030:parks": None,
    "ref-030:coffee": {"walk_time_min": 30, "rating": 4.0, "reviews": 100},
    "ref-030:grocery": {"walk_time_min": 25, "rating": 4.0, "reviews": 150},
    "ref-030:fitness": {"walk_time_min": 25, "rating": 4.0, "reviews": 80},
    "ref-030:transit": None,
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
    return apply_piecewise(SCORING_MODEL.coffee.knots, inputs["walk_time_min"])


def _score_grocery(inputs: dict) -> float:
    """Compute raw grocery score from walk_time_min via piecewise curve."""
    return apply_piecewise(SCORING_MODEL.grocery.knots, inputs["walk_time_min"])


def _score_fitness(inputs: dict) -> float:
    """Compute fitness score = distance_curve(walk_time) * quality_multiplier(rating)."""
    base = apply_piecewise(SCORING_MODEL.fitness.knots, inputs["walk_time_min"])
    mult = apply_quality_multiplier(
        SCORING_MODEL.fitness.quality_multipliers, inputs["rating"],
    )
    return round(base * mult, 1)


_DIMENSION_SCORERS = {
    "coffee": _score_coffee,
    "grocery": _score_grocery,
    "fitness": _score_fitness,
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
    # Skip if no synthetic inputs
    if inputs is None:
        pytest.skip(f"No synthetic inputs for {addr_id}:{dimension}")

    # Skip if no scorer for this dimension
    scorer = _DIMENSION_SCORERS.get(dimension)
    if scorer is None:
        pytest.skip(
            f"Dimension '{dimension}' requires full API context "
            f"(parks=GreenEscapeEvaluation, transit=TransitAccessResult)"
        )

    score = scorer(inputs)

    assert expected_lo <= score <= expected_hi, (
        f"{addr_label}:{dimension} — score {score:.1f} outside "
        f"expected [{expected_lo}, {expected_hi}]"
    )


# ---------------------------------------------------------------------------
# Part 3: Band classification tests
#
# Composite scoring requires ALL 6 dimension scores — parks and transit
# cannot be computed from synthetic inputs (they need GreenEscapeEvaluation
# and TransitAccessResult objects from live API calls).
#
# We SKIP band tests with an explicit reason rather than fabricating
# park/transit scores that could mask real issues.
# ---------------------------------------------------------------------------

def _build_band_test_cases():
    """Yield (addr_id, expected_band) for addresses with expected_band."""
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
    """Assert that composite score lands in the expected band.

    Skipped because composite requires parks + transit scores which
    need live API objects (GreenEscapeEvaluation, TransitAccessResult).
    """
    pytest.skip(
        "Composite band requires all 6 dimensions including parks "
        "(GreenEscapeEvaluation) and transit (TransitAccessResult) — "
        "cannot compute from synthetic scalar inputs"
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
