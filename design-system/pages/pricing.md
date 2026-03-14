# Pricing Page Overrides

Applies to: `templates/pricing.html`, styled by `static/css/pricing.css`

## Visual Sub-Palette
The pricing page intentionally uses a neutral monochrome palette that diverges from the blue-tinted token system. This is a deliberate design choice — the pricing page should feel calm and transparent, not branded/salesy.

- Headings: `#111111` (not `--color-text-primary: #0F172A`)
- Subtitle: `#8E8E8E` (not `--color-text-muted: #64748B`)
- Feature list text: `#555555`
- Meta labels: `#B0B0B0`
- Page background: `#F5F5F3` (`--color-bg-app`)

Structural tokens (spacing, font weights, radii, transitions) still use `var()`.

## Specific Rules
- Single pricing tier highlighted — no comparison grid needed
- CTA button uses `#111111` background (monochrome), not `--nc-accent` blue
- Price amount uses large display size (72px desktop, 56px mobile) with tabular-nums
- Feature list uses checkmark (Unicode `\2713`) as list marker, not custom SVG
- "Coming Soon" section uses the same card treatment as the price card but with less visual weight
- Trust signals (data sources, methodology transparency) below the fold — not on this page; they belong in the report itself
- No "most popular" badges or artificial urgency
- No pricing comparison tables (single tier for now)

## Mobile (< 640px)
- Title scales to `--font-size-display` (36px)
- Price card padding reduces
- Price amount scales to 56px
- Single column layout (already inherent)
