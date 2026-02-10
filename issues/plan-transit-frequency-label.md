# Feature Implementation Plan

**Overall Progress:** `100%`

## TLDR
Two parallel transit frequency systems produce conflicting labels on the same result page. The template shows `primary_transit.frequency_class` (review-count proxy, e.g. "Medium frequency") alongside `transit_access.frequency_bucket` (composite heuristic, e.g. "High"). The scorer already prefers System B (`frequency_bucket`) — the display layer should do the same. Consolidate to the single `frequency_label` the scorer already computes, and remove the duplicate/conflicting display.

## Critical Decisions
- **Use the scorer's `frequency_label` as the single source of truth** — it already prefers `transit_access.frequency_bucket` and falls back to `frequency_class`. No scoring logic changes needed.
- **Surface the label via the Tier2Score details string and the transit_access dict** — avoids inventing a new data path; the template and dimension summary both read from what's already computed.
- **Remove the separate "Transit Frequency" row from the template** — the label will appear inline on the primary transit row, eliminating the contradiction.

## Tasks:

- [x] 🟩 **Step 1: Expose the frequency label from the scorer**
  - [x] 🟩 Add `frequency_label` to the result dict returned by `result_to_dict()` so the template and summary can access it directly (app.py ~line 422-432)

- [x] 🟩 **Step 2: Update the template to use the single label**
  - [x] 🟩 Replace `pt.frequency_class` on template line 139 with `result.frequency_label`
  - [x] 🟩 Remove the standalone "Transit Frequency" block (template lines 152-163) — the info is now shown on the primary transit row

- [x] 🟩 **Step 3: Update the dimension summary in app.py**
  - [x] 🟩 Change the Getting Around summary (app.py lines 261-272) to use `result_dict.frequency_label` instead of branching between `frequency_class` and `frequency_bucket`

- [x] 🟩 **Step 4: Verify and test**
  - [x] 🟩 Run existing tests — 51 passed (2 pre-existing Flask import failures unrelated to change)
  - [x] 🟩 Confirm the Tier2Score details string still reads correctly (unchanged — it already uses `frequency_label`)
