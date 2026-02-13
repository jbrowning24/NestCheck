---
name: execute-plan
description: >
  Execute an implementation plan step-by-step, writing code that fits
  naturally into the existing codebase. Use when someone says "execute,"
  "implement the plan," "build it," or references a plan with task
  checkboxes. Turns approved plans into working code without scope drift.
---

# Execute Plan

You are now the builder. A plan has been approved. Your job is to
implement it precisely — task by task — writing code that a reader
would believe was written by the same person who wrote the rest of
the codebase.

## Before you write a single line

1. Find the plan. Look in the conversation for the most recently
   approved implementation plan. If no plan exists, stop and say so.

2. Read the codebase first. Scan the relevant files to internalize:
   - File and folder naming conventions
   - Import patterns and module structure
   - How similar features were built before
   - Error handling style, logging patterns, comment conventions

   The goal is to write code that looks like it belongs.

3. Identify the first task and start there. Don't skip ahead.

## How to implement each task

- Match existing patterns. Consistency beats cleverness.
- Keep changes small and focused. Each subtask should touch the
  fewest files possible.
- Comment the why, not the what.
- No side quests. If you notice something not in the plan, note it
  but don't fix it now. The plan is the scope.

### Verify before moving on
- Does the code run without errors?
- Does it accomplish what the task description says?
- Did you introduce any dependencies not in the plan?

## What NOT to do

- Don't rewrite working code that isn't part of the plan.
- Don't add dependencies without them being in the plan.
- Don't change code style to your preference. The codebase's style wins.
- Don't skip verification.
