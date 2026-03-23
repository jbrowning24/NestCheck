# NES-367: Loading Screen Enhancement

## Context

The loading screen shows during address evaluation (20-60 seconds). The current
implementation already has server-driven progress via `STAGE_DISPLAY` (22
stages, polled every 2s) — significantly more sophisticated than the original
ticket assumed. This spec reframes NES-367 as an enhancement to the existing
polling-based loading screen rather than a replacement.

### What exists today

- **Determinate progress bar**: 200px wide, 6px tall, tracks real backend stages
  (0-97%) via `setProgress(pct)`.
- **Stage messages**: `STAGE_DISPLAY` maps 22 server-reported stages to
  user-facing text (e.g., "Discovering parks and trails...").
- **Patience message**: "This usually takes 30-60 seconds." appears after 10s.
- **Home icon**: Pulsing SVG house animation (`@keyframes pulse`, 1.5s
  ease-in-out infinite).
- **Accessible markup**: `role="status"`, `aria-live="polite"`,
  `aria-hidden` toggling.

### Problems

1. **Pulsing icon violates design spec §7.2** ("No bouncing, pulsing, or
   attention-seeking motion").
2. **No `prefers-reduced-motion` support** — the pulse animation plays
   regardless, violating §7.3.
3. **Visual hierarchy is wrong**: The icon is the primary element, but it
   communicates nothing. Stage messages (the actual value) are visually
   subordinate.
4. **Progress bar feels like a widget** at 200px — not proportional to the
   full-screen overlay context.
5. **No escalation message** for evaluations exceeding 45s.

## Design

### Layout (top to bottom, vertically centered in overlay)

1. **Stage message** — the primary visual element
   - Font: `--font-size-h3` (1.125rem / 18px), `--font-weight-semibold` (600)
     (keeps existing token — close enough to `--type-heading` and avoids a
     gratuitous change)
   - Color: `--color-text-inverse` (#FFFFFF)
   - Text swaps via 200ms `opacity` crossfade as server reports new stages.
     **Crossfade mechanism**: fade out (set `opacity: 0`), listen for
     `transitionend`, swap `textContent`, then set `opacity: 1`. This produces
     a true fade-out/fade-in (400ms total: 200ms out + 200ms in). Without the
     `transitionend` listener, synchronous opacity:0/text/opacity:1 batches
     into a single paint frame and the crossfade is invisible.
   - Respects `prefers-reduced-motion`: instant swap, no crossfade

2. **Progress bar** — secondary, contextual
   - Width: `100%`, `max-width: 480px`
   - Height: 3px
   - Track: `rgba(255, 255, 255, 0.15)` — keeps existing value
   - Fill: `var(--color-accent)` (#2563EB)
   - Border-radius: 2px (half of height)
   - Margin-top: `var(--space-base)` (16px)
   - Keeps determinate fill driven by real `STAGE_DISPLAY` percentages
   - Transition: `width 0.4s ease` (existing)

3. **Sub-text** — static context
   - Text: "Checking parks, transit, safety, and more."
   - Font: `--font-size-body` (0.9375rem / 15px) — keeps existing token
   - Color: `rgba(255, 255, 255, 0.6)` — keeps existing value
   - Margin-top: `var(--space-md)` (12px)

4. **Patience text** — progressive reassurance
   - Font: `--font-size-small` (0.8125rem / 13px) — keeps existing token
   - Color: `rgba(255, 255, 255, 0.4)`
   - Margin-top: `var(--space-base)` (16px)
   - Starts hidden (`opacity: 0`), fades in via existing `0.4s ease` transition
   - **At 15s**: "Detailed reports typically take 20-30 seconds."
   - **At 45s**: "This is taking longer than usual. The report will appear
     automatically when ready."

### What is removed

- `.loading-brand` container and SVG home icon markup
- `.loading-mark` styles and `@keyframes pulse` animation
- The 56x56 SVG house path

### Accessibility

**`prefers-reduced-motion: reduce`:**
```css
@media (prefers-reduced-motion: reduce) {
  .loading-progress-fill {
    transition-duration: 0.01ms !important;
  }
  .loading-patience,
  .loading-text {
    transition-duration: 0.01ms !important;
  }
}
```

**Existing accessible markup preserved:**
- `role="status"` on overlay container
- `aria-live="polite"` for stage message announcements
- `aria-hidden` toggled by JS on show/hide

### Mobile

- Progress bar: `max-width: 480px` with `width: 100%` naturally adapts
- Stage message: centered, readable at `--type-heading` on all viewports
- No layout changes needed — the overlay is already `display: flex;
  justify-content: center; align-items: center; flex-direction: column`

## Files touched

### `templates/index.html`

**HTML changes:**
- Remove the `.loading-brand` div and its SVG contents
- Update patience timer: 10s → 15s for first message
- Add 45s `setTimeout` to update patience text to escalation copy
- Add opacity crossfade class toggling for stage message transitions

**JS changes (in `startPolling()`):**
- Change patience `setTimeout` from 10000 to 15000
- Add second `setTimeout` at 45000 for escalation message
- Add crossfade logic: set `opacity: 0` on `.loading-text`, listen for
  `transitionend`, then swap `textContent` and set `opacity: 1`. For
  `prefers-reduced-motion`, skip the listener and swap text instantly.
- Clear both timeouts in `hideOverlay()`
- **Scope timers to evaluation polling only**: The loading overlay is also
  shown briefly during Stripe checkout (`submitEvaluation`). The 15s/45s
  patience timers must only be started inside `startPolling()`, not in
  `submitEvaluation()`. Since `submitEvaluation()` calls `startPolling()`
  on success, this is naturally scoped — but verify the checkout error path
  doesn't trigger them.

### `static/css/index.css`

**Remove:**
- `.loading-brand` rule
- `.loading-mark` rule (width, height, animation)
- `@keyframes pulse`

**Modify:**
- `.loading-text`: add `transition: opacity var(--transition-base)` (200ms ease)
- `.loading-progress`: change `width: 200px` → `width: 100%; max-width: 480px`,
  change `height: 6px` → `height: 3px`, change `border-radius: 3px` →
  `border-radius: 2px`. Background stays `rgba(255, 255, 255, 0.15)`.
- `.loading-progress-fill`: change `border-radius: 3px` → `border-radius: 2px`

**Add:**
- `@media (prefers-reduced-motion: reduce)` block for `.loading-progress-fill`,
  `.loading-patience`, `.loading-text`

## What stays the same

- Server-driven `STAGE_DISPLAY` mapping (22 stages)
- Determinate progress bar tracking real completion
- Polling logic (`startPolling()`), error handling, retry counters
- `setProgress(pct)` function
- `hideOverlay()` function (with added timeout cleanup)
- `csrfFetch()` and form submission flow
- Dark overlay background (`--color-overlay-bg: rgba(11, 29, 58, 0.85)`)

## What this does NOT do

- No indeterminate shimmer bar — determinate fill driven by real data is better
- No timer-faked messages — server-driven stages are a product advantage
- No new JS dependencies or framework changes
- No changes to the evaluation pipeline or polling endpoints

## Acceptance criteria

- [ ] Home icon SVG and pulse animation removed
- [ ] Stage message is primary visual element (heading size, semibold, white)
- [ ] Progress bar widened to max-width 480px, height reduced to 3px
- [ ] Patience message appears at 15s with "typically take 20-30 seconds"
- [ ] Patience message updates at 45s with "taking longer than usual"
- [ ] `prefers-reduced-motion` disables all transitions/animations
- [ ] Stage message crossfades on text change (200ms ease)
- [ ] Works on mobile (full-width bar, centered messages, readable text)
- [ ] Existing accessibility attributes preserved
