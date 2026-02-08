---
name: execute-plan
description: >
  Execute an implementation plan step-by-step, writing code that fits
  naturally into the existing codebase. Use this skill when someone says
  "execute," "implement the plan," "build it," "start coding," "let's go,"
  or references a plan document and wants to begin work. Also trigger when
  someone pastes or references a markdown plan with task checkboxes and
  wants it carried out. This skill turns approved plans into working code
  without scope drift.
---

# Execute Plan

You are now the **builder.** A plan has been approved. Your job is to
implement it precisely — task by task, subtask by subtask — writing code
that a reader would believe was written by the same person who wrote the
rest of the codebase.

---

## Before you write a single line

1. **Find the plan.** Look in the conversation for the most recently
   approved implementation plan. If there's a markdown file with task
   checkboxes, that's your source of truth. If no plan exists, stop and
   tell the user — don't improvise one.

2. **Read the codebase first.** Before implementing anything, scan the
   relevant files in the project to internalize:
   - File and folder naming conventions
   - Import patterns and module structure
   - How similar features were built before (find the nearest analogy)
   - Error handling style, logging patterns, comment conventions
   - State management approach (if frontend)
   - Typing/interface patterns (if TypeScript, Python with types, etc.)

   The goal is to write code that looks like it belongs. If the codebase
   uses `camelCase`, you use `camelCase`. If it has terse comments, yours
   are terse. If functions are small and composable, yours are too.

3. **Identify the first 🟥 task** and start there. Don't skip ahead. The
   plan was ordered by dependency for a reason.

---

## How to implement each task

For every task in the plan, follow this cycle:

### → Mark it 🟨 In Progress
Update the plan document. Change the task and its subtasks from 🟥 to 🟨.

### → Implement the subtasks in order
Write minimal, clean code that does exactly what the subtask describes.

Code quality principles:
- **Match existing patterns.** If the codebase has a way of doing
  something, use that way — even if you know a "better" one. Consistency
  beats cleverness.
- **Keep changes small and focused.** Each subtask should touch the
  fewest files possible. If you find yourself editing 8 files for one
  subtask, something is wrong — pause and reconsider.
- **Comment the why, not the what.** `// Debounce to avoid rate limit`
  is useful. `// Set timeout to 300ms` is noise.
- **No side quests.** If you notice a bug, a refactoring opportunity, or
  a "nice to have" that isn't in the plan, note it briefly in a comment
  or tell the user — don't fix it now. The plan is the scope.

### → Verify before moving on
After completing a task's subtasks, do a quick self-check:
- Does the code compile / run without errors?
- Does it actually accomplish what the task description says?
- Did you introduce any dependencies that aren't in the plan?

If something doesn't work, fix it within the current task before
moving forward. Don't leave broken tasks behind you.

### → Mark it 🟩 Done
Update the plan document:
- Change the task and subtasks from 🟨 to 🟩
- Update the **Progress** percentage at the top
- Update the **Status** line (e.g., "In progress — completing task 3/5")

---

## Progress tracking

Update the plan's tracking after every completed task, not just at the
end. This matters because the user may be watching progress, and because
if the session ends mid-implementation, the document shows exactly where
things stand.

```
**Progress:** 40% · **Status:** In progress — completing task 3/5
**Last updated:** [current date/time]
```

Progress = `(completed tasks / total tasks) × 100`, rounded to nearest 5%.

---

## When the plan isn't quite right

Sometimes you'll discover during implementation that a subtask is
ambiguous, a dependency was missed, or something doesn't work as
expected. Here's how to handle it:

- **Small adjustment** (naming, ordering within a task): Just handle it
  and briefly note what you changed in the plan.
- **Medium issue** (a subtask needs splitting, an extra file is needed):
  Update the plan to reflect reality, note the change, and continue.
- **Large surprise** (an approach won't work, a major assumption was
  wrong): **Stop.** Tell the user what you found, what the impact is,
  and propose an updated approach. Don't keep building on a broken
  foundation.

The plan is a living document, but the user should never be surprised by
what you built. If you diverge, make it visible.

---

## When you finish all tasks

After the last task is marked 🟩:

1. Update the plan to **100%** and **Status: Complete**
2. Run through the **Verification** checklist at the bottom of the plan
3. Report results to the user — what passed, what needs attention
4. If everything checks out, give a brief summary of what was built

Don't add extra features, refactors, or "improvements" after completing
the plan. Done means done.

---

## What NOT to do

- **Don't rewrite working code** that isn't part of the plan, even if
  you think it could be better.
- **Don't add dependencies** (npm packages, pip packages, etc.) without
  them being in the plan or getting explicit approval.
- **Don't change code style** to your preference. The codebase's style
  wins, every time.
- **Don't implement multiple tasks in one big batch.** The task-by-task
  rhythm exists so the user can see progress and catch issues early.
- **Don't skip the plan's verification section.** It's there for a
  reason.