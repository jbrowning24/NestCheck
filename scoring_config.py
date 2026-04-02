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
class QualityCeilingConfig:
    """Parameters for quality-adjusted score ceiling on a dimension.

    The ceiling prevents high scores when venue options are low-diversity
    (all one category) or low-signal (few reviews).

    Formula: max_score = base_ceiling + diversity_bonus + social_bucket_bonus
             + depth_bonus, capped at 10.

    Two diversity signals:
      - Sub-type diversity: distinct Google Places sub-types (bakery/cafe/coffee_shop).
      - Social bucket diversity: broader social categories via _SOCIAL_BUCKET_MAP
        (coffee/bakery/bar/restaurant/other).
    """
    base_ceiling: float = 4.0       # starting ceiling before bonuses
    # Sub-type diversity: distinct _classify_coffee_sub_type categories.
    # Returns at most 3 types (bakery/cafe/coffee_shop),
    # so thresholds above 3 are unreachable with the current classifier.
    diversity_thresholds: Tuple[Tuple[int, float], ...] = (
        # (min_distinct_categories, bonus_points)
        (3, 2.0),   # 3 sub-types  → +2.0
        (2, 1.0),   # 2 sub-types  → +1.0
        # 1 sub-type  → +0.0 (no bonus)
    )
    # Social bucket diversity: distinct social-category buckets via _SOCIAL_BUCKET_MAP.
    # Up to 5 buckets (coffee/bakery/bar/restaurant/other).
    social_bucket_thresholds: Tuple[Tuple[int, float], ...] = (
        # (min_distinct_buckets, bonus_points)
        (4, 3.0),   # 4+ buckets → +3.0  (full social scene)
        (3, 2.0),   # 3 buckets  → +2.0  (good variety)
        (2, 1.0),   # 2 buckets  → +1.0  (decent variety)
        # 1 bucket   → +0.0 (no bonus)
    )
    # Review depth: median user_ratings_total across eligible venues
    depth_thresholds: Tuple[Tuple[int, float], ...] = (
        # (min_median_reviews, bonus_points)
        (200, 1.5),  # median 200+ → +1.5
        (100, 1.0),  # median 100+ → +1.0
        (50, 0.5),   # median 50+  → +0.5
        # median <50  → +0.0 (no bonus)
    )


@dataclass(frozen=True)
class DimensionConfig:
    """Scoring curve and parameters for one Tier 2 dimension."""
    knots: Tuple[PiecewiseKnot, ...]
    floor: float = 0.0  # minimum score returned (after curve + multiplier)
    quality_multipliers: Tuple[QualityMultiplier, ...] = ()
    quality_ceiling: Optional[QualityCeilingConfig] = None


@dataclass(frozen=True)
class Tier1Thresholds:
    """Thresholds for Tier 1 health/safety checks.

    Distance units are feet (suffix _ft) or meters (suffix _m).
    All proximity checks in property_evaluator.py should import from here.
    """
    # ── Gas station (Overpass) ───────────────────────────────────
    gas_station_fail_ft: int = 300   # hard fail — CA 300 ft setback
    gas_station_warn_ft: int = 500   # warning  — MD 500 ft setback

    # ── Highway / high-volume road (Overpass) ────────────────────
    highway_min_distance_ft: int = 500
    high_volume_road_min_distance_ft: int = 500

    # ── Environmental infrastructure (Overpass) ──────────────────
    power_line_warning_ft: int = 200
    substation_warning_ft: int = 300
    cell_tower_warning_ft: int = 500
    industrial_zone_warning_ft: int = 500

    # ── TRI facility (Overpass legacy check) ─────────────────────
    tri_facility_warning_ft: int = 5280  # 1 mile

    # ── UST proximity (Phase 1B — SpatiaLite) ────────────────────
    ust_fail_m: int = 90               # ~300 ft — CA setback
    ust_warn_m: int = 150              # ~500 ft — MD setback

    # ── TRI proximity (Phase 1B — SpatiaLite) ────────────────────
    tri_proximity_warn_m: int = 1600   # ~1 mile

    # ── HIFLD power lines (Phase 1B — SpatiaLite) ────────────────
    hifld_power_line_warn_m: int = 60  # ~200 ft

    # ── Rail corridor (Phase 1B — SpatiaLite / FRA) ──────────────
    rail_warn_m: int = 300             # ~1,000 ft

    # ── High-traffic road / HPMS (Phase 1B — SpatiaLite) ─────────
    high_traffic_aadt_threshold: int = 50_000   # vehicles/day
    high_traffic_fail_m: int = 150              # elevated-risk zone
    high_traffic_warn_m: int = 300              # diminishing-risk zone


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
    # Confidence tier (Phase 3).  Values: "verified" / "estimated" / "sparse" / "not_scored".
    # Legacy snapshots may contain "HIGH"/"MEDIUM"/"LOW" — migrated at display.
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

# Car-friendly mode: drive time in minutes → score.
# ≤5 min neighborhood-adjacent, 10 min comfortable errand, 15 min a trip,
# 20 min inconvenient, 25+ effectively inaccessible for routine use.
_COFFEE_DRIVE_KNOTS = (
    PiecewiseKnot(0, 6),
    PiecewiseKnot(5, 6),
    PiecewiseKnot(10, 5),
    PiecewiseKnot(15, 3),
    PiecewiseKnot(20, 1),
    PiecewiseKnot(25, 0),
    PiecewiseKnot(30, 0),
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

# Car-friendly mode: drive time in minutes → score.
# Same breakpoints as coffee — driving normalizes the experience.
_GROCERY_DRIVE_KNOTS = (
    PiecewiseKnot(0, 6),
    PiecewiseKnot(5, 6),
    PiecewiseKnot(10, 5),
    PiecewiseKnot(15, 3),
    PiecewiseKnot(20, 1),
    PiecewiseKnot(25, 0),
    PiecewiseKnot(30, 0),
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

# Policy: no dimension score exceeds this when best option requires driving.
# Universal safety net — currently fires only for fitness (the only wired
# drive fallback), but protects against future drift if other dimensions
# get drive wiring.  See NES-315.
DRIVE_ONLY_CEILING = 6

# Car-friendly mode: drive time in minutes → score.
# Ceiling is 6 (not 10) — driving is inherently higher-friction than walking.
# A 0-5 min drive is "good but not walkable-good".  See NES-315.
_FITNESS_DRIVE_KNOTS = (
    PiecewiseKnot(0, 6),
    PiecewiseKnot(5, 6),
    PiecewiseKnot(10, 5),
    PiecewiseKnot(15, 3),
    PiecewiseKnot(20, 1),
    PiecewiseKnot(25, 0),
    PiecewiseKnot(30, 0),
)

# ---------------------------------------------------------------------------
# Canopy cover → nature-feel subscore (0–2)
# Replaces keyword-based _score_nature_feel when NLCD data is available.
# ---------------------------------------------------------------------------

CANOPY_NATURE_FEEL_KNOTS = (
    PiecewiseKnot(5, 0.0),     # < 5% = barren/paved
    PiecewiseKnot(15, 0.5),    # sparse canopy
    PiecewiseKnot(25, 1.0),    # moderate urban canopy
    PiecewiseKnot(40, 1.5),    # well-treed neighborhood
    PiecewiseKnot(55, 2.0),    # heavily treed — subscore max
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
    version="1.10.0",

    coffee=DimensionConfig(
        knots=_COFFEE_KNOTS,
        floor=2.0,
        quality_ceiling=QualityCeilingConfig(),
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

    tier1=Tier1Thresholds(),

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


# Maps internal Tier2Score names (as produced by the scoring functions in
# property_evaluator.py) to user-facing dimension display names.
# Used by the compare route for consistent dimension ordering.
TIER2_NAME_TO_DIMENSION: Dict[str, str] = {
    "Primary Green Escape": "Parks & Green Space",
    "Third Place": "Coffee & Social Spots",  # backward compat for old snapshots
    "Provisioning": "Daily Essentials",
    "Fitness access": "Fitness & Recreation",
    "Urban access": "Getting Around",
    "Road Noise": "Road Noise",
}

# Total number of Tier 2 dimensions used in composite scoring.
# Referenced by the "Score based on N of M dimensions" annotation (NES-394).
# Update when adding or removing a scoring dimension.
TIER2_DIMENSION_COUNT: int = len(TIER2_NAME_TO_DIMENSION)


# =============================================================================
# Walk / drive time display thresholds (minutes)
# =============================================================================
# Controls when the report shows walk time, both, or drive time only.
#   walk_time <= BOTH          : walk only
#   BOTH < walk_time <= LEAD   : walk first, then drive
#   LEAD < walk_time <= ONLY   : drive first, then walk
#   walk_time > ONLY           : drive only
WALK_DRIVE_BOTH_THRESHOLD = 20
WALK_DRIVE_LEAD_DRIVE_THRESHOLD = 25
WALK_DRIVE_ONLY_THRESHOLD = 40


# =============================================================================
# Confidence tiers — unified three-tier system (Phase 3)
# =============================================================================
# Replaces the ad-hoc HIGH/MEDIUM/LOW system with semantically clear tiers.
# Old values are kept as aliases for backward compatibility with stored snapshots.

CONFIDENCE_VERIFIED = "verified"      # Multiple data sources, well-supported score
CONFIDENCE_ESTIMATED = "estimated"    # Partial data, reasonable inference
CONFIDENCE_SPARSE = "sparse"          # Data exists but too thin for trustworthy score
CONFIDENCE_NOT_SCORED = "not_scored"  # Insufficient data, suppress numeric score

# Maps old tier names to new ones for snapshot migration
_LEGACY_CONFIDENCE_MAP = {
    "HIGH": CONFIDENCE_VERIFIED,
    "MEDIUM": CONFIDENCE_ESTIMATED,
    "LOW": CONFIDENCE_SPARSE,  # LOW with a numeric score → sparse (thin data)
    # "LOW" with points=0 and not_scored semantics is handled explicitly
    # during migration by checking if the score was a "benefit of the doubt" fallback
}


# =============================================================================
# Venue eligibility thresholds — minimum reviews & rating for headline venues
# =============================================================================
# A venue below these thresholds is excluded from headline selection and
# dimension scoring.  Raw venue lists are still returned for display so users
# can see what exists nearby, even when we decline to score it.

VENUE_MIN_REVIEWS: Dict[str, int] = {
    "coffee_social": 15,    # lowered from 30 for suburban coverage (NES-251)
    "provisioning": 20,     # existing hardcoded value
    "fitness": 10,          # NEW — was 0 (no filter)
}

VENUE_MIN_RATING: Dict[str, float] = {
    "coffee_social": 4.0,   # existing hardcoded value
    "provisioning": 3.5,    # existing hardcoded value
    "fitness": 3.5,         # NEW — reasonable floor
}


# =============================================================================
# Health check citations — hyperlinked sources for "Why we check this"
# =============================================================================

HEALTH_CHECK_CITATIONS: Dict[str, list] = {
    # ── Gas Station ──────────────────────────────────────────────
    "Gas station": [
        {
            "label": "Hilpert et al. 2019",
            "url": "https://doi.org/10.1016/j.scitotenv.2019.05.316",
        },
        {
            "label": "IARC Monograph 100F (Benzene)",
            "url": "https://publications.iarc.fr/123",
        },
        {
            "label": "California OEHHA Air Toxics Program",
            "url": "https://oehha.ca.gov/air/air-toxics-program",
        },
    ],
    # ── Highway ──────────────────────────────────────────────────
    "Highway": [
        {
            "label": "HEI Panel on Traffic-Related Air Pollution, 2010",
            "url": "https://www.healtheffects.org/publication/traffic-related-air-pollution-critical-review-literature-emissions-exposure-and-health",
        },
        {
            "label": "CDC — Residential Proximity to Major Highways",
            "url": "https://www.cdc.gov/mmwr/preview/mmwrhtml/su6203a8.htm",
        },
    ],
    # ── High-volume road ─────────────────────────────────────────
    "High-volume road": [
        {
            "label": "HEI Panel on Traffic-Related Air Pollution, 2010",
            "url": "https://www.healtheffects.org/publication/traffic-related-air-pollution-critical-review-literature-emissions-exposure-and-health",
        },
    ],
    # ── High-traffic road (HPMS AADT) ────────────────────────────
    "High-traffic road": [
        {
            "label": "HEI Panel on Traffic-Related Air Pollution, 2010",
            "url": "https://www.healtheffects.org/publication/traffic-related-air-pollution-critical-review-literature-emissions-exposure-and-health",
        },
        {
            "label": "FHWA Highway Performance Monitoring System",
            "url": "https://www.fhwa.dot.gov/policyinformation/hpms.cfm",
        },
    ],
    # ── Power lines ──────────────────────────────────────────────
    "Power lines": [
        {
            "label": "IARC Monograph Vol. 80 (ELF-EMF), 2002",
            "url": "https://publications.iarc.fr/88",
        },
    ],
    # ── Electrical substation ────────────────────────────────────
    "Electrical substation": [
        {
            "label": "IARC Monograph Vol. 80 (ELF-EMF), 2002",
            "url": "https://publications.iarc.fr/88",
        },
    ],
    # ── Cell tower ───────────────────────────────────────────────
    "Cell tower": [
        {
            "label": "IARC Press Release No. 208 (RF-EMF), 2011",
            "url": "https://www.iarc.who.int/wp-content/uploads/2018/07/pr208_E.pdf",
        },
    ],
    # ── Industrial zone ──────────────────────────────────────────
    "Industrial zone": [],
    # ── Superfund (NPL) ──────────────────────────────────────────
    "Superfund (NPL)": [
        {
            "label": "EPA Superfund National Priorities List",
            "url": "https://www.epa.gov/superfund/superfund-national-priorities-list-npl",
        },
    ],
    # ── TRI Facility ─────────────────────────────────────────────
    "TRI facility": [
        {
            "label": "EPA Toxics Release Inventory",
            "url": "https://www.epa.gov/toxics-release-inventory-tri-program",
        },
    ],
    # ── Underground Storage Tanks (Phase 1B) ─────────────────────
    "ust_proximity": [
        {
            "label": "Hilpert et al. 2019",
            "url": "https://doi.org/10.1016/j.scitotenv.2019.05.316",
        },
    ],
    # ── Toxic Release Facilities (Phase 1B) ──────────────────────
    "tri_proximity": [
        {
            "label": "EPA Toxics Release Inventory",
            "url": "https://www.epa.gov/toxics-release-inventory-tri-program",
        },
    ],
    # ── High-Voltage Power Lines / HIFLD (Phase 1B) ──────────────
    "hifld_power_lines": [
        {
            "label": "IARC Monograph Vol. 80 (ELF-EMF), 2002",
            "url": "https://publications.iarc.fr/88",
        },
        {
            "label": "HIFLD Electric Power Transmission Lines",
            "url": "https://hifld-geoplatform.opendata.arcgis.com/datasets/electric-power-transmission-lines",
        },
    ],
    # ── Rail Corridor (Phase 1B) ─────────────────────────────────
    "rail_proximity": [
        {
            "label": "FRA Safety Data & Reporting",
            "url": "https://cms8.fra.dot.gov/safety-data",
        },
    ],
}


