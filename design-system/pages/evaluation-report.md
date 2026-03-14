# Evaluation Report Page Overrides

Applies to: `templates/_result_sections.html` (included by both `index.html` and `snapshot.html`), `templates/snapshot.html`

## Layout
- Two-column grid at >= 1200px: main content (1fr) + sticky sidebar (280-340px)
- Single column below 1200px; sidebar hidden
- Report content max-width: 1100-1120px, centered

## Specific Rules

### Health Check Cards
- Full-width layout on all screen sizes
- Left border color indicates status (pass/warning/fail/not-scored)
- Tier 1 checks (direct proximity hazards): prominent cards with full detail + citations
- Tier 2 checks (EJScreen area indicators): collapsible compact section, auto-expands when non-CLEAR items exist
- "Why we check this" expandable sections use subtle borders, not background color changes

### Score Display
- Score badges right-aligned in section headers (dimension scorecards)
- All `/10` dimension scores display as integers (`%.0f`)
- Google Places star ratings keep one decimal (`%.1f`)
- Score ring (SVG) in sidebar uses band colors for the circular progress indicator
- Confidence indicators appear as small pills below dimension scores (`.cb--*` classes)

### Dimension Scorecards
- CSS grid: `auto-fill minmax(260px, 1fr)` — responsive without explicit breakpoints
- Colored left border matches band (exceptional/strong/moderate/limited/poor)
- Four display states: normal, not_scored ("—"), sparse ("Limited data"), suppressed (hidden)
- Collapses to single column at 640px

### Verdict Card
- Highest visual weight: larger shadow, more padding than section cards
- Narrative text uses `--type-l1` sizing (28px, weight 400) for calm, non-aggressive feel
- Band color applied to score number and band label only, not card background

### Map Embeds
- Sharp edges for maps (no border-radius)
- 1px border in `--color-border`
- Leaflet map height: 250px in sidebar rail

### Collapsible Sections
- Toggle uses subtle borders, not background color changes
- Collapse icon: inline SVG with CSS transform rotation
- `aria-expanded` attribute toggled on click
- Keyboard accessible (Enter/Space triggers toggle)

### Share/Export Bar
- Flat row of direct action buttons (Share, Copy, PDF, JSON, CSV, Compare)
- `.share-btn` class handles both `<button>` and `<a>` elements
- No dropdown menus — all actions visible

### Print
- Hide: search bar, share bar, sidebar rail, loading overlay
- Report layout: single column, max-width 800px
- Score colors must remain distinguishable in grayscale print
