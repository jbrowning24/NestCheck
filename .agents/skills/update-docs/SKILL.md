---
name: update-docs
description: >
  Update project documentation to reflect recent code changes. Use
  when someone says "update docs," "sync the docs," or after completing
  an implementation. Reads the actual code to ensure documentation
  matches reality.
---

# Update Documentation

Code just changed. Your job is to make the documentation match what
the code actually does — not what it used to do.

## The cardinal rule

Read the code, not the docs. Existing documentation may be wrong or
stale. Every claim you write must be verified against the current
implementation. If docs say one thing and code does another, the
code wins.

## Step 1: Identify what changed

- Check git diff or recent commits for modified files
- Note new, deleted, renamed, and moved files
- Understand user-facing impact

If changes are purely internal refactors with no user-facing or
developer-facing impact, documentation may not need updating. Say so.

## Step 2: Read the implementation

For each changed area, understand:
- What it does now
- How it's called / configured
- What inputs and outputs
- Any new environment variables or dependencies
- Error states

## Step 3: Update the right files

Only update documentation that exists. Don't create new doc files
unless asked. Common targets: CHANGELOG.md, README.md, inline code
comments, API docs.

## Style

- Concise over complete
- Examples over explanations
- Match the existing tone
- No filler

## What NOT to do

- Don't document unchanged code
- Don't over-document
- Don't write documentation from memory — verify against code
- Don't create new doc files unprompted
