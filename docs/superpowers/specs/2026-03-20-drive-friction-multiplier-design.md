# NES-315: Drive-Only Friction Multiplier + Universal Access-Mode Annotations

**Status:** Approved
**Date:** 2026-03-20
**Linear:** [NES-315](https://linear.app/nestcheck/issue/NES-315)

## Problem

When the best option in a scored dimension requires driving, the score is inflated because the model treats drive-only access equivalently to walkable access. The expert panel (4/5 reviewers on the Princeton NJ evaluation) flagged fitness scoring 8/10 for an 8-minute drive as credibility-damaging. Users see a high score with no indication that the venue requires a car.

**Root cause:** `_FITNESS_DRIVE_KNOTS` maps a 0-5 min drive to 10/10 — identical to a 0-10 min walk. The piecewise curve has no ceiling reflecting the inherent friction of needing a car.

## Solution

Three-phase change: re-tune drive knots and add a universal ceiling (Phase 1), pass structured access-mode data to templates (Phase 2), render inline annotations on dimension cards (Phase 3).

### Scope

- **In scope:** Fitness drive scoring re-tune, universal `DRIVE_ONLY_CEILING` constant, structured access-mode fields in dimension result dicts, inline annotations on all 6 dimension cards.
- **Out of scope:** Wiring coffee/grocery drive fallbacks (knots exist in `scoring_config.py` but remain unwired). Transit drive scoring (already reasonable — drive proximity capped at 3/10). Road noise (not destination-based). Empty-state copy (NES-319).

### Dimensions affected

| Dimension | Scoring change | Annotation change |
|---|---|---|
| Fitness | Re-tuned drive knots + ceiling | Yes |
| Coffee | None (walk-only, unwired) | Yes (walk-time annotation when >15 min) |
| Grocery | None (walk-only, unwired) | Yes (walk-time annotation when >15 min) |
| Parks | None (composite daily_walk_value) | Yes (walk-time annotation when >15 min) |
| Transit | None (drive already capped at 3 pts) | No (commuter rail is expected to be driven to) |
| Road Noise | None (dBA-based) | No (not destination-based) |

---

## Phase 1: Re-tune Drive Knots + Universal Ceiling

### Constants

**New constant** in `scoring_config.py`:

```python
DRIVE_ONLY_CEILING = 6  # Policy: no dimension score exceeds this when best option requires driving
```

This is a universal policy constant, not fitness-specific. It fires today only for fitness (the only wired drive fallback), but protects against future drift if other dimensions get drive wiring.

### Knot changes

**`_FITNESS_DRIVE_KNOTS`** — ceiling drops from 10 to 6, decay curve preserved proportionally:

| Drive time | Current score | New score |
|---|---|---|
| 0 min | 10 | 6 |
| 5 min | 10 | 6 |
| 10 min | 8 | 5 |
| 15 min | 6 | 3 |
| 20 min | 3 | 1 |
| 25 min | 1 | 0 |
| 30 min | 0 | 0 |

```python
_FITNESS_DRIVE_KNOTS = (
    PiecewiseKnot(x=0, y=6),
    PiecewiseKnot(x=5, y=6),
    PiecewiseKnot(x=10, y=5),
    PiecewiseKnot(x=15, y=3),
    PiecewiseKnot(x=20, y=1),
    PiecewiseKnot(x=25, y=0),
    PiecewiseKnot(x=30, y=0),
)
```

**No changes** to `_COFFEE_DRIVE_KNOTS` or `_GROCERY_DRIVE_KNOTS` (unwired — they stay as-is for potential future use).

### Ceiling application

In `score_fitness_access()`, after the `max(walk_score, drive_score)` selection, apply the ceiling when the drive path wins:

```python
best_score = max(best_walk_score, best_drive_score)
if best_drive_score > best_walk_score:
    best_score = min(best_score, DRIVE_ONLY_CEILING)
```

The `min()` is redundant with the current knots (max knot value is 6 = ceiling) but makes the policy explicit. If someone later tweaks knots or quality multipliers, the ceiling still holds. The quality multiplier is applied before the ceiling: `drive_base * quality_multiplier` then `min(result, DRIVE_ONLY_CEILING)`.

### Score impact examples

| Scenario | Current | After |
|---|---|---|
| 4.5-star gym, 8 min drive, no walkable option | 8/10 | ~5/10 (knot ~5.4 at 8 min × 1.0 quality) |
| 4.0-star gym, 5 min drive, no walkable option | 8/10 | ~4.8/10 (6 × 0.8 quality) |
| 4.5-star gym, 12 min walk | 10/10 | 10/10 (unchanged — walk path) |
| 4.5-star gym, 18 min walk | ~7.2/10 | ~7.2/10 (unchanged — walk path) |

### Files changed

- `scoring_config.py` — `_FITNESS_DRIVE_KNOTS` values, new `DRIVE_ONLY_CEILING` constant
- `property_evaluator.py` — `min()` application in `score_fitness_access()` when drive path wins

### Verification

- Re-run the Princeton NJ address: fitness should drop from 8/10 to ~5-6/10.
- Run an address with a walkable gym (<20 min walk): score unchanged.
- Run the full ground truth test suite (463 tests) — expect some fitness score regressions in drive-dependent areas. These are intentional.

---

## Phase 2: Structured Access-Mode Data in Template Context

### Problem

The template currently receives a pre-formatted `summary` string (e.g., `"Equinox (4.5-star, 287 reviews) — 8 min drive"`). There are no structured fields for access mode, walk time, or drive time. Annotations need structured data to render conditionally.

### Changes

Add four fields to each dimension's result dict in `result_to_dict()`:

```python
{
    # Existing fields (unchanged)
    "name": "Fitness access",
    "score": 5,
    "max_score": 10,
    "summary": "Equinox (4.5-star, 287 reviews) — 8 min drive",
    "band": {"key": "moderate", "label": "Moderate — Some Trade-offs"},
    "data_confidence": "verified",

    # New fields (additive)
    "access_mode": "drive",          # "walk" | "drive" | None
    "walk_time_min": 32,             # int | None
    "drive_time_min": 8,             # int | None
    "venue_name": "Equinox",         # str | None
}
```

**Per-dimension sourcing:**

| Dimension | access_mode logic | walk_time source | drive_time source | venue_name source |
|---|---|---|---|---|
| Fitness | "drive" if drive path won, else "walk" | `best_walk_time` | `best_drive_time` (from NES-259 fallback) | `best_facility["name"]` |
| Coffee | Always "walk" (no drive wiring) | `best_walk_time` | None | `best_venue["name"]` |
| Grocery | Always "walk" (no drive wiring) | `best_walk_time` | None | `best_venue["name"]` |
| Parks | Always "walk" (composite path) | `best_park.walk_time_min` | None | `best_park.name` |
| Transit | Skip annotations (see Scope) | — | — | — |
| Road Noise | Skip annotations (see Scope) | — | — | — |

These fields are **additive** — the existing `summary` string is unchanged. If a field is absent or None, the template falls back to the summary string.

### Files changed

- `property_evaluator.py` — each scoring function populates new fields on `Tier2Score` or its `scoring_inputs` dict
- `app.py` (`result_to_dict()`) — passes new fields through to the template context dict

### What could break

Nothing — fields are additive. Template ignores fields it doesn't reference. Existing `summary` rendering is unchanged.

---

## Phase 3: Render Access-Mode Annotations

### Annotation rules

Three bands based on access mode and walk time:

| Condition | Annotation | Example |
|---|---|---|
| Walk time ≤ 15 min | None | (Walkable is the default — no explanation needed) |
| Walk time 16–25 min | "Best option is a {X}-min walk" | "Best option is an 18-min walk" |
| Drive-only (walk >25 min or no walkable option) | "Best option is a {X}-min drive — no walkable {category} at this address" | "Best option is an 8-min drive — no walkable fitness at this address" |

**Category names** for annotation copy: "fitness", "coffee shops", "grocery", "parks". These are lowercase, user-facing labels.

**Grammar:** Use "a" vs "an" correctly based on the number ("an 8-min", "a 14-min", "an 18-min", "a 22-min").

### Template rendering

Add annotation `<p>` below the existing `dim-card__detail` in `_result_sections.html`:

```html
{% if dim.summary %}
<p class="dim-card__detail">{{ dim.summary }}</p>
{% endif %}
{% if dim.access_mode == 'drive' %}
<p class="dim-card__annotation">
  Best option is a {{ dim.drive_time_min }}-min drive — no walkable {{ dim.category_label }} at this address
</p>
{% elif dim.access_mode == 'walk' and dim.walk_time_min and dim.walk_time_min > 15 %}
<p class="dim-card__annotation">
  Best option is a {{ dim.walk_time_min }}-min walk
</p>
{% endif %}
```

### Styling

Per UI spec Section 4.11 (annotation pattern):

```css
.dim-card__annotation {
    font-size: var(--type-detail);        /* 0.8125rem / 13px */
    color: var(--color-text-secondary);
    margin-top: 4px;
    margin-left: 4px;
    max-width: 120ch;
    line-height: 1.4;
}
```

### Additional template context field

Add `category_label` to the dimension result dict for annotation copy:

```python
"category_label": "fitness"  # "fitness" | "coffee shops" | "grocery" | "parks"
```

### Files changed

- `templates/_result_sections.html` — annotation `<p>` block
- `static/report.css` (or equivalent) — `.dim-card__annotation` styles
- `app.py` (`result_to_dict()`) — add `category_label` field

### What could break

Layout shift if annotation adds unexpected height to dimension cards. Test on:
- Mobile (single-column layout)
- Desktop (3-column grid)
- Cards with and without annotations side by side

---

## Implementation order

Phases are sequential — each builds on the prior:

1. **Phase 1** (scoring) — Can be verified independently via test suite and manual evaluation runs.
2. **Phase 2** (data plumbing) — Additive fields, no visible change. Verified by inspecting template context in debug mode.
3. **Phase 3** (template rendering) — Visible change. Verified by visual inspection on mobile and desktop.

## Test strategy

- **Unit tests:** New tests for `min(score, DRIVE_ONLY_CEILING)` logic, annotation band selection logic.
- **Regression:** Run full ground truth suite (463 tests). Expect fitness score drops in drive-dependent evaluations.
- **Manual verification:** Princeton NJ address (the panel evaluation that flagged the issue). Fitness should drop from 8/10 to ~5-6/10 with drive annotation.
- **Visual QA:** Check annotation rendering on mobile and desktop, with and without annotations, all annotation copy variants.
