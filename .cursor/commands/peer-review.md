---
name: peer-review
description: >
  Critically evaluate code review feedback from another AI model or
  reviewer. Use this skill when someone pastes review findings from
  another model (GPT, Gemini, Copilot, etc.) or another reviewer and
  wants you to verify whether the findings are real. Also trigger on
  phrases like "peer review," "check this feedback," "another model
  found these issues," "evaluate this review," or "here's what [model]
  said." This skill prevents blindly applying bad suggestions by
  treating every finding as a hypothesis to verify against the actual
  code.
---

# Peer Review

Another reviewer — likely a different AI model — has reviewed code from
this project and produced findings. Your job is to be the **team lead**
who decides what actually gets fixed.

## Why this exists

Different AI models catch different things. But they also hallucinate
different things. A model reviewing code without full project context
will frequently flag "issues" that aren't issues — patterns it doesn't
recognize, intentional tradeoffs it doesn't understand, or problems
in code that doesn't actually exist. Blindly applying every suggestion
from a code review is how you introduce bugs while trying to fix them.

You are the one with project context. The reviewer is a colleague who
glanced at the code with fresh eyes — valuable, but not authoritative.
Trust what you can verify. Discard what you can't.

---

## How to evaluate each finding

For every finding the reviewer raised, go through this process:

### 1. Verify it exists

Actually read the code. Don't trust the reviewer's description of what
the code does — look at the file, the function, the line. Ask yourself:

- Does the code the reviewer describes actually exist?
- Does it behave the way the reviewer claims?
- Is the "issue" actually an issue, or is it an intentional pattern?

Models frequently flag things like custom error handling as "missing
error handling," or describe behavior from an outdated version of a
file. Check the real code.

### 2. Check for context the reviewer missed

The reviewer has less context than you. They may not know:

- Why a pattern was chosen (a decision documented in the plan or
  discussed earlier in the conversation)
- That an "issue" is handled elsewhere in the codebase
- That a seemingly redundant check exists for a good reason
- That a piece of code is intentionally simple because the scope
  was deliberately limited

If the finding is wrong because of missing context, explain what the
reviewer missed. Be specific — name the file, function, or decision
that resolves the concern.

### 3. If it's real, assess severity

Not all real issues are worth fixing right now. Categorize:

- **Critical** — will cause bugs, data loss, or security issues in
  production. Fix immediately.
- **Important** — real issue that should be fixed, but won't cause
  immediate harm. Add to the fix plan.
- **Minor** — style, naming, or marginal improvement. Fix if it's
  quick, otherwise note for later.
- **Preference** — the reviewer would do it differently, but the
  current approach isn't wrong. Skip unless there's a compelling reason.

---

## Output format

Present your evaluation in this structure:

```markdown
## Peer Review Evaluation

**Reviewer:** [model name or source, if known]
**Findings evaluated:** [count]
**Confirmed issues:** [count] · **Dismissed:** [count]

---

### Confirmed Issues

**[Finding #] — [Short description]** · _[Critical / Important / Minor]_
[What's actually wrong, verified against the code. Reference the
specific file and location.]

[Repeat for each confirmed issue...]

---

### Dismissed Findings

**[Finding #] — [Short description]** · _Dismissed: [reason category]_
[Brief explanation of why this isn't actually an issue. Be specific —
"already handled in middleware/auth.js" not "already handled elsewhere."]

Reason categories: `not reproducible` · `intentional pattern` ·
`handled elsewhere` · `misread code` · `reviewer lacks context` ·
`preference, not issue`

[Repeat for each dismissed finding...]

---

### Action Plan

[Prioritized list of confirmed issues to fix, ordered by severity.
For each one, a brief description of the fix — enough that the
executor knows what to do, but not actual code.]

1. **[Critical/Important]** [What to fix and where]
2. **[Important]** [What to fix and where]
3. **[Minor]** [What to fix and where]
```

---

## Tone

- Respectful toward the reviewer, even when dismissing their findings.
  "They didn't have context on X" is fine. "They clearly don't
  understand" is not.
- Confident in your assessment — you have project context they don't.
  But if a finding makes you genuinely uncertain, say so and recommend
  investigating further.
- Direct with the user. Don't soften real issues to be polite, and
  don't inflate minor issues to seem thorough.

---

## What NOT to do

- **Don't accept findings without checking the code.** Every finding is
  a hypothesis until you verify it.
- **Don't dismiss findings just because you wrote the code.** If the
  reviewer caught a real bug, own it.
- **Don't fix things during the review.** This is evaluation, not
  implementation. The action plan goes to the executor.
- **Don't add your own new findings.** Stay focused on evaluating what
  the reviewer raised. If you spot something unrelated, mention it
  separately — don't mix it into the peer review evaluation.