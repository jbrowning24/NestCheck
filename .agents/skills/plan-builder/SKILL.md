---
name: plan-builder
description: >
  Generate structured implementation plans from conversation context.
  Use this skill whenever someone asks to "create a plan," "make a plan,"
  "write a plan," "plan this out," "break this into steps," or "what do I
  need to build." Also trigger when someone wraps up an exploration or
  brainstorming phase and says things like "okay, let's do it," "how should
  we build this," or "what's the path forward." The skill transforms messy
  discussion into a clean, trackable execution document - without writing
  any code.
---

# Plan Builder

You are transitioning from **thinking mode** to **building mode.** Your job
is to produce a single, high-signal implementation plan that a developer
(human or AI) can execute step-by-step without needing to re-read the
conversation.

This is a planning document, not a coding session. Do not write code. Do
not start building. The plan IS the deliverable.

## Why this matters

Plans prevent the #1 failure mode in AI-assisted development: the AI
eagerly writes code before understanding the problem, producing something
that looks right but is architecturally wrong. A good plan forces
clarity _before_ keystrokes. It also creates a checkpoint - the human
reviews and approves the plan, catching misunderstandings while they're
cheap to fix.

## Before you write anything

Scan the full conversation for:
1. **The goal** - what the user actually wants to exist when this is done
2. **Decisions already made** - tech choices, constraints, tradeoffs discussed
3. **Open questions** - anything ambiguous or unresolved
4. **Scope boundaries** - what's explicitly in, and what's explicitly out

If open questions remain that would meaningfully change the plan's
structure, surface them to the user in a short bulleted list BEFORE
producing the plan. Keep it to <=3 questions. Don't ask about things you
can make a reasonable default choice on - just document the assumption in
the plan.

## Plan structure

Use this exact template. Every section is required unless noted otherwise.

```markdown
# Implementation Plan: [Title]

**Progress:** 0% · **Status:** Not started
**Last updated:** [date]

## TLDR
[2-3 sentences. What are we building, for whom, and what's the key
technical approach. A busy person should be able to read this and know
whether to keep reading.]

## Scope
**In scope:**
- [thing 1]
- [thing 2]

**Out of scope:**
- [thing explicitly excluded and why]

## Key Decisions
[Decisions made during exploration that constrain the implementation.
Each one should have a brief rationale so a future reader understands
WHY, not just WHAT.]

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | [choice] | [why]     |
| 2 | [choice] | [why]     |

## Assumptions
[Things you're assuming to be true that, if wrong, would change the
plan. This section can be omitted if there are no meaningful assumptions.]

- [assumption 1]
- [assumption 2]

## Tasks

- [ ] 🟥 **1. [Task name]** · _[estimated complexity: S/M/L]_
  [One sentence describing what this task accomplishes and why it
  comes at this point in the sequence.]
  - [ ] 🟥 1.1 [Subtask - concrete, verifiable action]
  - [ ] 🟥 1.2 [Subtask]

- [ ] 🟥 **2. [Task name]** · _[S/M/L]_
  [Context sentence.]
  - [ ] 🟥 2.1 [Subtask]
  - [ ] 🟥 2.2 [Subtask]

[Continue as needed...]

## Verification
[How do we know this is done? 2-4 concrete checks someone can perform
after the last task is complete.]

- [ ] [Check 1 - e.g., "App loads without errors on localhost"]
- [ ] [Check 2 - e.g., "User can complete the core flow end-to-end"]
```

## How to write good tasks

Each task should pass these tests:

- **Ordered by dependency.** If task 3 requires task 1, task 1 comes
  first. Call out non-obvious dependencies explicitly.
- **One concern per task.** A task called "Set up auth and build the
  dashboard" is two tasks. Split them.
- **Subtasks are actions, not descriptions.** "Create the user model
  with fields: name, email, role" is good. "Handle user stuff" is not.
- **Verifiable completion.** Someone should be able to look at a finished
  subtask and confirm it's done without subjective judgment.
- **No gold-plating.** Include only what's needed to achieve the stated
  goal. Resist adding "nice to have" items unless the user explicitly
  asked for them. If something feels like scope creep, leave it out and
  mention it in a brief "Future considerations" note at the end.

Size estimates (S/M/L) are rough signals for the executor, not
commitments. S = a few minutes of focused work, M = meaningful chunk,
L = might need its own sub-plan.

## Status tracking

Use these markers consistently:

| Emoji | Meaning |
|-------|---------|
| 🟩 | Done |
| 🟨 | In progress |
| 🟥 | Not started |

Update the **Progress** percentage at the top when tasks are completed.
Calculate it as: `(completed tasks / total tasks) × 100`, rounded to
the nearest 5%.

## Tone and style

- Write for a builder, not a committee. Be direct.
- Prefer concrete nouns over abstract ones. "Create a PostgreSQL
  migration for the users table" beats "Set up the data layer."
- Keep the plan as short as possible while remaining unambiguous. If a
  section has nothing meaningful to say, omit it.
- Don't repeat information from the conversation - synthesize it.
- Use the user's own terminology for project-specific concepts.

## What NOT to do

- Don't include code snippets in the plan.
- Don't add testing/documentation/deployment tasks unless the user
  specifically asked for them. The executor can handle these as part of
  good practice without cluttering the plan.
- Don't hedge or add disclaimers. If something is uncertain, put it in
  Assumptions or surface it as a question.
- Don't produce a plan that's longer than the feature warrants. A simple
  CRUD endpoint doesn't need 15 tasks.
