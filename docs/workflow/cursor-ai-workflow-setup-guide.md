# Complete AI Development Workflow for Cursor

## Your Setup Checklist

You have:
- [x] Cursor Pro account
- [x] Claude Max plan
- [x] Claude Code extension in Cursor
- [x] Linear Business account

---

## Step 1: Configure Cursor Settings

### Enable Claude as Your Default Model

1. Open Cursor → **Settings** (Cmd/Ctrl + ,)
2. Go to **Models** section
3. Set **Claude Sonnet 4** or **Claude Opus 4** as your default model
4. Enable **Agent Mode** for complex tasks

### Configure Claude Code Extension

1. Open Command Palette (Cmd/Ctrl + Shift + P)
2. Search for "Claude Code: Configure"
3. Ensure your API key is connected (your Max plan covers this)

---

## Step 2: Set Up Slash Commands (Rules)

Cursor uses `.mdc` files in a `.cursor/rules/` directory for slash commands.

### Create the Rules Directory

```bash
# In your project root, create the rules folder
mkdir -p .cursor/rules
```

### Add the Slash Command Files

Copy each of the provided `.mdc` files into `.cursor/rules/`:

```
your-project/
├── .cursor/
│   └── rules/
│       ├── create-issue.mdc
│       ├── explore.mdc
│       ├── create-plan.mdc
│       ├── execute.mdc
│       ├── review.mdc
│       ├── peer-review.mdc
│       ├── document.mdc
│       └── learning-opportunity.mdc
├── src/
└── ...
```

### How to Use Slash Commands

In Cursor's chat or composer:
- Type `/` to see available commands
- Select the command (e.g., `/explore`)
- The prompt will be injected automatically

---

## Step 3: Set Up Linear MCP Integration

This allows Claude to create/read Linear issues directly.

### Install the Linear MCP Server

1. Open your terminal
2. Install the Linear MCP package:

```bash
npm install -g @anthropic/mcp-server-linear
```

3. Get your Linear API key:
   - Go to Linear → Settings → API → Personal API Keys
   - Create a new key with read/write access

4. Configure MCP in Cursor:
   - Open Cursor Settings → Features → MCP
   - Add new server configuration:

```json
{
  "mcpServers": {
    "linear": {
      "command": "mcp-server-linear",
      "env": {
        "LINEAR_API_KEY": "your-linear-api-key-here"
      }
    }
  }
}
```

5. Restart Cursor to activate

### Verify Integration

In Cursor chat, type:
```
Can you list my Linear issues?
```

If connected, Claude will fetch your issues.

---

## Step 4: Create Your claude.md System File

This file lives in your project root and gives Claude persistent context.

Create `claude.md` in your project root:

```markdown
# Project: [YOUR PROJECT NAME]

## Tech Stack
- Frontend: [e.g., React, Next.js, Vue]
- Backend: [e.g., Node.js, Supabase, Firebase]
- Database: [e.g., PostgreSQL, MongoDB]
- Styling: [e.g., Tailwind, CSS Modules]

## Project Structure
[Brief overview of your folder structure]

## Coding Standards
- Use TypeScript for all new files
- Follow existing naming conventions
- Add JSDoc comments for functions
- No console.log in production code

## Our Workflow
1. Create issue in Linear (capture ideas fast)
2. Explore the problem (understand before building)
3. Create detailed plan (markdown with checkboxes)
4. Execute plan step by step
5. Review code (self-review + peer review)
6. Update documentation

## Key Decisions Log
[Track important architectural decisions here]
```

---

## Step 5: The Complete Workflow

### Phase 1: Capture Ideas Fast
```
/create-issue
```
Use when you're mid-development and have a bug or feature idea. Claude creates a Linear issue so you don't lose context.

### Phase 2: Explore Before Building
```
/explore
```
Claude analyzes your codebase, asks clarifying questions, and ensures full understanding before any code is written.

### Phase 3: Create the Plan
```
/create-plan
```
Generates a markdown file with:
- TLDR summary
- Critical decisions
- Step-by-step tasks with status tracking (🟥🟨🟩)

### Phase 4: Execute
```
/execute
```
Implements the plan precisely, updating status as it goes.

### Phase 5: Review
```
/review
```
Comprehensive code review checking for logging, error handling, TypeScript, security, performance.

### Phase 6: Peer Review (The Secret Weapon)
```
/peer-review
```
Paste feedback from another AI model (GPT-4, Gemini, etc.) and have Claude critically evaluate each finding.

### Phase 7: Document
```
/document
```
Updates all relevant documentation based on code changes.

---

## Step 6: Multi-Model Strategy

Zevi's approach uses different models for different strengths:

| Model | Strength | Use For |
|-------|----------|---------|
| **Claude** | Planning, communication, architecture | Exploration, planning, complex logic |
| **GPT-4/Codex** | Deep debugging, gnarly bugs | Fixing stubborn issues |
| **Gemini** | UI/UX, visual design | Frontend work, design implementation |
| **Cursor Composer** | Speed | Quick iterations, simple tasks |

### How to Peer Review Across Models

1. Complete your feature with Claude
2. Open ChatGPT or Gemini
3. Paste the relevant code and ask for review
4. Copy their findings
5. Return to Cursor and run `/peer-review`
6. Paste the external feedback
7. Claude evaluates each finding with full project context

---

## Step 7: Learning Loop

### When Things Go Wrong

After any bug or failure, ask Claude:

> "What in your system prompt or tooling made you make this mistake?"

Then update your `claude.md` or slash commands to prevent it from happening again.

### Continuous Improvement
```
/learning-opportunity
```
Use this anytime you encounter something you don't understand. Claude explains at three levels of complexity.

---

## Quick Reference

| Command | When to Use |
|---------|-------------|
| `/create-issue` | Capture bug/feature idea quickly |
| `/explore` | Before starting any new work |
| `/create-plan` | After exploration is complete |
| `/execute` | When plan is approved |
| `/review` | After implementation |
| `/peer-review` | After getting external AI feedback |
| `/document` | After code changes |
| `/learning-opportunity` | When you want to understand something |

---

## Files Included

1. `cursor-ai-workflow-setup-guide.md` - This file
2. `slash-commands/` - All .mdc files for Cursor
3. `claude-cto-project.md` - CTO prompt for Claude Projects
4. `claude-md-template.md` - Template for your project's claude.md

---

## Next Steps

1. Copy slash command files to `.cursor/rules/`
2. Set up Linear MCP integration
3. Create your `claude.md` file
4. Set up your Claude CTO Project (see included file)
5. Start building!

Remember: **Plan before you build. The exploration phase is not optional.**
