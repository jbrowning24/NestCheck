# Result Presentation Contract + Tier Gate Removal

**Overall Progress:** `100%`

## TLDR
Add a presentation layer that classifies, explains, and narrates each Tier 1 check result. Remove the Tier 1 gate so Tier 2/3 always execute. Add single retry for API-based checks. Wire everything through `result_to_dict()` so the new results UI (Phase 2) has structured data to consume.

## Critical Decisions
- **Dicts over dataclasses for serialization:** `present_checks()` returns plain dicts (not `CheckPresentation` instances) so they drop straight into the JSON blob without a custom serializer.
- **Retry at call site, not inside check functions:** `_retry_once()` wraps the three API check calls in `evaluate_property()`. Check functions stay untouched.
- **`passed_tier1` kept but demoted:** Still computed and stored for presentation logic; no longer gates Tier 2/3 execution.
- **Old snapshot fallback:** `generate_verdict()` falls back to the old string when `presented_checks` is absent, so existing snapshots render correctly.

## Tasks

- [x] 🟩 **Step 1: Remove Tier 1 gate on Tier 2/3 execution** (`property_evaluator.py`)
  - [x] 🟩 Remove `if result.passed_tier1:` guard around Tier 2 scoring block (line ~2901)
  - [x] 🟩 Remove `if result.passed_tier1:` guard around Tier 3 bonuses block (line ~2937)
  - [x] 🟩 Add brief comments noting these blocks now always run
  - [x] 🟩 Verify `passed_tier1` is still computed at lines 2891-2895 (no change needed there)

- [x] 🟩 **Step 2: Add `_retry_once()` for API-based Tier 1 checks** (`property_evaluator.py`)
  - [x] 🟩 Add `_retry_once(check_fn, *args)` helper near the `evaluate_property()` function
  - [x] 🟩 Wrap `check_gas_stations` call (line 2880) with `_retry_once`
  - [x] 🟩 Wrap `check_highways` call (line 2881) with `_retry_once`
  - [x] 🟩 Wrap `check_high_volume_roads` call (line 2882) with `_retry_once`
  - [x] 🟩 Leave listing-based checks (`check_listing_requirements`) unwrapped

- [x] 🟩 **Step 3: Add `CheckPresentation` dataclass** (`property_evaluator.py`)
  - [x] 🟩 Add `CheckPresentation` dataclass after `Tier3Bonus` (after line 160)
  - [x] 🟩 Ensure `Optional` and `Any` are already imported (they are, line 26)

- [x] 🟩 **Step 4: Add `present_checks()` and supporting code** (`property_evaluator.py`)
  - [x] 🟩 Add content dictionaries: `CHECK_DISPLAY_NAMES`, `CHECK_EXPLANATIONS`, `_ACTION_HINTS`, `SAFETY_CHECKS`, `LISTING_CHECKS`
  - [x] 🟩 Add `_classify_check()` helper
  - [x] 🟩 Add `_generate_headline()` helper
  - [x] 🟩 Add `present_checks()` function returning `List[dict]`

- [x] 🟩 **Step 5: Add `generate_structured_summary()` and update `generate_verdict()`** (`app.py`)
  - [x] 🟩 Add `generate_structured_summary(presented_checks)` near `generate_verdict()` (line ~130)
  - [x] 🟩 Update `generate_verdict()` to use structured summary when `presented_checks` exist and Tier 1 failed

- [x] 🟩 **Step 6: Wire into `result_to_dict()`** (`app.py`)
  - [x] 🟩 Import `present_checks` from `property_evaluator` (update existing import line 15)
  - [x] 🟩 Add `presented_checks` field after tier1_checks serialization (after line ~304)
  - [x] 🟩 Add `show_score` field based on `blocks_scoring`
  - [x] 🟩 Add `structured_summary` field
  - [x] 🟩 Ensure `generate_verdict()` runs after `presented_checks` is set

- [x] 🟩 **Step 7: Smoke test**
  - [x] 🟩 Verify app starts without import errors
  - [x] 🟩 Confirm `present_checks()` output structure matches contract
  - [x] 🟩 Confirm old snapshots still render (fallback path)
