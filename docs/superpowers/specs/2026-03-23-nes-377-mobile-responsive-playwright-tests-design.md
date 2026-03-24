# NES-377: Mobile Viewport + Responsive Playwright Tests

## Summary

Add responsive Playwright tests that verify CSS breakpoint behavior across mobile (375px), tablet (768px), and desktop (1280px) viewports. Tests validate layout shifts, component visibility, and grid behavior — not content (content is covered by NES-376).

## Test File

`tests/playwright/test_responsive.py`

## Viewports

| Name | Width | Height | Rationale |
|------|-------|--------|-----------|
| Mobile | 375 | 812 | iPhone 14 equivalent |
| Tablet | 768 | 1024 | iPad portrait |
| Desktop | 1280 | 900 | From existing conftest default |

## Key Breakpoints (from CSS)

| Breakpoint | What changes |
|------------|-------------|
| 1072px | Tab bar hides, rail shows (primary mobile/desktop split) |
| 640px | Dimension grid collapses to single column |

## Test Classes

### TestMobileViewport (375x812)

Uses `healthy_report_url` fixture from existing conftest.

1. **Tab bar visible** — `.mobile-tab-bar` is visible
2. **Tab bar has expected tabs** — `.mobile-tab__link` elements include Verdict, Health, Dimensions at minimum
3. **Rail hidden** — `.report-layout__rail` is not visible (display: none)
4. **Dimension cards single column** — all `.dim-card` bounding boxes share the same x offset (stacked vertically)
5. **Venue scroll horizontal** — `.venue-scroll` has `overflow-x` computed as `auto` or `scroll`
6. **Screenshot** — mobile viewport screenshot saved for visual baseline

### TestTabletViewport (768x1024)

1. **Tab bar still visible** — 768 < 1072, so `.mobile-tab-bar` is visible
2. **Rail still hidden** — 768 < 1072
3. **Dimension cards multi-column** — `.dim-card` bounding boxes show at least 2 distinct x offsets (auto-fill produces 2+ columns at 768px)

### TestDesktopViewport (1280x900)

Uses the default viewport from conftest (no `set_viewport_size` needed).

1. **Rail visible** — `.report-layout__rail` is visible
2. **Rail is sticky** — computed `position` is `sticky`
3. **Tab bar hidden** — `.mobile-tab-bar` is not visible
4. **Dimension cards multi-column** — at least 2 distinct x offsets among `.dim-card` elements

## Approach

- Each test class sets viewport via `page.set_viewport_size()` at the start of each test (or via a class-level pattern)
- Layout assertions use `bounding_box()` for position checks and `evaluate()` for computed styles
- All tests use the `healthy_report_url` fixture (healthy report has all sections populated)
- Desktop tests can rely on the conftest default viewport (1280x900) — no explicit `set_viewport_size` needed

## Not in Scope

- Collapse/expand toggle behavior (toggles exist at all viewports — not mobile-specific)
- Content assertions (covered by NES-376 test_report_rendering.py)
- Scroll-triggered section navigation (JS behavior, not CSS layout)
- Visual regression diffing (screenshots are manual baselines)
