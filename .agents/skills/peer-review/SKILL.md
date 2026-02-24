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

Another reviewer, likely a different AI model, has reviewed code from
this project and produced findings. Act as the team lead who decides
what actually gets fixed.

## Why this exists

Different AI models catch different things. They also hallucinate
different things. A model reviewing code without full project context
will frequently flag "issues" that are not issues: patterns it does not
recognize, intentional tradeoffs it does not understand, or problems
in code that does not actually exist. Blindly applying every suggestion
from a code review introduces bugs while trying to fix them.

Treat the reviewer as a colleague who glanced at the code with fresh
eyes: valuable, but not authoritative. Trust what you can verify.
Discard what you cannot.

## How to evaluate each finding

For every finding the reviewer raised, follow this process:

### 1. Verify it exists

Read the code directly. Do not trust only the reviewer's description.
Check the actual file, function, and line.

- Does the code the reviewer describes actually exist?
- Does it behave the way the reviewer claims?
- Is the issue actually an issue, or an intentional pattern?

Models frequently flag custom error handling as "missing error handling,"
or describe behavior from an outdated file version.

### 2. Check for context the reviewer missed

The reviewer may not know:

- Why a pattern was chosen (documented plan or prior decisions)
- That an issue is handled elsewhere in the codebase
- That a seemingly redundant check exists for a good reason
- That a simple implementation is intentionally scoped

If a finding is wrong due to missing context, explain exactly what was
missed and reference the file/function/decision that resolves it.

### 3. If it is real, assess severity

- **Critical**: causes bugs, data loss, or security issues in production.
  Fix immediately.
- **Important**: real issue that should be fixed, but not immediate harm.
  Add to the fix plan.
- **Minor**: style/naming/marginal improvements. Fix if quick, otherwise
  track for later.
- **Preference**: alternative style/opinion; current approach is not
  wrong. Skip unless there is a compelling reason.

## Output format

Present evaluation in this structure:

```markdown
## Peer Review Evaluation

**Reviewer:** [model name or source, if known]
**Findings evaluated:** [count]
**Confirmed issues:** [count] · **Dismissed:** [count]

---

### Confirmed Issues

**[Finding #] — [Short description]** · _[Critical / Important / Minor]_
[What is actually wrong, verified against the code. Reference the
specific file and location.]

[Repeat for each confirmed issue...]

---

### Dismissed Findings

**[Finding #] — [Short description]** · _Dismissed: [reason category]_
[Brief explanation of why this is not an issue. Be specific, for
example "already handled in middleware/auth.js".]

Reason categories: `not reproducible` · `intentional pattern` ·
`handled elsewhere` · `misread code` · `reviewer lacks context` ·
`preference, not issue`

[Repeat for each dismissed finding...]

---

### Action Plan

[Prioritized list of confirmed issues to fix, ordered by severity.
For each item, provide enough detail for an executor to implement.]

1. **[Critical/Important]** [What to fix and where]
2. **[Important]** [What to fix and where]
3. **[Minor]** [What to fix and where]
```

## Tone

- Be respectful toward the reviewer, including when dismissing findings.
- Be confident in verified assessment grounded in project context.
- Be direct with the user. Do not soften real issues or inflate minor ones.
- If uncertain about a finding, say so and recommend focused follow-up.

## What NOT to do

- Do not accept findings without checking code.
- Do not dismiss findings just because you wrote the code.
- Do not fix issues during the review; this skill performs evaluation.
- Do not add unrelated new findings into the peer-review evaluation.
