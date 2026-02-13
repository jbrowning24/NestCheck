# Improve Park Result Quality: Exclusion Filters for Non-Public Spaces (NES-54)

**Overall Progress:** `15%` · **Status:** Step 1 complete — task 1/6 done
**Last updated:** 2026-02-12

## TLDR
Non-public spaces (golf courses, cemeteries, private clubs, utility facilities) sometimes surface as parks because Google Places co-types them as `"park"`. Three-layer fix: hard type-based exclusions (no park exemption), hard name-based heuristics, and soft OSM `access` tag checking. Single file change (`green_space.py`), zero additional API calls.

## Critical Decisions
- **New `NON_GREEN_TYPES` set, separate from `EXCLUDED_TYPES`** — categorically non-green types (cemetery, golf_course, gym) bypass the existing park-type exemption. This is cleaner than modifying the exemption logic.
- **OSM access is a soft signal, not a hard filter** — only reject on explicit `access=private` or `access=no`. Tag absence is ignored (avoids false negatives in areas with sparse OSM tagging).
- **No Overpass query changes needed** — `out body;` already returns all tags including `access`. We just start reading it.
- **Post-enrichment filtering for OSM access** — access check happens after `batch_enrich_from_osm()` but before scoring/ranking, since the data isn't available earlier.
- **Audit logging via `logger.debug` + `evaluation.messages`** — filtered park names logged to server logs in real-time, and appended to `evaluation.messages` for snapshot/dashboard visibility. Uses existing infrastructure rather than extending `nc_trace`'s timing-focused schema.

## Tasks

- [x] 🟩 **Step 1: Add `NON_GREEN_TYPES` constant and check in `_is_garbage()`**
  - [x] 🟩 Add new set: `NON_GREEN_TYPES = {"cemetery", "funeral_home", "golf_course", "gym"}`
  - [x] 🟩 Add check in `_is_garbage()` before the existing `EXCLUDED_TYPES` check — `if any(t in NON_GREEN_TYPES for t in types): return True` (no park exemption)

- [ ] 🟥 **Step 2: Expand `GARBAGE_NAME_KEYWORDS` for non-public spaces**
  - [ ] 🟥 Add non-public space terms: `"golf"`, `"country club"`, `"cemetery"`, `"funeral"`, `"mausoleum"`, `"swim club"`, `"pool club"`, `"yacht club"`, `"rowing club"`, `"nursing home"`, `"assisted living"`, `"retirement home"`
  - [ ] 🟥 Add utility company variants (NES-52 already has `"con ed"` and `"utility"`): `"coned"`, `"conedison"`, `"con edison"`, `"pse&g"`, `"pseg"`, `"national grid"`

- [ ] 🟥 **Step 3: Extract OSM `access` tag in enrichment**
  - [ ] 🟥 In `enrich_from_osm()` element parsing loop (~line 604): check `tags.get("access")` on park/green polygons (leisure=park, nature_reserve, etc.) and store the most restrictive value found in `result["access_private"]` (True if any polygon has `access=private` or `access=no`)
  - [ ] 🟥 Mirror the same logic in `_parse_osm_elements_for_place()` (~line 698) for batch enrichment consistency
  - [ ] 🟥 Add `osm_access_private: bool = False` field to `GreenSpaceResult` dataclass

- [ ] 🟥 **Step 4: Post-enrichment filter for OSM private access + audit logging**
  - [ ] 🟥 In `evaluate_green_escape()`, after OSM enrichment (line ~1270) and before scoring: filter out places where `osm_data.get("access_private")` is True
  - [ ] 🟥 `logger.debug("Filtered (OSM access=private): %s", name)` for real-time server logs
  - [ ] 🟥 Append filtered park names to `evaluation.messages` (e.g., `"Excluded: {name} (OSM access=private)"`) for snapshot/dashboard audit trail

- [ ] 🟥 **Step 5: Tests**
  - [ ] 🟥 Test `_is_garbage()` rejects cemetery + park co-type (NON_GREEN_TYPES bypasses park exemption)
  - [ ] 🟥 Test `_is_garbage()` rejects golf-related name keywords
  - [ ] 🟥 Test `_is_garbage()` rejects utility company variant spellings
  - [ ] 🟥 Test `_is_garbage()` still passes real parks (Central Park, etc.)
  - [ ] 🟥 Test OSM access=private extraction in enrichment result
  - [ ] 🟥 Test post-enrichment filtering removes access=private places and logs to messages

- [ ] 🟥 **Step 6: Verify with real evaluation**
  - [ ] 🟥 Run evaluation on an address known to produce golf course / cemetery results — confirm filtered
  - [ ] 🟥 Spot-check another address to confirm real parks still surface correctly
