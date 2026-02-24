# Linear MCP Integration Guide

This guide helps you connect Linear to Cursor so Claude can create and manage issues directly.

## What is MCP?

MCP (Model Context Protocol) is Anthropic's standard for connecting AI models to external tools. With Linear MCP, Claude in Cursor can:

- Create new issues from your conversations
- Read existing issues for context
- Update issue status
- Link issues to your development work

---

## Setup Options

### Option A: Official Linear MCP Server (Recommended)

#### Step 1: Get Your Linear API Key

1. Go to **Linear** → **Settings** (gear icon)
2. Navigate to **Account** → **API**
3. Click **Create new API key**
4. Give it a name like "Cursor MCP"
5. Copy the key (you won't see it again!)

#### Step 2: Install the MCP Server

```bash
npm install -g @anthropic-ai/mcp-server-linear
```

Or with Bun:
```bash
bun add -g @anthropic-ai/mcp-server-linear
```

#### Step 3: Configure Cursor

1. Open Cursor **Settings** → **Features** → **MCP**
2. Click **Add Server** or edit the config file directly

Add this configuration:

```json
{
  "mcpServers": {
    "linear": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-server-linear"],
      "env": {
        "LINEAR_API_KEY": "lin_api_YOUR_KEY_HERE"
      }
    }
  }
}
```

#### Step 4: Restart Cursor

Close and reopen Cursor for changes to take effect.

#### Step 5: Test the Connection

In Cursor chat:
```
Can you list my Linear issues?
```

If configured correctly, Claude will fetch and display your issues.

---

### Option B: Using npx (No Global Install)

If you don't want to install globally, use npx in your MCP config:

```json
{
  "mcpServers": {
    "linear": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-server-linear"],
      "env": {
        "LINEAR_API_KEY": "lin_api_YOUR_KEY_HERE"
      }
    }
  }
}
```

---

## Configuration File Locations

### macOS
```
~/Library/Application Support/Cursor/User/globalStorage/cursor.mcp/config.json
```

### Windows
```
%APPDATA%\Cursor\User\globalStorage\cursor.mcp\config.json
```

### Linux
```
~/.config/Cursor/User/globalStorage/cursor.mcp/config.json
```

---

## Available Linear Commands

Once connected, Claude can use these capabilities:

### Read Operations
- List issues (with filters)
- Get issue details
- Search issues
- List projects/teams

### Write Operations
- Create new issues
- Update issue properties
- Change issue status
- Add comments
- Assign issues

---

## Example Usage with /create-issue

When you run `/create-issue` in Cursor, Claude will:

1. Ask clarifying questions about the bug/feature
2. Search your codebase for relevant files
3. Create a well-formatted issue in Linear
4. Return the issue ID for reference

Example conversation:
```
You: /create-issue

Claude: Ready to capture. What's on your mind?

You: The login button is broken on mobile Safari

Claude: Got it. A few quick questions:
- What happens when tapped? (Nothing? Error? Wrong redirect?)
- Which page is this on?
- Is this blocking users?

You: Nothing happens. Landing page. Yes it's blocking signups.

Claude: Creating issue now...

✅ Created LIN-234: "Mobile Safari: Login button unresponsive on landing page"
Priority: High
Labels: bug, mobile
```

---

## Troubleshooting

### "MCP server not found"
- Check that the package is installed: `npm list -g @anthropic-ai/mcp-server-linear`
- Verify the command path in your config
- Restart Cursor

### "Authentication failed"
- Verify your API key is correct
- Check the key has proper permissions (read/write)
- Ensure there are no extra spaces in the key

### "Cannot connect to Linear"
- Check your internet connection
- Verify Linear is not having an outage: status.linear.app
- Try regenerating your API key

### "Issues not showing"
- Verify you have access to the team/project
- Check your Linear workspace is active
- Try filtering to a specific project

---

## Security Best Practices

1. **Use environment variables** - Don't commit API keys to git
2. **Limit key permissions** - Only grant access needed
3. **Rotate keys periodically** - Create new keys and revoke old ones
4. **Use team-specific keys** - If working across multiple workspaces

### Using Environment Variables

Instead of hardcoding the key:

```json
{
  "mcpServers": {
    "linear": {
      "command": "npx",
      "args": ["-y", "@anthropic-ai/mcp-server-linear"],
      "env": {
        "LINEAR_API_KEY": "${LINEAR_API_KEY}"
      }
    }
  }
}
```

Then set in your shell profile:
```bash
export LINEAR_API_KEY="lin_api_YOUR_KEY_HERE"
```

---

## Alternative: Linear Webhooks

If MCP doesn't work for your setup, you can use Linear's webhooks:

1. Create a small webhook handler (Vercel/Railway)
2. Have Linear notify on issue events
3. Store issue data locally for Claude to reference

This is more work but gives you:
- Offline access to issue data
- Custom filtering logic
- Lower latency (local data)

---

## Next Steps

1. ✅ Get Linear API key
2. ✅ Configure MCP in Cursor
3. ✅ Test connection
4. Start using `/create-issue` in your workflow!
