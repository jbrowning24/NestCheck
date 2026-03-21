# NestCheck Shipping Workflow

## Golden Rule

**Always start on `main`.** If you open Claude Code and you're not on `main`, something didn't get closed out last time. Run `git checkout main && git pull` before doing anything else.

**Every implementation prompt ends with "Do NOT commit or push."** Claude Code does the work. You decide when and how to ship it.

---

## Slash Commands

### `/pr-learn`

**What it does:** Reviews the current diff for bugs (red/yellow/green severity flags) and extracts new lessons into CLAUDE.md. **When to use:** After every implementation, before shipping. This is your code review + institutional learning step. **Location:** `.claude/commands/pr-learn.md` (project) and `~/.claude/commands/pr-learn.md` (global)

### `/code-review`

**What it does:** Deep comprehensive review — logging, error handling, type hints, production readiness, API safety, SQLite, templates, security, architecture. Outputs a structured report with severity levels. **When to use:** For larger or riskier changes where `/pr-learn`'s quick bug scan isn't enough. **Location:** `.claude/commands/code-review.md`

### `/ship`

**What it does:** Commits all changes with a conventional commit message (`feat:`, `fix:`, etc.) and pushes to the current branch (main). Sets upstream if needed. **When to use:** When you've reviewed the work and it doesn't need visual verification. Backend changes, scoring logic, data pipeline work. **Location:** `~/.claude/commands/ship.md`

### `/preview`

**What it does:** Creates a `preview/<description>` branch, commits changes with a NES-prefixed message, pushes, and opens a PR via `gh pr create --fill`. Prints the GitHub PR URL and reminds you to wait for the Railway preview environment. **When to use:** When the change touches templates, CSS, or anything visual that you need to see before it goes live. **Location:** `.claude/commands/preview.md`

### `/merge`

**What it does:** Finds the open PR for the current branch, squash-merges it, deletes the branch, checks out `main`, and pulls. Prints confirmation when done. **When to use:** After you've verified a `/preview` change via the Railway preview URL.**Location:** `.claude/commands/merge.md`

### `/commit-push-pr`

**What it does:** Commits all changes, pushes to the current branch, and opens a PR. Legacy command — uses pre-computed git context. **When to use:** Rarely. `/preview` and `/ship` cover the two main paths. Keep this around as a fallback. **Location:** `.claude/commands/commit-push-pr.md`

### `/exploration-phase`

**What it does:** Pre-implementation exploration. Analyzes the codebase, surfaces ambiguities, challenges assumptions. No code writing allowed. Iterates until zero questions remain. **When to use:** Before starting a new feature or complex change. This is the "understand the problem" step. **Location:** `.claude/commands/exploration-phase.md`

### `/create-plan`

**What it does:** Creates a structured implementation plan as a markdown file (`PLAN-[feature-name].md`) with status tracking emojis, phases, acceptance criteria, and a testing checklist. **When to use:** After exploration, before implementation. Produces the plan that Claude Code will execute. **Location:** `.claude/commands/create-plan.md`

---

## Workflows

### Workflow A: Backend / Scoring / Logic Changes

No visual verification needed. Fastest path.

```
1. Implementation prompt
   └── ends with "Do NOT commit or push"
2. /pr-learn
   └── reviews diff, flags bugs, updates CLAUDE.md
3. /ship
   └── commits + pushes to main
   └── Railway auto-deploys
```

### Workflow B: Template / CSS / Visual Changes

You need to see it before it goes live.

```
1. Implementation prompt
   └── ends with "Do NOT commit or push"
2. /pr-learn
   └── reviews diff, flags bugs, updates CLAUDE.md
3. /preview
   └── creates branch, opens PR, prints GitHub link
4. Wait ~2 min → click Railway preview URL in PR comment
5. /merge
   └── squash merges PR, deletes branch, returns to main
   └── Railway auto-deploys from main
```

### Workflow C: Large / Risky Changes

Extra review before shipping.

```
1. /exploration-phase
   └── understand the problem, surface ambiguities
2. /create-plan
   └── produces PLAN-[feature].md with phases
3. Implementation prompt (per phase)
   └── ends with "Do NOT commit or push"
4. /code-review
   └── deep review: security, architecture, API safety
5. /pr-learn
   └── bug scan + CLAUDE.md learning
6. /ship or /preview
   └── depending on whether visual verification is needed
```

---

## Railway Preview Environments

### Setup (one-time, in browser)

1. Railway dashboard → Project Settings → Environments
2. Toggle **Enable PR Environments**
3. Production service → Settings → Networking
4. Add a **Railway-provided domain** (keep your custom domain too)

### How it works

- When `/preview` opens a PR, Railway auto-builds a temporary environment
- The preview URL appears as a comment on the GitHub PR (~2 min)
- The environment is deleted when the PR is merged or closed
- Preview environments get a fresh database (no shared SQLite volume) — run an evaluation if you need to see a report

---

## Git Hygiene

### Rules

- **Start every session on `main`.**
- **Never leave a branch alive after its work is shipped.** `/merge` handles this. `/ship` skips branches entirely.
- **One branch = one piece of work.** Don't reuse branches across tasks.

### If things get messy

Run this diagnostic in Claude Code:

```
Run these commands and report the output:
1. git status
2. git branch -a
3. git log --oneline -10
4. gh pr list --state open
5. gh pr list --state closed --limit 5

Then tell me:
- What branch am I on right now?
- Are there uncommitted changes?
- Are there open PRs, and what branches are they pointing to?
- Are there local branches that don't have corresponding PRs?
- Are there PRs pointing to branches that are behind main?
```

### Cleanup stale branches

```
git branch | grep -v "main" | xargs git branch -D
```

---

## Weekly Sweep

Do this once a week (Sunday or Monday). Five minutes if everything is clean, fifteen if something slipped. The daily workflows above prevent most drift. This catches the rest.

### 1. Run the diagnostic

Open Claude Code and run the "if things get messy" diagnostic above. You're looking for branches that shouldn't exist, uncommitted changes, and open PRs that should have been merged or closed.

### 2. Cross-reference branches against Linear

Your branch naming convention (`jerabrowning/nes-XXX-...`) makes this fast. For each open branch:

- **Ticket is Done in Linear → branch not merged?** Either merge it or delete it. If you can't remember why it's hanging, `git log main..{branch} --oneline` tells you what's on it.
- **Ticket is Backlog → branch has commits?** You started work and got pulled away. Either push it forward or reset to main and let the ticket sit until you're ready.
- **Branch has no corresponding ticket?** That's an ad-hoc change that skipped the process. Decide: ship it, ticket it, or kill it.

### 3. Verify Railway deployment

```
# In Claude Code:
git log main -1 --format="%H %s"
```

Compare this against the `RAILWAY_GIT_COMMIT_SHA` in your Railway dashboard (Settings → Variables, or the latest deploy log). If they don't match:

- **Main is ahead of Railway:** Deploy may have failed. Check Railway build logs.
- **Railway is ahead of main:** Something was deployed from a branch or a force push. Investigate.

### 4. Review the backlog

Quick scan of Linear Backlog tickets. Ask three questions:

- Did anything ship this week that unblocks a Backlog ticket? **Promote it.**
- Is any Backlog ticket stale or no longer relevant? **Cancel it with a rationale.**
- Is any Backlog ticket actually urgent but sitting at Low priority because you filed it when you were busy? **Reprioritize it.**

This isn't planning. It's 2 minutes of triage so the backlog stays honest.

---

## Decision Guide: Which Path?

|Change type|Visual?|Path|
|---|---|---|
|Scoring logic, evaluator, models|No|`/pr-learn` → `/ship`|
|New data source, API integration|No|`/code-review` → `/pr-learn` → `/ship`|
|Template HTML changes|Yes|`/pr-learn` → `/preview` → verify → `/merge`|
|CSS / design system changes|Yes|`/pr-learn` → `/preview` → verify → `/merge`|
|Landing page updates|Yes|`/pr-learn` → `/preview` → verify → `/merge`|
|Bug fix (backend)|No|`/pr-learn` → `/ship`|
|Bug fix (UI)|Yes|`/pr-learn` → `/preview` → verify → `/merge`|
|New feature (complex)|Depends|Full Workflow C|

---

## File Locations

```
NestCheck/
  .claude/
    commands/
      code-review.md        # Deep code review
      commit-push-pr.md     # Legacy: commit + PR (prefer /ship or /preview)
      create-plan.md        # Structured implementation plans
      exploration-phase.md  # Pre-implementation analysis
      merge.md              # Squash merge + return to main
      pr-learn.md           # Quick review + CLAUDE.md learning
      preview.md            # Branch + PR for visual verification

~/.claude/
  commands/
    pr-learn.md             # Global version of pr-learn
    ship.md                 # Commit + push to main
```