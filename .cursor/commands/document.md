---
name: update-docs
description: >
  Update project documentation to reflect recent code changes. Use this
  skill when someone says "update docs," "update documentation," "sync
  the docs," "document what we just built," or after completing an
  implementation and wanting to keep docs accurate. Also trigger when
  someone says "update the changelog," "what changed," or wants to
  capture what was built for future reference. This skill reads the
  actual code — not existing docs — to ensure documentation matches
  reality.
---

# Update Documentation

Code just changed. Your job is to make the documentation match what the
code actually does — not what it used to do, and not what someone
intended it to do.

## The cardinal rule

**Read the code, not the docs.** Existing documentation may be wrong,
stale, or describe behavior that was just changed. Every claim you write
in documentation must be verified against the current implementation. If
the docs say one thing and the code does another, the code wins.

---

## Step 1: Identify what changed

Before updating anything, build a clear picture of what's different:

- Check git diff, recent commits, or the implementation plan's completed
  tasks for modified files
- Note new files, deleted files, renamed files, and moved files
- Identify which features or modules were affected
- Understand the user-facing impact: does this change what someone sees,
  what an API returns, how something is configured, or how something
  behaves?

If the changes are purely internal refactors with no user-facing or
developer-facing impact, documentation may not need updating at all.
Say so and move on — don't create busywork.

---

## Step 2: Read the implementation

For each changed area, read the actual code and understand:

- What it does now (not what it did before)
- How it's called / invoked / configured
- What inputs it expects and what outputs it produces
- Any new environment variables, config options, or dependencies
- Error states and what happens when things go wrong

Compare this against existing documentation. Note every discrepancy —
these are your update targets.

---

## Step 3: Update the right files

Only update documentation that exists in the project. Don't create new
doc files unless the user asks for them. Common targets:

### CHANGELOG.md
If the project has one, add entries under an "Unreleased" section (or
the current version if one is being prepared).

Use standard categories:
- **Added** — new features or capabilities
- **Changed** — modifications to existing behavior
- **Fixed** — bug fixes
- **Removed** — features or code that was deleted
- **Security** — vulnerability fixes or security improvements

Write entries in user-facing language. "Added pagination to the
transactions list" not "Refactored TransactionList component to accept
page and limit props." The audience is someone deciding whether to
upgrade, not someone reading the diff.

### README.md
Update if:
- Setup instructions changed (new env vars, new dependencies, new build
  steps)
- Usage examples no longer match the actual API or CLI
- Architecture descriptions are now inaccurate

Leave it alone if nothing user-facing changed in the getting-started
flow.

### Inline code comments
If the implementation changed in a way that makes existing code comments
misleading, update them. A comment that says `// Fetches all users` above
a function that now fetches paginated users is worse than no comment.

### API documentation
If endpoints, request/response shapes, or authentication requirements
changed, update the relevant API docs. Be precise about types and
required vs. optional fields.

### Other project-specific docs
Some projects have docs in `/docs`, wiki pages, or Notion. Only update
these if the user points you to them or if you can see them in the
project structure. Don't go hunting.

---

## Documentation style

- **Concise over complete.** A useful sentence beats a thorough
  paragraph nobody reads.
- **Examples over explanations.** Show a code snippet or command — then
  explain only what isn't obvious from looking at it.
- **Match the existing tone.** If the README is casual, stay casual. If
  it's terse, stay terse. Don't introduce a different voice.
- **No filler.** Cut phrases like "This section describes how to..."
  and "It should be noted that..." Just state the thing.

---

## When to ask the user

Documentation sometimes requires judgment calls you can't make from
code alone:

- The *intent* behind a change (was this a deliberate behavior change
  or a side effect of a refactor?)
- Whether a breaking change needs migration instructions
- Whether something is ready to document publicly or still experimental
- Which audience the docs serve (end users, developers, operators)

If you're unsure about any of these, ask. A wrong doc is worse than a
missing doc — it erodes trust in all the other docs too.

---

## What NOT to do

- **Don't document unchanged code.** Stay scoped to what just changed.
  If you notice pre-existing doc issues, mention them separately — don't
  mix them in.
- **Don't over-document.** Not every internal function needs a JSDoc
  block. Not every commit needs a changelog entry. Use judgment about
  what's worth the reader's attention.
- **Don't write documentation from memory.** Every factual claim must be
  verified against the current code. This includes function signatures,
  default values, environment variable names, and API paths.
- **Don't create new doc files unprompted.** If the project doesn't have
  a CONTRIBUTING.md, don't create one unless asked. Match the project's
  existing documentation footprint.