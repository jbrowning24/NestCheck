#!/usr/bin/env python3
"""
Generate ground-truth test cases for transit access scoring (Tier 2).

Creates synthetic test cases with controlled transit parameters and
pre-computed expected scores.  Unlike UST/HPMS generators, this does NOT
sample from spatial.db — all cases are hand-crafted to test specific
scoring properties (monotonicity, hub scaling, frequency, drive fallback,
no-transit floor, confidence caps).

No API calls — everything is synthetic.

Usage:
    python scripts/generate_ground_truth_transit.py
    python scripts/generate_ground_truth_transit.py --output data/ground_truth/transit.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Scoring thresholds — canonical values live in property_evaluator.py
# score_transit_access() at approximately line 4682.
# These must stay in sync.
# ---------------------------------------------------------------------------

# Confidence caps — canonical in scoring_config.py lines 404-407
try:
    from scoring_config import (
        CONFIDENCE_VERIFIED,
        CONFIDENCE_ESTIMATED,
        CONFIDENCE_SPARSE,
    )
    _CONSTS_IMPORTED = True
except ImportError:
    CONFIDENCE_VERIFIED = "verified"
    CONFIDENCE_ESTIMATED = "estimated"
    CONFIDENCE_SPARSE = "sparse"
    _CONSTS_IMPORTED = False


# ---------------------------------------------------------------------------
# Scoring logic mirrors (for computing expected scores)
# ---------------------------------------------------------------------------

def _walk_points(walk_time: int) -> int:
    if walk_time <= 10:
        return 4
    if walk_time <= 20:
        return 3
    if walk_time <= 30:
        return 2
    if walk_time <= 45:
        return 1
    return 0


def _drive_points(drive_time) -> int:
    if drive_time is None or drive_time >= 9999:
        return 0
    if drive_time <= 5:
        return 3
    if drive_time <= 10:
        return 2
    if drive_time <= 20:
        return 1
    return 0


def _frequency_points(bucket: str) -> int:
    return {"High": 3, "Medium": 2, "Low": 1, "Very low": 0}.get(bucket, 0)


def _hub_points(travel_time) -> int:
    if travel_time is None or travel_time <= 0:
        return 0
    if travel_time <= 45:
        return 3
    if travel_time <= 75:
        return 2
    if travel_time <= 110:
        return 1
    return 0


def _confidence_cap(confidence: str) -> int:
    return {
        CONFIDENCE_VERIFIED: 10,
        CONFIDENCE_ESTIMATED: 8,
        CONFIDENCE_SPARSE: 6,
    }.get(confidence, 10)


def _compute_expected(
    walk_time=None,
    drive_time=None,
    frequency_bucket="Very low",
    hub_time=None,
    has_primary_transit=True,
    confidence=CONFIDENCE_ESTIMATED,
):
    """Compute the expected final score, mirroring score_transit_access()."""
    if not has_primary_transit:
        return 0

    wp = _walk_points(walk_time)
    dp = _drive_points(drive_time)
    accessibility = max(wp, dp)
    freq = _frequency_points(frequency_bucket)
    hub = _hub_points(hub_time)
    raw = min(10, accessibility + freq + hub)
    return min(raw, _confidence_cap(confidence))


def _classify_confidence(has_walk_time: bool, node_count: int, frequency_bucket=None):
    """Mirror _classify_transit_confidence() from property_evaluator.py.

    The real classifier at line 4224 checks frequency_class against
    (None, "unknown", "Very low frequency", "Very low").  Both the legacy
    PrimaryTransitOption format ("Very low frequency") and the new
    TransitAccessResult format ("Very low") match the sparse gate.
    has_hub is derived from node_count >= 5 (line 4219).
    """
    has_hub = node_count >= 5
    if not has_walk_time and node_count == 0:
        if frequency_bucket in (None, "unknown", "Very low frequency", "Very low") and not has_hub:
            return CONFIDENCE_SPARSE
        return CONFIDENCE_ESTIMATED
    if has_walk_time and node_count >= 10:
        return CONFIDENCE_VERIFIED
    if has_walk_time:
        return CONFIDENCE_ESTIMATED
    return CONFIDENCE_ESTIMATED


# ---------------------------------------------------------------------------
# Test case builders
# ---------------------------------------------------------------------------

def _make_primary_transit(
    name="Test Station",
    mode="Train",
    walk_time_min=15,
    drive_time_min=None,
    user_ratings_total=500,
    frequency_class=None,
):
    return {
        "name": name,
        "mode": mode,
        "lat": 41.0,
        "lng": -73.8,
        "walk_time_min": walk_time_min,
        "drive_time_min": drive_time_min,
        "user_ratings_total": user_ratings_total,
        "frequency_class": frequency_class,
    }


def _make_hub(name="Grand Central Terminal", travel_time_min=60, transit_mode="train"):
    return {
        "name": name,
        "travel_time_min": travel_time_min,
        "transit_mode": transit_mode,
    }


def _make_transit_access(
    frequency_bucket="Medium",
    nearby_node_count=5,
    density_node_count=8,
    walk_minutes=None,
    mode=None,
    primary_stop=None,
):
    return {
        "primary_stop": primary_stop,
        "walk_minutes": walk_minutes,
        "mode": mode,
        "frequency_bucket": frequency_bucket,
        "score_0_10": 0,
        "reasons": [],
        "nearby_node_count": nearby_node_count,
        "density_node_count": density_node_count,
    }


def _build_case(
    case_id,
    category,
    category_label,
    primary_transit=None,
    major_hub=None,
    transit_access=None,
    expected_score=0,
    expected_confidence=CONFIDENCE_ESTIMATED,
    notes="",
):
    has_pt = primary_transit is not None
    return {
        "id": f"gt-transit-{case_id:04d}",
        "coordinates": {"lat": 41.0, "lng": -73.8},
        "layer": 4,
        "layer_notes": f"Synthetic — {category_label}",
        "test_category": category,
        "transit_params": {
            "primary_transit": primary_transit,
            "major_hub": major_hub,
            "transit_access": transit_access,
        },
        "tier1_health_checks": {},
        "tier2_scored_dimensions": {
            "urban_access": {
                "expected_score": expected_score,
                "expected_confidence": expected_confidence,
                "notes": notes,
            },
        },
    }


# ---------------------------------------------------------------------------
# Test case categories
# ---------------------------------------------------------------------------

def _monotonicity_walk_cases():
    """A: Closer transit stops should score higher (6 cases)."""
    cases = []
    walk_times = [5, 10, 15, 20, 30, 50]
    freq = "Medium"
    hub_time = 60
    node_count = 5

    for i, wt in enumerate(walk_times):
        conf = _classify_confidence(True, node_count, freq)
        score = _compute_expected(
            walk_time=wt, frequency_bucket=freq, hub_time=hub_time, confidence=conf,
        )
        cases.append(_build_case(
            case_id=i + 1,
            category="monotonicity_walk",
            category_label=f"Walk time monotonicity: {wt} min walk",
            primary_transit=_make_primary_transit(walk_time_min=wt),
            major_hub=_make_hub(travel_time_min=hub_time),
            transit_access=_make_transit_access(
                frequency_bucket=freq, nearby_node_count=node_count,
            ),
            expected_score=score,
            expected_confidence=conf,
            notes=f"walk={wt}min, freq={freq}, hub={hub_time}min → score={score}",
        ))
    return cases


def _hub_commute_scaling_cases():
    """B: Shorter hub commute should score higher (5 cases)."""
    cases = []
    hub_times = [30, 45, 60, 75, 120]
    walk = 10
    freq = "Medium"
    node_count = 5

    for i, ht in enumerate(hub_times):
        conf = _classify_confidence(True, node_count, freq)
        score = _compute_expected(
            walk_time=walk, frequency_bucket=freq, hub_time=ht, confidence=conf,
        )
        cases.append(_build_case(
            case_id=10 + i + 1,
            category="hub_commute_scaling",
            category_label=f"Hub commute scaling: {ht} min to hub",
            primary_transit=_make_primary_transit(walk_time_min=walk),
            major_hub=_make_hub(travel_time_min=ht),
            transit_access=_make_transit_access(
                frequency_bucket=freq, nearby_node_count=node_count,
            ),
            expected_score=score,
            expected_confidence=conf,
            notes=f"walk={walk}min, freq={freq}, hub={ht}min → score={score}",
        ))
    return cases


def _frequency_cases():
    """C: Higher frequency should score higher (4 cases)."""
    cases = []
    buckets = ["High", "Medium", "Low", "Very low"]
    walk = 15
    hub_time = 50
    node_count = 5

    for i, bucket in enumerate(buckets):
        conf = _classify_confidence(True, node_count, bucket)
        score = _compute_expected(
            walk_time=walk, frequency_bucket=bucket, hub_time=hub_time, confidence=conf,
        )
        cases.append(_build_case(
            case_id=20 + i + 1,
            category="frequency",
            category_label=f"Frequency scaling: {bucket}",
            primary_transit=_make_primary_transit(walk_time_min=walk),
            major_hub=_make_hub(travel_time_min=hub_time),
            transit_access=_make_transit_access(
                frequency_bucket=bucket, nearby_node_count=node_count,
            ),
            expected_score=score,
            expected_confidence=conf,
            notes=f"walk={walk}min, freq={bucket}, hub={hub_time}min → score={score}",
        ))
    return cases


def _drive_fallback_cases():
    """D: Drive fallback provides partial credit (5 cases)."""
    cases = []

    # Case 1: Walk 50min (0pts), drive 5min (3pts) → drive wins
    params = [
        (50, 5, "Medium", 60, "Walk impractical, drive fallback boosts score"),
        (50, 10, "Medium", 60, "Walk impractical, moderate drive fallback"),
        (50, 25, "Medium", 60, "Walk impractical, drive too long to help"),
        (10, 3, "Medium", 60, "Walk excellent (4pts), drive good (3pts) — walk wins"),
        (35, 8, "Medium", 60, "Walk marginal (1pt), drive good (2pts) — drive wins"),
    ]

    for i, (wt, dt, freq, ht, note) in enumerate(params):
        node_count = 5
        conf = _classify_confidence(True, node_count, freq)
        score = _compute_expected(
            walk_time=wt, drive_time=dt, frequency_bucket=freq,
            hub_time=ht, confidence=conf,
        )
        cases.append(_build_case(
            case_id=30 + i + 1,
            category="drive_fallback",
            category_label=f"Drive fallback: walk={wt}min, drive={dt}min",
            primary_transit=_make_primary_transit(
                walk_time_min=wt, drive_time_min=dt,
            ),
            major_hub=_make_hub(travel_time_min=ht),
            transit_access=_make_transit_access(
                frequency_bucket=freq, nearby_node_count=node_count,
            ),
            expected_score=score,
            expected_confidence=conf,
            notes=f"walk={wt}min, drive={dt}min, freq={freq}, hub={ht}min — {note} → score={score}",
        ))
    return cases


def _no_transit_floor_cases():
    """E: No transit available → score=0 (3 cases)."""
    cases = []

    # Case 1: No primary transit, no transit_access data
    cases.append(_build_case(
        case_id=40,
        category="no_transit_floor",
        category_label="No transit: empty urban_access",
        primary_transit=None,
        major_hub=None,
        transit_access=None,
        expected_score=0,
        expected_confidence=CONFIDENCE_SPARSE,
        notes="No primary transit found → floor score 0, sparse confidence",
    ))

    # Case 2: transit_access exists but no stop found
    cases.append(_build_case(
        case_id=41,
        category="no_transit_floor",
        category_label="No transit: transit_access with no stop",
        primary_transit=None,
        major_hub=None,
        transit_access=_make_transit_access(
            frequency_bucket="Very low", nearby_node_count=0,
            density_node_count=0,
        ),
        expected_score=0,
        expected_confidence=CONFIDENCE_SPARSE,
        notes="Transit access computed but no stops found → floor score 0, sparse confidence",
    ))

    # Case 3: Hub available but no primary transit
    cases.append(_build_case(
        case_id=42,
        category="no_transit_floor",
        category_label="No transit: hub exists but no station",
        primary_transit=None,
        major_hub=_make_hub(travel_time_min=45),
        transit_access=None,
        expected_score=0,
        expected_confidence=CONFIDENCE_SPARSE,
        notes="Hub accessible but no transit station → floor score 0, sparse confidence",
    ))

    return cases


def _confidence_cap_cases():
    """F: Confidence caps constrain high scores (5 cases)."""
    cases = []

    # Verified: uncapped (node_count >= 10)
    conf = _classify_confidence(True, 25, "High")
    score = _compute_expected(
        walk_time=5, frequency_bucket="High", hub_time=30, confidence=conf,
    )
    cases.append(_build_case(
        case_id=50,
        category="confidence_cap",
        category_label="Confidence: verified, uncapped",
        primary_transit=_make_primary_transit(walk_time_min=5),
        major_hub=_make_hub(travel_time_min=30),
        transit_access=_make_transit_access(
            frequency_bucket="High", nearby_node_count=25,
        ),
        expected_score=score,
        expected_confidence=conf,
        notes=f"verified (25 nodes), raw=10 → final={score}",
    ))

    # Estimated: capped at 8 (node_count < 10, walk time present)
    conf = _classify_confidence(True, 5, "High")
    raw = min(10, _walk_points(5) + _frequency_points("High") + _hub_points(30))
    score = min(raw, _confidence_cap(conf))
    cases.append(_build_case(
        case_id=51,
        category="confidence_cap",
        category_label="Confidence: estimated, raw 10 capped to 8",
        primary_transit=_make_primary_transit(walk_time_min=5),
        major_hub=_make_hub(travel_time_min=30),
        transit_access=_make_transit_access(
            frequency_bucket="High", nearby_node_count=5,
        ),
        expected_score=score,
        expected_confidence=conf,
        notes=f"estimated (5 nodes), raw=10, cap=8 → final={score}",
    ))

    # Estimated: capped at 8 with raw=10 (walk=10→4pts, different node count)
    conf = _classify_confidence(True, 3, "High")
    raw = min(10, _walk_points(10) + _frequency_points("High") + _hub_points(30))
    score = min(raw, _confidence_cap(conf))
    cases.append(_build_case(
        case_id=52,
        category="confidence_cap",
        category_label="Confidence: estimated, raw 10 capped to 8 (3 nodes)",
        primary_transit=_make_primary_transit(walk_time_min=10),
        major_hub=_make_hub(travel_time_min=30),
        transit_access=_make_transit_access(
            frequency_bucket="High", nearby_node_count=3,
        ),
        expected_score=score,
        expected_confidence=conf,
        notes=f"estimated (3 nodes), raw={raw}, cap=8 → final={score}",
    ))

    # Estimated: score below cap → no effect
    conf = _classify_confidence(True, 1, "Low")
    score = _compute_expected(
        walk_time=15, frequency_bucket="Low", hub_time=90, confidence=conf,
    )
    cases.append(_build_case(
        case_id=53,
        category="confidence_cap",
        category_label="Confidence: estimated, score below cap",
        primary_transit=_make_primary_transit(walk_time_min=15),
        major_hub=_make_hub(travel_time_min=90),
        transit_access=_make_transit_access(
            frequency_bucket="Low", nearby_node_count=1,
        ),
        expected_score=score,
        expected_confidence=conf,
        notes=f"estimated (1 node), raw={score}, below cap=8 → final={score}",
    ))

    # Verified: high score uncapped
    conf = _classify_confidence(True, 15, "Medium")
    score = _compute_expected(
        walk_time=10, frequency_bucket="Medium", hub_time=45, confidence=conf,
    )
    cases.append(_build_case(
        case_id=54,
        category="confidence_cap",
        category_label="Confidence: verified, score 8 uncapped",
        primary_transit=_make_primary_transit(walk_time_min=10),
        major_hub=_make_hub(travel_time_min=45),
        transit_access=_make_transit_access(
            frequency_bucket="Medium", nearby_node_count=15,
        ),
        expected_score=score,
        expected_confidence=conf,
        notes=f"verified (15 nodes), raw={score} → final={score}",
    ))

    return cases


def _cap_at_10_cases():
    """G: Score capped at 10 even when components sum higher (2 cases)."""
    cases = []

    # Exactly 10: 4 + 3 + 3
    node_count = 12
    conf = _classify_confidence(True, node_count, "High")
    score = _compute_expected(
        walk_time=5, frequency_bucket="High", hub_time=30, confidence=conf,
    )
    cases.append(_build_case(
        case_id=60,
        category="cap_at_10",
        category_label="Cap at 10: components sum to exactly 10",
        primary_transit=_make_primary_transit(walk_time_min=5),
        major_hub=_make_hub(travel_time_min=30),
        transit_access=_make_transit_access(
            frequency_bucket="High", nearby_node_count=node_count,
        ),
        expected_score=score,
        expected_confidence=conf,
        notes=f"walk=4 + freq=3 + hub=3 = 10, min(10,10) → {score}",
    ))

    # Just below 10: 3 + 3 + 3 = 9
    conf = _classify_confidence(True, node_count, "High")
    score = _compute_expected(
        walk_time=15, frequency_bucket="High", hub_time=30, confidence=conf,
    )
    cases.append(_build_case(
        case_id=61,
        category="cap_at_10",
        category_label="Cap at 10: components sum to 9",
        primary_transit=_make_primary_transit(walk_time_min=15),
        major_hub=_make_hub(travel_time_min=30),
        transit_access=_make_transit_access(
            frequency_bucket="High", nearby_node_count=node_count,
        ),
        expected_score=score,
        expected_confidence=conf,
        notes=f"walk=3 + freq=3 + hub=3 = 9, min(10,9) → {score}",
    ))

    return cases


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate ground-truth test cases for transit access scoring"
    )
    parser.add_argument(
        "--output", type=str, default="data/ground_truth/transit.json",
        help="Output file path (default: data/ground_truth/transit.json)",
    )
    args = parser.parse_args()

    if _CONSTS_IMPORTED:
        print("Confidence constants imported from scoring_config.py", flush=True)
    else:
        print("Confidence constants hardcoded (scoring_config.py import failed)", flush=True)

    # Build all test cases
    all_cases = []
    all_cases.extend(_monotonicity_walk_cases())
    all_cases.extend(_hub_commute_scaling_cases())
    all_cases.extend(_frequency_cases())
    all_cases.extend(_drive_fallback_cases())
    all_cases.extend(_no_transit_floor_cases())
    all_cases.extend(_confidence_cap_cases())
    all_cases.extend(_cap_at_10_cases())

    output = {
        "_schema_version": "0.1.0",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_generator": "generate_ground_truth_transit.py",
        "_test_count": len(all_cases),
        "_scoring_rules": {
            "walk_points": "<=10→4, <=20→3, <=30→2, <=45→1, >45→0",
            "drive_points": "<=5→3, <=10→2, <=20→1, >20→0 (max 3, so walk≤10 always wins)",
            "frequency_points": "High→3, Medium→2, Low→1, Very low→0",
            "hub_points": "<=45→3, <=75→2, <=110→1, >110→0",
            "total": "min(10, max(walk, drive) + frequency + hub)",
            "confidence_cap": "verified→10, estimated→8, sparse→6",
            "source": "property_evaluator.py score_transit_access()",
        },
        "addresses": all_cases,
    }

    # Resolve output path
    out_path = args.output
    if not os.path.isabs(out_path):
        project_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
        out_path = os.path.join(project_root, out_path)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nGenerated {len(all_cases)} test cases.")
    print(f"Output: {out_path}")

    # Breakdown by category
    by_cat = {}
    for c in all_cases:
        cat = c["test_category"]
        by_cat[cat] = by_cat.get(cat, 0) + 1
    for cat, count in by_cat.items():
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()
