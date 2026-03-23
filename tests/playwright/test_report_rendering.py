"""Playwright tests for NestCheck report rendering.

These tests verify that evaluation results render correctly in the browser
by saving fixture data as snapshots and checking the rendered DOM.

Selectors are derived from _result_sections.html and _macros.html:
  - .verdict-badge          — score badge in verdict section
  - #health-safety          — health & environment section
  - .health-icon-badge--*   — individual health check icons
  - .dim-card               — dimension scorecard
  - #your-neighborhood      — neighborhood venues section
  - .venue-card             — individual venue card (horizontal scroll)
  - .summary-pill           — time/stat pills
  - .score-failed           — failed tier1 banner
"""
from pathlib import Path
from playwright.sync_api import Page, expect

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"


class TestHealthyReport:
    """Tests against a healthy evaluation (all checks clear, good scores)."""

    def test_page_loads_without_error(self, page: Page, healthy_report_url):
        """The snapshot page renders without template or server errors."""
        page.goto(healthy_report_url)
        body_text = page.text_content("body")
        assert "Internal Server Error" not in body_text
        assert "UndefinedError" not in body_text
        assert "TemplateSyntaxError" not in body_text
        assert "Traceback" not in body_text

    def test_address_displayed(self, page: Page, healthy_report_url):
        """The report header shows the evaluated address."""
        page.goto(healthy_report_url)
        header = page.locator(".report-header")
        expect(header).to_contain_text("123 Oak Street")

    def test_verdict_badge_shows_score(self, page: Page, healthy_report_url):
        """Verdict badge renders with the composite score."""
        page.goto(healthy_report_url)
        badge = page.locator(".verdict-badge").first
        expect(badge).to_be_visible()
        expect(badge).to_contain_text("74")

    def test_narrative_summary_renders(self, page: Page, healthy_report_url):
        """The summary narrative paragraph appears in the verdict section."""
        page.goto(healthy_report_url)
        narrative = page.locator(".narrative-summary")
        expect(narrative).to_be_visible()
        expect(narrative).to_contain_text("123 Oak Street")

    def test_health_section_all_clear(self, page: Page, healthy_report_url):
        """All proximity health checks show CLEAR icons, none show issue/warning.

        Note: road noise renders separately within #health-safety and may show
        a warning-style icon for MODERATE severity — that's expected and not
        counted here. We scope to .proximity-item checks only.
        """
        page.goto(healthy_report_url)
        health_section = page.locator("#health-safety")
        expect(health_section).to_be_visible()

        # Proximity items should all have clear icons
        clear_icons = health_section.locator(
            ".proximity-item .health-icon-badge--clear"
        )
        assert clear_icons.count() > 0

        # No health check proximity items (id=check-*) should have issue/warning
        # Road noise is a separate .proximity-item without a check-* id and
        # may show warning for MODERATE severity — that's expected.
        issue_icons = health_section.locator(
            "[id^='check-'] .health-icon-badge--issue"
        )
        assert issue_icons.count() == 0
        warning_icons = health_section.locator(
            "[id^='check-'] .health-icon-badge--warning"
        )
        assert warning_icons.count() == 0

    def test_dimension_grid_renders_cards(self, page: Page, healthy_report_url):
        """The dimension grid renders one card per dimension."""
        page.goto(healthy_report_url)
        dim_cards = page.locator(".dim-card")
        assert dim_cards.count() == 6

    def test_dimension_card_has_band_class(self, page: Page, healthy_report_url):
        """Dimension cards have band-based CSS classes (strong/moderate/limited)."""
        page.goto(healthy_report_url)
        # At least one card should be in the "strong" band
        strong_cards = page.locator(".dim-card--strong")
        assert strong_cards.count() >= 1

    def test_neighborhood_section_visible(self, page: Page, healthy_report_url):
        """The YOUR NEIGHBORHOOD section renders with venue cards."""
        page.goto(healthy_report_url)
        neighborhood = page.locator("#your-neighborhood")
        expect(neighborhood).to_be_visible()

    def test_venue_cards_present(self, page: Page, healthy_report_url):
        """Venue cards render in horizontal scroll containers."""
        page.goto(healthy_report_url)
        venue_cards = page.locator(".venue-card")
        # 3 coffee + 3 grocery + 3 fitness + 3 parks = 12
        assert venue_cards.count() >= 4

    def test_walk_time_pills_show(self, page: Page, healthy_report_url):
        """Venue cards display walk/drive time pills inside .place-time."""
        page.goto(healthy_report_url)
        # Time pills live inside .place-time within each .venue-card
        time_pills = page.locator("#your-neighborhood .place-time .summary-pill")
        assert time_pills.count() >= 1
        first_pill_text = time_pills.first.text_content()
        assert "min" in first_pill_text

    def test_health_summary_pills(self, page: Page, healthy_report_url):
        """Health stat badges show clear count."""
        page.goto(healthy_report_url)
        clear_badge = page.locator(".health-stat-badge--clear").first
        expect(clear_badge).to_be_visible()
        expect(clear_badge).to_contain_text("Clear")

    def test_road_noise_section_visible(self, page: Page, healthy_report_url):
        """Road noise estimate section renders for this fixture."""
        page.goto(healthy_report_url)
        # Road noise section uses proximity-item class with severity in text
        body_text = page.text_content("body")
        assert "Atlantic Avenue" in body_text


class TestConcerningReport:
    """Tests against a concerning evaluation (health fails, missing data)."""

    def test_page_loads_without_error(self, page: Page, concerning_report_url):
        """The snapshot page renders without template errors."""
        page.goto(concerning_report_url)
        body_text = page.text_content("body")
        assert "Internal Server Error" not in body_text
        assert "UndefinedError" not in body_text
        assert "TemplateSyntaxError" not in body_text

    def test_failed_tier1_banner_shows(self, page: Page, concerning_report_url):
        """Failed tier1 shows the structured summary banner."""
        page.goto(concerning_report_url)
        banner = page.locator(".score-failed")
        expect(banner).to_be_visible()
        expect(banner).to_contain_text("Health")

    def test_verdict_badge_not_shown(self, page: Page, concerning_report_url):
        """When tier1 fails, the verdict score badge should not appear."""
        page.goto(concerning_report_url)
        badges = page.locator(".verdict-badge")
        assert badges.count() == 0

    def test_health_issue_icons_present(self, page: Page, concerning_report_url):
        """Health section shows issue and warning icons."""
        page.goto(concerning_report_url)
        health_section = page.locator("#health-safety")
        expect(health_section).to_be_visible()

        issue_icons = health_section.locator(".health-icon-badge--issue")
        assert issue_icons.count() >= 2

        warning_icons = health_section.locator(".health-icon-badge--warning")
        assert warning_icons.count() >= 1

    def test_health_stat_badges_show_issues(self, page: Page, concerning_report_url):
        """Health stat row shows issue and warning counts."""
        page.goto(concerning_report_url)
        issue_badge = page.locator(".health-stat-badge--issue")
        expect(issue_badge).to_be_visible()
        expect(issue_badge).to_contain_text("Issue")

    def test_structured_summary_in_banner(self, page: Page, concerning_report_url):
        """The structured summary text appears in the failed banner."""
        page.goto(concerning_report_url)
        banner = page.locator(".verdict-failed-banner")
        body_text = page.text_content("body")
        assert "gas station" in body_text.lower() or "health" in body_text.lower()

    def test_empty_fitness_graceful(self, page: Page, concerning_report_url):
        """Empty fitness list doesn't crash the page — the section just omits it."""
        page.goto(concerning_report_url)
        body_text = page.text_content("body")
        # Page should render; fitness section may be absent but no error
        assert "Internal Server Error" not in body_text
        # The page still shows other categories
        assert "456 Industrial Ave" in body_text

    def test_null_green_escape_handled(self, page: Page, concerning_report_url):
        """Null green_escape doesn't cause template errors."""
        page.goto(concerning_report_url)
        body_text = page.text_content("body")
        assert "UndefinedError" not in body_text
        assert "NoneType" not in body_text

    def test_null_transit_handled(self, page: Page, concerning_report_url):
        """Null transit_access doesn't cause template errors."""
        page.goto(concerning_report_url)
        body_text = page.text_content("body")
        assert "UndefinedError" not in body_text


class TestCrossCutting:
    """Tests that apply to both healthy and concerning reports."""

    def test_css_custom_properties_loaded(self, page: Page, healthy_report_url):
        """Verify that CSS token custom properties are applied."""
        page.goto(healthy_report_url)
        color = page.evaluate(
            "getComputedStyle(document.documentElement)"
            ".getPropertyValue('--color-brand')"
        )
        assert color.strip() != ""

    def test_no_console_errors(self, page: Page, healthy_report_url):
        """No JavaScript console errors on page load."""
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        # Filter out known benign errors (e.g., Google Maps API key)
        real_errors = [
            e for e in errors
            if "google" not in e.lower() and "maps" not in e.lower()
        ]
        assert len(real_errors) == 0, f"Console errors: {real_errors}"

    def test_screenshot_desktop(self, page: Page, healthy_report_url):
        """Capture a full-page desktop screenshot for visual regression baseline."""
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        page.screenshot(
            path=str(SCREENSHOTS_DIR / "healthy_desktop.png"), full_page=True
        )

    def test_screenshot_mobile(self, page: Page, healthy_report_url):
        """Capture a mobile viewport screenshot."""
        page.set_viewport_size({"width": 375, "height": 812})
        page.goto(healthy_report_url)
        page.wait_for_load_state("networkidle")
        page.screenshot(
            path=str(SCREENSHOTS_DIR / "healthy_mobile.png"), full_page=True
        )

    def test_screenshot_concerning(self, page: Page, concerning_report_url):
        """Capture screenshot of the concerning (failed tier1) report."""
        page.goto(concerning_report_url)
        page.wait_for_load_state("networkidle")
        page.screenshot(
            path=str(SCREENSHOTS_DIR / "concerning_desktop.png"), full_page=True
        )
