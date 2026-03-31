# NES-398: EJScreen/Superfund Visual Contradiction Fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the visual contradiction between a green checkmark on a passing Superfund address-level check and a warning triangle on the elevated EJScreen Superfund area-level indicator.

**Architecture:** When `_prepare_snapshot_for_display()` detects that an address-level check passes but the paired EJScreen percentile is elevated (>= threshold), it sets `icon_override = "info"` on the Tier 1 check dict. The template renders a blue info-circle badge instead of a green checkmark, and displays a caution callout (amber left-border) instead of the unstyled annotation. Tier 2 EJScreen icons are NOT changed — the area-level warning triangle is accurate at the area level.

**Tech Stack:** Python/Flask, Jinja2 templates, CSS custom properties

**Key decisions (CTO + CDO aligned):**
- New `"info"` icon type added to `health_check_icon` macro — blue (`--color-info`) info-circle badge
- Info badge renders at full size (no `--quiet` modifier) to draw attention
- Tier 1 annotation upgraded from `annotation()` to `callout(variant='caution')` for visual weight
- Tier 2 warning triangles left unchanged — area-level elevation is correctly represented
- Bridging text rewritten to explain address vs. area measurement distinction
- Threshold stays at 60 (deliberate CMO decision from NES-388 — 80th was too rare to resolve the perceived contradiction, 50th was noise)
- Existing tests fixed (4 tests failing because they assert `"Nth percentile"` but the current template produces `"higher than N%"` — the rewritten template text restores percentile language)

---

### Task 1: Add `"info"` icon type to health_check_icon macro

**Files:**
- Modify: `templates/_macros.html:297-305`
- Modify: `static/css/report.css:763`

- [ ] **Step 1: Add info SVG branch to the health_check_icon macro**

In `templates/_macros.html`, add an `elif` branch after the `warning` branch (line 302) and before the `else` (line 303):

```jinja2
    {%- elif icon_type == "info" -%}
      <circle cx="10" cy="10" r="7" /><line x1="10" y1="9" x2="10" y2="14" /><circle cx="10" cy="6.5" r="0.8" fill="white" stroke="none" />
```

The final macro should have branches: `clear`, `issue`, `warning`, `info`, then `else` (unverified).

- [ ] **Step 2: Add `.health-icon-badge--info` CSS class**

In `static/css/report.css`, add after line 763 (`.health-icon-badge--unverified`):

```css
.health-icon-badge--info { background: var(--color-info); }
```

- [ ] **Step 3: Verify visually (manual)**

The info icon should render as a blue (#2563EB) rounded-square badge with a white stroke circle containing a white "i" (line + dot). Same dimensions as other health check icons (24×24 badge, 14×14 SVG).

- [ ] **Step 4: Commit**

```bash
git add templates/_macros.html static/css/report.css
git commit -m "feat(NES-398): add info icon type to health_check_icon macro

Blue info-circle badge for checks that pass at address level but
have notable area-level context. Uses --color-info token."
```

---

### Task 2: Set icon_override in _prepare_snapshot_for_display

**Files:**
- Modify: `app.py:2323-2328`

- [ ] **Step 1: Add icon_override alongside area_context_annotation**

In `app.py`, in the `_prepare_snapshot_for_display` function, find the inner loop at lines 2323-2328:

```python
            for pc in result["presented_checks"]:
                if (pc.get("name") in xref["address_checks"]
                        and pc.get("result_type") == "CLEAR"):
                    pc["area_context_annotation"] = xref["template"].format(
                        pct=int(pct)
                    )
```

Add one line after the annotation assignment:

```python
            for pc in result["presented_checks"]:
                if (pc.get("name") in xref["address_checks"]
                        and pc.get("result_type") == "CLEAR"):
                    pc["area_context_annotation"] = xref["template"].format(
                        pct=int(pct)
                    )
                    pc["icon_override"] = "info"
```

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "feat(NES-398): set icon_override on cross-referenced passing checks

When address-level check is CLEAR but paired EJScreen indicator is
elevated, override the green checkmark with the info icon."
```

---

### Task 3: Update template to use icon_override and caution callout

**Files:**
- Modify: `templates/_result_sections.html:258-259, 276-278`

- [ ] **Step 1: Update icon selection to respect icon_override**

In `templates/_result_sections.html`, replace lines 258-259:

```jinja2
                  {% set _icon = {"CLEAR":"clear","CONFIRMED_ISSUE":"issue","WARNING_DETECTED":"warning"}.get(pc.result_type, "unverified") %}
                  {{ health_check_icon(_icon, quiet=(pc.result_type == 'CLEAR')) }}
```

With:

```jinja2
                  {% set _icon = pc.icon_override | default({"CLEAR":"clear","CONFIRMED_ISSUE":"issue","WARNING_DETECTED":"warning"}.get(pc.result_type, "unverified")) %}
                  {{ health_check_icon(_icon, quiet=(pc.result_type == 'CLEAR' and _icon == 'clear')) }}
```

This does two things:
1. Uses `icon_override` when present, falls back to the existing mapping
2. Only applies the `quiet` modifier when the icon is actually `clear` (not overridden to `info`)

- [ ] **Step 2: Replace annotation with caution callout**

In `templates/_result_sections.html`, replace lines 276-278:

```jinja2
                {% if pc.area_context_annotation is defined and pc.area_context_annotation %}
                  {{ annotation(pc.area_context_annotation) }}
                {% endif %}
```

With:

```jinja2
                {% if pc.area_context_annotation is defined and pc.area_context_annotation %}
                  {{ callout(variant='caution', icon='<svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="7"/><line x1="10" y1="9" x2="10" y2="14"/><circle cx="10" cy="6.5" r="0.8" fill="currentColor" stroke="none"/></svg>', text=pc.area_context_annotation) }}
                {% endif %}
```

The callout renders with an amber left border and light amber background — visually prominent, clearly distinct from the green checkmark it replaces.

- [ ] **Step 3: Commit**

```bash
git add templates/_result_sections.html
git commit -m "feat(NES-398): use icon_override and caution callout in health checks

- Icon respects icon_override field, skips quiet modifier when overridden
- Cross-reference annotation upgraded from unstyled annotation() to
  callout(variant='caution') with info icon for visual prominence"
```

---

### Task 4: Rewrite bridging text templates

**Files:**
- Modify: `app.py:955-983`

- [ ] **Step 1: Update the cross-reference template strings**

In `app.py`, replace the `_EJSCREEN_CROSS_REFS` config (lines 955-983). Preserve all three entries (Superfund/PNPL, TRI+UST/PTSDF, High-traffic road/PTRAF) and keep the threshold at 60 (deliberate CMO decision from NES-388):

```python
_EJSCREEN_CROSS_REFS = [
    {
        "address_checks": ["Superfund (NPL)"],
        "ejscreen_field": "PNPL",
        "threshold": 60,
        "template": (
            "This address is not inside a Superfund cleanup boundary. "
            "The wider census area ranks in the {pct}th percentile "
            "nationally for proximity to listed sites."
        ),
    },
    {
        "address_checks": ["TRI facility", "ust_proximity"],
        "ejscreen_field": "PTSDF",
        "threshold": 60,
        "template": (
            "No hazardous facilities found at this address. "
            "The wider census area ranks in the {pct}th percentile "
            "nationally for hazardous waste proximity."
        ),
    },
    {
        "address_checks": ["High-traffic road"],
        "ejscreen_field": "PTRAF",
        "threshold": 60,
        "template": (
            "No high-traffic roads found near this address. "
            "The wider census area ranks in the {pct}th percentile "
            "nationally for traffic proximity."
        ),
    },
]
```

Key changes:
- Template text explicitly distinguishes address-level vs area-level measurement
- Uses `"{pct}th percentile"` phrasing (clearer than `"higher than {pct}%"`)
- Removed "but" conjunction that implied contradiction
- Threshold stays at 60 per CMO decision — the visual fixes (info icon + callout) are what resolve the contradiction, not threshold tuning
- All three cross-reference pairs preserved (Superfund/PNPL, TRI+UST/PTSDF, High-traffic road/PTRAF)

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "fix(NES-398): rewrite bridging text for address vs area clarity

Text now explicitly explains address-level vs area-level distinction.
Uses 'Nth percentile' phrasing. Threshold stays at 60 per NES-388."
```

---

### Task 5: Fix and extend cross-reference tests

**Files:**
- Modify: `tests/test_app_helpers.py:530-653`

**Context:** 4 existing tests are failing because they assert `"Nth percentile"` in the annotation text, but the current code (pre-NES-398) produces `"higher than N%"`. Task 4's template rewrite restores percentile language, which will fix these assertions. This task also adds `icon_override` assertions and new negative tests.

- [ ] **Step 1: Update test assertions for new template text + add icon_override checks**

In `test_superfund_clear_high_pnpl_gets_annotation` (line 563-564), replace:
```python
        assert "area_context_annotation" in pc
        assert "94th percentile" in pc["area_context_annotation"]
```
With:
```python
        assert "area_context_annotation" in pc
        assert "94th percentile" in pc["area_context_annotation"]
        assert pc.get("icon_override") == "info"
```

In `test_superfund_fail_high_pnpl_no_annotation` (line 577), add after the existing assertion:
```python
        assert "area_context_annotation" not in pc
        assert "icon_override" not in pc
```

In `test_tri_and_ust_both_get_ptsdf_annotation` (line 591-593), replace:
```python
        assert "area_context_annotation" in tri
        assert "area_context_annotation" in ust
        assert "85th percentile" in tri["area_context_annotation"]
```
With:
```python
        assert "area_context_annotation" in tri
        assert "area_context_annotation" in ust
        assert "85th percentile" in tri["area_context_annotation"]
        assert tri.get("icon_override") == "info"
        assert ust.get("icon_override") == "info"
```

In `test_below_threshold_no_annotation` (line 606), add after the existing assertion:
```python
        assert "area_context_annotation" not in pc
        assert "icon_override" not in pc
```

In `test_no_ejscreen_data_no_annotation` (line 619), add after the existing assertion:
```python
        assert "area_context_annotation" not in pc
        assert "icon_override" not in pc
```

In `test_threshold_boundary_fires` (line 632-633), replace:
```python
        assert "area_context_annotation" in pc
        assert "80th percentile" in pc["area_context_annotation"]
```
With:
```python
        assert "area_context_annotation" in pc
        assert "60th percentile" in pc["area_context_annotation"]
        assert pc.get("icon_override") == "info"
```

Note: boundary test uses `PNPL: 80.0` but threshold is 60 — update test data to use `PNPL: 60.0` for a true boundary test:
```python
            ejscreen_profile={"PNPL": 60.0},
```

In `test_old_snapshot_without_presented_checks` (line 652-653), replace:
```python
        assert "area_context_annotation" in pc
        assert "90th percentile" in pc["area_context_annotation"]
```
With:
```python
        assert "area_context_annotation" in pc
        assert "90th percentile" in pc["area_context_annotation"]
        assert pc.get("icon_override") == "info"
```

- [ ] **Step 2: Add test for value between old-80 and current-60 threshold**

Add a new test to verify that values in the 60-79 range DO fire (validating the 60 threshold):

```python
    def test_moderate_percentile_still_fires(self):
        """PNPL at 72 (above 60 threshold) → annotation + icon_override."""
        result = self._result_with_checks(
            [("Superfund (NPL)", "PASS", "Clear")],
            ejscreen_profile={"PNPL": 72.0},
        )
        _prepare_snapshot_for_display(result)
        pc = next(
            p for p in result["presented_checks"]
            if p["name"] == "Superfund (NPL)"
        )
        assert "area_context_annotation" in pc
        assert "72nd percentile" in pc["area_context_annotation"]
        assert pc.get("icon_override") == "info"
```

- [ ] **Step 3: Add test for failing check not getting icon_override**

```python
    def test_fail_check_no_icon_override(self):
        """Failing check → no icon_override even with high PNPL."""
        result = self._result_with_checks(
            [("Superfund (NPL)", "FAIL", "Within Superfund site")],
            ejscreen_profile={"PNPL": 94.0},
        )
        _prepare_snapshot_for_display(result)
        pc = next(
            p for p in result["presented_checks"]
            if p["name"] == "Superfund (NPL)"
        )
        assert "icon_override" not in pc
```

- [ ] **Step 4: Run all cross-reference tests**

Run: `python -m pytest tests/test_app_helpers.py::TestEJScreenCrossRef -v`

Expected: All tests PASS (7 existing + 2 new = 9 total)

- [ ] **Step 5: Commit**

```bash
git add tests/test_app_helpers.py
git commit -m "test(NES-398): fix and extend EJScreen cross-reference tests

- Fix 4 tests broken by prior template text change (now uses percentile)
- Add icon_override assertions to all positive and negative cases
- Add boundary test at 72nd percentile (between old-80 and current-60)
- Add failing-check negative test for icon_override"
```

---

### Task 6: Update CLAUDE.md

**Files:**
- Modify: `.claude/CLAUDE.md`

- [ ] **Step 1: Update the EJScreen cross-reference body text**

In `.claude/CLAUDE.md`, find the `_EJSCREEN_CROSS_REFS` documentation paragraph (line ~236) and update it to mention the `icon_override` field. Add after the sentence ending with `"result_type == "CLEAR"` checks.`:

```
When the cross-reference fires, `icon_override = "info"` is also set on the check dict — the template renders a blue info-circle badge instead of a green checkmark, and renders the annotation as a `callout(variant='caution')` instead of an `annotation()`.
```

- [ ] **Step 2: Add decision log entry**

Add to the decision log table:

```
| 2026-03 | EJScreen cross-ref visual contradiction fix (NES-398) | Green checkmark on passing address-level check + warning triangle on elevated area-level EJScreen was a persistent visual contradiction (flagged 5x by Owen). Fix: blue info-circle icon (`icon_override = "info"`) replaces green checkmark when cross-ref fires, annotation upgraded from unstyled `annotation()` to `callout(variant='caution')`. Tier 2 warning triangles unchanged — area-level elevation is correctly represented. Threshold stays at 60 per NES-388 CMO decision. Template checks `pc.icon_override | default(...)` and skips `--quiet` modifier when overridden |
```

- [ ] **Step 3: Commit**

```bash
git add .claude/CLAUDE.md
git commit -m "docs(NES-398): update CLAUDE.md with icon_override pattern and decision log"
```
