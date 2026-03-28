#!/usr/bin/env python3
"""
Generate ground-truth test cases for parks & green space scoring (Tier 2).

Parks scoring uses a 4-component additive model (not piecewise curves):
  - Walk Time (0-3):       step function with linear interpolation
  - Size & Loop (0-3):     ParkServe/OSM enriched OR reviews/name fallback
  - Quality (0-2):         rating component + review volume component
  - Nature Feel (0-2):     OSM tags + name keywords + type bonuses

Total = sum of subscores, capped at 10.0.  No quality ceiling, no confidence
cap, no floor, no rounding to int.

Test types:
  - walk_time:          boundary + interpolation for _score_walk_time
  - size_enriched:      ParkServe/OSM size + path scoring
  - size_fallback:      reviews/name proxy scoring
  - quality:            rating + review count scoring
  - nature_feel:        OSM tags, name keywords, type bonuses
  - composite:          end-to-end compute_park_score tests
  - composite_cap:      verify cap at 10.0
  - monotonicity:       walk time monotonicity (closer = higher)
  - criteria:           PASS/BORDERLINE/FAIL classification

Usage:
    python scripts/generate_ground_truth_parks.py
    python scripts/generate_ground_truth_parks.py --seed 42
    python scripts/generate_ground_truth_parks.py --output data/ground_truth/parks.json
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone

# Project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from green_space import (
        WALK_TIME_EXCELLENT,
        WALK_TIME_GOOD,
        WALK_TIME_MARGINAL,
        SIZE_LARGE_SQM,
        SIZE_MEDIUM_SQM,
        SIZE_SMALL_SQM,
        PATH_NETWORK_DENSE,
        PATH_NETWORK_MODERATE,
        QUALITY_HIGH_RATING,
        QUALITY_MID_RATING,
        QUALITY_HIGH_REVIEWS,
        QUALITY_MID_REVIEWS,
        QUALITY_MIN_REVIEWS_RELIABLE,
        DAILY_PARK_MIN_WALK_SCORE,
        DAILY_PARK_MIN_SIZE_SCORE,
        DAILY_PARK_MIN_TOTAL,
        _score_walk_time,
        _score_size_loop,
        _score_quality,
        _score_nature_feel,
        _evaluate_criteria,
        compute_park_score,
    )
    _IMPORTS_OK = True
except Exception as e:
    print(f"WARNING: Could not import from green_space: {e}")
    print("Falling back to hardcoded constants.")
    _IMPORTS_OK = False

    # Hardcoded fallback (must stay in sync with green_space.py)
    WALK_TIME_EXCELLENT = 10
    WALK_TIME_GOOD = 20
    WALK_TIME_MARGINAL = 30
    SIZE_LARGE_SQM = 40_000
    SIZE_MEDIUM_SQM = 12_000
    SIZE_SMALL_SQM = 4_000
    PATH_NETWORK_DENSE = 5
    PATH_NETWORK_MODERATE = 2
    QUALITY_HIGH_RATING = 4.3
    QUALITY_MID_RATING = 3.8
    QUALITY_HIGH_REVIEWS = 200
    QUALITY_MID_REVIEWS = 50
    QUALITY_MIN_REVIEWS_RELIABLE = 20
    DAILY_PARK_MIN_WALK_SCORE = 1
    DAILY_PARK_MIN_SIZE_SCORE = 1
    DAILY_PARK_MIN_TOTAL = 5


# -- Subscore computation mirrors (used when imports succeed) --

def _compute_walk_time_score(walk_time_min):
    """Mirror of _score_walk_time, returns score only."""
    if _IMPORTS_OK:
        score, _ = _score_walk_time(walk_time_min)
        return score
    # Manual mirror
    if walk_time_min <= WALK_TIME_EXCELLENT:
        return 3.0
    elif walk_time_min <= WALK_TIME_GOOD:
        score = 3.0 - (walk_time_min - WALK_TIME_EXCELLENT) * (
            1.0 / (WALK_TIME_GOOD - WALK_TIME_EXCELLENT)
        )
        return round(max(2.0, score), 1)
    elif walk_time_min <= WALK_TIME_MARGINAL:
        score = 2.0 - (walk_time_min - WALK_TIME_GOOD) * (
            1.0 / (WALK_TIME_MARGINAL - WALK_TIME_GOOD)
        )
        return round(max(1.0, score), 1)
    else:
        return 0.5


def _compute_size_loop_score(osm_data, rating, reviews, name, parkserve_acres=None):
    """Mirror of _score_size_loop, returns score only."""
    if _IMPORTS_OK:
        score, _, is_estimate = _score_size_loop(
            osm_data, rating, reviews, name, parkserve_acres=parkserve_acres
        )
        return score, is_estimate
    raise RuntimeError("Cannot compute size_loop without imports")


def _compute_quality_score(rating, reviews):
    """Mirror of _score_quality, returns score only."""
    if _IMPORTS_OK:
        score, _ = _score_quality(rating, reviews)
        return score
    # Manual mirror
    if rating is None:
        return 0.0
    score = 0.0
    # Rating component
    if rating >= QUALITY_HIGH_RATING:
        rating_component = 1.2
    elif rating >= QUALITY_MID_RATING:
        rating_component = 0.8
    elif rating >= 3.5:
        rating_component = 0.4
    else:
        rating_component = 0.0
    if reviews < QUALITY_MIN_REVIEWS_RELIABLE:
        rating_component = min(0.6, rating_component)
    score += rating_component
    # Review component
    if reviews >= QUALITY_HIGH_REVIEWS:
        score += 0.8
    elif reviews >= QUALITY_MID_REVIEWS:
        score += 0.5
    elif reviews >= 10:
        score += 0.2
    return min(2.0, round(score, 1))


def _compute_nature_feel_score(osm_data, name, types, parkserve_type=None):
    """Mirror of _score_nature_feel, returns score only."""
    if _IMPORTS_OK:
        score, _ = _score_nature_feel(osm_data, name, types, parkserve_type=parkserve_type)
        return score
    raise RuntimeError("Cannot compute nature_feel without imports")


def _compute_full_score(**kwargs):
    """Mirror of compute_park_score."""
    if _IMPORTS_OK:
        return compute_park_score(**kwargs)
    raise RuntimeError("Cannot compute full score without imports")


# =============================================================================
# TEST GENERATORS
# =============================================================================

def _generate_walk_time_tests():
    """Test _score_walk_time at boundary and interpolation points."""
    cases = []

    # Boundary tests
    boundaries = [
        (0, 3.0, "walk_time=0 → max score 3.0"),
        (WALK_TIME_EXCELLENT, 3.0, f"walk_time={WALK_TIME_EXCELLENT} → excellent boundary 3.0"),
        (WALK_TIME_GOOD, 2.0, f"walk_time={WALK_TIME_GOOD} → good boundary 2.0"),
        (WALK_TIME_MARGINAL, 1.0, f"walk_time={WALK_TIME_MARGINAL} → marginal boundary 1.0"),
        (WALK_TIME_MARGINAL + 1, 0.5, f"walk_time={WALK_TIME_MARGINAL + 1} → beyond marginal 0.5"),
        (60, 0.5, "walk_time=60 → far 0.5"),
    ]

    for i, (wt, expected, desc) in enumerate(boundaries, 1):
        actual = _compute_walk_time_score(wt)
        cases.append({
            "id": f"gt-parks-wt-{i:02d}",
            "test_type": "walk_time",
            "description": desc,
            "inputs": {"walk_time_min": wt},
            "expected": {"walk_time_score": actual},
        })

    # Interpolation: midpoints in the declining segments
    # 10-20 segment: linear from 3.0 to 2.0
    for wt in [12, 15, 18]:
        actual = _compute_walk_time_score(wt)
        cases.append({
            "id": f"gt-parks-wt-{len(cases) + 1:02d}",
            "test_type": "walk_time",
            "description": f"walk_time={wt} → interpolated in 10-20 segment",
            "inputs": {"walk_time_min": wt},
            "expected": {"walk_time_score": actual},
        })

    # 20-30 segment: linear from 2.0 to 1.0
    for wt in [22, 25, 28]:
        actual = _compute_walk_time_score(wt)
        cases.append({
            "id": f"gt-parks-wt-{len(cases) + 1:02d}",
            "test_type": "walk_time",
            "description": f"walk_time={wt} → interpolated in 20-30 segment",
            "inputs": {"walk_time_min": wt},
            "expected": {"walk_time_score": actual},
        })

    return cases


def _generate_size_enriched_tests():
    """Test _score_size_loop with ParkServe/OSM enriched data."""
    cases = []

    # ParkServe acreage tests
    parkserve_tests = [
        # (acres, path_count, has_trail, expected_desc)
        (15.0, 0, False, "large park (ParkServe), no paths"),
        (15.0, PATH_NETWORK_DENSE, False, "large park + dense paths"),
        (15.0, 0, True, "large park + trail"),
        (5.0, PATH_NETWORK_MODERATE, False, "medium park + moderate paths"),
        (2.0, 1, False, "small park + minimal paths"),
        (0.5, 0, False, "pocket park, no paths"),
    ]

    for i, (acres, paths, trail, desc) in enumerate(parkserve_tests, 1):
        osm_data = {
            "enriched": paths > 0 or trail,
            "area_sqm": None,
            "path_count": paths,
            "has_trail": trail,
            "nature_tags": [],
        }
        score, is_estimate = _compute_size_loop_score(
            osm_data, rating=4.0, reviews=100, name="Test Park",
            parkserve_acres=acres,
        )
        cases.append({
            "id": f"gt-parks-sz-enr-{i:02d}",
            "test_type": "size_enriched",
            "description": desc,
            "inputs": {
                "park_acres": acres,
                "osm_path_count": paths,
                "osm_has_trail": trail,
                "rating": 4.0,
                "reviews": 100,
                "name": "Test Park",
            },
            "expected": {
                "size_loop_score": score,
                "is_estimate": is_estimate,
            },
        })

    # OSM area tests (no ParkServe)
    osm_area_tests = [
        (50_000, 0, False, "large OSM area, no paths"),
        (50_000, PATH_NETWORK_DENSE, False, "large OSM area + dense paths"),
        (20_000, PATH_NETWORK_MODERATE, False, "medium OSM area + moderate paths"),
        (5_000, 1, False, "small OSM area + minimal paths"),
        (2_000, 0, False, "tiny OSM area, no paths"),
    ]

    for i, (area_sqm, paths, trail, desc) in enumerate(osm_area_tests, 1):
        osm_data = {
            "enriched": True,
            "area_sqm": area_sqm,
            "path_count": paths,
            "has_trail": trail,
            "nature_tags": [],
        }
        score, is_estimate = _compute_size_loop_score(
            osm_data, rating=4.0, reviews=100, name="Test Park",
        )
        cases.append({
            "id": f"gt-parks-sz-osm-{i:02d}",
            "test_type": "size_enriched",
            "description": f"OSM: {desc}",
            "inputs": {
                "osm_area_sqm": area_sqm,
                "osm_path_count": paths,
                "osm_has_trail": trail,
                "rating": 4.0,
                "reviews": 100,
                "name": "Test Park",
            },
            "expected": {
                "size_loop_score": score,
                "is_estimate": is_estimate,
            },
        })

    return cases


def _generate_size_fallback_tests():
    """Test _score_size_loop fallback path (reviews + name proxy)."""
    cases = []

    fallback_tests = [
        # (reviews, name, desc)
        (600, "Central Park", "high reviews + generic park name"),
        (600, "Forest Trail Preserve", "high reviews + trail name"),
        (250, "Riverside Park", "moderate reviews + park name"),
        (250, "Nature Trail", "moderate reviews + trail name"),
        (80, "Town Green", "some reviews + generic name"),
        (80, "Greenway Path", "some reviews + trail name"),
        (10, "Pocket Park", "few reviews + park name"),
        (10, "Empty Lot", "few reviews + no keywords"),
    ]

    for i, (reviews, name, desc) in enumerate(fallback_tests, 1):
        osm_data = {"enriched": False, "area_sqm": None, "path_count": 0,
                     "has_trail": False, "nature_tags": []}
        score, is_estimate = _compute_size_loop_score(
            osm_data, rating=4.0, reviews=reviews, name=name,
        )
        cases.append({
            "id": f"gt-parks-sz-fb-{i:02d}",
            "test_type": "size_fallback",
            "description": f"Fallback: {desc}",
            "inputs": {
                "reviews": reviews,
                "name": name,
                "rating": 4.0,
            },
            "expected": {
                "size_loop_score": score,
                "is_estimate": is_estimate,
            },
        })

    return cases


def _generate_quality_tests():
    """Test _score_quality at rating/review boundaries."""
    cases = []

    quality_tests = [
        # (rating, reviews, desc)
        (None, 0, "no rating data"),
        (4.5, 300, "high rating + high reviews"),
        (4.5, 10, "high rating + few reviews (cap applies)"),
        (4.0, 100, "mid rating + moderate reviews"),
        (3.8, 200, "mid-boundary rating + high reviews"),
        (3.5, 50, "low-boundary rating + moderate reviews"),
        (3.2, 30, "below-average rating + some reviews"),
        (4.3, 5, "high rating but unreliable (<20 reviews)"),
        (4.5, 0, "high rating + zero reviews"),
        (2.0, 500, "very low rating + many reviews"),
    ]

    for i, (rating, reviews, desc) in enumerate(quality_tests, 1):
        score = _compute_quality_score(rating, reviews)
        cases.append({
            "id": f"gt-parks-qual-{i:02d}",
            "test_type": "quality",
            "description": desc,
            "inputs": {"rating": rating, "reviews": reviews},
            "expected": {"quality_score": score},
        })

    return cases


def _generate_nature_feel_tests():
    """Test _score_nature_feel with various inputs."""
    cases = []

    nature_tests = [
        # (nature_tags, name, types, desc)
        ([], "City Park", [], "no nature indicators"),
        (["forest"], "Woodland Park", [], "single forest tag + nature name"),
        (["forest", "water"], "Lake Forest", [], "two forest/water tags"),
        (["forest", "water", "wetland"], "Wetland Preserve", [],
         "multiple nature tags + preserve name"),
        (["grassland"], "Green Meadow", [], "non-forest green tag"),
        ([], "Forest Hills Nature Preserve", [], "nature name, no OSM tags"),
        ([], "Greenway Trail Path", [], "trail name, no OSM tags"),
        ([], "Regular Park", ["national_park"], "national_park type bonus"),
        ([], "Camp Area", ["campground"], "campground type bonus"),
        (["forest"], "Forest Park", ["national_park"],
         "forest tag + national_park type"),
        ([], "Generic Playground", [], "no nature indicators at all"),
        # ParkServe type classification (NES-359)
        ([], "Some Nature Area", [], "parkserve Nature Preserve, no other signals", "Nature Preserve"),
        ([], "City Park", [], "parkserve Community Park, no other signals", "Community Park"),
        ([], "Mini Green", [], "parkserve Mini Park (too small)", "Mini Park"),
        ([], "Regional Open Space", [], "parkserve Regional Park", "Regional Park"),
        ([], "River Trail", [], "parkserve Greenway", "Greenway"),
        (["forest"], "Forest Park", [], "parkserve Nature Preserve + OSM forest tag", "Nature Preserve"),
        (["forest", "water"], "Lake Nature Preserve", [], "parkserve Community Park vs strong OSM (OSM wins at 1.5)", "Community Park"),
        ([], "Trail Path", [], "parkserve Trail vs trail name keyword", "Trail"),
    ]

    for i, test_data in enumerate(nature_tests, 1):
        if len(test_data) == 5:
            tags, name, types, desc, ps_type = test_data
        else:
            tags, name, types, desc = test_data
            ps_type = None

        osm_data = {"enriched": len(tags) > 0, "area_sqm": None,
                     "path_count": 0, "has_trail": False,
                     "nature_tags": tags}
        score = _compute_nature_feel_score(osm_data, name, types, parkserve_type=ps_type)

        inputs = {
            "osm_nature_tags": tags,
            "name": name,
            "types": types,
        }
        if ps_type is not None:
            inputs["parkserve_type"] = ps_type

        cases.append({
            "id": f"gt-parks-nf-{i:02d}",
            "test_type": "nature_feel",
            "description": desc,
            "inputs": inputs,
            "expected": {"nature_feel_score": score},
        })

    return cases


def _generate_composite_tests():
    """Test compute_park_score end-to-end with realistic combinations."""
    cases = []

    composite_tests = [
        # (kwargs, desc)
        (
            {"walk_time_min": 5, "rating": 4.5, "reviews": 300,
             "name": "Forest Park", "park_acres": 20.0,
             "osm_path_count": 6, "osm_nature_tags": ["forest", "water"]},
            "excellent park: close, large, well-reviewed, natural",
        ),
        (
            {"walk_time_min": 15, "rating": 4.0, "reviews": 100,
             "name": "Town Park", "park_acres": 5.0,
             "osm_path_count": 3},
            "good park: moderate walk, medium size, decent quality",
        ),
        (
            {"walk_time_min": 25, "rating": 3.5, "reviews": 30,
             "name": "Small Green", "osm_area_sqm": 3000},
            "marginal park: far walk, small, average quality",
        ),
        (
            {"walk_time_min": 35, "rating": 3.0, "reviews": 5,
             "name": "Empty Lot"},
            "poor park: very far, no size data, low quality",
        ),
        (
            {"walk_time_min": 8, "rating": None, "reviews": 0,
             "name": "Unknown Park"},
            "close but no quality data",
        ),
        (
            {"walk_time_min": 5, "rating": 4.5, "reviews": 500,
             "name": "Nature Preserve", "types": ["national_park"],
             "park_acres": 50.0, "osm_path_count": 10,
             "osm_has_trail": True,
             "osm_nature_tags": ["forest", "water", "nature_reserve"]},
            "maximum everything — tests cap at 10",
        ),
        (
            {"walk_time_min": 0, "rating": 4.5, "reviews": 300,
             "name": "Park", "park_acres": 15.0, "osm_path_count": 5},
            "zero walk time + good park",
        ),
        (
            {"walk_time_min": 10, "rating": 4.3, "reviews": 200,
             "name": "Riverside Trail", "park_acres": 8.0,
             "osm_path_count": 4, "osm_has_trail": True,
             "osm_nature_tags": ["water"]},
            "excellent walk + trail park with water",
        ),
        (
            {"walk_time_min": 8, "rating": 4.2, "reviews": 150,
             "name": "Riverside Park", "park_acres": 15.0,
             "parkserve_type": "Nature Preserve",
             "osm_path_count": 3, "osm_nature_tags": []},
            "ParkServe Nature Preserve boosts nature_feel",
        ),
        (
            {"walk_time_min": 12, "rating": 3.8, "reviews": 50,
             "name": "Town Square", "parkserve_type": "Pocket Park"},
            "ParkServe Pocket Park — no nature_feel boost",
        ),
    ]

    for i, (kwargs, desc) in enumerate(composite_tests, 1):
        score = _compute_full_score(**kwargs)

        # Also compute subscores for pipeline verification
        wt = kwargs["walk_time_min"]
        wt_score = _compute_walk_time_score(wt)

        osm_data = {
            "enriched": (
                kwargs.get("osm_area_sqm") is not None
                or kwargs.get("osm_path_count", 0) > 0
                or kwargs.get("osm_has_trail", False)
                or len(kwargs.get("osm_nature_tags", [])) > 0
            ),
            "area_sqm": kwargs.get("osm_area_sqm"),
            "path_count": kwargs.get("osm_path_count", 0),
            "has_trail": kwargs.get("osm_has_trail", False),
            "nature_tags": kwargs.get("osm_nature_tags", []),
        }
        sz_score, _ = _compute_size_loop_score(
            osm_data, kwargs.get("rating"), kwargs.get("reviews", 0),
            kwargs.get("name", ""), parkserve_acres=kwargs.get("park_acres"),
        )
        q_score = _compute_quality_score(kwargs.get("rating"), kwargs.get("reviews", 0))
        nf_score = _compute_nature_feel_score(
            osm_data, kwargs.get("name", ""), kwargs.get("types", []),
            parkserve_type=kwargs.get("parkserve_type"),
        )

        cases.append({
            "id": f"gt-parks-comp-{i:02d}",
            "test_type": "composite",
            "description": desc,
            "inputs": kwargs,
            "expected": {
                "walk_time_score": wt_score,
                "size_loop_score": sz_score,
                "quality_score": q_score,
                "nature_feel_score": nf_score,
                "raw_total": round(wt_score + sz_score + q_score + nf_score, 1),
                "final_score": score,
            },
        })

    return cases


def _generate_composite_cap_tests():
    """Verify total is capped at 10.0 when subscores sum > 10."""
    cases = []

    # Construct inputs that max every subscore: 3 + 3 + 2 + 2 = 10 exactly
    # Then push nature_feel beyond 2 to trigger cap
    cap_tests = [
        (
            {"walk_time_min": 5, "rating": 4.5, "reviews": 500,
             "name": "Forest Nature Preserve", "types": ["national_park"],
             "park_acres": 50.0, "osm_path_count": 10, "osm_has_trail": True,
             "osm_nature_tags": ["forest", "water", "nature_reserve"]},
            "all subscores maxed — cap at 10",
        ),
    ]

    for i, (kwargs, desc) in enumerate(cap_tests, 1):
        score = _compute_full_score(**kwargs)
        cases.append({
            "id": f"gt-parks-cap-{i:02d}",
            "test_type": "composite_cap",
            "description": desc,
            "inputs": kwargs,
            "expected": {
                "final_score_max": 10.0,
                "final_score": score,
            },
        })

    return cases


def _generate_monotonicity_tests(rng):
    """Walk time increases → score decreases (or stays flat)."""
    cases = []

    # Systematic boundary pairs
    walk_times = sorted(set([
        0, 5, WALK_TIME_EXCELLENT, 12, 15, 18,
        WALK_TIME_GOOD, 22, 25, 28,
        WALK_TIME_MARGINAL, 35, 45, 60,
    ]))

    # Add random samples
    for _ in range(6):
        walk_times.append(rng.randint(0, 60))
    walk_times = sorted(set(walk_times))

    # Common park inputs (held constant)
    base_kwargs = {
        "rating": 4.0, "reviews": 100, "name": "Test Park",
        "park_acres": 10.0, "osm_path_count": 3,
    }

    idx = 0
    for i in range(len(walk_times) - 1):
        t1, t2 = walk_times[i], walk_times[i + 1]
        s1 = _compute_full_score(walk_time_min=t1, **base_kwargs)
        s2 = _compute_full_score(walk_time_min=t2, **base_kwargs)
        idx += 1
        cases.append({
            "id": f"gt-parks-mono-{idx:02d}",
            "test_type": "monotonicity",
            "description": (
                f"walk_time={t1} (score={s1}) >= "
                f"walk_time={t2} (score={s2})"
            ),
            "inputs": {
                "walk_time_a": t1,
                "walk_time_b": t2,
                "base_kwargs": base_kwargs,
            },
            "expected": {
                "score_a_gte_score_b": True,
                "score_a": s1,
                "score_b": s2,
            },
        })

    return cases


def _generate_criteria_tests():
    """Test PASS/BORDERLINE/FAIL classification."""
    cases = []

    criteria_tests = [
        # (walk_time, wt_score, sz_score, total, desc)
        (5, 3.0, 2.0, 7.0, "PASS: good total, good walk + size"),
        (8, 3.0, 1.5, 6.0, "PASS: meets all criteria"),
        (10, 3.0, 1.0, 5.0, "PASS: exact threshold"),
        (15, 2.5, 1.5, 5.5, "PASS: moderate walk, meets criteria"),
        (35, 0.5, 2.0, 4.0, "FAIL: walk > 30 min (automatic)"),
        (25, 1.5, 0.5, 3.5, "BORDERLINE: low size score"),
        (28, 1.2, 1.0, 4.0, "BORDERLINE: score near threshold"),
        (5, 3.0, 0.5, 4.5, "BORDERLINE: good walk but low size"),
        (20, 2.0, 0.5, 3.0, "FAIL: low total + low size"),
        (10, 3.0, 0.0, 4.0, "BORDERLINE: no size evidence"),
    ]

    for i, (walk_time, wt_score, sz_score, total, desc) in enumerate(
        criteria_tests, 1
    ):
        if _IMPORTS_OK:
            status, _ = _evaluate_criteria(total, wt_score, sz_score, walk_time)
        else:
            # Manual mirror
            if walk_time > WALK_TIME_MARGINAL:
                status = "FAIL"
            elif total >= DAILY_PARK_MIN_TOTAL and wt_score >= DAILY_PARK_MIN_WALK_SCORE and sz_score >= DAILY_PARK_MIN_SIZE_SCORE:
                status = "PASS"
            elif total >= DAILY_PARK_MIN_TOTAL - 1.5:
                status = "BORDERLINE"
            else:
                status = "FAIL"

        cases.append({
            "id": f"gt-parks-crit-{i:02d}",
            "test_type": "criteria",
            "description": desc,
            "inputs": {
                "walk_time_min": walk_time,
                "walk_time_score": wt_score,
                "size_loop_score": sz_score,
                "total": total,
            },
            "expected": {"criteria_status": status},
        })

    return cases


def main():
    parser = argparse.ArgumentParser(
        description="Generate ground-truth test cases for parks & green space scoring"
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--output", type=str, default="data/ground_truth/parks.json",
        help="Output JSON path (default: data/ground_truth/parks.json)",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)

    print(f"Imports from green_space: {'OK' if _IMPORTS_OK else 'FALLBACK'}")
    print(f"Walk time thresholds: excellent={WALK_TIME_EXCELLENT}, "
          f"good={WALK_TIME_GOOD}, marginal={WALK_TIME_MARGINAL}")
    print(f"Size thresholds (sqm): large={SIZE_LARGE_SQM}, "
          f"medium={SIZE_MEDIUM_SQM}, small={SIZE_SMALL_SQM}")
    print(f"Quality ceiling: none (parks has no ceiling config)")
    print()

    # Generate all test cases
    all_cases = []

    wt_cases = _generate_walk_time_tests()
    all_cases.extend(wt_cases)
    print(f"Generated {len(wt_cases)} walk time tests")

    sz_enr_cases = _generate_size_enriched_tests()
    all_cases.extend(sz_enr_cases)
    print(f"Generated {len(sz_enr_cases)} size/loop enriched tests")

    sz_fb_cases = _generate_size_fallback_tests()
    all_cases.extend(sz_fb_cases)
    print(f"Generated {len(sz_fb_cases)} size/loop fallback tests")

    qual_cases = _generate_quality_tests()
    all_cases.extend(qual_cases)
    print(f"Generated {len(qual_cases)} quality tests")

    nf_cases = _generate_nature_feel_tests()
    all_cases.extend(nf_cases)
    print(f"Generated {len(nf_cases)} nature feel tests")

    comp_cases = _generate_composite_tests()
    all_cases.extend(comp_cases)
    print(f"Generated {len(comp_cases)} composite tests")

    cap_cases = _generate_composite_cap_tests()
    all_cases.extend(cap_cases)
    print(f"Generated {len(cap_cases)} composite cap tests")

    mono_cases = _generate_monotonicity_tests(rng)
    all_cases.extend(mono_cases)
    print(f"Generated {len(mono_cases)} monotonicity tests")

    crit_cases = _generate_criteria_tests()
    all_cases.extend(crit_cases)
    print(f"Generated {len(crit_cases)} criteria tests")

    print(f"\nTotal: {len(all_cases)} test cases")

    # Build output
    scoring_version = "unknown"
    try:
        from scoring_config import SCORING_MODEL
        scoring_version = SCORING_MODEL.version
    except Exception:
        pass

    output = {
        "_schema_version": "0.2.0",
        "_generated_at": datetime.now(timezone.utc).isoformat(),
        "_generator": "generate_ground_truth_parks.py",
        "_scoring_model_version": scoring_version,
        "_test_count": len(all_cases),
        "_seed": args.seed,
        "_subscore_model": {
            "walk_time": {"max": 3.0, "thresholds": {
                "excellent": WALK_TIME_EXCELLENT,
                "good": WALK_TIME_GOOD,
                "marginal": WALK_TIME_MARGINAL,
            }},
            "size_loop": {"max": 3.0, "thresholds_sqm": {
                "large": SIZE_LARGE_SQM,
                "medium": SIZE_MEDIUM_SQM,
                "small": SIZE_SMALL_SQM,
            }},
            "quality": {"max": 2.0},
            "nature_feel": {"max": 2.0},
            "total_cap": 10.0,
        },
        "_quality_ceiling": False,
        "test_cases": all_cases,
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

    print(f"\nGround truth written to: {out_path}")


if __name__ == "__main__":
    main()
