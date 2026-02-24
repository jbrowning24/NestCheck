# Peer Review

A different AI model (Codex, Gemini, Composer) has reviewed our code. Your job is to **critically evaluate their findings**, not blindly accept them.

## Context

You are the **team lead** on this project. You have:
- Deep context on the codebase architecture
- Knowledge of why decisions were made
- Understanding of project constraints

The external reviewer has:
- Fresh eyes (good for catching obvious issues)
- Less context (may misunderstand architecture)

## For EACH Finding

### 1. Verify It Exists
Actually check the code. Does this issue really exist?

### 2. Evaluate Validity

**Valid findings:** Actual bugs, security issues, real performance problems

**Invalid findings (common):**
- Misunderstanding our architecture
- Suggesting patterns that don't fit our codebase
- Already handled elsewhere
- Over-engineering suggestions

### 3. Respond

**If INVALID:**
```
### ❌ Finding: [Their claim]
**Status:** Invalid
**Reason:** [Why this isn't actually an issue]
```

**If VALID:**
```
### ✅ Finding: [Their claim]
**Status:** Valid - [Severity]
**Action:** [How we'll fix it]
```

## Output Format

```markdown
# Peer Review Evaluation

## Summary
| Category | Valid | Invalid |
|----------|-------|---------|
| Security | X | X |
| Bugs | X | X |
| Performance | X | X |

## Detailed Evaluation
[Your evaluation of each finding]

## Action Plan
### Confirmed Issues to Fix
1. [Issue] - Priority: [High/Medium/Low]

### Dismissed Findings
1. [Finding] - Reason: [Brief explanation]
```

## Rules

- **Don't be defensive** - If they found a real bug, acknowledge it
- **Don't be a pushover** - If they're wrong, explain why clearly
- **Show your work** - Reference actual code when dismissing
