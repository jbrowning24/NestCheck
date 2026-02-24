"""Unit tests for insight generator functions.

Each test targets one classification branch using synthetic input dicts
— no API calls or mocking needed.  All insight functions are pure:
dict in → string (or None) out.
"""

from app import (
    _insight_neighborhood,
    _insight_getting_around,
    _insight_parks,
    _insight_community_profile,
    _join_labels,
    _nearest_walk_time,
    _weather_context,
    generate_insights,
)
from property_evaluator import proximity_synthesis


# ---------------------------------------------------------------------------
# Helpers — build synthetic inputs for any score combination
# ---------------------------------------------------------------------------

def _make_place(name: str, walk_min: int) -> dict:
    """Return a minimal place dict matching the shape used by the evaluator."""
    return {"name": name, "walk_time_min": walk_min}


def _build_inputs(
    coffee_score: int,
    grocery_score: int,
    fitness_score: int,
    parks_score: int = 5,
    *,
    coffee_places: list | None = None,
    grocery_places: list | None = None,
    fitness_places: list | None = None,
    parks_places: list | None = None,
) -> tuple[dict, dict]:
    """Build a (neighborhood, tier2) pair for _insight_neighborhood().

    Places default to one nearby result per dimension unless explicitly
    set to an empty list.  parks_score defaults to 5 (middling) so existing
    3-dimension test scenarios keep their intended branch routing.
    """
    neighborhood = {
        "coffee": coffee_places if coffee_places is not None else [_make_place("Blue Bottle", 5)],
        "grocery": grocery_places if grocery_places is not None else [_make_place("Trader Joe's", 8)],
        "fitness": fitness_places if fitness_places is not None else [_make_place("Planet Fitness", 10)],
        "parks": parks_places if parks_places is not None else [_make_place("Memorial Park", 7)],
    }
    tier2 = {
        "Coffee & Social Spots": {"points": coffee_score},
        "Daily Essentials": {"points": grocery_score},
        "Fitness & Recreation": {"points": fitness_score},
        "Parks & Green Space": {"points": parks_score},
    }
    return neighborhood, tier2


# ---------------------------------------------------------------------------
# Branch: all strong (4 dims >= 7)
# ---------------------------------------------------------------------------

class TestAllStrong:
    def test_output_mentions_lead_and_others(self):
        neighborhood, tier2 = _build_inputs(9, 8, 7, 7)
        result = _insight_neighborhood(neighborhood, tier2)
        assert result is not None
        assert "Blue Bottle" in result  # lead (highest score)
        assert "grocery stores" in result
        assert "gyms and fitness options" in result
        assert "parks and green spaces" in result

    def test_no_duplicate_labels(self):
        neighborhood, tier2 = _build_inputs(9, 8, 7, 7)
        result = _insight_neighborhood(neighborhood, tier2)
        # Lead label should appear only in the lead clause, not the "also" clause
        parts = result.split("\u2014")  # split on em-dash
        assert "cafés" not in parts[1] if len(parts) > 1 else True


# ---------------------------------------------------------------------------
# Branch: all weak (4 dims < 4) — with places
# ---------------------------------------------------------------------------

class TestAllWeakWithPlaces:
    def test_driving_phrasing(self):
        neighborhood, tier2 = _build_inputs(
            2, 1, 3, 2,
            coffee_places=[_make_place("Far Café", 25)],
            grocery_places=[_make_place("Far Grocery", 30)],
            fitness_places=[_make_place("Far Gym", 28)],
            parks_places=[_make_place("Far Park", 26)],
        )
        result = _insight_neighborhood(neighborhood, tier2)
        assert result is not None
        assert "driving" in result.lower()


# ---------------------------------------------------------------------------
# Branch: all weak — no places at all
# ---------------------------------------------------------------------------

class TestAllWeakNoPlaces:
    def test_didnt_find_phrasing(self):
        neighborhood, tier2 = _build_inputs(
            0, 0, 0, 0,
            coffee_places=[],
            grocery_places=[],
            fitness_places=[],
            parks_places=[],
        )
        result = _insight_neighborhood(neighborhood, tier2)
        assert result is not None
        assert "didn't find" in result.lower()


# ---------------------------------------------------------------------------
# Branch: one standout + rest middling (the primary bug fix)
# ---------------------------------------------------------------------------

class TestOneStandoutRestMiddling:
    def test_lead_appears_once(self):
        """Grocery is strong, coffee+fitness+parks middling.
        'grocery' must not appear in the second sentence."""
        neighborhood, tier2 = _build_inputs(5, 9, 4)
        result = _insight_neighborhood(neighborhood, tier2)
        assert result is not None
        # Lead sentence mentions grocery by label
        assert "grocery" in result.lower()
        # The label should appear exactly once (in the lead sentence)
        assert result.lower().count("grocery") == 1

    def test_other_dims_present(self):
        """All non-lead dims (coffee, fitness, parks) in second sentence."""
        neighborhood, tier2 = _build_inputs(5, 9, 4)
        result = _insight_neighborhood(neighborhood, tier2)
        assert "cafés and social spots" in result.lower()
        assert "gyms and fitness options" in result.lower()
        assert "parks and green spaces" in result.lower()

    def test_lead_place_name_in_output(self):
        neighborhood, tier2 = _build_inputs(5, 9, 4)
        result = _insight_neighborhood(neighborhood, tier2)
        assert "Trader Joe's" in result


# ---------------------------------------------------------------------------
# Branch: two strong + one middling (edge case within standout branch)
# ---------------------------------------------------------------------------

class TestTwoStrongRestMiddling:
    def test_no_dropped_dims(self):
        """All four dimension labels must appear in the output."""
        neighborhood, tier2 = _build_inputs(8, 9, 5)
        result = _insight_neighborhood(neighborhood, tier2)
        assert result is not None
        # Lead is grocery (score 9)
        assert "Trader Joe's" in result
        # Remaining strong (coffee) and middling (fitness, parks) all in output
        assert "cafés and social spots" in result.lower()
        assert "gyms and fitness options" in result.lower()
        assert "parks and green spaces" in result.lower()

    def test_lead_not_in_others(self):
        neighborhood, tier2 = _build_inputs(8, 9, 5)
        result = _insight_neighborhood(neighborhood, tier2)
        # "grocery" should appear once (lead sentence), not in the others list
        assert result.lower().count("grocery") == 1


# ---------------------------------------------------------------------------
# Branch: mixed — strong and weak
# ---------------------------------------------------------------------------

class TestMixedStrongAndWeak:
    def test_strength_and_weakness_mentioned(self):
        neighborhood, tier2 = _build_inputs(
            8, 2, 5,
            grocery_places=[_make_place("Distant Grocery", 20)],
        )
        result = _insight_neighborhood(neighborhood, tier2)
        assert result is not None
        # Strength lead
        assert "Blue Bottle" in result
        # Weakness hedge
        assert "grocery" in result.lower()

    def test_no_duplicate_dim_in_both_sentences(self):
        neighborhood, tier2 = _build_inputs(
            8, 2, 5,
            grocery_places=[_make_place("Distant Grocery", 20)],
        )
        result = _insight_neighborhood(neighborhood, tier2)
        # "café" label should not appear in the weakness sentence
        assert "on the other hand" in result.lower()
        parts = result.lower().split("on the other hand")
        assert "café" not in parts[1]

    def test_weak_with_no_places(self):
        neighborhood, tier2 = _build_inputs(
            8, 1, 5,
            grocery_places=[],
        )
        result = _insight_neighborhood(neighborhood, tier2)
        assert result is not None
        assert "didn't find" in result.lower()


# ---------------------------------------------------------------------------
# Branch: no strong, middling + weak
# ---------------------------------------------------------------------------

class TestNoStrongMiddlingAndWeak:
    def test_ok_and_weakness_mentioned(self):
        neighborhood, tier2 = _build_inputs(
            5, 2, 4,
            grocery_places=[_make_place("Distant Grocery", 22)],
        )
        result = _insight_neighborhood(neighborhood, tier2)
        assert result is not None
        # Middling lead (coffee, highest middling)
        assert "Blue Bottle" in result
        # Weakness — grocery is the only weak dim (score 2)
        assert "grocery" in result.lower()

    def test_weak_no_places(self):
        neighborhood, tier2 = _build_inputs(
            5, 1, 4,
            grocery_places=[],
        )
        result = _insight_neighborhood(neighborhood, tier2)
        assert result is not None
        assert "didn't find" in result.lower()


# ---------------------------------------------------------------------------
# Branch: all middling (4 dims scoring 4-6)
# ---------------------------------------------------------------------------

class TestAllMiddling:
    def test_generic_phrasing(self):
        neighborhood, tier2 = _build_inputs(5, 5, 5, 5)
        result = _insight_neighborhood(neighborhood, tier2)
        assert result is not None
        assert "within reach" in result.lower()

    def test_mentions_all_labels(self):
        neighborhood, tier2 = _build_inputs(5, 5, 5, 5)
        result = _insight_neighborhood(neighborhood, tier2)
        assert "cafés and social spots" in result.lower()
        assert "grocery stores" in result.lower()
        assert "gyms and fitness options" in result.lower()
        assert "parks and green spaces" in result.lower()


# ---------------------------------------------------------------------------
# Edge case: empty neighborhood dict
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_neighborhood_returns_none(self):
        assert _insight_neighborhood({}, {}) is None

    def test_none_neighborhood_returns_none(self):
        assert _insight_neighborhood(None, {}) is None


# ===========================================================================
# _insight_getting_around()
# ===========================================================================

# ---------------------------------------------------------------------------
# Helpers — build synthetic inputs for transit scenarios
# ---------------------------------------------------------------------------

def _make_urban(station: str, walk_min: int, *, hub: str | None = None,
                hub_min: int | None = None, freq_class: str = "") -> dict:
    """Build a minimal urban access dict."""
    urban = {"primary_transit": {"name": station, "walk_time_min": walk_min}}
    if freq_class:
        urban["primary_transit"]["frequency_class"] = freq_class
    if hub:
        urban["major_hub"] = {"name": hub, "travel_time_min": hub_min}
    return urban


def _ga_tier2(score: int) -> dict:
    """Build a tier2 dict for the Getting Around dimension."""
    return {"Getting Around": {"points": score}}


# ---------------------------------------------------------------------------
# Branch: strong rail (score >= 7)
# ---------------------------------------------------------------------------

class TestGettingAroundStrongRail:
    def test_station_and_walk_time(self):
        urban = _make_urban("Scarsdale", 8, hub="Grand Central", hub_min=35)
        result = _insight_getting_around(urban, None, None, "peak-hour", _ga_tier2(8))
        assert "Scarsdale" in result
        assert "8 minutes" in result

    def test_hub_travel_time(self):
        urban = _make_urban("Scarsdale", 8, hub="Grand Central", hub_min=35)
        result = _insight_getting_around(urban, None, None, "peak-hour", _ga_tier2(8))
        assert "Grand Central" in result
        assert "35 minutes" in result

    def test_freq_label_included(self):
        urban = _make_urban("Scarsdale", 8)
        result = _insight_getting_around(urban, None, None, "Peak-Hour", _ga_tier2(8))
        assert "peak-hour" in result.lower()


# ---------------------------------------------------------------------------
# Branch: moderate rail (score 4-6)
# ---------------------------------------------------------------------------

class TestGettingAroundModerateRail:
    def test_station_and_service_caveat(self):
        urban = _make_urban("Brewster", 14)
        result = _insight_getting_around(urban, None, None, "hourly", _ga_tier2(5))
        assert "Brewster" in result
        assert "service runs at" in result.lower()

    def test_backup_option_advice(self):
        urban = _make_urban("Brewster", 14)
        result = _insight_getting_around(urban, None, None, "hourly", _ga_tier2(5))
        assert "backup" in result.lower()


# ---------------------------------------------------------------------------
# Branch: weak rail (score < 4)
# ---------------------------------------------------------------------------

class TestGettingAroundWeakRail:
    def test_nearest_transit_phrasing(self):
        urban = _make_urban("Wassaic", 25)
        result = _insight_getting_around(urban, None, None, "limited", _ga_tier2(2))
        assert "nearest transit" in result.lower()
        assert "Wassaic" in result

    def test_driving_for_most_trips(self):
        urban = _make_urban("Wassaic", 25)
        result = _insight_getting_around(urban, None, None, "", _ga_tier2(2))
        assert "driving" in result.lower()


# ---------------------------------------------------------------------------
# Branch: bus-only fallback (no rail)
# ---------------------------------------------------------------------------

class TestGettingAroundBusOnly:
    def test_bus_stop_details(self):
        transit = {"primary_stop": "Rt 9 / Main St", "walk_minutes": 6,
                   "frequency_bucket": "Moderate"}
        result = _insight_getting_around(None, transit, None, "", _ga_tier2(5))
        assert "Rt 9 / Main St" in result
        assert "6 minutes" in result
        assert "moderate" in result.lower()

    def test_low_score_driving_advice(self):
        transit = {"primary_stop": "Rt 9 / Main St", "walk_minutes": 6,
                   "frequency_bucket": "Infrequent"}
        result = _insight_getting_around(None, transit, None, "", _ga_tier2(2))
        assert "driving" in result.lower() or "rideshare" in result.lower()


# ---------------------------------------------------------------------------
# Branch: no transit at all
# ---------------------------------------------------------------------------

class TestGettingAroundNoTransit:
    def test_limited_transit_phrasing(self):
        """Urban=empty dict (truthy but no primary_transit), transit=None."""
        result = _insight_getting_around({}, None, None, "", _ga_tier2(1))
        assert "limited" in result.lower()

    def test_no_data_returns_none(self):
        """Both urban and transit are None → no data guard returns None."""
        result = _insight_getting_around(None, None, None, "", _ga_tier2(0))
        assert result is None


# ---------------------------------------------------------------------------
# Addons: bike score, walk description
# ---------------------------------------------------------------------------

class TestGettingAroundAddons:
    def test_bike_note_when_score_high(self):
        urban = _make_urban("Bronxville", 6)
        ws = {"bike_score": 75, "walk_description": "Very Walkable"}
        result = _insight_getting_around(urban, None, ws, "", _ga_tier2(7))
        assert "bik" in result.lower()

    def test_no_bike_note_when_score_low(self):
        urban = _make_urban("Bronxville", 6)
        ws = {"bike_score": 40, "walk_description": "Somewhat Walkable"}
        result = _insight_getting_around(urban, None, ws, "", _ga_tier2(7))
        assert "bik" not in result.lower()

    def test_walk_description_included_when_score_ge_4(self):
        urban = _make_urban("Bronxville", 6)
        ws = {"walk_description": "Very Walkable"}
        result = _insight_getting_around(urban, None, ws, "", _ga_tier2(7))
        assert "Very Walkable" in result

    def test_walk_description_omitted_when_score_lt_4(self):
        urban = _make_urban("Wassaic", 25)
        ws = {"walk_description": "Car-Dependent"}
        result = _insight_getting_around(urban, None, ws, "", _ga_tier2(2))
        assert "Car-Dependent" not in result


# ===========================================================================
# _insight_parks()
# ===========================================================================

# ---------------------------------------------------------------------------
# Helpers — build synthetic green escape inputs
# ---------------------------------------------------------------------------

def _make_park(name: str, walk_min: int, *, osm_enriched: bool = False,
               area_sqm: float = 0, has_trail: bool = False,
               path_count: int = 0) -> dict:
    """Build a minimal best_daily_park dict."""
    park = {"name": name, "walk_time_min": walk_min, "osm_enriched": osm_enriched}
    if osm_enriched:
        park["osm_area_sqm"] = area_sqm
        park["osm_has_trail"] = has_trail
        park["osm_path_count"] = path_count
    return park


def _parks_tier2(score: int) -> dict:
    """Build a tier2 dict for the Parks & Green Space dimension."""
    return {"Parks & Green Space": {"points": score}}


# ---------------------------------------------------------------------------
# Branch: strong + close (score >= 7, walk <= 15)
# ---------------------------------------------------------------------------

class TestParksStrongClose:
    def test_park_name_and_walk_time(self):
        ge = {"best_daily_park": _make_park("Saxon Woods", 10), "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(8))
        assert "Saxon Woods" in result
        assert "10 minutes" in result

    def test_activity_phrasing(self):
        ge = {"best_daily_park": _make_park("Saxon Woods", 10), "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(8))
        assert "go for a run" in result.lower()


# ---------------------------------------------------------------------------
# Branch: high score but not close enough for "strong" (score >= 7, walk > 15)
# Falls through to moderate branch, NOT strong-close.
# ---------------------------------------------------------------------------

class TestParksHighScoreFarWalk:
    def test_falls_to_moderate_branch(self):
        ge = {"best_daily_park": _make_park("Tibbetts Brook", 18),
              "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(8))
        assert "regular visits" in result.lower()
        assert "go for a run" not in result.lower()


# ---------------------------------------------------------------------------
# Branch: good park but far (score < 7, walk > 20)
# ---------------------------------------------------------------------------

class TestParksGoodButFar:
    def test_weekend_destination(self):
        ge = {"best_daily_park": _make_park("Ward Pound Ridge", 25),
              "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(5))
        assert "weekend destination" in result.lower()
        assert "25 minutes" in result


# ---------------------------------------------------------------------------
# Branch: moderate (score >= 4)
# ---------------------------------------------------------------------------

class TestParksModerate:
    def test_regular_visits(self):
        ge = {"best_daily_park": _make_park("Tibbetts Brook", 14),
              "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(5))
        assert "regular visits" in result.lower()
        assert "Tibbetts Brook" in result


# ---------------------------------------------------------------------------
# Branch: weak (score < 4)
# ---------------------------------------------------------------------------

class TestParksWeak:
    def test_limited_green_space(self):
        ge = {"best_daily_park": _make_park("Small Lot", 18),
              "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(2))
        assert "limited" in result.lower()
        assert "Small Lot" in result


# ---------------------------------------------------------------------------
# Branch: no park found (best_daily_park missing or no name)
# ---------------------------------------------------------------------------

class TestParksNoPark:
    def test_no_best_park(self):
        ge = {"best_daily_park": None, "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(0))
        assert "no parks" in result.lower()

    def test_park_without_name(self):
        ge = {"best_daily_park": {"name": None}, "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(0))
        assert "no parks" in result.lower()


# ---------------------------------------------------------------------------
# OSM enrichment features
# ---------------------------------------------------------------------------

class TestParksOSMEnrichment:
    def test_acreage_shown_when_large(self):
        park = _make_park("Kensico Dam", 12, osm_enriched=True,
                          area_sqm=80_000)  # ~20 acres
        ge = {"best_daily_park": park, "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(8))
        assert "acres" in result.lower()

    def test_acreage_hidden_when_small(self):
        park = _make_park("Pocket Park", 8, osm_enriched=True,
                          area_sqm=8_000)  # ~2 acres, below 5-acre threshold
        ge = {"best_daily_park": park, "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(8))
        assert "acres" not in result.lower()

    def test_trails_noted(self):
        park = _make_park("Blue Mt", 10, osm_enriched=True, has_trail=True)
        ge = {"best_daily_park": park, "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(8))
        assert "trails" in result.lower()

    def test_paths_noted_when_enough(self):
        park = _make_park("Bronx River", 10, osm_enriched=True, path_count=4)
        ge = {"best_daily_park": park, "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(8))
        assert "4 paths" in result


# ---------------------------------------------------------------------------
# Nearby green spaces notation
# ---------------------------------------------------------------------------

class TestParksNearbyNotation:
    def test_multiple_nearby(self):
        nearby = [{"name": "A", "walk_time_min": 8},
                  {"name": "B", "walk_time_min": 12}]
        ge = {"best_daily_park": _make_park("Main Park", 10),
              "nearby_green_spaces": nearby}
        result = _insight_parks(ge, _parks_tier2(8))
        assert "2 other green spaces" in result

    def test_one_nearby(self):
        ge = {"best_daily_park": _make_park("Main Park", 10),
              "nearby_green_spaces": [{"name": "Side Park", "walk_time_min": 9}]}
        result = _insight_parks(ge, _parks_tier2(8))
        assert "another green space" in result.lower()

    def test_no_nearby(self):
        ge = {"best_daily_park": _make_park("Main Park", 10),
              "nearby_green_spaces": []}
        result = _insight_parks(ge, _parks_tier2(8))
        assert "other green space" not in result.lower()


# ---------------------------------------------------------------------------
# Edge case: None/empty green_escape
# ---------------------------------------------------------------------------

class TestParksEdgeCases:
    def test_none_returns_none(self):
        assert _insight_parks(None, _parks_tier2(0)) is None

    def test_empty_dict_returns_none(self):
        assert _insight_parks({}, _parks_tier2(0)) is None


# ===========================================================================
# generate_insights() — orchestrator
# ===========================================================================

class TestGenerateInsights:
    def test_returns_all_five_keys(self):
        result = generate_insights({})
        assert set(result.keys()) == {
            "your_neighborhood", "getting_around", "parks", "proximity",
            "community_profile",
        }

    def test_empty_input_returns_all_none(self):
        result = generate_insights({})
        assert all(v is None for v in result.values())

    def test_populated_input_produces_strings(self):
        """A fully populated result_dict should yield non-None strings."""
        rd = {
            "neighborhood_places": {
                "coffee": [_make_place("Café A", 5)],
                "grocery": [_make_place("Shop B", 8)],
                "fitness": [_make_place("Gym C", 10)],
                "parks": [_make_place("Park D", 7)],
            },
            "tier2_scores": [
                {"name": "Coffee & Social Spots", "points": 8, "max": 10},
                {"name": "Daily Essentials", "points": 7, "max": 10},
                {"name": "Fitness & Recreation", "points": 7, "max": 10},
                {"name": "Parks & Green Space", "points": 8, "max": 10},
                {"name": "Getting Around", "points": 7, "max": 10},
            ],
            "urban_access": {
                "primary_transit": {"name": "Scarsdale", "walk_time_min": 8},
                "major_hub": {"name": "Grand Central", "travel_time_min": 35},
            },
            "frequency_label": "Peak-Hour",
            "green_escape": {
                "best_daily_park": _make_park("Saxon Woods", 10),
                "nearby_green_spaces": [],
            },
            "presented_checks": [
                {"category": "SAFETY", "result_type": "CLEAR",
                 "check_id": "highway", "display_name": "Highway"},
            ],
        }
        result = generate_insights(rd)
        assert isinstance(result["your_neighborhood"], str)
        assert isinstance(result["getting_around"], str)
        assert isinstance(result["parks"], str)
        assert isinstance(result["proximity"], str)


# ===========================================================================
# proximity_synthesis()  (property_evaluator.py)
# ===========================================================================

# ---------------------------------------------------------------------------
# Helpers — build synthetic safety check dicts
# ---------------------------------------------------------------------------

def _make_check(check_id: str, result_type: str, display_name: str = "") -> dict:
    """Build a minimal presented_check dict for proximity_synthesis."""
    return {
        "category": "SAFETY",
        "result_type": result_type,
        "check_id": check_id,
        "display_name": display_name or check_id.replace("_", " ").title(),
    }


# ---------------------------------------------------------------------------
# Branch: all clear
# ---------------------------------------------------------------------------

class TestProximitySynthesisAllClear:
    def test_no_concerns(self):
        checks = [
            _make_check("highway", "CLEAR"),
            _make_check("gas_station", "CLEAR"),
        ]
        result = proximity_synthesis(checks)
        assert "no environmental concerns" in result.lower()


# ---------------------------------------------------------------------------
# Branch: unverified only (no confirmed issues)
# ---------------------------------------------------------------------------

class TestProximitySynthesisUnverifiedOnly:
    def test_single_unverified(self):
        checks = [
            _make_check("highway", "CLEAR"),
            _make_check("gas_station", "VERIFICATION_NEEDED", "Gas Station"),
        ]
        result = proximity_synthesis(checks)
        assert "Gas Station" in result
        assert "could not be verified" in result.lower()

    def test_two_unverified(self):
        checks = [
            _make_check("highway", "VERIFICATION_NEEDED"),
            _make_check("gas_station", "VERIFICATION_NEEDED"),
        ]
        result = proximity_synthesis(checks)
        assert "a highway" in result
        assert "a gas station" in result
        assert "could not be verified" in result.lower()

    def test_all_three_unverified(self):
        checks = [
            _make_check("highway", "VERIFICATION_NEEDED"),
            _make_check("gas_station", "VERIFICATION_NEEDED"),
            _make_check("high-volume_road", "VERIFICATION_NEEDED"),
        ]
        result = proximity_synthesis(checks)
        assert "none of the proximity checks" in result.lower()


# ---------------------------------------------------------------------------
# Branch: confirmed issues (with and without remaining clears)
# ---------------------------------------------------------------------------

class TestProximitySynthesisConfirmed:
    def test_confirmed_with_clears(self):
        checks = [
            _make_check("highway", "CONFIRMED_ISSUE"),
            _make_check("gas_station", "CLEAR"),
        ]
        result = proximity_synthesis(checks)
        assert "close to a highway" in result.lower()
        assert "remaining checks are clear" in result.lower()

    def test_confirmed_only_no_clears(self):
        checks = [_make_check("highway", "CONFIRMED_ISSUE")]
        result = proximity_synthesis(checks)
        assert "close to a highway" in result.lower()
        assert "remaining" not in result.lower()

    def test_multiple_confirmed(self):
        checks = [
            _make_check("highway", "CONFIRMED_ISSUE"),
            _make_check("gas_station", "CONFIRMED_ISSUE"),
        ]
        result = proximity_synthesis(checks)
        assert "a highway" in result
        assert "a gas station" in result


# ---------------------------------------------------------------------------
# Branch: confirmed + unverified mix
# ---------------------------------------------------------------------------

class TestProximitySynthesisMixed:
    def test_both_mentioned(self):
        checks = [
            _make_check("highway", "CONFIRMED_ISSUE"),
            _make_check("rail_corridor", "VERIFICATION_NEEDED"),
        ]
        result = proximity_synthesis(checks)
        assert "close to a highway" in result.lower()
        assert "an active rail line" in result.lower()
        assert "could not be verified" in result.lower()


# ---------------------------------------------------------------------------
# Edge case: no safety checks
# ---------------------------------------------------------------------------

class TestProximitySynthesisEdgeCases:
    def test_empty_list_returns_none(self):
        assert proximity_synthesis([]) is None

    def test_non_safety_category_ignored(self):
        checks = [{"category": "LIFESTYLE", "result_type": "CLEAR",
                    "check_id": "library", "display_name": "Library"}]
        assert proximity_synthesis(checks) is None


# ===========================================================================
# _weather_context()
# ===========================================================================

# ---------------------------------------------------------------------------
# Helpers — build synthetic weather dicts with trigger flags
# ---------------------------------------------------------------------------

def _make_weather(triggers: list[str], monthly: list[dict] | None = None) -> dict:
    """Build a minimal weather dict for _weather_context."""
    return {"triggers": triggers, "monthly": monthly or []}


def _winter_monthly() -> list[dict]:
    """Monthly data with snow Dec-Mar and freezing temps."""
    return [
        {"month": m, "avg_snowfall_in": (4.0 if m in (12, 1, 2, 3) else 0),
         "avg_high_f": 35 if m in (12, 1, 2) else 60}
        for m in range(1, 13)
    ]


def _summer_monthly() -> list[dict]:
    """Monthly data with hot temps Jun-Aug."""
    return [
        {"month": m, "avg_high_f": (92 if m in (6, 7, 8) else 70),
         "avg_snowfall_in": 0}
        for m in range(1, 13)
    ]


# ---------------------------------------------------------------------------
# Guards: None / empty
# ---------------------------------------------------------------------------

class TestWeatherContextGuards:
    def test_none_returns_none(self):
        assert _weather_context(None) is None

    def test_empty_dict_returns_none(self):
        assert _weather_context({}) is None

    def test_no_triggers_returns_none(self):
        assert _weather_context({"triggers": [], "monthly": []}) is None


# ---------------------------------------------------------------------------
# Snow + freezing combined
# ---------------------------------------------------------------------------

class TestWeatherContextSnowFreezing:
    def test_combined_sentence(self):
        w = _make_weather(["snow", "freezing"], _winter_monthly())
        result = _weather_context(w)
        assert "snow" in result.lower()
        assert "freezing" in result.lower()

    def test_month_range_included(self):
        w = _make_weather(["snow", "freezing"], _winter_monthly())
        result = _weather_context(w)
        # Should contain the winter month range from _snow_months()
        assert "December" in result
        assert "March" in result


# ---------------------------------------------------------------------------
# Snow only (no freezing)
# ---------------------------------------------------------------------------

class TestWeatherContextSnowOnly:
    def test_notable_snow(self):
        w = _make_weather(["snow"], _winter_monthly())
        result = _weather_context(w)
        assert "notable snow" in result.lower()
        assert "freezing" not in result.lower()


# ---------------------------------------------------------------------------
# Freezing only (no snow)
# ---------------------------------------------------------------------------

class TestWeatherContextFreezingOnly:
    def test_freezing_temperatures(self):
        w = _make_weather(["freezing"])
        result = _weather_context(w)
        assert "freezing" in result.lower()
        assert "snow" not in result.lower()


# ---------------------------------------------------------------------------
# Extreme heat
# ---------------------------------------------------------------------------

class TestWeatherContextExtremeHeat:
    def test_hot_summers(self):
        w = _make_weather(["extreme_heat"], _summer_monthly())
        result = _weather_context(w)
        assert "hot" in result.lower()
        assert "June" in result
        assert "August" in result


# ---------------------------------------------------------------------------
# Rain
# ---------------------------------------------------------------------------

class TestWeatherContextRain:
    def test_rain_without_snow(self):
        w = _make_weather(["rain"])
        result = _weather_context(w)
        assert "frequent rain" in result.lower()

    def test_rain_suppressed_when_snow_present(self):
        """Rain trigger is skipped when snow is also present."""
        w = _make_weather(["snow", "rain"], _winter_monthly())
        result = _weather_context(w)
        assert "rain" not in result.lower()


# ---------------------------------------------------------------------------
# Max 2 sentences
# ---------------------------------------------------------------------------

class TestWeatherContextMaxSentences:
    def test_capped_at_two_sentences(self):
        """Snow+freezing (1 sentence) + extreme_heat (1 sentence) = 2 max."""
        monthly = [
            {"month": m,
             "avg_snowfall_in": (4.0 if m in (12, 1, 2, 3) else 0),
             "avg_high_f": (92 if m in (6, 7, 8) else 35 if m in (12, 1, 2) else 60)}
            for m in range(1, 13)
        ]
        w = _make_weather(["snow", "freezing", "extreme_heat"], monthly)
        result = _weather_context(w)
        # Exactly 2 sentences joined by ". " → exactly 1 joiner
        assert result.count(". ") == 1
        assert "snow" in result.lower()
        assert "hot" in result.lower()


# ===========================================================================
# _nearest_walk_time()
# ===========================================================================

class TestNearestWalkTime:
    def test_returns_minimum(self):
        places = [{"walk_time_min": 12}, {"walk_time_min": 5}, {"walk_time_min": 8}]
        assert _nearest_walk_time(places) == 5

    def test_single_place(self):
        assert _nearest_walk_time([{"walk_time_min": 7}]) == 7

    def test_empty_list_returns_none(self):
        assert _nearest_walk_time([]) is None

    def test_skips_none_values(self):
        places = [{"walk_time_min": None}, {"walk_time_min": 10}]
        assert _nearest_walk_time(places) == 10

    def test_all_none_returns_none(self):
        places = [{"walk_time_min": None}, {}]
        assert _nearest_walk_time(places) is None


# ===========================================================================
# _join_labels()
# ===========================================================================

class TestJoinLabels:
    def test_single_item(self):
        assert _join_labels(["cafés"]) == "cafés"

    def test_two_items(self):
        assert _join_labels(["cafés", "grocery stores"]) == "cafés and grocery stores"

    def test_three_items_oxford_comma(self):
        result = _join_labels(["cafés", "grocery stores", "gyms"])
        assert result == "cafés, grocery stores, and gyms"

    def test_four_items(self):
        result = _join_labels(["a", "b", "c", "d"])
        assert result == "a, b, c, and d"

    def test_custom_conjunction(self):
        assert _join_labels(["cafés", "gyms"], "or") == "cafés or gyms"

    def test_custom_conjunction_three_items(self):
        result = _join_labels(["cafés", "gyms", "parks"], "or")
        assert result == "cafés, gyms, or parks"


# ---------------------------------------------------------------------------
# Community Profile insight (NES-134)
# ---------------------------------------------------------------------------

def _make_demographics(
    children_pct=35.0,
    renter_pct=38.8,
    owner_pct=61.2,
    transit_pct=12.5,
    walk_pct=5.0,
    bike_pct=2.5,
    wfh_pct=7.5,
    drive_alone_pct=62.5,
    median_rent=1800,
    county_children_pct=32.0,
    county_renter_pct=35.0,
    county_transit_pct=18.0,
    county_median_rent=1650,
    county_name="Westchester County",
):
    """Build a synthetic demographics dict matching serialized CensusProfile."""
    return {
        "children_pct": children_pct,
        "renter_pct": renter_pct,
        "owner_pct": owner_pct,
        "commute": {
            "drive_alone_pct": drive_alone_pct,
            "transit_pct": transit_pct,
            "walk_pct": walk_pct,
            "bike_pct": bike_pct,
            "wfh_pct": wfh_pct,
            "carpool_pct": 10.0,
        },
        "median_rent": median_rent,
        "county_children_pct": county_children_pct,
        "county_renter_pct": county_renter_pct,
        "county_commute": {
            "transit_pct": county_transit_pct,
            "drive_alone_pct": 58.0,
            "walk_pct": 4.0,
            "bike_pct": 1.0,
            "wfh_pct": 11.0,
            "carpool_pct": 8.0,
        },
        "county_median_rent": county_median_rent,
        "county_name": county_name,
        "geoid": "36119025300",
    }


class TestInsightCommunityProfile:
    def test_none_demographics_returns_none(self):
        assert _insight_community_profile(None, None, {}) is None

    def test_balanced_persona_children_first(self):
        demo = _make_demographics()
        result = _insight_community_profile(demo, {"key": "balanced"}, {})

        assert result is not None
        # Children sentence should come before tenure sentence
        children_pos = result.find("children")
        rent_pos = result.find("rent")
        assert children_pos < rent_pos or rent_pos == -1

    def test_commuter_persona_commute_first(self):
        demo = _make_demographics()
        result = _insight_community_profile(demo, {"key": "commuter"}, {})

        assert result is not None
        # Commute info should appear before children
        commute_pos = result.find("commuters") if "commuters" in result else result.find("drive")
        children_pos = result.find("children")
        assert commute_pos >= 0, "Expected commute info in output"
        assert children_pos >= 0, "Expected children info in output"
        assert commute_pos < children_pos

    def test_county_comparison_included(self):
        demo = _make_demographics()
        result = _insight_community_profile(demo, {"key": "balanced"}, {})

        assert "Westchester County" in result
        assert "32%" in result  # county children pct

    def test_transit_comparison_for_high_transit(self):
        demo = _make_demographics(transit_pct=15.0)
        result = _insight_community_profile(demo, {"key": "balanced"}, {})

        assert "transit" in result.lower()
        assert "18%" in result  # county transit pct

    def test_quiet_persona_tenure_first(self):
        demo = _make_demographics()
        result = _insight_community_profile(demo, {"key": "quiet"}, {})

        assert result is not None
        # Tenure sentence should come first
        assert result.startswith("This tract is")

    def test_sidewalk_cross_reference(self):
        demo = _make_demographics(walk_pct=5.0)
        result_dict = {"sidewalk_coverage": {"sidewalk_pct": 75.0}}
        result = _insight_community_profile(demo, {"key": "commuter"}, result_dict)

        assert result is not None
        assert "sidewalk" in result.lower()
        assert "75%" in result

    def test_no_sidewalk_cross_ref_when_low_walk(self):
        demo = _make_demographics(walk_pct=1.0)
        result_dict = {"sidewalk_coverage": {"sidewalk_pct": 75.0}}
        result = _insight_community_profile(demo, {"key": "commuter"}, result_dict)

        # walk_pct < 3 so no sidewalk cross-reference
        if result:
            assert "sidewalk" not in result.lower()

    def test_wfh_sentence_for_quiet_persona(self):
        demo = _make_demographics(wfh_pct=15.0)
        result = _insight_community_profile(demo, {"key": "quiet"}, {})

        assert "work from home" in result.lower()
        assert "15%" in result

    def test_default_persona_when_none(self):
        """When persona is None, falls back to balanced ordering."""
        demo = _make_demographics()
        result = _insight_community_profile(demo, None, {})

        assert result is not None
        # Should use balanced ordering (children first)
        assert "children" in result.lower()
