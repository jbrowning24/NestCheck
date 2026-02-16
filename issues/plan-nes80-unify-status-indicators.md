# NES-80: Unify Status Indicator Systems

**Overall Progress:** `100%`

## TLDR
Two status indicator systems coexist in the Proximity & Environment section: the newer proximity-band system (`.proximity-item` with colored left borders) and the legacy check-row system (`.check-row` with circular icons). The legacy paths only activate for old snapshots missing `presented_checks` or `proximity_band`. We backfill old snapshots at load time — the same pattern used for `score_band` and `dimension_summaries` — then remove both legacy template paths and their CSS.

## Critical Decisions
- **Backfill at load time, not migration script:** Follows existing pattern in `view_snapshot()` (lines 1449-1456). Re-derives `presented_checks` from raw `tier1_checks` on each old snapshot load. No DB migration needed.
- **Keep raw `tier1_checks` in snapshot JSON:** It's the source-of-truth data that makes backfill possible. Removing it would be irreversible data loss for no benefit.
- **LIFESTYLE checks out of scope:** They're computed and stored but not rendered — separate design decision.
- **Old snapshots without `distance_ft`:** `_proximity_band()` handles this gracefully (PASS→NEUTRAL, UNKNOWN→NOTABLE, FAIL without distance→VERY_CLOSE). Conservative but correct.

## Files Touched
- `app.py` — backfill logic in `view_snapshot()`, add `Tier1Check` import
- `templates/_result_sections.html` — remove legacy rendering paths (lines 478-491, 496-510)
- `static/css/report.css` — remove `.check-row`, `.check-icon`, `.check-pass`, `.check-fail`, `.check-unknown`, `.check-text`, `.check-label`, `.check-detail`, `.check-explanation` rules

## Tasks

- [x] 🟩 **Phase 1: Backfill `presented_checks` for old snapshots**
  - [x] 🟩 Add `Tier1Check` to the import from `property_evaluator` in `app.py` (line 22)
  - [x] 🟩 Add backfill block in `view_snapshot()` after existing backfills (after line 1456): if `presented_checks` not in `result`, reconstruct `Tier1Check` objects from `result["tier1_checks"]` dicts (mapping `result` string back to `CheckResult` enum, defaulting `distance_ft=None`), call `present_checks()`, and attach to `result`
  - [x] 🟩 Also backfill `structured_summary` from the new `presented_checks` if missing (it depends on `presented_checks`)
  - [ ] 🟥 Manually verify: load an old snapshot URL (`/s/<id>`) — confirm it renders via the proximity-band path, not the check-row path

- [x] 🟩 **Phase 2: Remove legacy template paths**
  - [x] 🟩 In `_result_sections.html`, remove the backward-compat `{% else %}` block (lines 478-491) — the `proximity_band` check + else is no longer needed since backfill guarantees it exists
  - [x] 🟩 Remove the `{% else %}` / `tier1_checks` fallback block (lines 496-510) — backfill guarantees `presented_checks` exists
  - [x] 🟩 Simplify the remaining template: remove the `{% if pc.proximity_band is defined and pc.proximity_band %}` guard (line 454) since `proximity_band` is now always present for SAFETY checks — keep only the proximity-band rendering
  - [ ] 🟥 Verify: load both a new evaluation and an old snapshot, confirm both render correctly with only the proximity-band path

- [x] 🟩 **Phase 3: Remove legacy CSS**
  - [x] 🟩 Grep entire codebase for `check-row`, `check-icon`, `check-pass`, `check-fail`, `check-unknown`, `check-text`, `check-label`, `check-detail`, `check-explanation` to confirm no remaining references
  - [x] 🟩 Delete the "Check Items" CSS block from `report.css` (lines 205-231 + line 640-644 for `.check-explanation`)
  - [ ] 🟥 Visual verification: load a report and confirm no broken styles
