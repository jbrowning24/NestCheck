---
name: code-review
description: >
  Review code for bugs, security issues, and production readiness.
  Use when asked to "review this code," "check my work," or after
  completing an implementation. Self-review catches obvious issues
  so human review can focus on the subtle stuff.
---

# Code Review

You are reviewing code that was recently written or modified. Your job
is to find real issues — things that would cause bugs, security
vulnerabilities, performance problems, or maintenance headaches in
production.

## The right mindset

You are likely reviewing code you just wrote. This creates a blind spot:
you already believe the code works because you intended it to work. Fight
this by reading the code as if someone else wrote it and you're seeing it
for the first time.

Ask yourself at each file: "If this shipped tonight and I got paged at
3am, what would go wrong?"

## What to check

### Correctness
- Does the logic actually do what the task description says?
- Are edge cases handled? (empty arrays, null values, missing fields,
  network failures)

### Error handling
- Do API calls have try-except with meaningful error messages?
- Do errors propagate to where they can be handled? (not swallowed
  silently)
- Would a user see a helpful error, or a blank screen / cryptic message?

### Security
- Are user inputs validated before use?
- Are there hardcoded secrets, API keys, or tokens? (even in comments)

### Performance
- Any unnecessary API calls? (Google Maps calls cost real money)
- Are batch endpoints used where available? (walking_times_batch, etc.)
- Are there potential infinite loops or unbounded recursion?

### Production readiness
- No debug print statements left behind
- No TODO, FIXME, HACK comments left from implementation
- No test data or commented-out code blocks

### Architecture
- Does the new code follow the same patterns as existing code?
- Is the code in the right file / module?
- Would another developer know where to find this code?

## How to report

Be specific. "There might be an issue with error handling" helps nobody.
"The walking_time call in property_evaluator.py:340 has no except block —
if the API fails, the evaluation will crash" is actionable.

### Severity levels

| Level | Meaning |
|-------|---------|
| CRITICAL | Will cause failures, data loss, or security exposure |
| HIGH | Real bugs or significant UX/performance problems |
| MEDIUM | Code quality issues that compound over time |
| LOW | Style and minor improvements |

## What NOT to do

- Don't review code that wasn't changed.
- Don't suggest rewrites.
- Don't flag style preferences as issues. Match what exists.
- Don't inflate the count. If the code is clean, say so.
