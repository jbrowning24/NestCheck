# Create Plan

Based on our exploration, create a comprehensive implementation plan as a markdown file.

## Plan Requirements

### Structure
- Clear, minimal, actionable steps
- Each step is independently testable
- Steps ordered by dependency
- No unnecessary complexity

### Status Tracking
Use these emojis for each task:
- 🟩 Done
- 🟨 In Progress
- 🟥 To Do
- ⏸️ Blocked

### Template

Create a file named `PLAN-[feature-name].md`:

```markdown
# Implementation Plan: [Feature Name]

**Progress:** [----------] 0%
**Created:** [Date]

## TL;DR
[2-3 sentences: What we're building and why]

## Critical Decisions
| Decision | Choice | Rationale |
|----------|--------|-----------|
| [Area] | [What we chose] | [Why] |

## Tasks

### Phase 1: [Foundation]
- [ ] 🟥 **Task 1.1: [Name]**
  - Files: `path/to/file.ts`
  - Acceptance: [How we know it's done]

### Phase 2: [Core Implementation]
- [ ] 🟥 **Task 2.1: [Name]**
  ...

## Testing Checklist
- [ ] Unit tests for [component]
- [ ] Manual QA: [scenarios]
```

## Rules

- **Still no code** - Just the plan
- **Be specific** - Include file paths
- **Define done** - Each task needs acceptance criteria
- **Keep phases small** - 3-5 tasks per phase max
