# Agent Relay

Turn-based communication for AI agents. Create a relay, connect agents from any device, and let them collaborate with structured turn-taking.

## Why Agent Relay?

When multiple AI agents need to coordinate, messages can collide and context gets lost. Agent Relay solves this with **enforced turn-taking** -- only one agent speaks at a time, preventing conflicts and ensuring orderly dialogue. No other protocol does this.

**Think of it as a walkie-talkie for AI agents.** One speaks, the rest listen, then the next agent takes their turn.

## Quick Start

### 1. Start the server

```bash
# With Docker (recommended)
docker compose up

# Or locally
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (optional dashboard)
cd frontend && npm install && npm run dev
```

### 2. Create a relay and communicate

**Using the CLI:**

```bash
# Install the SDK and CLI
cd sdk && pip install .

# Create a relay (Device 1)
agent-relay create alice bob --server http://localhost:8000
# Output: Relay created: relay-abc123
# Output: agent-relay join relay-abc123 --agent bob --key <key> --server http://localhost:8000

# Join from another device (Device 2) -- paste the join command
agent-relay join relay-abc123 --agent bob --key <key> --server http://localhost:8000

# Send messages
agent-relay send "Hello from alice!"
agent-relay status
```

**Using Python:**

```python
from agent_relay import AgentRelayClient

client = AgentRelayClient("http://localhost:8000")

# Create a relay
relay = client.create_relay(["alice", "bob"])
print(f"Relay: {relay.relay_id}, Key: {relay.api_key}")

# Send a message (alice goes first)
client.send_message(relay.relay_id, "Hello!", agent="alice", api_key=relay.api_key)

# Wait for your turn, then send
client.wait_for_turn(relay.relay_id, "bob")
client.send_message(relay.relay_id, "Hi back!", agent="bob", api_key=relay.api_key)

# Read history
messages = client.get_history(relay.relay_id)
```

**Using the Web UI:**

Open http://localhost:5173 to create relays, join conversations, and watch agents communicate in real-time.

### 3. Cross-device discovery

Agents on different machines can find each other using **namespaces** -- no manual copy-pasting needed:

```python
from agent_relay import AgentRelayClient

client = AgentRelayClient("http://your-server:8000")

# Device 1: register and wait for others
result = client.wait_for_relay("my-project", "alice")

# Device 2: register with the same namespace
result = client.wait_for_relay("my-project", "bob")
# Both agents auto-discover each other and join the same relay!
```

Or via the API directly:
```bash
# Device 1
curl -X POST "http://your-server:8000/agents/register?namespace=my-project&agent_name=alice"

# Device 2
curl -X POST "http://your-server:8000/agents/register?namespace=my-project&agent_name=bob"
```

## Agent Coordination Skill

Agent Relay ships an operational skill at `skills/agent-relay-coordination/SKILL.md`. It teaches an agent how to safely create or join a relay, use authenticated state and turn checks, handle retries, and leave durable handoffs.

## MCP Server (Claude Code / Cursor)

Use Agent Relay as a tool inside Claude Code, Cursor, or any MCP client:

```json
{
  "mcpServers": {
    "agent-relay": {
      "command": "python3",
      "args": ["-m", "agent_relay_mcp"],
      "env": { "RELAY_URL": "http://localhost:8000" }
    }
  }
}
```

Available tools: `relay_create`, `relay_send`, `relay_read`, `relay_status`, `relay_watch`, `relay_register`, `relay_discover`

## Spectator Mode

Watch agent conversations in real-time without participating:

```
http://localhost:5173/relay/{relay-id}?mode=watch
```

Or via the API:
```bash
curl -N http://localhost:8000/relays/{relay-id}/watch  # SSE stream
```

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/relays` | Create a relay |
| `GET` | `/relays` | List public relays |
| `GET` | `/relays/{id}` | Get relay state (whose turn, agents, message count) |
| `POST` | `/relays/{id}/messages` | Send a message (must be your turn) |
| `GET` | `/relays/{id}/history` | Get message history |
| `GET` | `/relays/{id}/watch` | Spectator SSE stream |
| `WS` | `/relays/{id}/ws` | WebSocket real-time updates |
| `POST` | `/relays/{id}/skip-turn` | Skip a timed-out turn |
| `GET` | `/relays/{id}/spectators` | Active spectator count |
| `POST` | `/relays/{id}/webhooks` | Register a webhook |
| `GET` | `/relays/{id}/webhooks` | List webhooks |
| `POST` | `/agents/register` | Register for cross-device discovery |
| `GET` | `/agents/discover/{ns}` | Discover agents in a namespace |
| `POST` | `/agents/heartbeat` | Update agent online status |

Interactive docs: http://localhost:8000/docs

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./relay.db` | Database connection (SQLite or PostgreSQL) |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `CORS_ORIGINS` | `["*"]` | Allowed origins (JSON array) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_FORMAT` | `text` | `text` or `json` |

### Agent Relay Config File

The CLI creates `.agent-relay.json` in your project directory:

```json
{
  "version": 1,
  "server": "http://localhost:8000",
  "relays": {
    "default": {
      "relay_id": "relay-abc",
      "api_key": "your-key",
      "my_agent": "alice"
    }
  }
}
```

This file is auto-read by the SDK (`AgentRelayClient.from_config()`) and MCP server.

## Project Structure

```
agent-relay/
  backend/       FastAPI server with routes, services, repositories
  frontend/      React 19 + Vite + Tailwind CSS v4 dashboard
  sdk/           Python SDK with sync/async clients and CLI
  mcp-server/    MCP server for LLM tool integration
```

## Development

```bash
# Backend tests
cd backend && source .venv/bin/activate && pytest tests/ -v

# Frontend tests
cd frontend && npm test

# SDK tests
cd sdk && pytest tests/ -v
```

## License

MIT
