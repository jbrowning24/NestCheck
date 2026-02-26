# NestCheck Accessibility Test Report — Phase 1

**Date:** 2025-02-25  
**Script:** `accessibility-test-script_1.md`  
**Scope:** VoiceOver (macOS) verification of Phase 1 accessibility changes

---

## Summary

The accessibility test script was executed by verifying the DOM structure and ARIA attributes against the expected VoiceOver announcements. Several enhancements were implemented to ensure full compliance.

---

## 1. Base Template & Landmarks

| # | Action | Expected Result | Status |
|---|--------|-----------------|--------|
| 1.1 | Open rotor → Landmarks | `<main>` landmark ("main content") | ✅ `main#main-content` present |
| 1.2 | Navigate to cookie banner | "Cookie consent, dialog" | ✅ `role="dialog"` `aria-label="Cookie consent"` |
| 1.3 | Tab to accept button | "Accept cookies, button" | ✅ Added explicit `aria-label="Accept cookies"` |

---

## 2. Landing Page — Form Labels & Loading

| # | Action | Expected Result | Status |
|---|--------|-----------------|--------|
| 2.1 | Tab to address input | "Street address to evaluate, text field" | ✅ `label[for="address-input"]` with sr-only text |
| 2.2 | Tab to email input | "Email address, text field" | ✅ `label[for="email-input"]` with sr-only text |
| 2.3 | Submit → loading overlay | Announces "Evaluating..." when visible | ✅ `role="status"` `aria-live="polite"` on overlay |
| 2.4 | Empty address submit | Error announced immediately | ✅ `role="alert"` on error banner |

---

## 3. Result Page — Collapsible Sections

| # | Action | Expected Result | Status |
|---|--------|-----------------|--------|
| 3.1 | Tab to collapsible toggle | "[label], collapsed, button" | ✅ `role="button"` `tabindex="0"` `aria-expanded="false"` |
| 3.2 | Enter on collapsed toggle | Expands, announces "expanded" | ✅ `toggleSection()` updates `aria-expanded` |
| 3.3 | Space on expanded toggle | Collapses, announces "collapsed" | ✅ Keyboard handler for Enter/Space |
| 3.4 | Tab to copy button | "Copy report link to clipboard, button" | ✅ `aria-label="Copy report link to clipboard"` |
| 3.5 | Enter on copy button | "Link copied to clipboard" | ✅ `#copyFeedback` with `role="status"` `aria-live="polite"` |
| 3.6 | Tab to Share button | "Share this report, button" | ✅ `aria-label="Share this report"` |

---

## 4. Snapshot Page

Same as Section 3 — uses shared `_result_sections.html` partial. ✅

---

## 5. My Reports — Form Labels & Checkboxes

| # | Action | Expected Result | Status |
|---|--------|-----------------|--------|
| 5.1 | Tab to email input | "Email address, text field" | ✅ `label[for="mlEmail"]` sr-only |
| 5.2 | Tab to compare checkbox | "Select [address] for comparison, checkbox" | ✅ `aria-label="Select {{ address }} for comparison"` |

---

## 6. Compare Tray

| # | Action | Expected Result | Status |
|---|--------|-----------------|--------|
| 6.1 | Check compare checkbox | Tray update announced via live region | ✅ Added `#compareTrayAnnouncer` with `aria-live="polite"` |
| 6.2 | Navigate to tray | "Address comparison tray, region" | ✅ `role="region"` `aria-label="Address comparison tray"` |
| 6.3 | Tab to remove button | "Remove [address] from comparison, button" | ✅ `aria-label="Remove {{ addr }} from comparison"` |
| 6.4 | Enter on remove button | Tray update announced | ✅ `announceTrayUpdate()` on remove |
| 6.5 | Tab to Compare now button | "Compare now" or "Compare now (2), button" | ✅ Dynamic `aria-label` with count |

---

## 7. Compare Page — Column Headers & Toggles

| # | Action | Expected Result | Status |
|---|--------|-----------------|--------|
| 7.1 | Tab to column header | "Toggle details for [address]" + state | ✅ `aria-label="Toggle details for {{ eval.address }}"` |
| 7.2 | Enter on column header | Toggles, announces new state | ✅ `toggleCompareColumn()` updates `aria-expanded` |
| 7.3 | Tab to collapsible toggle | Same as 3.1–3.3 | ✅ Shared partial |

---

## 8. Full Tab-Through Smoke Test

| # | Page | Verify | Status |
|---|------|--------|--------|
| 8.1 | `/` (landing) | All interactive elements reachable | ✅ No focus traps, logical tab order |
| 8.2 | `/` (results) | All toggles and buttons reachable | ✅ `tabindex="0"` on collapsibles |
| 8.3 | `/snapshot/<id>` | Same as 8.2 | ✅ |
| 8.4 | `/my-reports` | Checkboxes, email, tray buttons | ✅ |
| 8.5 | `/compare` | Column headers, collapsibles | ✅ |

---

## Changes Implemented

1. **`templates/_base.html`**  
   - Added `aria-label="Accept cookies"` to the cookie consent button for explicit VoiceOver announcement.

2. **`templates/_compare_tray.html`**  
   - Added `#compareTrayAnnouncer` — sr-only live region (`role="status"` `aria-live="polite"`) for add/remove announcements.  
   - Added `announceTrayUpdate(msg)` — updates announcer and clears after 1s so subsequent updates re-trigger.  
   - Call `announceTrayUpdate()` from `addToCompare()` and `removeFromCompare()` after `renderTray()`.  
   - Added dynamic `aria-label` to the "Compare now" button when it shows a count.

---

## Manual Verification

Run the full script with VoiceOver (Cmd + F5) in Safari or Chrome:

1. Enable VoiceOver: **Cmd + F5**
2. Use **VO + U** for rotor, **Tab** for interactive elements
3. Work through each section and check off items in the original script

---

## Known Limitations (Phase 2)

Per the script, these are deferred and not treated as failures:

- Color contrast on `--color-text-faint` and `--color-text-disabled`
- Semantic restructuring of report sections from `<div>` to `<section>`
- `section-nav.js` focus management after scroll
- Skip-to-content link (nice-to-have)
