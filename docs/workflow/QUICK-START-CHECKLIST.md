# Quick Start Checklist

## 5-Minute Setup

### Step 1: Copy Slash Commands (2 min)

```bash
# In your project root
mkdir -p .cursor/rules

# Copy all .mdc files from slash-commands/ to .cursor/rules/
```

Files to copy:
- `create-issue.mdc`
- `explore.mdc`
- `create-plan.mdc`
- `execute.mdc`
- `review.mdc`
- `peer-review.mdc`
- `document.mdc`
- `learning-opportunity.mdc`

### Step 2: Create claude.md (1 min)

Copy `claude-md-template.md` to your project root as `claude.md`

Customize:
- [ ] Project name
- [ ] Tech stack
- [ ] Project structure
- [ ] Coding standards

### Step 3: Set Up Linear MCP (2 min)

1. Get API key from Linear: Settings → API → Create key
2. Add to Cursor: Settings → Features → MCP → Add Server
3. Restart Cursor

See `linear-mcp-setup.md` for detailed instructions.

### Step 4: Create Your CTO Project

1. Go to claude.ai
2. Create new Project
3. Paste instructions from `claude-cto-project.md`
4. Customize for your project

---

## Your First Workflow Run

### Test the Setup

1. Open Cursor in your project
2. Type `/explore` in the chat
3. Describe a simple feature you want to build
4. Let Claude ask questions
5. When ready, type `/create-plan`
6. Review the plan
7. Type `/execute`
8. After completion, type `/review`

### Peer Review Test

1. Copy your code to ChatGPT or Gemini
2. Ask it to review the code
3. Copy its findings
4. Back in Cursor, type `/peer-review`
5. Paste the external feedback
6. Watch Claude evaluate each finding

---

## Files Included

| File | Purpose |
|------|---------|
| `cursor-ai-workflow-setup-guide.md` | Complete setup instructions |
| `slash-commands/*.mdc` | All 8 slash command files |
| `claude-cto-project.md` | CTO project for Claude |
| `claude-md-template.md` | Template for your project context |
| `linear-mcp-setup.md` | Linear integration guide |
| `QUICK-START-CHECKLIST.md` | This file |

---

## Common Commands

| What you want | Command |
|---------------|---------|
| Capture a quick idea | `/create-issue` |
| Start a new feature | `/explore` → answer questions |
| Get a plan | `/create-plan` |
| Build the thing | `/execute` |
| Check my code | `/review` |
| Get a second opinion | `/peer-review` + external AI feedback |
| Update docs | `/document` |
| Learn something | `/learning-opportunity` |

---

## Troubleshooting

### Slash commands not showing
- Check files are in `.cursor/rules/`
- File extension must be `.mdc`
- Restart Cursor

### Linear not connecting
- Verify API key is correct
- Check MCP config syntax
- Restart Cursor

### Claude seems confused
- Update your `claude.md` with more context
- Start a fresh conversation
- Be more specific in your prompts

---

## Next Level Tips

1. **Use voice mode** with your CTO project for faster ideation

2. **Different models for different tasks:**
   - Claude: Planning, complex logic
   - GPT-4: Stubborn bugs
   - Gemini: UI work

3. **Update when things break** - After any bug, ask Claude: "What made you make this mistake?"

4. **Build the decision log** - Every major choice goes in `claude.md`

5. **Use `/learning-opportunity`** liberally - Understanding > speed

---

You're ready! Go build something. 🚀
