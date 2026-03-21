# NES-316: EJScreen Cross-Reference Annotations

**Date:** 2026-03-20
**Status:** Approved
**Linear:** NES-316

## Problem

Address-level health checks (Tier 1) and EJScreen area-level indicators (Tier 2) measure the same underlying hazards at different geographic scales. When they diverge — address check passes but area percentile is elevated — the report presents them pages apart with no reconciliation. Users interpret this as a contradiction.

Example: "Superfund — Clear" (address not inside NPL boundary) alongside 94th percentile Superfund Proximity (block group level). Both are correct, but without cross-referencing, lay users cannot reconcile them.

## Design

### Cross-reference config

A list of dicts in `app.py` defining address-check-to-EJScreen-indicator mappings:

```python
_EJSCREEN_CROSS_REFS = [
    {
        "address_checks": ["Superfund (NPL)"],
        "ejscreen_field": "PNPL",
        "threshold": 80,
        "template": "Address clear, but this area ranks {pct}th percentile nationally for Superfund proximity.",
    },
    {
        "address_checks": ["TRI facility", "ust_proximity"],
        "ejscreen_field": "PTSDF",
        "threshold": 80,
        "template": "No facilities in our buffer, but this area ranks {pct}th percentile nationally for hazardous waste proximity.",
    },
]
```

- `address_checks` is a list because PTSDF maps to both TRI and UST (same hazard family).
- `threshold` is the EJScreen national percentile at which divergence is meaningful. 80th is the starting point, tunable per-indicator.
- `template` texts are under 120 characters per UI spec Section 4.11.
- Adding a future pair means adding one dict. No other changes needed.

### Annotation injection

Location: `_prepare_snapshot_for_display()` in `app.py`, **after** the NES-241 hazard_tier backfill comprehension (currently the last step in the presented_checks pipeline, line ~2127). Must be after the backfill because it rebuilds dicts via `{**pc, ...}` — placing the annotation injection before it would silently drop the `area_context_annotation` key on old snapshots.

Rationale for this location:
- `present_checks()` only receives `tier1_checks` — no access to `ejscreen_profile`. Changing its signature would affect all 4 call sites.
- `_prepare_snapshot_for_display()` has access to the full `result` dict and is the canonical migration pipeline for all deserialization paths.

Logic:

```python
ejscreen = result.get("ejscreen_profile")
if ejscreen:
    for xref in _EJSCREEN_CROSS_REFS:
        pct = ejscreen.get(xref["ejscreen_field"])
        if pct is None or pct < xref["threshold"]:
            continue
        for pc in result["presented_checks"]:
            if (pc.get("name") in xref["address_checks"]
                    and pc.get("result_type") == "CLEAR"):
                pc["area_context_annotation"] = xref["template"].format(
                    pct=int(pct)
                )
```

Key fields:
- `result_type` is the presentation-layer status field, set in `present_checks()`. Values: `CLEAR`, `WARNING_DETECTED`, `CONFIRMED_ISSUE`, `VERIFICATION_NEEDED`.
- `ejscreen_profile` is a dict keyed by indicator field name (`PNPL`, `PTSDF`, etc.) with float percentile values, set at `property_evaluator.py:5978`.

### Template rendering

In `_result_sections.html`, inside the Tier 1 check card (after the satellite-link conditional block, before the "Why we check this" collapsible — i.e., between the `VERIFICATION_NEEDED` satellite link and the `health_context` toggle), add:

```jinja2
{% if pc.area_context_annotation is defined and pc.area_context_annotation %}
  {{ annotation(pc.area_context_annotation) }}
{% endif %}
```

Uses the existing `annotation()` macro from `_macros.html`. No new CSS, no new component.

### Pass-only gate

The annotation only appears on checks with `result_type == "CLEAR"`. If the address-level check is already in caution or fail state, the address-level concern is the dominant signal. The area percentile would add noise without changing the user's takeaway.

## What doesn't change

- **Evaluation logic** in `property_evaluator.py` — untouched.
- **EJScreen Tier 2 compact section** in the health cards — stays as-is.
- **EPA Environmental Profile** section at page bottom — stays as-is.
- **Check status** — a passing check stays green/CLEAR. The annotation adds context, not a status change.
- **Serialization/storage** — `area_context_annotation` is added at display time in `_prepare_snapshot_for_display()`, not stored in the snapshot.

## Edge cases

| Scenario | Behavior |
|----------|----------|
| EJScreen data missing (`ejscreen_profile` is None) | No annotation, silent no-op |
| Old snapshots | `_prepare_snapshot_for_display()` runs on all 4 deserialization paths, so old snapshots with `ejscreen_profile` get annotations |
| Superfund FAIL + high PNPL | Annotation suppressed (pass-only gate). SEMS dedup in evaluator already suppresses the EJScreen Superfund Tier 2 check |
| Both TRI and UST pass + high PTSDF | Both cards get the annotation. Correct — the area context applies to both |
| EJScreen percentile is exactly 80 | Fires (`>=` threshold). 80th is the boundary |

## Pairs not mapped (and why)

| EJScreen indicator | Why no cross-reference |
|---|---|
| PM25, OZONE, DSLPM, CANCER | No address-level counterpart. Manufacturing a fake cross-reference would be dishonest |
| PTRAF (Traffic Proximity) | Semantically adjacent to road noise but measurement approaches are too different (AADT at specific segments vs. modeled area-level index). Revisit if users ask |
| LEAD (Lead Paint) | No address-level lead check. Area-level indicator only |
| PRMP (RMP Facility Proximity) | No address-level RMP check exists |
| PWDIS (Wastewater Discharge) | No address-level wastewater check exists |
| UST (EJScreen UST indicator) | Address-level `ust_proximity` exists but is mapped to PTSDF instead — PTSDF (Hazardous Waste Proximity) is the broader category that encompasses USTs, TRI facilities, and TSDF sites. Using the parent indicator avoids redundant annotations |

## Files touched

| File | Change |
|------|--------|
| `app.py` | `_EJSCREEN_CROSS_REFS` config (~15 lines), annotation injection in `_prepare_snapshot_for_display()` (~12 lines) |
| `templates/_result_sections.html` | 3-line annotation rendering in Tier 1 check card |
