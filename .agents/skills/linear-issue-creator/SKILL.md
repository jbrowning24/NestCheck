---
name: linear-issue-creator
description: >
  Quickly capture bugs, features, and improvements as Linear issues while the user is mid-flow.
  Use this skill whenever the user wants to create a Linear issue, log a bug, file a ticket,
  track a feature request, or capture any work item in Linear. Also trigger when the user says
  things like "we should track this", "make a ticket for", "log this as a bug", "add this to
  the backlog", "create an issue for", or describes a problem/feature that should be captured.
---

# Linear Issue Creator

Create a well-structured Linear issue quickly so the user can keep moving.

## Core Principles

**Prioritize speed over perfection.** Create a good issue now, then let the user refine later.

**Be conversational.** Avoid turning issue creation into a long form.

**Protect flow.** Ask at most one follow-up round, with 2-3 focused questions max.

## Workflow

### 1. Gather context quickly

Extract from the user message:

- **What**: bug, feature, or improvement
- **Current vs expected**: what happens now vs what should happen
- **Type**: infer unless ambiguous
- **Priority**: default to Medium (`3`) unless context indicates otherwise
- **Relevant files**: include if known

If the issue is coherent enough to write title + description, create it immediately.

If critical details are missing, ask one concise follow-up with up to 2-3 targeted questions.

### 2. Check Linear context only when useful

Run lookups only if they improve quality:

- List teams to pick the right team (cache mentally in-session)
- Search issues if duplication is likely
- List projects if project membership is obvious
- Use `assignee: "me"` unless the user asks otherwise

Skip unnecessary lookups for straightforward requests.

### 3. Create the issue

Use `mcp__linear__create_issue` with:

- `team`: required
- `title`: concise, area-prefixed when possible
- `description`: markdown template below
- `assignee`: `"me"` by default
- `priority`: `1` Urgent, `2` High, `3` Medium (default), `4` Low
- `labels`: apply existing labels when clearly relevant
- `parentId`: set only when clearly a sub-issue
- `project`: set only when clearly associated
- `state`: set to backlog/todo state; never set in-progress unless asked

Title patterns:

- Bug: `[Area] Brief description of what's broken`
- Feature: `[Area] Brief description of what to build`
- Improvement: `[Area] Brief description of what to improve`

Description template:

```markdown
**TL;DR**
One-sentence summary.

**Current behavior**
What happens now. (Skip for net-new feature requests.)

**Expected behavior**
What should happen instead.

**Files**
- `path/to/file.ts` - reason it is relevant
- `path/to/other.ts` - reason it is relevant

**Notes**
Risks, dependencies, edge cases, or extra context.
```

Keep descriptions scannable and brief.

### 4. Wire relationships when obvious

If clear from context:

- Set `parentId` for sub-issues
- Set `project` for active project alignment
- Add related issue identifiers in description notes

Do not force relationships.

### 5. Confirm succinctly

After creating, respond in 2-3 lines with:

- Issue identifier (for example `TEAM-123`)
- Title
- Link (if available)
- Any relationship you set

## Priority Heuristics

- `1` Urgent: outage, severe security issue, blocked release
- `2` High: user-facing breakage, core flow regression
- `3` Medium: default for normal bugs/features/improvements
- `4` Low: polish or non-urgent follow-up

## Guardrails

- Do not ask about type/priority if obvious
- Do not ask for confirmation before creating
- Do not create multiple issues unless asked
- Do not write long, dense descriptions
- Do not include more than 3 files in the Files section
