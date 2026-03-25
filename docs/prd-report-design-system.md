# Version 1.1 **March 2026**

**Revision from v1.0:** Adds Inter typeface decision, inline annotation pattern, empty/error states, scroll-aware navigation, scoring key as standalone card, mobile sticky nav spec, auto-fill dimension grid, and drill-down affordance pattern. Incorporates CDO review feedback.

**Scope:** Evaluation report surface. Covers token system, typography, color, spacing, component patterns, layout structure, responsive behavior, and error states. Does not cover content strategy, copywriting, or editorial voice.

**Audience:** CTO (implementation), CDO (design review), and any AI-assisted development tooling consuming this spec as a prompt or reference.

---

## 1. Design Philosophy

NestCheck is an information product for high-stakes decisions. Every design choice should be evaluated against one question: does this help the user understand what it would be like to live at this address?

### 1.1 Guiding Principles

These are listed in priority order. When two principles conflict, the higher-numbered principle yields to the lower.

1. **Trust through transparency.** Every score, badge, and assessment must be traceable to its data source. The user should never wonder where a number came from. Source attribution is a first-class design element, not a footnote.
2. **Information density over progressive disclosure.** Users are making a six-figure decision. Default to showing more, not less. Use hierarchy, grouping, and visual weight to make dense information scannable. Do not remove information to create simplicity. Exception: on mobile, secondary sections may collapse, but the health section always shows fully expanded.
3. **Health is visually primary.** The health and environment section gets the strongest visual treatment, the most prominent placement, and the most assertive design language when concerns are present. This is the product's differentiator and must feel like it.
4. **Spatial consistency.** When position, color, and typography encode meaning, that encoding must be identical everywhere it appears. A health pass badge looks and means the same thing in the verdict, the health section, and the snapshot. A user who learns the visual grammar in one section can navigate every other section by instinct.
5. **Color encodes meaning, not decoration.** Color is never arbitrary. The health severity scale is reserved for health. Band colors communicate scoring tiers. The accent color marks interactive elements. No color appears without a semantic role.
6. **Design for the skeptic.** No dark patterns. No persuasive nudges toward a conclusion. No green/red quality spectrum for non-health metrics. Neutral presentation for anything correlated with demographics or income.

### 1.2 What This Report Should Feel Like

The report should feel like it was prepared by a meticulous analyst who respects your intelligence. It is not a government form (too cold), not a marketing brochure (too slick), not a clinical readout (too sterile). It is a trusted advisor's briefing: comprehensive, organized, confident about what it knows, honest about what it doesn't.

Reference products that share this quality: Linear's issue detail view (information-dense, quiet, scannable), Stripe's documentation (layered depth, explanation adjacent to the thing explained), the Financial Times' annotated charts (data plus interpretation at the point of need).

### 1.3 Anti-Patterns

**Decoration without meaning.** No gradients, glows, animated beams, or visual effects that don't encode data. Every visual element either carries information or helps the user decode information.

**Component showcase syndrome.** Each section must use the same visual grammar as every other section. If parks get a radar chart, why don't dimensions? Consistency beats novelty.

**Confidence theater.** The report must not look more certain than the data warrants. When data coverage is limited, the design should communicate that honestly through data confidence indicators, not generate a uniform-looking score.

**Color as wallpaper.** Dimension cards should not have colored background fills. Color appears as accents (pills, thin bars, left borders), not surfaces.

---

## 2. Token System

All visual values are defined as CSS custom properties in `tokens.css`. No hardcoded hex values, pixel sizes, or font weights should appear in `report.css` or templates. The token file is the single source of truth.

### 2.1 Color Tokens

Colors are organized into five functional groups. Each group has a defined semantic purpose. Colors must not be used outside their assigned role.

#### 2.1.1 Brand & Interactive

|Token|Value|Usage|
|---|---|---|
|`--color-accent`|`#2563EB`|CTAs, links, interactive elements, focus rings|
|`--color-accent-hover`|`#1D4ED8`|Hover state for interactive elements|
|`--color-accent-light`|`#EFF6FF`|Light tint for selected states, active nav|

#### 2.1.2 Text Hierarchy

|Token|Value|Usage|
|---|---|---|
|`--color-text`|`#1E293B`|Primary text: headings, scores, place names|
|`--color-text-secondary`|`#475569`|Secondary text: descriptions, walk times, labels|
|`--color-text-tertiary`|`#94A3B8`|Tertiary text: citations, timestamps, captions|

#### 2.1.3 Health Severity Scale

This palette is reserved exclusively for health and environmental metrics. Never use these colors for non-health contexts. This is both a Fair Housing Act concern and a design coherence requirement.

|Token|Value|Background|Usage|
|---|---|---|---|
|`--color-health-pass`|`#16A34A`|`#F0FDF4`|All clear; no health concern detected|
|`--color-health-caution`|`#D97706`|`#FFFBEB`|Moderate concern; evidence contested or distance marginal|
|`--color-health-concern`|`#EA580C`|`#FFF7ED`|Elevated concern; within warning buffer distance|
|`--color-health-fail`|`#DC2626`|`#FEF2F2`|Hard fail; within evidence-based danger threshold|

**Rule:** Each severity level has a foreground (icon, text) and a background (card tint). The foreground is always the saturated color. The background is always the desaturated tint. These pairs are fixed and must not be mixed.

#### 2.1.4 Scoring Band Colors

Used for dimension score pills, progress bar accents, and band labels in the verdict section. These are informational, not evaluative. They communicate tiers, not quality judgments.

|Token|Value|Band|
|---|---|---|
|`--color-band-strong`|`#1D6B3F`|Strong (7–10)|
|`--color-band-moderate`|`#9A6700`|Moderate (4–6)|
|`--color-band-limited`|`#6B7280`|Limited (0–3)|

**Rule:** Band colors appear as text color on labels and as fill on small pills. They never appear as card background fills. White card backgrounds are universal; band color is accent-only.

#### 2.1.5 Surfaces & Borders

|Token|Value|Usage|
|---|---|---|
|`--color-surface`|`#FFFFFF`|Card backgrounds, primary surface|
|`--color-surface-alt`|`#F8FAFC`|Page background, recessed areas|
|`--color-surface-raised`|`#FFFFFF`|Elevated cards (with shadow)|
|`--color-border-light`|`#E2E8F0`|Card borders, dividers, table rules|
|`--color-border-medium`|`#CBD5E1`|Stronger dividers, input borders|

### 2.2 Typography Tokens

The primary typeface is **Inter**, loaded from Google Fonts at weights 400, 500, and 600. Inter was chosen for its optical sizing at small screens, its precision-without-coldness quality, and its proven use in high-density UI products (Linear, Figma documentation). It signals that someone made a deliberate typographic choice, which matters for a product that positions itself as a trusted advisor.

**Font loading:** Load via a single `<link>` tag to Google Fonts. Specify `font-display: swap`. This means the system font (`-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `Roboto`) renders immediately on page load, and Inter swaps in when loaded (∼200ms on most connections). For a server-rendered report that arrives complete, this brief visual shift is acceptable. Do not add font-loading optimization beyond `font-display: swap`.

**Fallback stack:** `Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`. The system fonts serve as the FOUT fallback and as the rendering face for any context where Inter fails to load (offline, blocked CDN, etc.).

**Monospace:** Addresses and raw data values use the system monospace stack: `ui-monospace, 'SF Mono', Menlo, Consolas, monospace`. No loaded monospace font.

#### 2.2.1 Type Scale

Five levels, each with a defined role. The scale creates clear visual separation between tiers without requiring decorative treatment.

|Token|Value|~px|Role|
|---|---|---|---|
|`--type-verdict`|`clamp(1.25rem, 2.5vw, 1.625rem)`|20–26|Narrative summary only. One instance per report.|
|`--type-section`|`0.75rem`|12|Section titles. Uppercase, wide-tracked. Labels, not headings.|
|`--type-heading`|`1.05rem`|~17|Dimension names, category labels, place names in cards.|
|`--type-body`|`0.9rem`|~14|Primary data: scores, check labels, key metrics.|
|`--type-detail`|`0.8rem`|~13|Supporting: walk times, ratings, subscore reasons.|
|`--type-caption`|`0.7rem`|~11|Citations, data sources, timestamps.|

#### 2.2.2 Weight Scale

|Token|Value|Usage|
|---|---|---|
|`--weight-normal`|`400`|Body text, descriptions, narrative prose|
|`--weight-medium`|`500`|Place names, check labels, pills, nav items|
|`--weight-semibold`|`600`|Scores, section titles, verdict score number|

#### 2.2.3 Letter Spacing

|Token|Value|Usage|
|---|---|---|
|`--tracking-section`|`0.08em`|Section titles (uppercase labels)|
|`--tracking-tight`|`-0.01em`|Verdict headline|
|`--tracking-normal`|`0`|Everything else|

### 2.3 Spacing Tokens

A constrained spacing scale prevents visual drift. All margin, padding, and gap values in `report.css` must reference these tokens. The scale is deliberately small; five values cover all needs.

|Token|Value|Usage|
|---|---|---|
|`--space-1`|`4px`|Tight: inline pill padding, icon-to-label gap|
|`--space-2`|`8px`|Compact: within-component gaps, badge margins|
|`--space-3`|`12px`|Standard: card internal padding (tight), row gaps|
|`--space-4`|`16px`|Comfortable: card padding, section internal margins|
|`--space-5`|`24px`|Generous: between-section gaps, page margins|
|`--space-6`|`32px`|Major: between report tiers (verdict → health → neighborhood)|

### 2.4 Shape Tokens

|Token|Value|Usage|
|---|---|---|
|`--radius-sm`|`4px`|Pills, badges, small interactive elements|
|`--radius-md`|`8px`|Cards, section containers, inputs|
|`--radius-lg`|`12px`|Verdict card, modal containers|
|`--radius-full`|`9999px`|Circular badges, avatar-like elements|

### 2.5 Elevation Tokens

Shadows are used sparingly. Most cards use borders, not shadows. Elevation is reserved for elements that float above the page plane.

|Token|Value|Usage|
|---|---|---|
|`--shadow-sm`|`0 1px 3px rgba(0,0,0,0.04)`|Card hover, subtle lift|
|`--shadow-md`|`0 4px 12px rgba(0,0,0,0.08)`|Verdict card, floating sidebar|

---

## 3. Report Layout Architecture

The evaluation report is a single-page, vertically-scrolling document with a fixed sidebar on desktop that collapses to top-of-page on mobile. The layout has three tiers, and the vertical gap between tiers is larger than the gap between sections within a tier.

### 3.1 Three-Tier Content Hierarchy

The report content is organized into three visual tiers. The spacing between tiers (`--space-6`: 32px) is larger than the spacing between sections within a tier (`--space-5`: 24px). This creates a visual rhythm that helps the reader distinguish major transitions from minor ones.

**Tier 1 — The Verdict (first viewport).** Score, narrative summary, and health status. This is what the user sees before scrolling. It should answer: "Is this place any good, and what's the catch?"

Components: overall score badge + band label, narrative summary paragraph (3–5 sentences from CMO), dimension score summary pills (e.g., "2 Strong · 2 Moderate · 2 Limited"), health status badge ("10 Clear" or "2 Concerns"), and a compact scoring key that explains what the bands mean. The scoring key links to a full methodology page.

**Tier 2 — The Analysis (scrollable depth).** Detailed breakdowns of each dimension and the full health section. This is where the report earns its price.

Sections in order: Health & Environment (always first in Tier 2 — this is the product differentiator), Dimension Scorecards (the 2×3 grid), Neighborhood Venues (cafés, groceries, fitness, parks as venue lists), Getting Around (transit, walkability summary), Parks & Green Space (primary park detail card + nearby list).

**Tier 3 — Context & Reference (below the fold).** Supporting information that enriches the picture but isn't part of the evaluation.

Sections: Area Context (demographic data from Census ACS — architecturally separated from scores per Fair Housing guardrails), scoring methodology summary, data sources and freshness, disclaimer.

### 3.2 Desktop Layout: Main + Sidebar

On viewports above 1024px, the report renders as a two-column layout. The main column holds the full report. The sidebar holds persistent context that the reader benefits from seeing regardless of scroll position.

**Main column:** `max-width: 720px`. Contains all three tiers of content.

**Sidebar:** `width: 280px`. `Position: sticky`, `top: 80px` (below nav). Contains: (1) Map with address pin, (2) Walkability summary widget (walk times + verdict), (3) Quick-nav links to report sections.

**Gap between columns:** `--space-5` (24px).

The sidebar is not a miniature version of the report. It holds exactly three things: geographic orientation (map), mobility summary (walkability), and navigation. Nothing else should be added to the sidebar without explicit CDO approval.

**Architectural requirement (build-it-right-the-first-time):** Every report section must render its summary data in semantic markup with stable IDs that the `IntersectionObserver` can target. The following IDs are implemented and wired into both the desktop rail nav (`_report_rail.html`) and mobile tab bar (`_tab_bar.html`) via `data-section` attributes:

* `#verdict` — verdict card
* `#health-safety` — health & environment section
* `#section-dimensions` — dimension scorecards grid
* `#your-neighborhood` — venue lists (coffee, grocery, fitness)
* `#getting-around` — transit + walkability
* `#parks-green-space` — parks & green space
* `#community-profile` — demographics / area context
* `#school-district` — school district data
* `#ejscreen-profile` — EJScreen environmental justice indicators
* `#emergency-services`, `#libraries`, `#pharmacies` — local services
* `#how-we-score` — scoring methodology

All IDs have `scroll-margin-top: 52px` applied at all breakpoints (not media-query-scoped) in `report.css`.

### 3.3 Mobile Layout: Single Column

Below 1024px, the sidebar collapses. The map moves to the top of Tier 1 (above the verdict). The walkability summary moves inline, positioned between the dimension scores and the health section. Section nav becomes a sticky horizontal tab bar at the top of the screen.

**Content width:** 100% with 16px horizontal padding.

**Health section:** Always fully expanded on mobile. No collapse. This is the product's differentiator and must be visible without interaction.

**Other sections:** May use collapse/expand. Default state: Tier 1 and Tier 2 expanded, Tier 3 collapsed with a clear "Show more" affordance.

### 3.4 Spacing Between Report Tiers

The three tiers are visually separated by a combination of larger vertical gaps and a subtle horizontal rule. This helps the reader feel the major transitions as they scroll.

|Boundary|Gap|Visual Treatment|
|---|---|---|
|Tier 1 → Tier 2|`--space-6` (32px)|1px rule in `--color-border-light`|
|Tier 2 → Tier 3|`--space-6` (32px)|1px rule in `--color-border-light` + muted background shift to `--color-surface-alt`|
|Between sections in same tier|`--space-5` (24px)|No rule; gap alone creates separation|

---

## 4. Component Patterns

The report uses a small set of reusable component patterns. Every element on the page is a composition of these primitives. When a new section or feature is built, it must use existing patterns or formally extend this spec. No one-off styling.

### 4.1 Verdict Card

The verdict card is the single most important component. It occupies the first viewport and answers the user's primary question.

**Structure:** Score badge (large, circular or rounded-square, with band color and score number) + band label ("Strong Daily Fit") to the left. Narrative summary paragraph (from CMO) below. Dimension summary pills ("4 Strong · 2 Moderate") below narrative. Health status badge at bottom of card.

**Score badge specs:** Width/height: 72px. Border-radius: `--radius-lg` (12px). Background: white. Border: 3px solid, using band color token. Score number: `--type-verdict` size, `--weight-semibold`, band color. Band label: `--type-body`, `--weight-medium`, `--color-text-secondary`, positioned below the badge.

**Card container:** `background: var(--color-surface)`. `border: 1px solid var(--color-border-light)`. `border-radius: var(--radius-lg)`. `padding: var(--space-5)`. `box-shadow: var(--shadow-md)`. No colored background fills.

### 4.2 Dimension Scorecard

Each of the six scored dimensions (green space, coffee/social, provisioning, fitness, road noise, urban access) renders as a compact card in a responsive grid.

**Layout:** `grid-template-columns: repeat(auto-fill, minmax(200px, 1fr))`. This naturally handles 5, 6, 7, or 8 cards as dimensions are added or removed. At 720px main column width, this produces 3 columns for 200px min-width cards. At 5 cards, the last card sits alone in the third row. The visual rhythm is slightly uneven but honest — the grid does not pad empty cards to fill.

**Card anatomy:**

- Dimension name (`--type-heading`, `--weight-medium`, `--color-text`).
- Score pill (e.g., "8/10", using band color for text, on a very light tinted background).
- Progress bar (4px height, band color fill, track in `--color-border-light`).
- Band label ("STRONG" / "MODERATE" / "LIMITED", `--type-caption`, uppercase, band color as text color).
- Detail line (top venue name · rating · walk time, `--type-detail`, `--color-text-secondary`).
- Confidence badge (if applicable).

**Card container:** `background: var(--color-surface)`. `border: 1px solid var(--color-border-light)`. `border-radius: var(--radius-md)`. `padding: var(--space-4)`. No colored background fills. Hover: `box-shadow: var(--shadow-sm)`.

**Critical rule:** Band color appears only on the score pill, the progress bar accent, and the band label text. The card background is always white. This was a specific design decision to move away from the "Google Sheet conditional formatting" look of colored card fills.

### 4.3 Health Check Row

The health section uses two tiers of checks with different visual treatments based on evidence strength.

#### 4.3.1 Tier 1 Checks (High-Evidence Hazards)

Gas stations, high-traffic roads, Superfund sites, FEMA flood zones, TRI facilities, UST proximity. These always render as individual cards regardless of status.

**Passing state:** Individual card per check. Background: `var(--color-surface)`. Border: `1px solid var(--color-border-light)`. Border-radius: `var(--radius-md)`. Padding: `14px 18px`. Icon: checkmark SVG, 28×28px, color: `var(--color-health-pass)`. Label: `--type-body`, `--weight-medium`. "Why we check this" toggle preserved. Distance data shown (e.g., "Nearest: Gardella Bros., 726 ft") in `--type-detail`, `--color-text-secondary`.

**Warning state:** Same card structure but: left border: `3px solid var(--color-health-caution)`. Background: `var(--color-health-caution-bg)`. Icon: warning triangle SVG, color: `var(--color-health-caution)`. Detail text explains the specific concern and distance. "What this means" expandable with plain-language interpretation.

**Fail state:** Same card structure but: left border: `3px solid var(--color-health-fail)`. Background: `var(--color-health-fail-bg)`. Icon: alert circle SVG, color: `var(--color-health-fail)`. Bold label text. Detail text includes specific hazard, distance, and evidence basis. Card expanded by default (no user interaction required to see the concern).

#### 4.3.2 Tier 2 Checks (Moderate/Contested Evidence)

Power lines, substations, cell towers, rail proximity, industrial zones. When all pass, these render as a compact group to avoid visual monotony.

**All-passing state:** Single collapsible section: "Additional checks (4 clear)." Toggle header: `--type-body`, `--weight-medium`, `--color-text-secondary`. When expanded, each item is a single-line row: checkmark icon + label. `--type-detail`. Padding: `8px 0`. Border-bottom: `1px solid var(--color-border-light)`. "Why we check this" still available per item.

**Any warning/fail:** The check with a concern graduates to individual card treatment (same specs as Tier 1 warning/fail). Remaining clear checks stay in compact group.

### 4.4 Venue Card

Used for cafes, groceries, fitness, and parks in the neighborhood section. Horizontal scrolling row of cards within each category.

**Card anatomy:** Venue name (`--type-heading`, `--weight-medium`, truncate with ellipsis at 2 lines). Rating (star icon + number, `--type-detail`, `--color-text-secondary`). Review count in parentheses. Walk/drive time pill.

**Time pill logic (critical rule):**

- If walk time ≤ 25 minutes: show walk time as primary. Pill text: "14 min walk." Color: `--color-text-secondary` on `--color-surface-alt` background.
- If walk time > 25 minutes: show drive time as primary. Pill text: "4 min drive." Style: same neutral treatment. Walk time available as secondary detail on tap/hover.
- Accessibility label: "Walkable," "Drive Only," or "Very Close" badge. The "Drive Only" badge uses `var(--color-surface-alt)` background and `var(--color-text-secondary)` text. It must NOT use `--color-health-fail` or any red tone. Driving to a park is not a health failure.

### 4.5 Park Detail Card

The primary park gets an expanded card with quality subscoring. This is one of NestCheck's most distinctive features and deserves a carefully designed component.

**Structure:** Park name (`--type-heading`, `--weight-semibold`). Rating + review count. Walk time pill. Daily Value score. Four subscores in a 2×2 grid: Walk Time, Size & Loop Potential, Quality, Nature Feel.

**Subscore rendering:** Each subscore uses a consistent pattern: label (`--type-detail`, `--weight-medium`), score as filled/unfilled segments (e.g., ●●○ for 2/3), and a one-line rationale (`--type-detail`, `--weight-normal`, `--color-text-secondary`). The filled/unfilled segment pattern is the universal scoring visualization. It must be visually identical to any other instance of fractional scoring in the report.

**Container:** `background: var(--color-surface)`. `border: 1px solid var(--color-border-light)`. `border-radius: var(--radius-md)`. `padding: var(--space-4)`. Same card treatment as dimension scorecards. The park card is not a special snowflake; it is a standard card with more content inside.

### 4.6 Data Row

The universal pattern for displaying a single item with a label, a key metric, and optional secondary detail. This replaces the proliferation of `.place-item`, `.hub-row`, `.dimension-row`, and `.proximity-item` patterns.

**Anatomy:** Icon (optional, 16–20px, left-aligned) + Primary label (`--type-body`, `--weight-medium`) + Secondary detail (`--type-detail`, `--color-text-secondary`, below or inline) + Right-aligned value/badge (score, walk time pill, or status icon).

**CSS:** `display: flex`. `align-items: center`. `padding: var(--space-3) 0`. `border-bottom: 1px solid var(--color-border-light)`. Gap between icon and label: `var(--space-2)`. The last item in a group drops the border-bottom.

This pattern covers: health check items, transit station rows, nearby park list items, and any future list-style content. The visual grammar is always: left icon, label text, right-aligned value. Consistent everywhere.

### 4.7 Informational Callout

A reusable component for non-dismissible informational messages. Established in the sign-in callout on the landing page; applies across surfaces.

**Anatomy:** Left border accent (3px solid, color varies by context). Icon (20px, optional, left-aligned). Text content (`--type-body`, `--color-text-secondary`). Background: `var(--color-surface-alt)`. Padding: `var(--space-3) var(--space-4)`. Border-radius: `var(--radius-sm)` on right side only.

**Variants:**

- **Neutral** (border: `--color-accent`): general information, sign-in prompts.
- **Caution** (border: `--color-health-caution`): data confidence warnings, flood zone verification prompts.

This component is not a CTA block. It does not have a dismiss button. It is not fully clickable. Inline links within the text are permitted.

### 4.8 Confidence Badge

Indicates the reliability of a score based on data coverage. Three tiers.

**Verified (high confidence):** No badge. The absence of a badge means the data is solid. Only surfaces if the same report has Estimated or Sparse badges elsewhere, to establish contrast.

**Estimated (moderate confidence):** Small pill: "Estimated." Background: `var(--color-surface-alt)`. Color: `var(--color-text-tertiary)`. Font: `--type-caption`. Tooltip (desktop) or tap-to-reveal (mobile) with reason.

**Sparse (low confidence):** Same pill pattern: "Sparse data." Border: `1px dashed var(--color-border-medium)`. This is the only use of dashed borders in the design system; it visually communicates incompleteness.

### 4.9 Section Container

Wraps each report section (Health & Environment, Neighborhood, Getting Around, Parks, etc.).

**Structure:** Section label (`--type-section`, uppercase, `--tracking-section`, `--color-text-tertiary`). Content area below. No box/border around the section itself; sections are delineated by the section label and vertical spacing.

**Collapsible variant:** Section label becomes a toggle. Chevron SVG (12×12, stroke: currentColor, stroke-width: 1.5) to the left of the label. Rotates 90° on expand via CSS transform with 200ms ease transition. Toggle target: the label row, not just the chevron.

The section container is deliberately minimal. It creates structure through spacing and typography, not through borders or background colors. This keeps the page feeling like a continuous document rather than a stack of boxed-off modules.

### 4.10 Scoring Key (Standalone Card)

A compact reference for what the score bands mean. Rendered as a standalone card directly below the verdict card, not inside it. This gives the scoring key breathing room and establishes it as a distinct reference element that the user encounters before scrolling into Tier 2.

**Container:** `background: var(--color-surface-alt)`. `border-top: 1px solid var(--color-border-light)`. `border-radius: var(--radius-md)`. `padding: var(--space-3) var(--space-4)`. `margin-bottom: var(--space-6)`.

**Structure:** Five rows, each with: colored dot (8px circle, band color), band label ("Exceptional"), score range ("85–100"), one-line description. All in `--type-detail`. Total height: approximately 100px. Link at bottom: "How we score →" in `--color-accent`.

This component is not the full methodology. It is a quick-reference decoder ring that helps first-time readers understand what a 77 or a 55 means. The full methodology (data sources, weighting, thresholds) lives on a dedicated page.

### 4.11 Inline Annotation

The annotation is where NestCheck's editorial voice lives at the point of need. It transforms the report from "here's data, you figure it out" to "here's data, and here's what it means for your daily life." This is the NestCheck equivalent of the Financial Times' annotated charts.

**Anatomy:** A single sentence in `--type-detail`, `--color-text-secondary`, `--weight-normal`. Indented 4px from the left edge of its parent data point (aligning with the detail line, not the label). No icon, no border, no background. The annotation is visually subordinate to the data it explains — it reads as a parenthetical, not a callout.

**Placement:** Annotations appear below the data point they interpret, never beside it. Separated from the data by `--space-1` (4px) — tight enough to read as attached, loose enough to not collide.

**Character limit:** Maximum 120 characters per annotation. This forces tight writing, prevents annotations from becoming paragraphs, and keeps visual weight subordinate. If an interpretation needs more than 120 characters, it belongs in a "What this means" expandable, not an inline annotation.

**Color rule:** All annotations use `--color-text-secondary`, including those on health checks in caution/fail state. The card's left border and icon already carry the severity signal. Coloring annotation text in the severity color would double-encode and make the annotation feel like an alarm rather than an explanation. The annotation's job is to calm and contextualize, not to amplify.

**Where annotations appear in v1:**

- Dimension scorecards with score ≤ 3 (constraint callout, e.g., "Nearest grocery is nearly 1 hour on foot").
- Health checks in caution or fail state (contextualizing the risk, e.g., "Zone X-shaded means moderate risk. Flood insurance is typically recommended but not required").
- Walkability summary when car-dependent ("Most residents drive for daily errands at this distance").
- Flood zone unverified state (what it means practically).

**Content rules (for CMO):** Annotations interpret, they don't editorialize. "Most residents drive for daily errands at this distance" is good. "This is a terrible location for groceries" is not. The tone is informative, not judgmental — consistent with the product's "opinionated on health, neutral on everything else" stance.

### 4.12 Empty and Error States

NestCheck's integrity depends on showing what it doesn't know. An absent data state that looks like a zero score, or worse, a missing section with no explanation, destroys trust faster than any other design bug. This section defines the design for every data failure mode.

**Design principle:** Every failure mode maps to a user-facing state. The design follows from the failure taxonomy, not the component library.

#### 4.12.1 Failure Taxonomy

**F1. API temporarily unavailable (Walk Score, Google Places, Overpass).** Cause: upstream service is down, rate-limited, or timing out. The data could exist but we can't reach it right now. User-facing state: Informational callout (caution variant) in the affected section. Message pattern: "[Dimension] data is temporarily unavailable. This dimension is not included in your score." The dimension scorecard renders with a dashed border (same as "Sparse data" confidence badge), no score pill, and the text "Unavailable" in `--color-text-tertiary` where the score would be. Score impact: The overall score is computed from available dimensions only, with the denominator adjusted. The scoring key annotation notes: "Score based on [N] of 6 dimensions — [dimension] data was unavailable."

**F2. Data source stale or outdated (EJScreen annual refresh, Census ACS lag).** Cause: bulk data hasn't been refreshed on schedule. The data exists but may be 6–18 months old. User-facing state: Data freshness indicator on the affected section. Pattern: a caption-level line below the section label: "Data from [source], last updated [date]." Uses `--type-caption`, `--color-text-tertiary`. This is informational, not a warning — it's expected that Census data is 12–18 months stale.

**F3. Google Places returning incorrect or absent POI data.** Cause: Places API returns a closed business, a misclassified POI (corporate office tagged as "park"), or no results for a category. User-facing state for zero results: The venue scroll section renders an empty state card (same card dimensions as a venue card) with text: "No [category] found within search radius." Background: `--color-surface-alt`. Text: `--color-text-tertiary`. No score pill on the dimension card — replaced with "No data" in `--color-text-tertiary`. User-facing state for suspected bad data: If the evaluator's confidence heuristic flags a result as potentially misclassified, show the venue card with a caution confidence badge and an annotation: "This result may be misclassified. Verify before relying on it."

**F4. Health check with no data source coverage.** Cause: A health check (e.g., flood zone) cannot be evaluated because the data source doesn't cover this area, or the API returned no geometry. User-facing state: The health check card renders in the caution variant (left border in `--color-health-caution`, background in `--color-health-caution-bg`). Icon: question mark circle, not checkmark. Label: "[Check type] could not be verified." Annotation: actionable next step ("Use the satellite link to check manually" or "Consult your home inspector"). This check is explicitly excluded from the "N Clear" count and instead counted separately: "9 Clear · 1 Unverified."

**F5. Entire section has insufficient data to render.** Cause: No transit stations found, no parks found within radius, or critical data pipeline failure. User-facing state: The section container renders with its label, followed by a single data row with an info icon (16px, `--color-text-tertiary`) and explanation text: "We couldn't find [transit options / parks / etc.] near this address. [Contextual sentence, e.g., 'Driving will likely be the primary way to get around.']" This is not an error — it's a legitimate evaluation result (the absence of transit IS the finding).

**F6. Complete evaluation failure.** Cause: Geocoding fails, address is unrecognizable, or a critical backend error prevents any evaluation. User-facing state: No report renders. A full-page error state appears with: NestCheck logo, the entered address, and a message: "We couldn't evaluate this address. This may be due to a temporary issue or an address we don't support yet." A "Try again" button (`--color-accent`, primary button style) and a "Report a problem" link (`--color-text-secondary`, text link). No score, no sections, no partial report.

#### 4.12.2 Implementation Note

Section 3.2 defines the semantic ID requirement for section summaries. That architectural decision applies here: every error/empty state must also be identifiable by ID so that the sidebar (current and future) can reference the state. For example, a health check in the "Unverified" state should have `id="health-check-flood-unverified"` so the sidebar health badge can reflect "9 Clear · 1 Unverified" without DOM parsing.

### 4.13 Drill-Down Affordance

A consistent visual cue that communicates "there's more detail available if you want it." Defines the pattern now; applies it in v1 only where destination content exists.

**Visual pattern:** A 12×12 external-link or arrow SVG icon, rendered in `--color-text-tertiary` by default. On hover/focus (desktop): transitions to `--color-accent` over 100ms ease. On mobile: always visible in `--color-text-tertiary` (no hover state). The icon sits inline after the clickable text, separated by `--space-1` (4px).

**Visibility model:** Desktop: the icon is visible on hover/focus of its parent element, invisible otherwise. This follows the Wikipedia model — drill-down affordances exist but don't add visual noise during normal reading. Mobile: always visible, since hover is not available.

**v1 applications (content exists):**

- Health check "Why we check this" (already built, in-place expansion).
- Scoring methodology "How we score →" link (links to dedicated page).
- Data source attribution links (links to source websites).

**v1.1 applications (content to be built):**

- Dimension score drill-down (methodology per dimension).
- Park quality subscore drill-down (how walk time, loop potential, quality, and nature feel are computed).
- Health check evidence basis (peer-reviewed research citations).

### 4.14 Walkability Summary Widget (Sidebar)

A compact sidebar widget that synthesizes the walk times scattered across dimension cards into a single walkability verdict. This is NestCheck's own assessment based on actual walk times to the specific best options the report identifies — distinct from Walk Score, which measures proximity to generic amenity categories.

**Destinations shown:** Five rows, one per scored daily-needs dimension: Coffee, Groceries, Fitness, Parks, Transit. Each row shows the dimension label and the walk time to the best option in that category.

**Color-coding:** Walk times under 20 minutes: `--color-band-strong` (green). Walk times 20–25 minutes: `--color-band-moderate` (amber). Walk times over 25 minutes or drive-only: rendered in `--color-text-secondary` with no color coding — the absence of color signals that this dimension is not walkable.

**Verdict label:** A one-line verdict above the walk time rows. Three options based on how many of the 5 dimensions have walk times ≤ 25 min: "Most daily needs are walkable" (≥ 4 of 5), "Mixed — some walkable, some need driving" (2–3 of 5), "Car-dependent — most errands need driving" (0–1 of 5). Verdict text: `--type-body`, `--weight-medium`, color matches the majority band.

**Container:** `background: var(--color-surface)`. `border: 0.5px solid var(--color-border-light)`. `border-radius: var(--radius-md)`. `padding: var(--space-3) var(--space-4)`. Sits in the sidebar between the map and the section nav.

**Link:** No drill-down link in v1. In v1.1, links to the Getting Around section via anchor.

---

## 5. Iconography

All icons are inline SVGs defined in `_macros.html`. No icon fonts, no external sprite sheets, no emoji. SVGs render crisply at all sizes and inherit color from their parent via `currentColor`.

### 5.1 Icon Style Rules

**Stroke-based, not filled.** Icons use stroke outlines (stroke-width: 1.5–2) rather than solid fills. This matches the restrained, informational tone of the product. Filled icons feel heavier and more decorative.

**Size scale:** 16px (inline with text, data rows), 20px (standard component icons, callouts), 28px (health check icons in Tier 1 cards). No other sizes without CDO approval.

**Color:** Icons inherit color via `currentColor` from their parent element. Health check icons use the severity token (pass/caution/concern/fail). All other icons use `--color-text-secondary`.

**No decorative icons.** Every icon communicates a category (health, transit, park, café) or a status (pass, warning, fail, expand). If an icon doesn't help the user decode the adjacent content, remove it.

### 5.2 Health Check Icon Set

Each health check type has a distinct icon that identifies the hazard category at a glance. The icon family should feel cohesive: same stroke weight, same level of detail, same visual density.

Gas station: fuel pump. High-traffic road: road with speed lines. Superfund: hazard diamond. Flood zone: water waves. TRI facility: factory chimney. UST: underground tank cross-section. Power line: transmission tower. Substation: transformer box. Cell tower: antenna. Rail: train tracks. Industrial: factory building. Road noise: sound waves.

**Status overlay:** when a check passes, the icon renders in `--color-health-pass`. No additional checkmark overlay is needed; the color carries the status. When a check warns or fails, the icon renders in the appropriate severity color and a small status indicator (triangle for warning, circle-X for fail) appears in the bottom-right corner of the icon at 10px size.

### 5.3 Interaction Icons

**Chevron (expand/collapse):** 12×12 SVG. Polyline: `points="4,2 8,6 4,10"`. Stroke: `currentColor`. Stroke-width: 1.5. Stroke-linecap: round. Rotates 90° clockwise when expanded. Transition: `transform 200ms ease`.

**External link:** 12×12 SVG. Arrow pointing up-right from a square. Used for "Why we check this" and source attribution links.

**Info circle:** 16×16 SVG. Used for confidence badge tooltips and methodology links.

---

## 6. Responsive Behavior

Three breakpoints. Design mobile-first, then adapt for tablet and desktop.

|Breakpoint|Width|Layout Changes|
|---|---|---|
|Mobile|< 640px|Single column. Dimension grid: 1 column. Venue cards: horizontal scroll. Map: full width above verdict.|
|Tablet|640–1023px|Single column, wider. Dimension grid: 2 columns. Sidebar content moves inline.|
|Desktop|≥ 1024px|Two-column: main (720px max) + sidebar (280px). Dimension grid: 3 columns. Sidebar: sticky.|

### 6.1 Mobile-Specific Rules

**Health section:** Always expanded. No collapse toggle. Tier 1 checks show as full cards. Tier 2 compact group still collapses.

**Venue cards:** Horizontal scroll with snap points. Card min-width: 200px. Show 1.5 cards visible to signal scrollability.

**Park subscores:** 2×2 grid becomes 1 column stack.

**Confidence badges:** Tap-to-reveal detail (no hover on mobile). 200ms fade-in.

**Typography:** `--type-verdict` uses the lower end of its clamp range (1.25rem). All other sizes hold constant.

**Dimension grid:** `auto-fill` naturally stacks to 1 column below 640px via the `minmax(200px, 1fr)` rule.

### 6.2 Mobile Sticky Tab Bar

On mobile (< 1024px), the sidebar section nav transforms into a sticky horizontal tab bar at the top of the viewport. This is the primary navigation affordance on mobile and requires precise specification.

**Container:** `height: 44px` (iOS touch target minimum). `background: var(--color-surface)`. `border-bottom: 1px solid var(--color-border-light)`. No box-shadow. `position: sticky`. `top: 0`. `z-index: 100`. `overflow-x: auto`. `-webkit-overflow-scrolling: touch`. `scroll-snap-type: x proximity`.

**Tabs:** `display: inline-flex`. `gap: 0`. Each tab: `padding: 0 var(--space-4)`. `height: 44px`. `display: flex`. `align-items: center`. `font-size: --type-caption` (11px). `font-weight: --weight-medium` (500). `color: var(--color-text-tertiary)`. `white-space: nowrap`. `border-bottom: 2px solid transparent`. `transition: color 100ms ease, border-color 100ms ease`.

**Active tab:** `color: var(--color-accent)`. `border-bottom: 2px solid var(--color-accent)`. `font-weight: --weight-medium` (500). No background change — the underline is the active indicator.

**Tab order:** Verdict, Health, Dimensions, Neighborhood, Getting Around, Parks, Context. Health is always the second tab.

**Scroll behavior on tap:** smooth scroll to the section heading, with offset = tab bar height (44px) + 8px buffer. Use `scroll-margin-top: 52px` on section headings in CSS.

**Active state updates on scroll:** IntersectionObserver on section headings. `rootMargin: "-52px 0px -70% 0px"`. The -52px accounts for the sticky bar height. The -70% bottom margin means the active section updates when ~30% of the section heading is visible, preventing the "I'm at the bottom of health but nav says parks" mismatch.

### 6.3 Desktop Scroll-Aware Sidebar Nav

On desktop (≥ 1024px), the sidebar section nav items highlight based on which section is currently in view. This provides spatial orientation without decorative animation.

**Active state:** The nav item for the currently visible section gets: `background: var(--color-accent-light, #EFF6FF)`. `border-left: 2px solid var(--color-accent)`. `color: var(--color-text)` (promoted from `--color-text-secondary`). `Transition: background 100ms ease`. The transition is a state change, not an animation.

**Observer logic:** Same IntersectionObserver as mobile tab bar, shared in a single JS module. The observer fires a callback that updates both the mobile tab bar active state and the desktop sidebar nav active state. One observer, two consumers.

**Implementation:** ∼20 lines of vanilla JS. No library needed. The CTO should implement this as a small self-contained module (e.g., `section-observer.js`) that initializes on DOMContentLoaded and attaches to both nav surfaces.

---

## 7. Interaction & Motion

Motion is minimal and functional. It communicates state changes, not personality. The report is a static document that the user reads; it is not an app that the user operates. Every animation must be achievable with CSS transitions and vanilla JS.

### 7.1 Permitted Transitions

|Element|Property|Duration|Easing|
|---|---|---|---|
|Chevron rotation|`transform`|200ms|ease|
|Section expand/collapse|`max-height`, `opacity`|250ms|ease-in-out|
|Card hover shadow|`box-shadow`|150ms|ease|
|Link/button hover|`color`, `background`|100ms|ease|
|Tooltip/badge detail|`opacity`|200ms|ease|

### 7.2 Prohibited Motion

No entrance animations (fade-in on scroll, slide-up on load). No parallax. No animated counters for scores. No bouncing, pulsing, or attention-seeking motion. No skeleton loading screens (the report is server-rendered and arrives complete). The report should feel like it was always there, waiting for you.

### 7.3 prefers-reduced-motion

All transitions must respect the user's motion preference. Wrap all transition/animation properties in a media query:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 8. Accessibility Requirements

These are non-negotiable implementation requirements, not aspirational guidelines.

### 8.1 Color Contrast

**Text contrast:** All text must meet WCAG 2.1 AA minimum contrast ratios. Normal text (≤ 18px): 4.5:1 against background. Large text (> 18px bold or > 24px normal): 3:1 against background.

**Health severity colors:** All four severity colors (pass green, caution amber, concern orange, fail red) have been selected to meet 4.5:1 contrast on white backgrounds. Do not lighten these values.

**Band colors on pills:** If band color is used as text on a tinted pill background, verify contrast. `--color-band-strong` (`#1D6B3F`) on white: 7.2:1 (passes). `--color-band-moderate` (`#9A6700`) on white: 5.3:1 (passes). `--color-band-limited` (`#6B7280`) on white: 4.6:1 (passes).

### 8.2 Semantic HTML

**Headings:** use `<h2>` for report section titles, `<h3>` for subsection titles. Never skip heading levels. The `<h1>` is the address.

**Landmark regions:** `<main>` wraps the report. `<nav>` wraps section navigation. `<aside>` wraps the sidebar. `<footer>` wraps the disclaimer and data sources.

**Health checks:** use `<ul>` for the check list. Each check is an `<li>`. The status (pass/warn/fail) is communicated via `aria-label` on the icon, not just color.

**Expand/collapse:** toggle buttons must have `aria-expanded="true"/"false"` and `aria-controls` pointing to the collapsible content's ID.

### 8.3 Keyboard Navigation

All interactive elements (expand toggles, links, tooltip triggers) must be reachable via Tab and activatable via Enter/Space. Focus indicators: 2px solid outline in `--color-accent` with 2px offset. Never remove focus outlines.

### 8.4 Screen Reader Considerations

**Score badges:** include `aria-label` like "Overall score: 77 out of 100, Strong Daily Fit."

**Health check icons:** `aria-label` describing the status, e.g., "No gas stations nearby — clear."

**Decorative SVGs** (progress bars, dividers): `aria-hidden="true"`.

**Venue cards in horizontal scroll:** the scroll container has `role="list"` and each card has `role="listitem"`. Include a visually-hidden heading before the scroll: "Café options near this address."

---

## 9. Implementation Notes for CTO

This section translates design decisions into concrete technical requirements for the Flask/Jinja2 stack.

### 9.1 CSS Architecture

**File structure:**

- `tokens.css` — all custom properties (this spec, Section 2). Loaded first.
- `base.css` — reset, nav, typography utility classes, shared components (callout, badge, data-row).
- `report.css` — report-specific: verdict card, dimension grid, health section, venue cards, park detail.

Both `index.html` and `snapshot.html` link to the same three files. No inline `<style>` blocks in templates except for truly page-specific overrides (`pricing.html` may have its own `pricing.css`). This eliminates the ∼500-line CSS duplication between index and snapshot.

### 9.2 Component Mapping to Templates

|Component|Template|Notes|
|---|---|---|
|Verdict card|`_result_sections.html`|First rendered section in results|
|Dimension scorecard|`_result_sections.html`|Jinja2 loop over dimension data|
|Health check row|`_result_sections.html`|Conditional tier logic from Python|
|Venue card|`_result_sections.html`|Horizontal scroll container|
|Park detail card|`_result_sections.html`|Subscore grid inside card|
|Data row|`_macros.html`|Jinja2 macro: `data_row(icon, label, detail, value)`|
|Informational callout|`_macros.html`|Jinja2 macro: `callout(variant, icon, text)`|
|Confidence badge|`_macros.html`|Jinja2 macro: `confidence_badge(tier, reason)`|
|SVG icons|`_macros.html`|Jinja2 macros per icon, using `currentColor`|
|Inline annotation|`_macros.html`|Jinja2 macro: `annotation(text)`, renders below parent|
|Empty state card|`_macros.html`|Jinja2 macro: `empty_state(section, message)`|
|Drill-down affordance|`_macros.html`|Inline SVG icon macro, attached to clickable elements|
|Mobile tab bar|`_base.html` or `_nav.html`|Sticky nav, shared IntersectionObserver with sidebar|
|Scoring key card|`_result_sections.html`|Standalone card below verdict|
|Walkability widget|`_result_sections.html`|Sidebar widget; see Section 4.14 stub|

### 9.3 Token Enforcement Rule

No hardcoded color values (hex, rgb, hsl) in `report.css`. All values must reference tokens. A CI lint check or manual audit should flag any raw color value outside of `tokens.css`. The same applies to font sizes, spacing values, and border radii. If a value appears in `report.css` and it is not a `var()` reference, it is a bug.

### 9.4 Dark Mode

Not in scope for v1. However, the token architecture is designed to support it. When dark mode is implemented, `tokens.css` gains a `@media (prefers-color-scheme: dark)` block that overrides surface, text, and border tokens. All component CSS that references tokens adapts automatically. This is one of the core benefits of the token-based approach.

### 9.5 Print Stylesheet

Detailed print specification is deferred to v1.1. Print is a primary share path for a six-figure-decision document and will receive a full spec covering section order, Tier 3 inclusion/exclusion, dimension grid reflow, header/footer content, and verdict card print layout.

**Minimum requirements for v1 (CTO can implement as baseline):** `@media print` block in `report.css`. Remove sidebar (`display: none`). Remove sticky nav and mobile tab bar (`display: none`). Expand all collapsed sections (`max-height: none`, `overflow: visible`). Set all backgrounds to white. Ensure text uses `--color-text` (dark) for print contrast. Hide interactive elements (share bar, "Evaluate an address" CTA, cookie banner). Add a simple text header: "NestCheck · [Address] · Evaluated [Date]" at the top of the printed page.

---

## Appendix: Design Decisions Referenced

This spec codifies decisions made across multiple design review sessions. Each decision has been discussed, debated, and agreed upon. They are listed here for traceability.

|Decision|Rationale|
|---|---|
|White card backgrounds only|Colored fills on dimension cards create a "Google Sheet" look. Band color appears as accent (pills, bars, text), not surface.|
|Health severity scale is exclusive|Pass/caution/concern/fail colors are reserved for health. "Drive Only" park badges use neutral gray, not fail red.|
|25-minute walk/drive threshold|If walk time exceeds 25 min, lead with drive time. Below 25 min, lead with walk time. Walkability is the default; driving is the fallback.|
|No third-party Walk Score display|NestCheck's own walk-time-based walkability verdict avoids competing numbers that measure different things.|
|Walkability summary in sidebar|Persistent context. Not a full section. Walk times + verdict label. Visible at all scroll positions on desktop.|
|Health Tier 1 always visible|High-evidence hazards show individual cards even when passing. Trust comes from showing every check, not hiding the passing ones.|
|Health Tier 2 compact when clear|Moderate/contested evidence checks collapse into a group to avoid visual monotony. Expand on warning/fail.|
|No animated entrance effects|Motion is for state changes (expand/collapse, hover). Not for entrance. The report is a static document, not an app.|
|Informational callout pattern|Left-border accent, no dismiss, not fully clickable. Established as a reusable component distinct from CTA blocks.|
|Filled/unfilled segments for subscores|Universal fractional scoring visualization. Same pattern for park quality, dimension subscores, and any future fractional display.|
|Demographics separated from scores|Fair Housing Act architectural guardrail. Census data on separate Tier 3 context section. Never adjacent to evaluation scores.|
|Data confidence as design feature|Per PRD: confidence indicators are first-class, not footnotes. Three tiers: Verified (no badge), Estimated (pill), Sparse (dashed pill).|
|System fonts → Inter (revised v1.1)|v1.0 chose system fonts for performance. Revised after CDO review: system defaults read as "nobody made a choice." Inter chosen for deliberate typographic identity. System fonts retained as FOUT fallback.|
|Compact scoring key in verdict|Answers "Is this score good?" at point of need. Standalone card below verdict, not inside it. Full methodology on a linked page answers "Should I trust this score?"|
|Inter typeface, font-display: swap|System fonts read as "nobody made a choice." Inter (400/500/600) via Google Fonts signals deliberate design. font-display: swap for immediate content rendering.|
|Inline annotations at point of need|120-char max. `--color-text-secondary` always (no severity coloring). 4px indent below parent data. Calm and contextualize, never amplify.|
|Drill-down affordance: hover-visible|12px icon in `--color-text-tertiary`, visible on hover (desktop) or always (mobile). Apply only where destination content exists.|
|Empty states from failure taxonomy|Design follows from backend failure modes, not frontend components. Six failure types defined (F1–F6) with specific user-facing states.|
|auto-fill dimension grid|`repeat(auto-fill, minmax(200px, 1fr))` instead of fixed 3-column. Handles 5–8 cards naturally as dimensions change.|
|Section headings need semantic IDs|Build for future contextual sidebar. Summary data in markup with IDs that IntersectionObserver can reference. Build it right the first time.|

---

_NestCheck UI Design Specification v1.1 — March 2026_