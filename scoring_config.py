"""
Scoring model configuration for NestCheck.

Owns every numeric constant that affects the livability score.
Search parameters, presentation thresholds, and transit constants
remain in property_evaluator.py.

Frozen dataclasses provide type checking and IDE support without
the indirection of YAML/JSON config files.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass(frozen=True)
class PiecewiseKnot:
    """A single (x, y) breakpoint on a piecewise linear curve."""
    x: float  # input value (e.g. walk time in minutes)
    y: float  # output value (e.g. score 0-10)


@dataclass(frozen=True)
class QualityMultiplier:
    """Maps a minimum rating threshold to a score multiplier.

    Multipliers are evaluated highest-first: the first entry whose
    min_rating <= the place's rating is used.
    """
    min_rating: float
    multiplier: float


@dataclass(frozen=True)
class DimensionConfig:
    """Scoring curve and parameters for one Tier 2 dimension."""
    knots: Tuple[PiecewiseKnot, ...]
    floor: float = 0.0  # minimum score returned (after curve + multiplier)
    quality_multipliers: Tuple[QualityMultiplier, ...] = ()


@dataclass(frozen=True)
class Tier1Thresholds:
    """Minimum safe distances for Tier 1 health/safety checks (feet)."""
    gas_station_fail_ft: int = 300   # hard fail — within CA 300 ft setback
    gas_station_warn_ft: int = 500   # warning  — within MD 500 ft setback


@dataclass(frozen=True)
class Tier3Bonuses:
    """Bonus point values for Tier 3 lifestyle features."""
    parking: int = 5
    outdoor: int = 5
    bedroom: int = 5
    bedroom_threshold: int = 3  # bedrooms >= this to earn bonus
    max_total: int = 15


@dataclass(frozen=True)
class ScoreBand:
    """Maps a minimum score threshold to a human-readable band label."""
    threshold: int
    label: str
    css_class: str = ""


@dataclass
class DimensionResult:
    """Rich return type for a Tier 2 scoring dimension.

    Backwards-compatible with Tier2Score via .score/.max_score/.name/.details.
    Tier2Score is NOT deleted — transit still uses it.
    """
    score: float              # 0-10
    max_score: float          # 10.0
    name: str
    details: str              # human-readable summary (backwards-compat with Tier2Score)
    scoring_inputs: dict      # e.g. {"walk_time_min": 18, "rating": 4.3}
    subscores: Optional[dict] = None  # e.g. {"proximity": 7.2, "quality": 0.8} for fitness
    model_version: str = ""
    # Data confidence indicator (NES-189).  "HIGH" / "MEDIUM" / "LOW" with note.
    data_confidence: Optional[str] = None
    data_confidence_note: Optional[str] = None

    # Aliases so consumers that read Tier2Score attributes still work.
    # Uses floor(x + 0.5) instead of Python's round() to avoid banker's
    # rounding (round-half-to-even), which produces unintuitive results
    # at .5 boundaries (e.g. round(6.5) -> 6, round(7.5) -> 8).
    @property
    def points(self) -> int:
        """Tier2Score compatibility: .points -> rounded score."""
        return int(self.score + 0.5)

    @property
    def max_points(self) -> int:
        """Tier2Score compatibility: .max_points -> rounded max_score."""
        return int(self.max_score + 0.5)


@dataclass(frozen=True)
class PersonaPreset:
    """A persona preset with dimension weights for Tier 2 scoring.

    Weights are multipliers applied during aggregation — higher weight means
    the dimension contributes proportionally more to the final 0-100 score.
    All persona weight dicts must have exactly 6 keys summing to 6.0 so the
    maximum possible raw weighted score stays at 60 (same as 6 × 10).
    """
    key: str                   # URL-safe identifier, e.g. "balanced"
    label: str                 # Human-readable, e.g. "Balanced"
    description: str           # Short tagline for UI
    weights: Dict[str, float]  # dimension_name -> weight multiplier


@dataclass(frozen=True)
class ScoringModel:
    """Top-level container for all scoring parameters.

    A single module-level instance (SCORING_MODEL) is the source of truth.
    Bump `version` on every change that alters score outputs.
    """
    version: str
    coffee: DimensionConfig
    grocery: DimensionConfig
    fitness: DimensionConfig
    road_noise: DimensionConfig
    tier1: Tier1Thresholds
    tier3: Tier3Bonuses
    score_bands: Tuple[ScoreBand, ...]


# =============================================================================
# Pure scoring functions
# =============================================================================

def apply_piecewise(knots: Tuple[PiecewiseKnot, ...], x: float) -> float:
    """Evaluate a piecewise linear curve at *x*.

    Linearly interpolates between adjacent knots.  Values outside the
    knot range are clamped to the first / last y value.

    Requires at least one knot.
    """
    if not knots:
        raise ValueError("knots must not be empty")

    # Before first knot — clamp
    if x <= knots[0].x:
        return knots[0].y

    # After last knot — clamp
    if x >= knots[-1].x:
        return knots[-1].y

    # Walk the knots to find the surrounding pair
    for i in range(1, len(knots)):
        if x <= knots[i].x:
            k0 = knots[i - 1]
            k1 = knots[i]
            # Avoid division by zero for duplicate x values
            dx = k1.x - k0.x
            if dx == 0:
                return k1.y
            t = (x - k0.x) / dx
            return k0.y + t * (k1.y - k0.y)

    # Shouldn't reach here, but clamp to last value for safety
    return knots[-1].y


def apply_quality_multiplier(
    multipliers: Tuple[QualityMultiplier, ...],
    rating: float,
) -> float:
    """Return the multiplier for a given place rating.

    Multipliers are assumed sorted highest min_rating first.
    Returns the multiplier of the first entry whose min_rating <= rating.
    If no entry matches, returns 0.0.
    """
    for m in multipliers:
        if rating >= m.min_rating:
            return m.multiplier
    return 0.0


# =============================================================================
# SCORING_MODEL — current production values
# =============================================================================

# Phase 1b smooth piecewise linear curves.
# Replaces the Phase 1a step-function knots with gradual slopes so that
# a 1-minute change in walk time produces a proportional score change
# rather than an abrupt cliff.

_COFFEE_KNOTS = (
    PiecewiseKnot(0, 10),
    PiecewiseKnot(10, 10),
    PiecewiseKnot(15, 8),
    PiecewiseKnot(20, 6),
    PiecewiseKnot(30, 4),
    PiecewiseKnot(45, 2),
    PiecewiseKnot(60, 2),
)

_GROCERY_KNOTS = (
    PiecewiseKnot(0, 10),
    PiecewiseKnot(10, 10),
    PiecewiseKnot(15, 8),
    PiecewiseKnot(20, 6),
    PiecewiseKnot(30, 4),
    PiecewiseKnot(45, 2),
    PiecewiseKnot(60, 2),
)

# Fitness: distance_curve(walk_time) × quality_multiplier(rating).
# Proximity dominates; quality modifies.  All gyms are scored regardless
# of rating — quality_multipliers handle differentiation post-search.
_FITNESS_KNOTS = (
    PiecewiseKnot(0, 10),
    PiecewiseKnot(10, 10),
    PiecewiseKnot(20, 6),
    PiecewiseKnot(30, 3),
    PiecewiseKnot(45, 1),
    PiecewiseKnot(60, 1),
)

_FITNESS_QUALITY_MULTIPLIERS = (
    QualityMultiplier(min_rating=4.5, multiplier=1.0),
    QualityMultiplier(min_rating=4.2, multiplier=1.0),
    QualityMultiplier(min_rating=4.0, multiplier=0.8),
    QualityMultiplier(min_rating=3.5, multiplier=0.6),
    QualityMultiplier(min_rating=0.0, multiplier=0.3),
)

# Road noise: subtractive — higher dBA → lower score.
# Knots calibrated to FHWA/WHO thresholds:
#   40 dBA  = quiet residential, perfect score
#   55 dBA  = WHO nighttime guideline for residential areas
#   65 dBA  = FHWA Noise Abatement Criteria (Category B, residential)
#   75 dBA  = EPA prolonged-exposure concern threshold
#   85 dBA  = near-highway, zero score
_ROAD_NOISE_KNOTS = (
    PiecewiseKnot(x=40, y=10),
    PiecewiseKnot(x=55, y=8),
    PiecewiseKnot(x=65, y=5),
    PiecewiseKnot(x=75, y=2),
    PiecewiseKnot(x=85, y=0),
)


SCORING_MODEL = ScoringModel(
    version="1.4.0",

    coffee=DimensionConfig(
        knots=_COFFEE_KNOTS,
        floor=2.0,
    ),

    grocery=DimensionConfig(
        knots=_GROCERY_KNOTS,
        floor=2.0,
    ),

    fitness=DimensionConfig(
        knots=_FITNESS_KNOTS,
        floor=0.0,
        quality_multipliers=_FITNESS_QUALITY_MULTIPLIERS,
    ),

    road_noise=DimensionConfig(
        knots=_ROAD_NOISE_KNOTS,
        floor=0.0,
    ),

    tier1=Tier1Thresholds(
        gas_station_fail_ft=300,
        gas_station_warn_ft=500,
    ),

    tier3=Tier3Bonuses(
        parking=5,
        outdoor=5,
        bedroom=5,
        bedroom_threshold=3,
        max_total=15,
    ),

    score_bands=(
        ScoreBand(85, "Exceptional Daily Fit", "band-exceptional"),
        ScoreBand(70, "Strong Daily Fit", "band-strong"),
        ScoreBand(55, "Moderate — Some Trade-offs", "band-moderate"),
        ScoreBand(40, "Limited — Car Likely Needed", "band-limited"),
        ScoreBand(0, "Significant Gaps", "band-poor"),
    ),
)


# =============================================================================
# Persona presets — scoring lens weights for Tier 2 aggregation (NES-133)
# =============================================================================

PERSONA_PRESETS = {
    "balanced": PersonaPreset(
        key="balanced",
        label="Balanced",
        description="Equal weight across all dimensions",
        weights={
            "Parks & Green Space": 1.0,
            "Coffee & Social Spots": 1.0,
            "Daily Essentials": 1.0,
            "Fitness & Recreation": 1.0,
            "Road Noise": 1.0,
            "Getting Around": 1.0,
        },
    ),
    "active": PersonaPreset(
        key="active",
        label="Active & Outdoorsy",
        description="Emphasizes parks, trails, and fitness",
        weights={
            "Parks & Green Space": 1.6,
            "Coffee & Social Spots": 0.6,
            "Daily Essentials": 0.8,
            "Fitness & Recreation": 1.6,
            "Road Noise": 0.6,
            "Getting Around": 0.8,
        },
    ),
    "commuter": PersonaPreset(
        key="commuter",
        label="Urban Commuter",
        description="Emphasizes transit and walkable amenities",
        weights={
            "Parks & Green Space": 0.6,
            "Coffee & Social Spots": 1.5,
            "Daily Essentials": 0.9,
            "Fitness & Recreation": 0.7,
            "Road Noise": 0.6,
            "Getting Around": 1.7,
        },
    ),
    "quiet": PersonaPreset(
        key="quiet",
        label="Peace & Quiet",
        description="Emphasizes quiet living and daily essentials",
        weights={
            "Parks & Green Space": 1.2,
            "Coffee & Social Spots": 0.7,
            "Daily Essentials": 1.3,
            "Fitness & Recreation": 0.6,
            "Road Noise": 1.5,
            "Getting Around": 0.7,
        },
    ),
}

DEFAULT_PERSONA = "balanced"

# Maps internal Tier2Score names (as produced by the scoring functions in
# property_evaluator.py) to the user-facing dimension names used as keys
# in PersonaPreset.weights.  Scores whose name is NOT in this mapping
# (e.g. "Cost") get a default weight of 1.0 across all personas.
TIER2_NAME_TO_DIMENSION: Dict[str, str] = {
    "Primary Green Escape": "Parks & Green Space",
    "Third Place": "Coffee & Social Spots",
    "Provisioning": "Daily Essentials",
    "Fitness access": "Fitness & Recreation",
    "Urban access": "Getting Around",
    "Road Noise": "Road Noise",
    # "Cost" has a Tier2Score but no persona weight (budget is universal).
}

# Validate all persona weights at import time (ValueError, not assert,
# so validation is never stripped by python -O).
for _k, _p in PERSONA_PRESETS.items():
    _wsum = sum(_p.weights.values())
    if abs(_wsum - 6.0) >= 0.001:
        raise ValueError(f"Persona {_k!r} weights sum to {_wsum}, expected 6.0")
    if len(_p.weights) != 6:
        raise ValueError(f"Persona {_k!r} has {len(_p.weights)} weights, expected 6")
