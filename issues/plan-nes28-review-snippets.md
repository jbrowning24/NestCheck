# NES-28: Google Review Snippets on Headline Place Cards

**Overall Progress:** `100%`

## TLDR
Add a curated review snippet to the top place card in each neighborhood category (coffee, grocery, fitness, parks). Fetches reviews via Place Details API for only the headline place per category (4 calls, parallel), filters for ≥ 4-star reviews, and displays a ~100-char truncated quote with relative time. Creates a visual hierarchy: headline card gets premium treatment, remaining cards stay compact.

## Critical Decisions
- **Headline only (4 calls, not 10-15):** Controls cost to ~$0.07/eval instead of $0.25. Top place per category gets the snippet; others stay as-is.
- **Parallel execution after tier 2 scoring:** Fires 4 Place Details calls concurrently at line 3262, adding ~400ms (invisible in 60-90s budget).
- **Filter reviews ≥ 4 stars:** We're curating a neighborhood portrait, not running Yelp. Skip negative top reviews.
- **Cache in snapshot JSON:** Attach `review_snippet` + `review_time` directly to the place dict. No schema changes needed.
- **Include relative time:** "2 months ago" adds credibility signal. Styled as secondary text.

## Tasks

- [x] 🟩 **Step 1: Backend — Fetch and attach review snippets**
  - [x] 🟩 Add helper function to fetch reviews for a single place_id (calls `place_details` with `fields=["reviews"]`, filters for rating ≥ 4, truncates text to ~100 chars at word boundary + ellipsis, returns `review_snippet` and `review_time`)
  - [x] 🟩 After `result.neighborhood_places` assembly (~line 3262), pick index `[0]` from each category
  - [x] 🟩 Fire 4 parallel `place_details` calls using existing `ThreadPoolExecutor` pattern
  - [x] 🟩 Attach `review_snippet` and `review_time` to each headline place dict (no-op if no qualifying review found)

- [x] 🟩 **Step 2: Frontend — Headline card template**
  - [x] 🟩 In `_result_sections.html`, detect first place in each category as headline (has `review_snippet`)
  - [x] 🟩 Apply `.place-card--headline` class to that card
  - [x] 🟩 Render `review_snippet` as a single truncated line below rating
  - [x] 🟩 Render `review_time` as secondary text after the snippet

- [x] 🟩 **Step 3: CSS — Headline card styling**
  - [x] 🟩 `.place-card--headline` — wider than standard 160px cards, visually distinct
  - [x] 🟩 `.place-snippet` — single-line truncated, quoted/italic styling
  - [x] 🟩 `.place-snippet-time` — muted color, smaller font, lighter weight

- [x] 🟩 **Step 4: Edge cases and resilience**
  - [x] 🟩 Handle Place Details failure gracefully (card renders without snippet, no error surfaced)
  - [x] 🟩 Handle zero qualifying reviews (all < 4 stars or no reviews) — headline card still renders, just without snippet line
  - [x] 🟩 Handle empty/missing `review_time` field
