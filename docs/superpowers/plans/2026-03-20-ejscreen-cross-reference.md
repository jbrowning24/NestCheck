# EJScreen Cross-Reference Annotations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an address-level health check passes but the paired EJScreen area indicator is elevated (>= 80th percentile), show an inline annotation on the passing check card reconciling the two scales.

**Architecture:** Config-driven cross-reference mapping in `app.py`, injected at display time in `_prepare_snapshot_for_display()`, rendered via existing `annotation()` Jinja macro. No evaluator changes, no new components.

**Tech Stack:** Python (Flask), Jinja2 templates

**Spec:** `docs/superpowers/specs/2026-03-20-ejscreen-cross-reference-design.md`

---

### Task 1: Add cross-reference config and injection logic

**Files:**
- Modify: `app.py:818-819` (add `_EJSCREEN_CROSS_REFS` config after `_CHECK_RESULT_SEVERITY`)
- Modify: `app.py:2127-2128` (add annotation injection after hazard_tier backfill in `_prepare_snapshot_for_display()`)

- [ ] **Step 1: Write the failing test**

Add a new test class to `tests/test_app_helpers.py`. The test builds a minimal result dict with a passing Superfund check and an `ejscreen_profile` with PNPL at 94, then runs `_prepare_snapshot_for_display()` and asserts the annotation appears.

```python
# At top of file, add _prepare_snapshot_for_display to the import:
from app import (
    app,
    generate_verdict,
    generate_report_narrative,
    present_checks,
    suppress_unknown_safety_checks,
    _serialize_urban_access,
    result_to_dict,
    _prepare_snapshot_for_display,
)


# At bottom of file, add:

# ============================================================================
# EJScreen cross-reference annotations (NES-316)
# ============================================================================

class TestEJScreenCrossRef:
    """Tests for _EJSCREEN_CROSS_REFS annotation injection."""

    def _result_with_checks(self, checks, ejscreen_profile=None):
        """Build a minimal result dict suitable for _prepare_snapshot_for_display."""
        tier1 = [
            {"name": c[0], "result": c[1], "details": c[2]}
            for c in checks
        ]
        result = {
            "tier1_checks": tier1,
            "ejscreen_profile": ejscreen_profile,
            "passed_tier1": True,
            "final_score": 70,
            "address": "123 Test St",
        }
        # present_checks must run first (normally called inside _prepare_snapshot)
        result["presented_checks"] = present_checks(tier1)
        return result

    def test_superfund_clear_high_pnpl_gets_annotation(self):
        """Passing Superfund + PNPL >= 80 → annotation on the check card."""
        result = self._result_with_checks(
            [("Superfund (NPL)", "PASS", "Not within an EPA Superfund site")],
            ejscreen_profile={"PNPL": 94.0},
        )
        _prepare_snapshot_for_display(result)
        pc = next(
            p for p in result["presented_checks"]
            if p["name"] == "Superfund (NPL)"
        )
        assert "area_context_annotation" in pc
        assert "94th percentile" in pc["area_context_annotation"]

    def test_superfund_fail_high_pnpl_no_annotation(self):
        """Failing Superfund check → no annotation even with high PNPL."""
        result = self._result_with_checks(
            [("Superfund (NPL)", "FAIL", "Within Superfund site")],
            ejscreen_profile={"PNPL": 94.0},
        )
        _prepare_snapshot_for_display(result)
        pc = next(
            p for p in result["presented_checks"]
            if p["name"] == "Superfund (NPL)"
        )
        assert "area_context_annotation" not in pc

    def test_tri_and_ust_both_get_ptsdf_annotation(self):
        """Both TRI and UST pass + high PTSDF → both get annotations."""
        result = self._result_with_checks(
            [
                ("TRI facility", "PASS", "No TRI facility nearby"),
                ("ust_proximity", "PASS", "No UST nearby"),
            ],
            ejscreen_profile={"PTSDF": 85.0},
        )
        _prepare_snapshot_for_display(result)
        tri = next(p for p in result["presented_checks"] if p["name"] == "TRI facility")
        ust = next(p for p in result["presented_checks"] if p["name"] == "ust_proximity")
        assert "area_context_annotation" in tri
        assert "area_context_annotation" in ust
        assert "85th percentile" in tri["area_context_annotation"]

    def test_below_threshold_no_annotation(self):
        """PNPL below 80 → no annotation even on passing check."""
        result = self._result_with_checks(
            [("Superfund (NPL)", "PASS", "Clear")],
            ejscreen_profile={"PNPL": 45.0},
        )
        _prepare_snapshot_for_display(result)
        pc = next(
            p for p in result["presented_checks"]
            if p["name"] == "Superfund (NPL)"
        )
        assert "area_context_annotation" not in pc

    def test_no_ejscreen_data_no_annotation(self):
        """Missing ejscreen_profile → no annotation, no error."""
        result = self._result_with_checks(
            [("Superfund (NPL)", "PASS", "Clear")],
            ejscreen_profile=None,
        )
        _prepare_snapshot_for_display(result)
        pc = next(
            p for p in result["presented_checks"]
            if p["name"] == "Superfund (NPL)"
        )
        assert "area_context_annotation" not in pc

    def test_threshold_boundary_fires(self):
        """Exactly 80th percentile → annotation fires (>= threshold)."""
        result = self._result_with_checks(
            [("Superfund (NPL)", "PASS", "Clear")],
            ejscreen_profile={"PNPL": 80.0},
        )
        _prepare_snapshot_for_display(result)
        pc = next(
            p for p in result["presented_checks"]
            if p["name"] == "Superfund (NPL)"
        )
        assert "area_context_annotation" in pc
        assert "80th percentile" in pc["area_context_annotation"]

    def test_old_snapshot_without_presented_checks(self):
        """Old snapshot missing presented_checks → backfill + annotation."""
        result = {
            "tier1_checks": [
                {"name": "Superfund (NPL)", "result": "PASS",
                 "details": "Clear"},
            ],
            "ejscreen_profile": {"PNPL": 90.0},
            "passed_tier1": True,
            "final_score": 70,
            "address": "123 Test St",
        }
        # Do NOT pre-populate presented_checks — simulates old snapshot
        _prepare_snapshot_for_display(result)
        pc = next(
            p for p in result["presented_checks"]
            if p["name"] == "Superfund (NPL)"
        )
        assert "area_context_annotation" in pc
        assert "90th percentile" in pc["area_context_annotation"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_app_helpers.py::TestEJScreenCrossRef -v`
Expected: All 7 tests FAIL (6 original + 1 old-snapshot test) (most with `KeyError` or `area_context_annotation not in pc`)

- [ ] **Step 3: Add `_EJSCREEN_CROSS_REFS` config to `app.py`**

Insert after `_CHECK_RESULT_SEVERITY` (line 819), before the comparison view section:

```python
# ---------------------------------------------------------------------------
# EJScreen cross-reference: area-level annotations on passing address checks
# (NES-316)
# ---------------------------------------------------------------------------

_EJSCREEN_CROSS_REFS = [
    {
        "address_checks": ["Superfund (NPL)"],
        "ejscreen_field": "PNPL",
        "threshold": 80,
        "template": (
            "Address clear, but this area ranks {pct}th percentile "
            "nationally for Superfund proximity."
        ),
    },
    {
        "address_checks": ["TRI facility", "ust_proximity"],
        "ejscreen_field": "PTSDF",
        "threshold": 80,
        "template": (
            "No facilities in our buffer, but this area ranks {pct}th "
            "percentile nationally for hazardous waste proximity."
        ),
    },
]
```

- [ ] **Step 4: Add annotation injection to `_prepare_snapshot_for_display()`**

Insert **after** the NES-241 hazard_tier backfill (after line 2127), **before** the NES-210 migration calls:

```python
    # NES-316: Cross-reference EJScreen area indicators on passing checks.
    _ejscreen = result.get("ejscreen_profile")
    if _ejscreen:
        for xref in _EJSCREEN_CROSS_REFS:
            pct = _ejscreen.get(xref["ejscreen_field"])
            if pct is None or pct < xref["threshold"]:
                continue
            for pc in result["presented_checks"]:
                if (pc.get("name") in xref["address_checks"]
                        and pc.get("result_type") == "CLEAR"):
                    pc["area_context_annotation"] = xref["template"].format(
                        pct=int(pct)
                    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/test_app_helpers.py::TestEJScreenCrossRef -v`
Expected: All 7 tests PASS (6 original + 1 old-snapshot test)

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/ -v`
Expected: All existing tests still pass

- [ ] **Step 7: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add app.py tests/test_app_helpers.py
git commit -m "feat(NES-316): add EJScreen cross-reference annotations on passing health checks

When address-level checks pass but paired EJScreen area indicator is
>= 80th percentile, inject inline annotation on the check card.
Two pairs: Superfund/PNPL and TRI+UST/PTSDF.

Config-driven via _EJSCREEN_CROSS_REFS for future extensibility."
```

---

### Task 2: Render annotation in template

**Files:**
- Modify: `templates/_result_sections.html:241-242` (add annotation rendering between satellite link and health_context)

- [ ] **Step 1: Add `annotation` to the macro import**

In `templates/_result_sections.html` line 11, add `annotation` to the existing import:

```jinja2
{% from "_macros.html" import fmt_time, data_row, score_ring, school_card, health_check_icon, confidence_badge, coverage_badge, annotation %}
```

- [ ] **Step 2: Add annotation rendering to Tier 1 check card**

In `templates/_result_sections.html`, insert between the satellite-link `{% endif %}` (line 241) and the `{% if pc.health_context %}` block (line 242):

```jinja2
                {% if pc.area_context_annotation is defined and pc.area_context_annotation %}
                  {{ annotation(pc.area_context_annotation) }}
                {% endif %}
```

- [ ] **Step 3: Verify template renders without error**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/ -v`
Expected: All tests pass (template changes don't break existing rendering)

- [ ] **Step 4: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add templates/_result_sections.html
git commit -m "feat(NES-316): render EJScreen cross-reference annotation in health cards

Adds annotation() macro call on Tier 1 check cards when
area_context_annotation is present. Appears after the detail line,
before the 'Why we check this' collapsible."
```

---

### Task 3: Update CLAUDE.md with cross-reference pattern

**Files:**
- Modify: `CLAUDE.md` (add entry to Decision Log and a coding standard note)

- [ ] **Step 1: Add decision log entry**

Add to the Decision Log table in `CLAUDE.md`:

```
| 2026-03 | EJScreen cross-reference annotations (NES-316) | When address-level health checks pass but paired EJScreen area indicators are elevated (>= 80th percentile), inline annotations provide context on the passing check card. Two pairs: Superfund/PNPL and TRI+UST/PTSDF. Config-driven via `_EJSCREEN_CROSS_REFS` in `app.py` — adding a new pair is one dict entry. Annotations injected at display time in `_prepare_snapshot_for_display()` (after hazard_tier backfill to avoid dict rebuild dropping the key). Pass-only gate: annotations never appear on failing/warning checks |
```

- [ ] **Step 2: Add coding standard note**

Add to the Coding Standards section under Check Display Metadata:

```
- **EJScreen cross-reference annotations** (NES-316): `_EJSCREEN_CROSS_REFS` in `app.py` maps address-level check names to EJScreen indicator fields. Annotation injection in `_prepare_snapshot_for_display()` must run AFTER the NES-241 hazard_tier backfill (which rebuilds dicts via `{**pc, ...}`). Adding a new cross-reference pair: add one dict to `_EJSCREEN_CROSS_REFS` with `address_checks` (list of check names), `ejscreen_field`, `threshold` (percentile), and `template` (under 120 chars per UI spec Section 4.11). Annotations only fire on `result_type == "CLEAR"` checks.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/jeremybrowning/NestCheck
git add CLAUDE.md
git commit -m "docs(NES-316): add cross-reference pattern to CLAUDE.md"
```
