"""Unit tests for insight generator functions.

Each test targets one classification branch using synthetic input dicts
— no API calls or mocking needed.  All insight functions are pure:
dict in → string (or None) out.
"""

from app import (
    _insight_neighborhood,
    _insight_getting_around,
    _insight_parks,
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
