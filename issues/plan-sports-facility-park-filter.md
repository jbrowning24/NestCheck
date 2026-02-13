# Fix: Sports Facilities Surfacing as Parks (NES-52)

**Overall Progress:** `100%` · **Status:** Complete
**Last updated:** 2025-02-12

## TLDR
"Con Ed FIAO Soccer" and similar sports facilities / corporate properties surface as parks in the Green Space evaluation. Root cause: Google Places tags them as type `"park"`, which bypasses all our garbage filters. Fix tightens `_is_garbage()`, adds sports/corporate garbage keywords, and removes the overly broad `"field"` green keyword. Single file change (`green_space.py`), no API cost impact.

## Critical Decisions
- **Name-based garbage checks always apply, even with `"park"` type** — the park-type exemption should only skip type-based exclusion, not name-based. This is the core logic fix.
- **Remove `"field"` from GREEN_NAME_KEYWORDS entirely** — too broad (matches "Springfield", "Fairfield", etc.). Real fields that are parks will still pass via their Google `"park"` type.
- **Sports keywords are garbage, not excluded types** — we add them as name keywords rather than Google types because Google doesn't reliably type sports facilities distinctly.

## Tasks

- [x] :green_square: **Step 1: Add sports & corporate terms to `GARBAGE_NAME_KEYWORDS`**
  - [x] :green_square: Add sports terms: `"soccer"`, `"football"`, `"baseball"`, `"softball"`, `"batting cage"`, `"athletic"`, `"tennis court"`, `"basketball court"`, `"little league"`, `"rugby"`, `"lacrosse"`, `"cricket"`
  - [x] :green_square: Add corporate/utility terms: `"con ed"`, `"utility"`, `"corporate"`, `"campus"`, `"headquarters"`, `"office park"`, `"industrial"`

- [x] :green_square: **Step 2: Remove `"field"` from `GREEN_NAME_KEYWORDS`**
  - [x] :green_square: Delete `"field"` from the list (line ~127)

- [x] :green_square: **Step 3: Fix `_is_garbage()` park-type exemption**
  - [x] :green_square: Reorder logic: check name-based garbage keywords FIRST (always applies)
  - [x] :green_square: Only then check type-based exclusion, with the existing park-type exemption
  - [x] :green_square: Net effect: a place named "Con Ed Soccer" with type `"park"` now gets caught by name check

- [x] :green_square: **Step 4: Add debug logging for filtered places**
  - [x] :green_square: In `find_green_spaces()` filter loop (~line 388), log when `_is_garbage()` or `!_is_green_space()` rejects a place
  - [x] :green_square: Logger already exists (`logger = logging.getLogger(__name__)` at line 33)

- [x] :green_square: **Step 5: Verify**
  - [x] :green_square: Run evaluation on the address that produced Con Ed FIAO Soccer — confirm it no longer appears
  - [x] :green_square: Spot-check another address to ensure real parks still surface
  - [x] :green_square: Review debug log output for any surprising filtered-out places

## Risk
- **Legitimate parks with sports terms in names** (e.g., "Central Park Athletic Fields") would be filtered — but the parent "Central Park" surfaces separately via its own place_id. Sub-features of large parks are not the primary result.
- **Existing snapshots unaffected** — already computed and stored.

## Files Changed
- `green_space.py` — only file modified
- `test_green_space.py` — added verification tests for NES-52

## Verification
- Unit tests pass: `test_con_ed_soccer_is_garbage_even_with_park_type`, `test_sports_facility_is_garbage`, `test_field_removed_from_green_keywords`
- Real parks (Central Park, Riverside Park, etc.) still pass `_is_garbage` and `_is_green_space`
