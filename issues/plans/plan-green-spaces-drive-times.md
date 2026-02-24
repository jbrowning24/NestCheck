# NES-12: Green Spaces — Show Drive Times for Far Parks

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** 2026-02-09

## TLDR
The nearby green spaces list shows parks with absurd walk times (60-250 min) when the search expands to 5,000m. For parks beyond walking distance (>30 min walk), fetch and display drive time instead. Filter out parks that are also too far to drive.

## Critical Decisions
- **Drive time threshold for nearby list:** 20 min — parks beyond 30 min walk AND 20 min drive are excluded from the nearby list (too remote for practical use)
- **Batch API call:** Add `driving_times_batch()` to `GoogleMapsClient` mirroring the existing `walking_times_batch()` pattern, to minimize API cost (1 request per 25 destinations)
- **Fetch drive times only for the final nearby list** — not all 50 candidates — to keep API calls minimal (likely 1 extra request for ≤8 parks)
- **Best daily park stays walk-focused** — it already prioritizes walkability via scoring; drive time added as supplementary info only

## Tasks:

- [x] 🟩 **Step 1: Add `drive_time_min` field to `GreenSpaceResult`**
  - [x] 🟩 Add `drive_time_min: Optional[int] = None` to the dataclass ([green_space.py:187-219](green_space.py#L187-L219))

- [x] 🟩 **Step 2: Add `driving_times_batch()` to `GoogleMapsClient`**
  - [x] 🟩 Add method mirroring `walking_times_batch()` with `mode=driving` ([property_evaluator.py:723-755](property_evaluator.py#L723-L755))

- [x] 🟩 **Step 3: Fetch drive times in `evaluate_green_escape()`**
  - [x] 🟩 After building the nearby list + best park (line ~1271), collect parks where `walk_time_min > WALK_TIME_MARGINAL`
  - [x] 🟩 Batch-fetch drive times for those parks via `maps_client.driving_times_batch()`
  - [x] 🟩 Set `drive_time_min` on each `GreenSpaceResult`
  - [x] 🟩 Filter out nearby parks where `walk_time_min > WALK_TIME_MARGINAL` and `drive_time_min > 20` (or unreachable)

- [x] 🟩 **Step 4: Update serialization**
  - [x] 🟩 Add `drive_time_min` to `_space_dict()` in `green_escape_to_dict()` ([green_space.py:1289-1321](green_space.py#L1289-L1321))
  - [x] 🟩 Add `drive_time_min` to `green_escape_to_legacy_format()` ([green_space.py:1333-1369](green_space.py#L1333-L1369))

- [x] 🟩 **Step 5: Update template display**
  - [x] 🟩 Best daily park: if `drive_time_min` is set and `walk_time_min > 30`, show "X min drive" instead of walk ([_result_sections.html:235](templates/_result_sections.html#L235))
  - [x] 🟩 Nearby list: same logic — show "X min drive" or "X min walk" based on threshold ([_result_sections.html:288](templates/_result_sections.html#L288))

- [x] 🟩 **Step 6: Update tests**
  - [x] 🟩 Add mock `driving_times_batch` to test fixtures ([test_green_space.py:59-65](test_green_space.py#L59-L65))
  - [x] 🟩 Test that parks beyond 30 min walk get drive times populated
  - [x] 🟩 Test that parks beyond 30 min walk + 20 min drive are filtered from nearby list
