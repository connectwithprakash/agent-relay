# Agent Relay MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that exposes Agent Relay tools to AI assistants like Claude Code, Cursor, and other MCP-compatible clients.

## Installation

```bash
cd mcp-server
pip install -e .
```

## Available Tools

| Tool | Description |
|------|-------------|
| `relay_create` | Create a new relay with specified agent names |
| `relay_send` | Send a message (only works on your turn) |
| `relay_read` | Read recent messages from a relay |
| `relay_status` | Check relay status and whose turn it is |

## Configuration

### Claude Code

Add to your `.claude/settings.json`:

```json
{
  "mcpServers": {
    "agent-relay": {
      "command": "agent-relay-mcp",
      "env": {
        "RELAY_URL": "http://localhost:8000"
      }
    }
  }
}
```

### Cursor

Add to your MCP settings:

```json
{
  "mcpServers": {
    "agent-relay": {
      "command": "agent-relay-mcp",
      "env": {
        "RELAY_URL": "http://localhost:8000"
      }
    }
  }
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RELAY_URL` | `http://localhost:8000` | Base URL for the Agent Relay API |

## Usage Example

Once configured, you can use the tools from your AI assistant:

1. **Create a relay**: "Create a relay with agents alice and bob"
2. **Check status**: "What's the status of relay abc-123?"
3. **Send a message**: "Send 'hello' as alice in relay abc-123"
4. **Read history**: "Show me the last 10 messages in relay abc-123"

## Running Standalone

```bash
# Set the relay URL (optional, defaults to localhost:8000)
export RELAY_URL="http://localhost:8000"

# Run the MCP server
agent-relay-mcp
```
