# NES-397: Surface Destination Parks Beyond Walk Radius

**Date:** 2026-04-01
**Status:** Design approved
**Linear:** NES-397

## Problem

Dobbs Ferry's Waterfront Park — arguably the town's signature green space — is absent from the parks list for 29 Ridge Rd. The current pipeline searches at 2km (expanding to 5km if <3 results), which doesn't reach notable parks that are a short drive away. Janet's panel feedback: "The report doesn't mention Waterfront Park... its absence from the parks list feels like a gap."

## Solution

Add a secondary parks search at 8km radius that surfaces notable parks (50+ Google reviews) beyond the primary walk-radius search. These render in a separate "Parks worth the drive" subsection below the existing nearby parks list, with drive-time pills only. The primary park scoring (Daily Walk Value, subscores) is completely unaffected.

## Architecture

### Discovery: `green_space.py`

New function `_find_destination_parks(maps_client, lat, lng, primary_place_ids)`:

- Single `maps_client.places_nearby(location, radius=8000, type="park")` call
- Filter: `user_ratings_total >= 50`
- Deduplicate: exclude any `place_id` already in `primary_place_ids` (from the primary search)
- Cap: return at most 3 parks, sorted by review count descending
- No OSM enrichment (no Overpass call)
- Returns `List[GreenSpaceResult]` with identity + location fields populated; `walk_time_min=0` as sentinel for "not applicable"

Called from `evaluate_green_escape()` after the primary pipeline completes. Primary place IDs (from best daily park + nearby list) are collected and passed for dedup.

### Drive Times: `green_space.py`

Destination parks need a separate `driving_times_batch()` call. The existing batch (~line 1736) operates on `far_parks` derived from the primary pipeline — destination parks aren't in that list and don't have `walk_time_min` populated. A second batch call with the destination park coordinates fires after `_find_destination_parks()` returns. Cost: 1 additional Distance Matrix call for up to 3 destinations (~$0.015).

### Data Model: `green_space.py`

`GreenEscapeEvaluation` gains a new field:

```python
destination_parks: List[GreenSpaceResult] = field(default_factory=list)
```

Destination parks are excluded from `score_green_space()` entirely. They do not influence the Daily Walk Value or any composite score.

### Serialization: `app.py`

`_serialize_green_escape()` serializes the `destination_parks` list with a minimal shape:

- `name`, `place_id`, `rating`, `user_ratings_total`, `drive_time_min`, `lat`, `lng`

No `daily_walk_value`, no `subscores`, no `walk_time_min`, no OSM fields.

### Template: `_result_sections.html`

New subsection after the nearby green spaces list (after ~line 965), inside the `{% if is_full_access %}` gate:

```html
{% if result.green_escape and result.green_escape.destination_parks %}
  <div class="subsection-divider">
    <div class="section-label">Parks worth the drive</div>
    {% for park in result.green_escape.destination_parks %}
      {# park name linked to Google Maps, rating + reviews meta, drive time pill #}
      {{ data_row(
          name=park_link,
          detail=rating_and_reviews,
          value=fmt_time(park.drive_time_min, "drive"),
          variant="place"
      ) }}
    {% endfor %}
  </div>
{% endif %}
```

**Display per park:** Name (Google Maps link), rating (1 decimal), review count, drive-time pill.
**No:** Daily Walk Value score, distance badge, OSM details, walk time.
**Empty state:** Subsection does not render. No empty-state message.

### Insight Text: `app.py`

`_insight_parks()` is not modified. The narrative insight stays focused on the best daily park.

## API Cost

| Call | Count | Cost |
|------|-------|------|
| Places Nearby (8km, type=park) | +1 | ~$0.032 |
| Distance Matrix (destination batch) | +1 | ~$0.015 |
| Overpass | +0 | $0.00 |
| **Total per evaluation** | | **~$0.047** |

## Acceptance Criteria

1. Waterfront Park appears in the Dobbs Ferry (29 Ridge Rd) report as a destination park
2. Destination parks are visually distinct — separate "Parks worth the drive" subsection with drive-time pills, no scores
3. Primary park scoring (Daily Walk Value, subscores, composite) is completely unaffected
4. Additional API cost: 1 Places Nearby call + 1 Distance Matrix batch per evaluation
5. If zero destination parks found, subsection does not render (no empty state)

## Files Changed

| File | Change |
|------|--------|
| `green_space.py` | Add `_find_destination_parks()`, add `destination_parks` field to `GreenEscapeEvaluation`, call from `evaluate_green_escape()`, include in drive-time batch |
| `app.py` | Serialize `destination_parks` in `_serialize_green_escape()` |
| `templates/_result_sections.html` | Add "Parks worth the drive" subsection after nearby list |

## Risk

Low. Purely additive — display-only, no scoring changes, no schema migration, no existing behavior modified. Only failure mode is 0 destination parks found, which silently omits the subsection.

Old snapshots without `destination_parks` will silently omit the subsection (Jinja2 undefined-is-falsy). No backfill needed.
