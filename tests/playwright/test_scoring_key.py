"""Playwright tests for the scoring key card (NES-326)."""


def test_scoring_key_renders_below_verdict(page, healthy_report_url):
    """Scoring key card appears below verdict with 5 band rows."""
    page.goto(healthy_report_url)
    page.wait_for_load_state("networkidle")

    card = page.locator(".scoring-key").first
    assert card.is_visible()

    rows = card.locator(".scoring-key__row")
    assert rows.count() == 5


def test_scoring_key_active_row_matches_band(page, healthy_report_url):
    """The active row's band-dot class matches the verdict band (band-strong)."""
    page.goto(healthy_report_url)
    page.wait_for_load_state("networkidle")

    active_row = page.locator(".scoring-key__row--active").first
    assert active_row.is_visible()

    # The healthy fixture has score 74 = band-strong
    dot = active_row.locator(".band-dot")
    dot_classes = dot.get_attribute("class")
    assert "band-strong" in dot_classes


def test_scoring_key_has_how_we_score_link(page, healthy_report_url):
    """Footer link points to #how-we-score anchor."""
    page.goto(healthy_report_url)
    page.wait_for_load_state("networkidle")

    link = page.locator(".scoring-key__link").first
    assert link.is_visible()
    assert link.get_attribute("href") == "#how-we-score"
    assert "How we score" in link.inner_text()


def test_scoring_key_in_methodology_section(page, healthy_report_url):
    """How We Score section also uses the scoring key (no active row)."""
    page.goto(healthy_report_url)
    page.wait_for_load_state("networkidle")

    methodology = page.locator("#how-we-score")
    methodology_key = methodology.locator(".scoring-key")
    assert methodology_key.is_visible()

    # No active row in the methodology section
    active_rows = methodology_key.locator(".scoring-key__row--active")
    assert active_rows.count() == 0


def test_scoring_key_each_row_has_range_and_description(page, healthy_report_url):
    """Each row shows a range (e.g., '85-100') and a description."""
    page.goto(healthy_report_url)
    page.wait_for_load_state("networkidle")

    rows = page.locator(".scoring-key").first.locator(".scoring-key__row")
    for i in range(rows.count()):
        row = rows.nth(i)
        assert row.locator(".scoring-key__range").inner_text().strip() != ""
        assert row.locator(".scoring-key__desc").inner_text().strip() != ""
