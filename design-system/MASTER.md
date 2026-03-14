# NestCheck Design System

## Design Philosophy

NestCheck's visual language conveys **trust, authority, and calm**. This is a health-and-safety evaluation report — not a SaaS dashboard or startup landing page. The aesthetic draws from medical reports and consumer protection documents: clean typography, restrained color, clear data hierarchy, and no visual noise. Every design choice should make the homebuyer feel informed and confident, never overwhelmed or sold to.

## Current State Audit

### What exists today (`tokens.css`)
The project already has a mature CSS custom property system in `static/css/tokens.css`, loaded first by `_base.html`. All page-specific CSS files reference these tokens. The design system documented here is a **formalization and extension** of what exists, not a replacement.

### Consistency assessment
- **tokens.css + base.css + report.css**: Highly consistent. Use CSS custom properties throughout.
- **index.css + pricing.css**: Intentionally divergent — these use a neutral monochrome sub-palette (`#111111`, `#8E8E8E`, `#B0B0B0`) that differs from the blue-tinted token system. Per the decision log, this is by design (structural tokens reused, palette colors explicit).
- **Font**: DM Sans is used universally (heading + body). JetBrains Mono for monospace/data.
- **Spacing**: 4px grid system, well-defined in tokens.

---

## Color Palette

### Core Colors
```css
--nc-primary: #0B1D3A;           /* Deep navy — brand, authority, trust */
--nc-primary-light: #1A3A5C;     /* Lighter navy — hover states */
--nc-primary-dark: #060F1F;      /* Darker navy — rare, pressed states */
--nc-accent: #2563EB;            /* Bright blue — CTAs, links, interactive */
--nc-accent-hover: #1D4ED8;      /* Accent hover state */
--nc-text: #0F172A;              /* Primary text — near-black, high contrast */
--nc-text-secondary: #475569;    /* Descriptions, supporting text */
--nc-text-muted: #64748B;        /* Explanations, lower-priority text */
--nc-text-faint: #94A3B8;        /* Labels, metadata, de-emphasized */
--nc-bg: #F8F9FB;                /* Page background — warm off-white */
--nc-bg-surface: #FFFFFF;        /* Card/section background */
--nc-bg-subtle: #F1F3F6;         /* Nested element background */
--nc-border: #E2E8F0;            /* Default border */
--nc-border-strong: #CBD5E1;     /* Emphasized borders */
--nc-border-light: #F0F2F5;      /* Subtle borders (card edges) */
```

**Mapping to existing tokens:**
| Design System Token | Existing `tokens.css` Variable |
|---|---|
| `--nc-primary` | `--color-brand` |
| `--nc-primary-light` | `--color-brand-light` |
| `--nc-accent` | `--color-accent` |
| `--nc-text` | `--color-text-primary` |
| `--nc-text-secondary` | `--color-text-secondary` |
| `--nc-text-muted` | `--color-text-muted` |
| `--nc-text-faint` | `--color-text-faint` |
| `--nc-bg` | `--color-bg-page` |
| `--nc-bg-surface` | `--color-bg-card` |
| `--nc-border` | `--color-border` |

### Health Status Colors
```css
/* PASS — safe, no concern */
--nc-pass: #16A34A;              /* Green-600 — confident but not neon */
--nc-pass-bg: #F0FDF4;           /* Green-50 — tinted background */
--nc-pass-border: #BBF7D0;       /* Green-200 */
--nc-pass-text: #065F46;         /* Green-800 — readable on pass-bg */

/* WARNING — moderate concern, worth noting */
--nc-warning: #D97706;           /* Amber-600 */
--nc-warning-bg: #FFFBEB;        /* Amber-50 */
--nc-warning-border: #FDE68A;    /* Amber-200 */
--nc-warning-text: #92400E;      /* Amber-800 */

/* FAIL — hard fail, significant concern */
--nc-fail: #DC2626;              /* Red-600 — serious but not alarming */
--nc-fail-bg: #FEF2F2;           /* Red-50 */
--nc-fail-border: #FECACA;       /* Red-200 */
--nc-fail-text: #991B1B;         /* Red-800 */

/* NOT SCORED — insufficient data */
--nc-not-scored: #94A3B8;        /* Slate-400 — neutral gray */
--nc-not-scored-bg: #F8FAFC;     /* Slate-50 */
--nc-not-scored-border: #E2E8F0; /* Slate-200 */
--nc-not-scored-text: #64748B;   /* Slate-500 */
```

**Mapping to existing tokens:**
| Design System Token | Existing `tokens.css` Variable |
|---|---|
| `--nc-pass` | `--color-pass` |
| `--nc-pass-bg` | `--color-pass-bg` |
| `--nc-warning` | `--color-warning` |
| `--nc-warning-bg` | `--color-warning-bg` |
| `--nc-fail` | `--color-fail` |
| `--nc-fail-bg` | `--color-fail-bg` |

### Confidence Tier Colors
```css
/* VERIFIED — high confidence, multiple corroborating sources */
--nc-verified: #16A34A;          /* Same as pass — green checkmark */
--nc-verified-bg: #F0FDF4;

/* ESTIMATED — moderate confidence, single source or modeled */
--nc-estimated: #D97706;         /* Amber — caution, not certainty */
--nc-estimated-bg: #FFFBEB;

/* SPARSE — low confidence, limited data */
--nc-sparse: #D97706;            /* Same as estimated — maps to estimated badge */
--nc-sparse-bg: #FFFBEB;

/* NOT SCORED — no data available */
--nc-not-scored-confidence: #94A3B8;  /* Neutral gray — absent, not bad */
--nc-not-scored-confidence-bg: #F8FAFC;
```

### Score Band Colors
These follow an AQI-inspired progression from green to red.

```css
/* Exceptional: 90-100 */
--nc-band-exceptional: #16A34A;
--nc-band-exceptional-bg: #F0FDF4;

/* Strong: 80-89 */
--nc-band-strong: #65A30D;
--nc-band-strong-bg: #F7FEE7;

/* Moderate: 70-79 — renamed from "Good" for clarity */
--nc-band-moderate: #D97706;
--nc-band-moderate-bg: #FFFBEB;

/* Limited: 60-69 — renamed from "Fair" */
--nc-band-limited: #EA580C;
--nc-band-limited-bg: #FFF7ED;

/* Poor: Below 60 */
--nc-band-poor: #DC2626;
--nc-band-poor-bg: #FEF2F2;
```

**Mapping to existing tokens:**
| Design System Token | Existing `tokens.css` Variable |
|---|---|
| `--nc-band-exceptional` | `--band-exceptional` |
| `--nc-band-strong` | `--band-strong` |
| `--nc-band-moderate` | `--band-moderate` |
| `--nc-band-limited` | `--band-limited` |
| `--nc-band-poor` | `--band-poor` |

### Landing/Pricing Sub-Palette
The landing page and pricing page use an intentionally neutral monochrome palette. These are **not** mapped to the blue-tinted token system — they stay as explicit values.

```css
/* Landing/pricing only — do NOT add to :root tokens */
#111111  /* Headings, primary text, CTA backgrounds */
#333333  /* CTA hover state */
#555555  /* Secondary text */
#8E8E8E  /* Subtitle, muted text */
#B0B0B0  /* Labels, meta text */
#EBEBEB  /* Pill backgrounds, light borders */
#F0F0F0  /* Dividers */
#F5F5F3  /* Page background (--color-bg-app) */
```

---

## Typography

### Font Stack
```css
/* Display/Heading */
--nc-font-heading: 'DM Sans', sans-serif;
/* Why: Geometric sans-serif with optical sizing. Clean, modern, readable at all sizes.
   Already in use across the entire app. Good x-height for UI and report headings. */

/* Body */
--nc-font-body: 'DM Sans', sans-serif;
/* Why: Using the same family for body and headings creates visual unity appropriate
   for a data-heavy report. Weight and size differentiation provides hierarchy. */

/* Mono/Data */
--nc-font-mono: 'JetBrains Mono', monospace;
/* Why: Clear numeral differentiation (important for scores and distances).
   Tabular figures by default. Used sparingly for data values. */

/* Google Fonts import URL */
/* https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap */
```

**UUPM recommended alternatives (not adopted):**
- Lora + Raleway (health/wellness) — too editorial, doesn't match the existing DM Sans identity
- Lexend + Source Sans 3 (corporate trust) — excellent readability but would require a full migration
- IBM Plex Sans (financial trust) — strong candidate for a future rebrand but not worth the disruption now
- EB Garamond + Lato (legal/authority) — serif headings would add gravitas but conflict with the current geometric aesthetic

**Rationale for keeping DM Sans:** The font is already deeply integrated across all templates. Changing it would require touching every CSS file and testing every page. DM Sans is a strong choice for this use case — it's clean, readable, and neutral enough for a health report context.

### Type Scale
```css
--nc-text-xs: 0.6875rem;   /* 11px — fine print, badges, L5 meta labels */
--nc-text-sm: 0.8125rem;   /* 13px — labels, metadata, small body */
--nc-text-base: 0.9375rem; /* 15px — primary body text */
--nc-text-lg: 1.125rem;    /* 18px — subsection headers (L3) */
--nc-text-xl: 1.375rem;    /* 22px — section headers (H2) */
--nc-text-2xl: 1.75rem;    /* 28px — page titles, report headlines (L1) */
--nc-text-3xl: 2.25rem;    /* 36px — hero display text */
```

**Mapping to existing tokens:**
| Design System Token | Existing `tokens.css` Variable |
|---|---|
| `--nc-text-xs` | `--text-xs` (11px) |
| `--nc-text-sm` | `--font-size-small` (13px) |
| `--nc-text-base` | `--font-size-body` (15px) |
| `--nc-text-lg` | `--font-size-h3` (18px) |
| `--nc-text-xl` | `--font-size-h2` (22px) |
| `--nc-text-2xl` | `--font-size-h1` (28px) |
| `--nc-text-3xl` | `--font-size-display` (36px) |

### Font Weights
```css
--nc-font-normal: 400;
--nc-font-medium: 500;
--nc-font-semibold: 600;
--nc-font-bold: 700;
```

### Five-Level Typographic Hierarchy (Report)
Already defined in `tokens.css` as `--type-l1` through `--type-l5`. This is the canonical heading system for report pages:

| Level | Size | Weight | Use | Transform |
|-------|------|--------|-----|-----------|
| L1 | 28px | 400 | Page headline (narrative summary) | none |
| L2 | 14px | 600 | Section label (uppercase dividers) | uppercase |
| L3 | 18px | 600 | Section heading (area context) | none |
| L4 | 15px | 600 | Subsection heading | none |
| L5 | 11px | 600 | Meta label (card headers, badges) | uppercase |

---

## Spacing

### Scale (4px grid)
```css
--nc-space-1: 4px;
--nc-space-2: 8px;
--nc-space-3: 12px;
--nc-space-4: 16px;
--nc-space-5: 20px;
--nc-space-6: 24px;
--nc-space-8: 32px;
--nc-space-10: 40px;
--nc-space-12: 48px;
--nc-space-16: 64px;
```

**Mapping to existing tokens:**
All map 1:1 to `--space-1` through `--space-16` in `tokens.css`.

**Named aliases (preferred for readability):**
```css
--nc-space-xs: 4px;     /* --space-xs */
--nc-space-sm: 8px;     /* --space-sm */
--nc-space-md: 12px;    /* --space-md */
--nc-space-base: 16px;  /* --space-base */
--nc-space-lg: 24px;    /* --space-lg */
--nc-space-xl: 32px;    /* --space-xl */
--nc-space-2xl: 48px;   /* --space-2xl */
--nc-space-3xl: 64px;   /* --space-3xl */
```

---

## Border & Radius
```css
--nc-radius-sm: 6px;     /* Small elements: badges, tags, pills */
--nc-radius-md: 10px;    /* Cards, inputs, standard containers */
--nc-radius-lg: 14px;    /* Modals, large containers, report cards */
--nc-radius-full: 9999px; /* Pill shapes (search bar, CTAs) */

--nc-border-width: 1px;
--nc-border-color: var(--nc-border); /* #E2E8F0 */
```

**Mapping to existing tokens:**
| Design System Token | Existing `tokens.css` Variable |
|---|---|
| `--nc-radius-sm` | `--radius-sm` (6px) |
| `--nc-radius-md` | `--radius-md` (10px) |
| `--nc-radius-lg` | `--radius-lg` (14px) |
| `--nc-radius-full` | `--radius-full` (9999px) |

---

## Shadows
```css
--nc-shadow-sm: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
/* Subtle lift — borders, small cards */

--nc-shadow-md: 0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04);
/* Cards on hover, emphasized elements */

--nc-shadow-lg: 0 8px 24px rgba(0,0,0,0.10), 0 2px 8px rgba(0,0,0,0.06);
/* Modals, dropdowns, search bar */
```

**Mapping to existing tokens:**
| Design System Token | Existing `tokens.css` Variable |
|---|---|
| `--nc-shadow-sm` | `--shadow-card` |
| `--nc-shadow-md` | `--shadow-card-hover` |
| `--nc-shadow-lg` | `--shadow-elevated` |

---

## Component Patterns

### Health Check Card
```css
/* A pass/fail/warning health check item — full-width card with status indicator */
.health-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-left: 4px solid var(--color-pass); /* or --color-warning / --color-fail */
  border-radius: var(--radius-md);
  padding: var(--space-base) var(--space-lg);
}
.health-card--pass  { border-left-color: var(--color-pass); }
.health-card--warning { border-left-color: var(--color-warning); }
.health-card--fail  { border-left-color: var(--color-fail); }
.health-card--not-scored { border-left-color: var(--color-text-faint); }

.health-card__headline {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
.health-card__detail {
  font-size: var(--font-size-small);
  color: var(--color-text-muted);
  margin-top: var(--space-xs);
}
```

### Score Badge
```css
/* Numeric score with band-colored background — used in dimension cards and sidebar */
.score-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 48px;
  padding: var(--space-xs) var(--space-sm);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-bold);
  font-variant-numeric: tabular-nums;
  color: white;
}
.score-badge--exceptional { background: var(--band-exceptional); }
.score-badge--strong { background: var(--band-strong); }
.score-badge--moderate { background: var(--band-moderate); }
.score-badge--limited { background: var(--band-limited); }
.score-badge--poor { background: var(--band-poor); }
.score-badge--not-scored {
  background: var(--color-bg-subtle);
  color: var(--color-text-faint);
}
```

### Confidence Indicator
```css
/* Small pill showing data confidence tier — inline with scores */
.confidence-pill {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  padding: 2px var(--space-sm);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-meta);
}
.confidence-pill--verified {
  background: var(--color-pass-bg);
  color: var(--color-pass-text);
}
.confidence-pill--estimated {
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
}
.confidence-pill--not-scored {
  background: var(--color-bg-subtle);
  color: var(--color-text-faint);
}
```

**Note:** The existing `confidence_badge` Jinja macro in `_macros.html` uses `.cb--verified`, `.cb--estimated`, `.cb--not_scored` classes. These patterns are compatible.

### Section Header
```css
/* Dimension section headers (Health, Parks, Transit, etc.) */
.section-label {
  font-size: var(--type-l2-size);       /* 14px */
  font-weight: var(--type-l2-weight);   /* 600 */
  color: var(--type-l2-color);          /* faint */
  text-transform: var(--type-l2-transform); /* uppercase */
  letter-spacing: var(--type-l2-tracking);  /* 0.05em */
  line-height: var(--type-l2-leading);
}

.section-heading {
  font-size: var(--type-l3-size);       /* 18px */
  font-weight: var(--type-l3-weight);   /* 600 */
  color: var(--type-l3-color);          /* primary */
  line-height: var(--type-l3-leading);
}
```

### Verdict Card
```css
/* Overall property verdict — highest visual weight in the report */
.verdict-card {
  background: var(--color-bg-card);
  border-radius: var(--radius-lg);
  padding: var(--space-xl) var(--space-2xl);
  box-shadow: var(--shadow-card);
  border: 1px solid var(--color-border);
  text-align: center;
}
.verdict-card__score {
  font-family: var(--font-mono);
  font-size: var(--font-size-display); /* 36px */
  font-weight: var(--font-weight-bold);
  font-variant-numeric: tabular-nums;
  line-height: 1;
}
.verdict-card__band {
  font-size: var(--font-size-h3);      /* 18px */
  font-weight: var(--font-weight-semibold);
  margin-top: var(--space-sm);
}
.verdict-card__narrative {
  font-size: var(--font-size-body);
  color: var(--color-text-muted);
  line-height: var(--line-height-relaxed);
  margin-top: var(--space-base);
  max-width: 600px;
  margin-left: auto;
  margin-right: auto;
}
```

### Dimension Scorecard
```css
/* Grid card for each scored dimension (Coffee, Parks, Transit, etc.) */
.dim-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-left: 4px solid var(--band-strong); /* colored by band */
  border-radius: var(--radius-md);
  padding: var(--space-base) var(--space-lg);
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.dim-card__name {
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
}
.dim-card__score {
  font-family: var(--font-mono);
  font-size: var(--font-size-h3);
  font-weight: var(--font-weight-bold);
  font-variant-numeric: tabular-nums;
}
.dim-card__band-label {
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  text-transform: uppercase;
  letter-spacing: var(--letter-spacing-meta);
}
.dim-card__summary {
  font-size: var(--font-size-small);
  color: var(--color-text-muted);
  line-height: var(--line-height-normal);
}
```

---

## Anti-Patterns (Do NOT Use)

### Color
- No gradients on backgrounds — flat, clean surfaces only
- No purple/blue AI-startup aesthetic (no `#7C3AED`, no aurora gradients)
- No neon greens or reds — status colors should feel clinical, not alarming
- No dark mode elements on a light page
- No background images or textures

### Typography
- No decorative or display fonts (no Playfair Display, no Lobster)
- No font sizes below 11px (accessibility floor)
- No more than 3 font weights on a single page
- No letter-spacing wider than 0.08em on body text

### Layout
- No rounded-everything — selective radius use (sharp edges for maps and data tables)
- No card shadows heavier than `--shadow-lg`
- No floating/sticky elements beyond the sidebar and cookie banner
- No parallax or scroll-triggered effects

### Interaction
- No animations or motion beyond hover transitions (150-300ms ease)
- No skeleton loading screens (server-rendered pages)
- No confetti, celebration animations, or gamification

### Content
- No emoji as icons — use inline SVGs (Lucide icon style)
- No decorative illustrations or mascots
- No "most popular" badges or artificial urgency markers
- No exclamation marks in UI text (calm, authoritative tone)

---

## Implementation Notes

### Architecture
- All colors defined as CSS custom properties on `:root` in `tokens.css`
- All templates inherit from `_base.html`, which loads `tokens.css` first, then `base.css`
- Page-specific CSS files (`index.css`, `report.css`, `pricing.css`, `snapshot.css`) load after base
- No CSS preprocessor, no PostCSS, no CSS-in-JS — vanilla CSS only

### Naming Convention
- Token-level: `--color-*`, `--font-*`, `--space-*`, `--radius-*`, `--shadow-*`
- Component-level: BEM-like (`.component__element--modifier`)
- Page-scoped: Prefix with page name when generic (`.pricing-section-label` not `.section-label`)

### Print
- All report pages must be printable (no background images, reasonable contrast)
- Print-specific `@media print` blocks hide interactive elements (search, share, sidebar)
- Score colors must remain distinguishable in grayscale

### Mobile
- Mobile-first approach: readable on 375px phones
- Report sharing via URL is a key use case — mobile layout is not secondary
- Input font size minimum 16px to prevent iOS auto-zoom
- Use `100dvh` over `100vh` (Safari URL bar issue)
- Fixed-position bottom elements must include `env(safe-area-inset-bottom)`

### Accessibility
- WCAG AA contrast ratio (4.5:1) minimum for all text
- Focus states visible for keyboard navigation
- `prefers-reduced-motion` respected (no animations to disable, but noted for future)
- Semantic HTML: `role`, `aria-label`, `aria-expanded` on interactive elements
- Screen reader utility: `.sr-only` class defined in `tokens.css`

### UUPM Pre-Delivery Checklist (adapted)
- [ ] No emojis as icons (use inline SVG)
- [ ] `cursor: pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Text contrast 4.5:1 minimum
- [ ] Focus states visible for keyboard nav
- [ ] Responsive: 375px, 640px, 768px, 1024px, 1200px breakpoints
