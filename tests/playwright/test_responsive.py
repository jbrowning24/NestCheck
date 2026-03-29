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

MOBILE = {"width": 375, "height": 812}
TABLET = {"width": 768, "height": 1024}
DESKTOP = {"width": 1280, "height": 900}

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
        scrollers = page.locator(".venue-scroll")
        stacks = page.locator(".venue-stack")
        assert scrollers.count() + stacks.count() >= 1, (
            "No venue-scroll or venue-stack containers found"
        )
        if scrollers.count() >= 1:
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
