---
name: code-review
description: >
  Review code for bugs, security issues, and production readiness.
  Use this skill when someone asks to "review this code," "check my
  work," "look for issues," "is this ready to ship," or any request to
  evaluate code quality. Also trigger after an execute phase completes
  and the user wants a sanity check before peer review. This is a
  self-review by the same model that wrote the code — it catches the
  obvious stuff so peer review can focus on the subtle stuff.
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

---

## What to check

Review the changed files against this checklist. Not every category
applies to every change — skip what's irrelevant, but be honest about
what's relevant.

### Correctness
- Does the logic actually do what the task description says?
- Are edge cases handled? (empty arrays, null values, missing fields,
  network failures)
- Are async operations awaited properly? Could anything race?

### Error handling
- Do async calls have try-catch (or `.catch`) with meaningful error
  messages?
- Do errors propagate to where they can be handled? (not swallowed
  silently)
- Would a user see a helpful error, or a blank screen / cryptic message?

### Security
- Is authentication checked where needed?
- Are user inputs validated before use?
- Are there hardcoded secrets, API keys, or tokens? (even in comments)
- If using a database with RLS: are policies in place for new tables?

### Performance
- Any obvious N+1 queries or unnecessary re-fetching?
- In React: are expensive computations memoized? Do effects have
  correct dependency arrays?
- Are there potential infinite loops or unbounded recursion?
- Large lists: is pagination or virtualization needed?

### Production readiness
- No `console.log` statements (use the project's logger if one exists)
- No `TODO`, `FIXME`, `HACK` comments left from implementation
- No `@ts-ignore`, `any` types, or disabled lint rules without
  justification
- No debug flags, test data, or commented-out code blocks

### Architecture
- Does the new code follow the same patterns as existing code?
  (file structure, naming, imports, state management)
- Is the code in the right directory / module?
- Are new abstractions justified, or could this use an existing one?
- Would another developer know where to find this code?

---

## How to report

Be specific. "There might be an issue with error handling" helps nobody.
"The `fetchUser` call in `api/users.ts:34` has no catch block — if the
request fails, the component will show a loading spinner forever" is
actionable.

### Output format

```markdown
## Code Review

**Files reviewed:** [list of files checked]
**Scope:** [what was being built — one line]

---

### Issues

**[CRITICAL]** `file/path.ts:line` — [concise description]
> [Why this matters. What would happen in production.]
> **Fix:** [specific action to take]

**[HIGH]** `file/path.ts:line` — [concise description]
> [Why this matters.]
> **Fix:** [specific action]

**[MEDIUM]** `file/path.ts:line` — [concise description]
> **Fix:** [specific action]

**[LOW]** `file/path.ts:line` — [concise description]
> **Fix:** [specific action]

---

### Looks Good

- [Positive observation about something done well — be specific]
- [Another thing that's solid]

---

### Summary

| Severity | Count |
|----------|-------|
| Critical | X     |
| High     | X     |
| Medium   | X     |
| Low      | X     |

**Verdict:** [Ship it / Fix critical issues first / Needs rework]
```

### Severity levels

| Level | Meaning | Examples |
|-------|---------|---------|
| **CRITICAL** | Will cause failures, data loss, or security exposure | Missing auth check, unhandled crash path, exposed secrets |
| **HIGH** | Real bugs or significant UX/performance problems | Race condition, missing error boundary, N+1 query |
| **MEDIUM** | Code quality issues that compound over time | Untyped interfaces, duplicated logic, unclear naming |
| **LOW** | Style and minor improvements | Formatting, slightly better variable name, unused import |

---

## Tone

- Issues first, praise second. Don't bury a critical bug under five
  paragraphs about what looks good.
- Be direct about severity. If something is fine, don't inflate it to
  seem thorough. If something is broken, don't soften it to be polite.
- When something is done well — especially a tricky pattern handled
  correctly — say so specifically. Good feedback includes positive
  signal, not just a list of complaints.

---

## What NOT to do

- **Don't review code that wasn't changed.** If a file wasn't touched
  in this implementation, it's out of scope. You can note pre-existing
  issues if they directly affect the new code, but label them clearly
  as pre-existing.
- **Don't suggest rewrites.** The review evaluates what was built.
  Architectural second-guessing belongs in exploration, not review.
- **Don't flag style preferences as issues.** If the codebase uses
  semicolons and you prefer no semicolons, that's not a finding.
  Match what exists.
- **Don't inflate the count.** Five real findings are more useful than
  fifteen padded ones. If the code is clean, say so and move on.