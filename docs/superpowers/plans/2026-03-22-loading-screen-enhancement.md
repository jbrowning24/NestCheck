# NES-367: Loading Screen Enhancement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the existing polling-based loading screen by removing the pulsing home icon, promoting stage messages to primary visual element, widening the progress bar, adding `prefers-reduced-motion` support, and adding a 45s escalation patience message.

**Architecture:** Pure frontend change — CSS modifications in `static/css/index.css` and HTML/JS changes in `templates/index.html`. No backend, no new files, no new dependencies. The existing server-driven `STAGE_DISPLAY` progress tracking is preserved.

**Tech Stack:** Vanilla CSS, vanilla JS, Jinja2 HTML template

**Spec:** `docs/superpowers/specs/2026-03-22-loading-screen-enhancement-design.md`

**Spec correction:** The crossfade targets `.loading-sub` (not `.loading-text` as stated in some parts of the spec). `.loading-text` is static ("Evaluating this address..."); `.loading-sub` is the element updated with stage messages by the polling JS. The spec's design section correctly describes the sub-text changing, but the implementation sections originally named the wrong element. The spec has been updated.

**Accessibility note:** Existing `role="status"`, `aria-live="polite"`, and `aria-hidden` attributes are not touched by any task — they are preserved as-is.

**Mobile note:** `width: 100%; max-width: 480px` on the progress bar handles mobile naturally. The overlay is already `display: flex; justify-content: center; align-items: center; flex-direction: column`.

---

### Task 1: Remove home icon and pulse animation (CSS + HTML)

**Files:**
- Modify: `static/css/index.css:304-317` (remove `.loading-brand`, `.loading-mark`, `@keyframes pulse`)
- Modify: `templates/index.html:65-70` (remove `.loading-brand` div)

- [ ] **Step 1: Remove `.loading-brand`, `.loading-mark`, and `@keyframes pulse` from CSS**

Delete these three rules (lines 304-317 of `index.css`):

```css
/* DELETE THIS: */
.loading-brand {
  color: var(--color-text-inverse);
}

.loading-mark {
  width: 56px;
  height: 56px;
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { transform: scale(0.95); opacity: 0.6; }
  50%       { transform: scale(1.05); opacity: 1; }
}
```

- [ ] **Step 2: Remove the `.loading-brand` div and its SVG contents from HTML**

Delete lines 65-70 of `index.html`:

```html
<!-- DELETE THIS: -->
  <div class="loading-brand">
    <svg class="loading-mark" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M8 22 L24 8 L40 22 V40 A2 2 0 0 1 38 42 H10 A2 2 0 0 1 8 40 Z"/>
      <rect x="18" y="28" width="12" height="14" rx="1"/>
    </svg>
  </div>
```

The loading overlay should now start with `<div class="loading-text">`.

- [ ] **Step 3: Commit**

```bash
git add static/css/index.css templates/index.html
git commit -m "feat(NES-367): remove home icon SVG and pulse animation from loading overlay"
```

---

### Task 2: Widen progress bar and reduce height (CSS)

**Files:**
- Modify: `static/css/index.css` — `.loading-progress` and `.loading-progress-fill` rules

- [ ] **Step 1: Update `.loading-progress` dimensions**

Change the `.loading-progress` rule from:

```css
.loading-progress {
  width: 200px;
  height: 6px;
  margin-top: 16px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 3px;
  overflow: hidden;
}
```

To:

```css
.loading-progress {
  width: 100%;
  max-width: 480px;
  height: 3px;
  margin-top: 16px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 2px;
  overflow: hidden;
}
```

- [ ] **Step 2: Update `.loading-progress-fill` border-radius**

Change `border-radius: 3px` to `border-radius: 2px` in `.loading-progress-fill`.

- [ ] **Step 3: Commit**

```bash
git add static/css/index.css
git commit -m "style(NES-367): widen progress bar to max-width 480px, reduce height to 3px"
```

---

### Task 3: Add crossfade transition and `prefers-reduced-motion` (CSS)

**Files:**
- Modify: `static/css/index.css` — `.loading-sub` rule + existing `@media (prefers-reduced-motion: reduce)` block

- [ ] **Step 1: Add opacity transition to `.loading-sub`**

This is the element whose text changes with stage updates. Add `transition: opacity 200ms ease`:

```css
.loading-sub {
  margin-top: 12px;
  font-size: var(--font-size-body);
  color: rgba(255, 255, 255, 0.6);
  transition: opacity 200ms ease;          /* NEW */
}
```

- [ ] **Step 2: Add loading overlay rules to the existing reduced-motion media query**

Find the existing `@media (prefers-reduced-motion: reduce)` block (around line 472) and add these rules inside it, before the closing `}`:

```css
  /* Loading overlay — disable transitions */
  .loading-sub,
  .loading-patience,
  .loading-progress-fill {
    transition-duration: 0.01ms !important;
  }
```

- [ ] **Step 3: Commit**

```bash
git add static/css/index.css
git commit -m "style(NES-367): add crossfade transition and prefers-reduced-motion support"
```

---

### Task 4: Add 45s escalation timer, crossfade JS, and timer cleanup

**Files:**
- Modify: `templates/index.html` — `startPolling()` function and `hideOverlay()` function

Three JS changes:

1. Promote timer variables to module scope for `hideOverlay()` access
2. Replace the patience timer (10s → 15s) and add a 45s escalation timer
3. Add crossfade logic for stage message text changes

- [ ] **Step 1: Add module-level timer variables**

Near the top of the `<script>` block (before `startPolling`), add:

```javascript
var patienceTimerId = null;
var escalationTimerId = null;
```

- [ ] **Step 2: Replace patience timer and add escalation timer in `startPolling()`**

Find the patience timer block (around line 569-572):

```javascript
var patienceEl = document.getElementById('loadingPatience');
var patienceTimer = setTimeout(function() {
  if (patienceEl) patienceEl.classList.add('visible');
}, 10000);
```

Replace with:

```javascript
var patienceEl = document.getElementById('loadingPatience');
patienceTimerId = setTimeout(function() {
  if (patienceEl) {
    patienceEl.textContent = 'Detailed reports typically take 20\u201330 seconds.';
    patienceEl.classList.add('visible');
  }
}, 15000);

escalationTimerId = setTimeout(function() {
  if (patienceEl) {
    patienceEl.textContent = 'This is taking longer than usual. The report will appear automatically when ready.';
  }
}, 45000);
```

Note: `\u2013` is the en-dash character (–).

- [ ] **Step 3: Update all `clearTimeout(patienceTimer)` calls**

There are 5 places in `startPolling()` that call `clearTimeout(patienceTimer)`. Replace each with:

```javascript
clearTimeout(patienceTimerId);
clearTimeout(escalationTimerId);
```

The 5 locations are:
- 404 error after max retries
- Non-404 server error after max retries
- `status === 'done'` success path
- `status === 'failed'` path
- Network error catch block

- [ ] **Step 4: Add crossfade logic for stage message updates**

In `startPolling()`, find where `loadingSub.textContent` is updated with stage text. Replace the simple assignment with crossfade logic:

```javascript
if (stageInfo) {
  if (loadingSub.textContent !== stageInfo.text) {
    var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reducedMotion) {
      loadingSub.textContent = stageInfo.text;
    } else {
      loadingSub.style.opacity = '0';
      loadingSub.addEventListener('transitionend', function() {
        loadingSub.textContent = stageInfo.text;
        loadingSub.style.opacity = '1';
      }, { once: true });
    }
  }
  setProgress(stageInfo.pct);
}
```

The `{ once: true }` option auto-removes the listener after one invocation — no manual `removeEventListener` needed.

- [ ] **Step 5: Update `hideOverlay()` to clean up timers**

```javascript
function hideOverlay(overlay) {
  overlay.classList.remove('active');
  overlay.setAttribute('aria-hidden', 'true');
  var p = document.getElementById('loadingPatience');
  if (p) p.classList.remove('visible');
  clearTimeout(patienceTimerId);
  clearTimeout(escalationTimerId);
}
```

- [ ] **Step 6: Commit**

```bash
git add templates/index.html
git commit -m "feat(NES-367): add 45s escalation message, crossfade stage text, clean up timers"
```

---

### Task 5: Manual verification

**Files:** None (testing only)

- [ ] **Step 1: Start the dev server**

```bash
cd /Users/jeremybrowning/NestCheck
python app.py
```

- [ ] **Step 2: Submit an evaluation and observe the loading screen**

Verify:
1. No home icon or pulsing animation visible
2. Stage message text is primary (large, semibold, white, centered)
3. Progress bar spans most of the overlay width (up to 480px)
4. Sub-text crossfades when stage text changes
5. At ~15s, patience message fades in: "Detailed reports typically take 20–30 seconds."
6. At ~45s, patience message updates to escalation text
7. On mobile viewport (use Chrome DevTools), bar and text are readable and centered

- [ ] **Step 3: Test `prefers-reduced-motion`**

In Chrome DevTools → Rendering → Emulate CSS media feature `prefers-reduced-motion: reduce`:
1. Progress bar fills without visible transition
2. Stage text changes instantly (no fade)
3. Patience message appears instantly (no fade)

- [ ] **Step 4: Verify smoke test markers still pass**

```bash
python smoke_test.py
```

The loading overlay's `id="loadingOverlay"` is not in `LANDING_REQUIRED_MARKERS`, so no smoke test update is needed.

---

## Execution Notes

**Task ordering:** Tasks 1-3 are independent CSS/HTML changes. Task 4 depends on Task 3 (the CSS transition must exist for the JS crossfade to work). Task 5 depends on all previous tasks.

**Recommended order:** 1 → 2 → 3 → 4 → 5
