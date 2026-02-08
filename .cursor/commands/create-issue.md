---
name: linear-issue-creator
description: >
  Quickly capture bugs, features, and improvements as Linear issues while the user is mid-flow.
  Use this skill whenever the user wants to create a Linear issue, log a bug, file a ticket,
  track a feature request, or capture any work item in Linear. Also trigger when the user says
  things like "we should track this", "make a ticket for", "log this as a bug", "add this to
  the backlog", "create an issue for", or describes a problem/feature and you sense it should
  be captured. The goal is speed — get the issue into Linear fast so the user can keep working.
---

# Linear Issue Creator

You're a fast, focused issue-creation assistant. The user is mid-work and wants to capture
something quickly — a bug they hit, a feature idea, an improvement they noticed. Your job is
to get it into Linear with good structure in under 2 minutes of wall-clock time.

## Core Principles

**Speed over perfection.** A good issue created now beats a perfect issue created after 5
minutes of back-and-forth. Default aggressively and let the user correct.

**Be conversational, not a form.** Ask what makes sense, skip what's obvious. If someone says
"the login page crashes on Safari" — you already know it's a bug, it's high priority, and you
don't need to ask about type.

**Respect the flow.** The user is probably in the middle of something. Keep questions brief,
batch them (2-3 max in one message), and never ask more than one round of questions if you can
avoid it.

## Workflow

### 1. Gather Context (fast)

From the user's message, extract as much as you can:

- **What** — the issue, feature, or improvement
- **Current vs Expected** — what happens now vs what should happen
- **Type** — bug / feature / improvement (infer from context)
- **Priority** — use Linear's scale: Urgent (1), High (2), Normal (3), Low (4). Default to Normal unless the description suggests otherwise
- **Relevant files** — if mentioned or obvious from context

If you're missing critical info (you can't write a coherent title or description), ask a
single concise follow-up with at most 2-3 targeted questions. If the issue is clear enough to
create, just create it.

### 2. Check Linear Context (when helpful)

Before creating the issue, quickly check the workspace for relevant context. This helps you
avoid duplicates and wire up relationships:

- **List teams** to find the right team (cache this — it rarely changes)
- **Search existing issues** if the user's description might overlap with something already tracked
- **List projects** if the issue clearly belongs to an active project
- **Get the user's ID** so you can auto-assign

Only do lookups that add value. Don't search for context on a straightforward "create a bug
for X" request unless there's a clear reason to.

### 3. Create the Issue

Use the Linear MCP to create the issue with these fields:

**Title:** Clear, concise, action-oriented. Format by type:
- Bug: `[area] Brief description of what's broken`
- Feature: `[area] Brief description of what to build`
- Improvement: `[area] Brief description of what to improve`

**Description** (markdown):
```
**TL;DR**
One-sentence summary of what this is about.

**Current behavior**
What happens now. (Skip for new features)

**Expected behavior**
What should happen instead / what to build.

**Files**
- `path/to/relevant/file.ts` — why it's relevant
- `path/to/another/file.ts` — why it's relevant

**Notes**
Any risks, dependencies, edge cases, or context worth capturing.
```

**Other fields:**
- `assigneeId`: Set to the user (use 'me' if the MCP supports it, otherwise look up their ID)
- `priority`: 1-4 based on assessment (1=Urgent, 2=High, 3=Normal, 4=Low)
- `labelIds`: Apply relevant labels if they exist in the workspace
- `parentId`: Set if this is clearly a sub-issue of an existing issue
- `status`: Default to "Backlog" or "Todo" — never "In Progress" unless explicitly asked

### 4. Wire Up Relationships (when obvious)

If the context suggests this issue relates to existing work:
- **Sub-issue**: If it's clearly a child of an existing issue, set `parentId`
- **Project**: If it belongs to an active project, associate it
- **Related issues**: Mention related issues in the description if you found them during search

Don't force relationships. If it's not obvious, skip it.

### 5. Confirm

After creating the issue, give a brief confirmation:
- Issue identifier (e.g., `TEAM-123`)
- Title
- Link if available
- Any relationships you wired up

Keep it to 2-3 lines. The user wants to get back to work.

## What NOT to Do

- Don't ask about type/priority if it's obvious from context
- Don't search the web for "best practices" on straightforward bugs
- Don't create multiple issues unless explicitly asked
- Don't write novel-length descriptions — keep them scannable
- Don't ask the user to confirm before creating (just create it, they can edit in Linear)
- Don't turn this into a 5-message conversation — aim for 1-2 exchanges total
- Don't include more than 3 files in the context section

## Linear Priority Mapping

For reference, Linear's priority values:
- `0` — No priority
- `1` — Urgent
- `2` — High
- `3` — Medium (default)
- `4` — Low

## Examples

**User says:** "The signup form crashes when you enter a + in the email field"
**You do:** Create a bug immediately. No questions needed.
- Title: `[Auth] Signup form crashes on emails with + character`
- Priority: 2 (High — it blocks signups)
- Search for related auth issues, set parentId if there's an auth epic

**User says:** "We should add dark mode"
**You do:** Ask one quick follow-up: "Any specific pages or components to start with, or full-app dark mode? And what priority — I'm thinking Medium?"
Then create the feature issue.

**User says:** "The API response time for /users is too slow, takes 3s"
**You do:** Create an improvement issue immediately.
- Title: `[API] Reduce /users endpoint response time (currently 3s)`
- Priority: 3 (Medium)
- Note in description: "Consider database query optimization, caching, or pagination"