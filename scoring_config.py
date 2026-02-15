"""
Scoring model configuration for NestCheck.

Owns every numeric constant that affects the livability score.
Search parameters, presentation thresholds, and transit constants
remain in property_evaluator.py.

Frozen dataclasses provide type checking and IDE support without
the indirection of YAML/JSON config files.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional


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
    gas_station_ft: int = 500
    highway_ft: int = 500
    high_volume_road_ft: int = 500


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
    version="1.2.0",

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
        gas_station_ft=500,
        highway_ft=500,
        high_volume_road_ft=500,
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
