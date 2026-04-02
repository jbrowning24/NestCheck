# NES-396: EJScreen Percentile Context Annotations

## Problem

EJScreen percentile values are technically accurate but not actionable. NES-321 shipped plain-language annotations ("Higher than 84% of U.S. neighborhoods") which solve the "what is a percentile" problem. This ticket adds the next layer: **what does this percentile mean in practice?**

Users need to understand whether a percentile is typical for the kind of area they're considering or signals proximity to a specific pollution source.

## Approach

Add indicator-specific contextual annotations to EJScreen percentiles at or above the 50th percentile. Two severity bands (`moderate`: 50-74th, `high`: 75th+) with distinct copy per indicator.

### Architecture

**Backend dict in `app.py`** — follows the existing `_EJSCREEN_CROSS_REFS` pattern. A new `_EJSCREEN_CONTEXT` dict maps `(field_key, band)` to contextual phrases. The resolved annotation is injected into `ejscreen_profile` during `_prepare_snapshot_for_display()`, so the template simply renders what it's given.

### Data Structure

```python
_EJSCREEN_CONTEXT = {
    "PM25": {
        "high":     "Often seen near urban corridors or areas downwind of industry",
        "moderate": "Common in suburban areas near commuter routes",
    },
    "OZONE": {
        "high":     "Typical of areas in ozone-prone regions or near urban sprawl",
        "moderate": "Common in suburban areas during warm months",
    },
    "DSLPM": {
        "high":     "Typical near truck routes, freight corridors, or bus depots",
        "moderate": "Common near moderate commercial or delivery traffic",
    },
    "CANCER": {
        "high":     "Often near facilities with chemical releases tracked by EPA",
        "moderate": "Common in areas with some industrial or commercial activity nearby",
    },
    "RESP": {
        "high":     "Often near industrial operations or chemical manufacturing",
        "moderate": "Common in areas with nearby commercial or light-industrial use",
    },
    # Note: CANCER maps to RSEI_AIR in EJScreen V2.32 (chemical release risk).
    # RESP may return None in V2.32 — the None guard handles this gracefully.
    "PTRAF": {
        "high":     "Typical within a few blocks of highways or high-volume intersections",
        "moderate": "Common near arterial roads or moderate commuter corridors",
    },
    "PNPL": {
        "high":     "Usually indicates a Superfund site within a few miles",
        "moderate": "More distant Superfund presence in the wider area",
    },
    "PRMP": {
        "high":     "Indicates a facility handling hazardous chemicals nearby",
        "moderate": "Facility with risk management plan in the wider area",
    },
    "PTSDF": {
        "high":     "Usually indicates a treatment or disposal facility nearby",
        "moderate": "Hazardous waste handling facility in the wider area",
    },
    "UST": {
        "high":     "Higher density of underground fuel tanks nearby, often gas stations",
        "moderate": "Some underground storage tanks in the surrounding area",
    },
    "PWDIS": {
        "high":     "Usually near a wastewater outfall or treatment plant discharge",
        "moderate": "Wastewater discharge points in the wider area",
    },
    "LEAD": {
        "high":     "Most housing stock built before 1960 when lead paint was standard",
        "moderate": "Mix of pre- and post-1960 housing in the area",
    },
}
```

### Band Logic

```python
def _ejscreen_band(pct: float) -> str | None:
    if pct >= 75:
        return "high"
    if pct >= 50:
        return "moderate"
    return None  # no annotation below 50th
```

### Injection Point

In `_prepare_snapshot_for_display()`, after the existing NES-316 cross-reference block in `app.py`:

```python
# NES-396: Add practical context annotations to EJScreen indicators.
if _ejscreen:
    ejscreen_context = {}
    for field_key in _EJSCREEN_CONTEXT:
        pct = _ejscreen.get(field_key)
        if pct is None:
            continue
        band = _ejscreen_band(pct)
        if band:
            ejscreen_context[field_key] = _EJSCREEN_CONTEXT[field_key][band]
    result["ejscreen_context"] = ejscreen_context
```

### Template Change

In `_result_sections.html`, at the top of the EJScreen block (after `{% set ej = result.ejscreen_profile %}`), add:

```jinja2
{% set ejctx = result.ejscreen_context if result.ejscreen_context is defined else {} %}
```

Then after the existing `__annotation` span (line ~1239), add:

```jinja2
{% if ejctx[field_key] is defined %}
  <span class="ejscreen-indicator__context">{{ ejctx[field_key] }}</span>
{% endif %}
```

This follows the existing pattern where `ej` aliases `result.ejscreen_profile`.

### CSS

```css
.ejscreen-indicator__context {
  display: block;
  font-size: var(--type-detail);
  color: var(--color-text-secondary);
  line-height: var(--line-height-normal);
  margin-top: 2px;
}
```

No new tokens needed — uses existing `--type-detail` and `--color-text-secondary` per the UI spec (Section 4.11).

## Acceptance Criteria

1. EJScreen percentile values >= 50th show a one-line contextual annotation below the existing NES-321 annotation
2. Annotations are indicator-specific (12 indicators x 2 bands = 24 phrases)
3. Annotations use `--type-detail` size, `--color-text-secondary` color, 120-char max
4. No annotation appears below the 50th percentile
5. Annotations interpret, they don't editorialize (per UI spec: "calm and contextualize, never amplify")
6. Copy is defined as a backend constant, not inline in the template

## Files Changed

| File | Change |
|------|--------|
| `app.py` | Add `_EJSCREEN_CONTEXT` dict, `_ejscreen_band()` helper, inject in `_prepare_snapshot_for_display()` |
| `templates/_result_sections.html` | Add `__context` span in EJScreen indicator loop |
| `static/css/components.css` (or inline) | Add `.ejscreen-indicator__context` rule |

## What This Does NOT Include

- Geographic comparison (Level 2 — requires county-level EJScreen aggregates)
- Cross-report comparison (Level 3 — requires multi-report infrastructure)
- Any changes to Tier 1 health check generation or scoring
- Any new API calls or data sources

## Risk

**Low.** Pure presentation-layer change. No new API calls, no scoring changes, no data model changes. The only risk is copy quality — phrases that mislead or editorialize would violate the "calm and contextualize" principle. All phrases are factual descriptions of common pollution source patterns.

## Backward Compatibility

Old snapshots without `ejscreen_context` in their result dict are safe — the template uses `{% set ejctx = result.ejscreen_context if result.ejscreen_context is defined else {} %}` which defaults to an empty dict, so no context annotations render for old data. The `_prepare_snapshot_for_display()` pipeline runs on all deserialization paths, so any snapshot viewed after this ships will get the enrichment.
