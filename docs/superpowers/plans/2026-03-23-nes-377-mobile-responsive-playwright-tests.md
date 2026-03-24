# NES-377: Mobile Viewport + Responsive Playwright Tests

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Playwright tests that verify CSS breakpoint behavior across mobile, tablet, and desktop viewports.

**Architecture:** Single test file `tests/playwright/test_responsive.py` with three test classes (mobile/tablet/desktop). Reuses existing conftest fixtures (`healthy_report_url`, live Flask server). Layout assertions use `bounding_box()` for position checks and `page.evaluate()` for computed CSS styles.

**Tech Stack:** Playwright Python, pytest, existing Flask test server infrastructure

**Spec:** `docs/superpowers/specs/2026-03-23-nes-377-mobile-responsive-playwright-tests-design.md`

---

## File Structure

- **Create:** `tests/playwright/test_responsive.py` — all responsive tests (3 classes, ~12 tests)
- **Read-only reference:** `tests/playwright/conftest.py` — existing fixtures (healthy_report_url, base_url, browser_context_args)
- **Read-only reference:** `tests/playwright/test_report_rendering.py` — existing patterns to follow
- **Read-only reference:** `static/css/snapshot.css` — rail breakpoint at 1072px, sticky top: 80px
- **Read-only reference:** `static/css/report.css` — tab bar, dimension grid, venue scroll breakpoints

---

### Task 1: Mobile viewport tests

**Files:**
- Create: `tests/playwright/test_responsive.py`

- [ ] **Step 1: Write TestMobileViewport class with all 6 tests**

```python
"""Playwright tests for responsive layout behavior across viewports.

Verifies CSS breakpoint behavior: component visibility, grid column counts,
and sticky positioning at mobile (375px), tablet (768px), and desktop (1280px).

Key breakpoints (from snapshot.css and report.css):
  - 1072px: tab bar hides, rail shows
  - 640px:  dimension grid collapses to single column
"""
from pathlib import Path
from playwright.sync_api import Page, expect

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"

# Viewport constants
MOBILE = {"width": 375, "height": 812}
TABLET = {"width": 768, "height": 1024}
DESKTOP = {"width": 1280, "height": 900}

# Minimum expected tabs in the mobile tab bar (healthy fixture has all sections)
EXPECTED_TAB_LABELS = ["Verdict", "Health", "Dimensions", "Neighborhood",
                       "Getting Around", "Parks", "Scoring"]


class TestMobileViewport:
    """Layout tests at 375x812 (iPhone 14 equivalent)."""

    def test_tab_bar_visible(self, page: Page, healthy_report_url):
        """Mobile tab bar is visible below the 1072px breakpoint."""
        page.set_viewport_size(MOBILE)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        tab_bar = page.locator(".mobile-tab-bar")
        expect(tab_bar).to_be_visible()

    def test_tab_bar_has_expected_tabs(self, page: Page, healthy_report_url):
        """Tab bar contains the expected navigation tabs."""
        page.set_viewport_size(MOBILE)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        links = page.locator(".mobile-tab__link")
        tab_texts = [links.nth(i).text_content().strip()
                     for i in range(links.count())]
        for label in EXPECTED_TAB_LABELS:
            assert label in tab_texts, f"Missing tab: {label}. Found: {tab_texts}"

    def test_rail_hidden(self, page: Page, healthy_report_url):
        """Desktop rail is hidden on mobile (display: none below 1072px)."""
        page.set_viewport_size(MOBILE)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        rail = page.locator(".report-layout__rail")
        expect(rail).not_to_be_visible()

    def test_dimension_cards_single_column(self, page: Page, healthy_report_url):
        """Dimension cards stack in a single column at 375px (below 640px breakpoint)."""
        page.set_viewport_size(MOBILE)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        cards = page.locator(".dim-card")
        assert cards.count() >= 2, "Need at least 2 dim-cards to check layout"
        # All visible cards should share the same x offset (single column)
        x_offsets = set()
        for i in range(cards.count()):
            card = cards.nth(i)
            if card.is_visible():
                box = card.bounding_box()
                if box:
                    x_offsets.add(round(box["x"]))
        assert len(x_offsets) == 1, (
            f"Expected single column (1 x-offset), got {len(x_offsets)}: {x_offsets}"
        )

    def test_venue_scroll_horizontal(self, page: Page, healthy_report_url):
        """Venue scroll containers have horizontal overflow enabled."""
        page.set_viewport_size(MOBILE)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        # Target non-static scroll containers only
        scrollers = page.locator(".venue-scroll:not(.venue-scroll--static)")
        if scrollers.count() == 0:
            # Fall back to any venue-scroll if no non-static ones
            scrollers = page.locator(".venue-scroll")
        assert scrollers.count() >= 1, "No venue-scroll containers found"
        overflow_x = scrollers.first.evaluate(
            "el => getComputedStyle(el).overflowX"
        )
        assert overflow_x in ("auto", "scroll"), (
            f"Expected overflow-x auto or scroll, got: {overflow_x}"
        )

    def test_screenshot_mobile_responsive(self, page: Page, healthy_report_url):
        """Capture mobile layout screenshot for visual baseline."""
        page.set_viewport_size(MOBILE)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        page.screenshot(
            path=str(SCREENSHOTS_DIR / "responsive_mobile.png"), full_page=True
        )
```

- [ ] **Step 2: Run mobile tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/playwright/test_responsive.py::TestMobileViewport -v`
Expected: 6 PASSED

- [ ] **Step 3: Commit mobile viewport tests**

```bash
cd /Users/jeremybrowning/NestCheck
git add tests/playwright/test_responsive.py
git commit -m "feat(NES-377): add mobile viewport Playwright tests

Tests tab bar visibility, rail hiding, single-column dimension grid,
venue scroll overflow, and mobile screenshot capture at 375x812."
```

---

### Task 2: Tablet viewport tests

**Files:**
- Modify: `tests/playwright/test_responsive.py`

- [ ] **Step 1: Add TestTabletViewport class**

Append after `TestMobileViewport`:

```python
class TestTabletViewport:
    """Layout tests at 768x1024 (iPad portrait)."""

    def test_tab_bar_still_visible(self, page: Page, healthy_report_url):
        """Tab bar is still visible at 768px (below 1072px breakpoint)."""
        page.set_viewport_size(TABLET)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        tab_bar = page.locator(".mobile-tab-bar")
        expect(tab_bar).to_be_visible()

    def test_rail_still_hidden(self, page: Page, healthy_report_url):
        """Rail is still hidden at 768px (below 1072px breakpoint)."""
        page.set_viewport_size(TABLET)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        rail = page.locator(".report-layout__rail")
        expect(rail).not_to_be_visible()

    def test_dimension_cards_multi_column(self, page: Page, healthy_report_url):
        """Dimension cards arrange in 2+ columns at 768px (above 640px breakpoint)."""
        page.set_viewport_size(TABLET)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        cards = page.locator(".dim-card")
        assert cards.count() >= 2, "Need at least 2 dim-cards to check layout"
        x_offsets = set()
        for i in range(cards.count()):
            card = cards.nth(i)
            if card.is_visible():
                box = card.bounding_box()
                if box:
                    x_offsets.add(round(box["x"]))
        assert len(x_offsets) >= 2, (
            f"Expected multi-column (2+ x-offsets), got {len(x_offsets)}: {x_offsets}"
        )
```

- [ ] **Step 2: Run tablet tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/playwright/test_responsive.py::TestTabletViewport -v`
Expected: 3 PASSED

- [ ] **Step 3: Commit tablet viewport tests**

```bash
cd /Users/jeremybrowning/NestCheck
git add tests/playwright/test_responsive.py
git commit -m "feat(NES-377): add tablet viewport Playwright tests

Tests tab bar/rail visibility at 768px and multi-column dimension grid."
```

---

### Task 3: Desktop viewport tests

**Files:**
- Modify: `tests/playwright/test_responsive.py`

- [ ] **Step 1: Add TestDesktopViewport class**

Append after `TestTabletViewport`:

```python
class TestDesktopViewport:
    """Layout tests at 1280x900 (standard desktop)."""

    def test_rail_visible(self, page: Page, healthy_report_url):
        """Desktop rail is visible above the 1072px breakpoint."""
        page.set_viewport_size(DESKTOP)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        rail = page.locator(".report-layout__rail")
        expect(rail).to_be_visible()

    def test_rail_sticky_with_offset(self, page: Page, healthy_report_url):
        """Rail has position: sticky with top: 80px at desktop width."""
        page.set_viewport_size(DESKTOP)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        rail = page.locator(".report-layout__rail")
        position = rail.evaluate("el => getComputedStyle(el).position")
        assert position == "sticky", f"Expected position: sticky, got: {position}"
        top = rail.evaluate("el => getComputedStyle(el).top")
        assert top == "80px", f"Expected top: 80px, got: {top}"

    def test_tab_bar_hidden(self, page: Page, healthy_report_url):
        """Mobile tab bar is hidden above the 1072px breakpoint."""
        page.set_viewport_size(DESKTOP)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        tab_bar = page.locator(".mobile-tab-bar")
        expect(tab_bar).not_to_be_visible()

    def test_dimension_cards_multi_column(self, page: Page, healthy_report_url):
        """Dimension cards arrange in multiple columns at 1280px."""
        page.set_viewport_size(DESKTOP)
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        cards = page.locator(".dim-card")
        assert cards.count() >= 2, "Need at least 2 dim-cards to check layout"
        x_offsets = set()
        for i in range(cards.count()):
            card = cards.nth(i)
            if card.is_visible():
                box = card.bounding_box()
                if box:
                    x_offsets.add(round(box["x"]))
        assert len(x_offsets) >= 2, (
            f"Expected multi-column (2+ x-offsets), got {len(x_offsets)}: {x_offsets}"
        )
```

- [ ] **Step 2: Run desktop tests to verify they pass**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/playwright/test_responsive.py::TestDesktopViewport -v`
Expected: 4 PASSED

- [ ] **Step 3: Commit desktop viewport tests**

```bash
cd /Users/jeremybrowning/NestCheck
git add tests/playwright/test_responsive.py
git commit -m "feat(NES-377): add desktop viewport Playwright tests

Tests rail visibility, sticky positioning with top:80px offset,
tab bar hiding, and multi-column dimension grid at 1280px."
```

---

### Task 4: Full suite verification

- [ ] **Step 1: Run the complete responsive test file**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/playwright/test_responsive.py -v`
Expected: 13 PASSED (6 mobile + 3 tablet + 4 desktop)

- [ ] **Step 2: Run all Playwright tests together to check no conflicts**

Run: `cd /Users/jeremybrowning/NestCheck && python -m pytest tests/playwright/ -v`
Expected: 39 PASSED (26 existing + 13 new), no failures

- [ ] **Step 3: Update Linear ticket status**

Mark NES-377 as Done in Linear.
