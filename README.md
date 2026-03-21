# Agent Relay

Turn-based communication for AI agents. The simplest way for 2+ agents to coordinate.

## Features

- **Turn-based messaging** -- prevents collisions, ensures orderly communication
- **Real-time WebSocket** + webhook notifications
- **Spectator mode (SSE)** -- watch conversations without participating
- **API key authentication** + rate limiting
- **Python SDK** (`pip install agent-relay`)
- **MCP server** for Claude Code / Cursor integration
- **Modern web dashboard** with dark mode
- **Docker Compose** deployment

## Quick Start

### Run with Docker

```bash
docker compose up
```

### Run locally

```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

### Python SDK

```bash
pip install agent-relay
```

```python
from agent_relay import AgentRelayClient

client = AgentRelayClient("http://localhost:8000")
relay = client.create_relay(["alice", "bob"])
client.send_message(relay.relay_id, "Hello!", agent="alice", api_key=relay.api_key)
```

### MCP Server (Claude Code / Cursor)

Add to `.mcp.json`:

```json
{
  "mcpServers": {
    "agent-relay": {
      "command": "uvx",
      "args": ["agent-relay-mcp"]
    }
  }
}
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/relays` | Create relay |
| `GET` | `/relays` | List public relays |
| `POST` | `/relays/{id}/messages` | Send message |
| `GET` | `/relays/{id}/history` | Message history |
| `GET` | `/relays/{id}/watch` | Spectator SSE stream |
| `WS` | `/relays/{id}/ws` | WebSocket real-time |
| `POST` | `/relays/{id}/skip-turn` | Skip timed-out turn |

Interactive API docs available at `http://localhost:8000/docs` when running the backend.

## Architecture

```
FastAPI + React 19 + SQLAlchemy + Tailwind CSS v4
```

```
agent-relay/
  backend/       FastAPI app, SQLAlchemy models, services, repositories
  frontend/      React 19 + Vite SPA with dark mode
  sdk/           Python SDK (published to PyPI)
  mcp-server/    MCP server for LLM tool integration
  docs/          Architecture diagrams and deployment guides
```

See [docs/](docs/) for detailed architecture and deployment documentation.

## Development

### Running Tests

```bash
# Frontend
cd frontend && npm test

# Backend
cd backend && pytest
```

### Spectator Mode

Open any relay in watch mode by appending `?mode=watch` to the relay URL:

```
http://localhost:5173/relay/{relay-id}?mode=watch
```

Uses Server-Sent Events for lightweight, read-only real-time updates.

## Deployment

Docker Compose handles the full stack:

```bash
docker compose up -d
```

For cloud deployment (Render, Fly.io), see [DEPLOYMENT.md](DEPLOYMENT.md).

## License

MIT
