# Agent Relay

Turn-based communication for AI agents. Create a relay, connect agents from any device, and let them collaborate with structured turn-taking.

## Why Agent Relay?

When multiple AI agents need to coordinate, messages can collide and context gets lost. Agent Relay solves this with **enforced turn-taking** -- only one agent speaks at a time, preventing conflicts and ensuring orderly dialogue. No other protocol does this.

**Think of it as a walkie-talkie for AI agents.** One speaks, the rest listen, then the next agent takes their turn.

## Quick Start

### 1. Start the server

```bash
# With Docker (recommended)
POSTGRES_PASSWORD='choose-a-strong-local-password' docker compose up --build

# If ports 8000 or 3000 are already in use
POSTGRES_PASSWORD='choose-a-strong-local-password' BACKEND_PORT=18000 FRONTEND_PORT=13000 docker compose up --build

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
# Output: agent-relay join-invitation <one-time-invitation> --server http://localhost:8000

# Join from another device (Device 2) -- paste bob's one-time command
agent-relay join-invitation <one-time-invitation> --server http://localhost:8000

# Send messages
agent-relay send "Hello from alice!"
agent-relay status
```

**Using Python:**

```python
from agent_relay import AgentRelayClient

client = AgentRelayClient("http://localhost:8000")

# Create a relay. The client retains alice's creator token.
relay = client.create_relay(["alice", "bob"])
invitation = client.create_invitation(relay.relay_id, "bob")

# On bob's device, redeem the participant-bound invitation.
bob = AgentRelayClient("http://localhost:8000")
pairing = bob.redeem_invitation(invitation["invitation"])

# Send a message (alice goes first)
client.send_message(
    relay.relay_id,
    "Hello!",
    agent="alice",
    idempotency_key="alice-hello-1",
)

# Read state, then send with optimistic concurrency protection.
state = bob.get_relay(relay.relay_id)
bob.send_message(
    relay.relay_id,
    "Hi back!",
    agent="bob",
    expected_version=state.version,
    idempotency_key="bob-reply-1",
)

# Read history
messages = client.get_history(relay.relay_id)
```

**Using the Web UI:**

With standard Docker Compose, open http://localhost:3000. For the Vite development server or development Compose stack, open http://localhost:5173.

### 3. Secure cross-device pairing

Create the relay on one device and transfer a named, single-use invitation to each participant over an authenticated channel.

```python
from agent_relay import AgentRelayClient

creator = AgentRelayClient("http://your-server:8000")
relay = creator.create_relay(["alice", "bob"])
invitation = creator.create_invitation(relay.relay_id, "bob")

# Device 2: receive only the invitation secret, then redeem it once.
bob = AgentRelayClient("http://your-server:8000")
bob.redeem_invitation(invitation["invitation"])
```

Namespace registration is a legacy unauthenticated discovery mechanism. It remains disabled unless an operator explicitly sets `ALLOW_UNAUTHENTICATED_REGISTRY_ENROLLMENT=true`; it should not be used as an authorization boundary.

## Managed cross-harness control

Agent Relay can also pair a controller with a worker running on another device and expose a fixed, worker-owned harness profile. The worker keeps its credential, executable, and working directory local; a controller can request a session, observe terminal output, and temporarily acquire an exclusive input lease.

### Worker setup

First create a private relay with the controller and worker as named participants. The creator keeps the controller config; send the one-time invitation printed for the worker participant to the worker device over an authenticated channel.

```bash
# Controller device: this writes the controller's .agent-relay.json and prints
# one join-invitation command for the named worker.
agent-relay create controller work-mac --server https://relay.example

# Worker device: redeem the invitation once. This writes that worker's local config.
agent-relay join-invitation ONE_TIME_WORKER_INVITATION --server https://relay.example
```

Then run only an allowlisted local profile. `claude-code` requires an existing absolute working directory and executable path; these values are configured locally and are never accepted from the controller.

```bash
agent-relay worker-run \
  --name "Work Mac Claude service" \
  --profile claude-code \
  --claude-workdir /absolute/path/to/checkout \
  --claude-executable /absolute/path/to/claude
```

The worker writes a mode-`0600` PID file at `~/.agent-relay/worker.pid`, heartbeats the Relay while it is online, and terminates only PTYs it owns when stopped.

The `claude-code-tmux` profile runs Claude Code inside a tmux session so a restarted worker can re-attach to it; it needs `tmux` installed, plus `--claude-workdir` and `--claude-executable` like `claude-code`. On stop, the worker detaches and leaves the tmux session running. Its output capture files hold raw terminal output, which may contain secrets, as plaintext under `~/.agent-relay/worker` (directory mode `0700`, files `0600`, rotated at 8 MB per generation). They are kept after a detach and removed when the session ends. Use `claude-code-tmux` only on machines you trust.

### Controller flow

```bash
# Inspect remembered online workers.
agent-relay worker-list

# Start the fixed profile on a selected worker.
agent-relay session-start WORKER_ID claude-code --idempotency-key work-session-1

# After the worker reports ready, claim a bounded input lease.
agent-relay session-list
agent-relay session-claim SESSION_ID --version VERSION --lease-seconds 60

# Release when finished.
agent-relay session-release SESSION_ID
```

For the browser UI, create a short-lived controller-browser invitation with `agent-relay browser-pairing-invitation`, redeem it once on the home page, then open `/relay/{relay-id}/control`. Select an online worker and open the generated session to reach `/relay/{relay-id}/sessions/{session-id}/live`.

After a browser controller is paired, its Home page exposes **Your workers → Manage workers** and the header exposes **Workers** when one controller relay is saved. The Controller dashboard can create and copy one-time codes for another browser or an unpaired work-computer participant. A work-computer code is redeemed by the installed local Worker app; that native component alone owns the approved local Claude executable and worktree.

### Browser-to-worker sequence

```mermaid
sequenceDiagram
    actor User
    participant B as Browser controller
    participant R as Agent Relay
    participant W as Local Worker app
    participant C as Claude Code PTY

    User->>B: Open Workers and create work-computer code
    B->>R: Create one-time invitation for unpaired participant
    R-->>B: Short-lived code
    User->>W: Approve local setup and redeem code
    W->>R: Redeem code; store local credential
    W->>R: Register worker and send heartbeats
    R-->>B: Worker appears online
    User->>B: Start session and take control
    B->>R: Request session and exclusive lease
    R->>W: Deliver session and input events
    W->>C: Start approved local profile and forward input
    C-->>W: Terminal output
    W->>R: Persist output events
    R-->>B: Replay or stream terminal output
```

### Safety boundaries

- Workers expose only fixed profiles from their local allowlist; controllers cannot supply arbitrary commands, executable paths, or working directories.
- Control input requires an active, exclusive, expiring lease. Every input and output is durably recorded for session replay.
- Workers are marked offline when their heartbeat expires; active leases are released and affected sessions are detached.
- Browser and stream credentials are sent in authenticated headers or WebSocket subprotocols, never in URLs.

## Agent Coordination Skill

Agent Relay ships operational guidance at `skills/agent-relay-coordination/SKILL.md`; the Claude compatibility skill at `.claude/skills/agent-relay/SKILL.md` follows the same authenticated pairing and recovery boundaries.

### Transient read recovery

The Python SDK retries bounded transient transport and gateway failures for read-only `GET` requests, including relay status, history, health, and polling. All `POST` requests are single-attempt for transport and `5xx` failures, including turn-advancing writes; callers should use the message idempotency key when retrying a write intentionally. Existing rate-limit (`429`) retries apply to every request method and honor a numeric `Retry-After` header.

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

Available tools include `relay_create`, `relay_create_invitation`, `relay_redeem_invitation`, `relay_send`, `relay_read`, `relay_status`, `relay_watch`, `relay_register`, and `relay_discover`.

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
| `POST` | `/relays/{id}/invitations` | Create a one-time named participant invitation |
| `POST` | `/pairing-invitations/{secret}/redeem` | Redeem a participant invitation |
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
| `ALLOW_LEGACY_SHARED_PAIRING` | `false` | Enable deprecated relay-wide pairing codes |
| `ALLOW_UNAUTHENTICATED_REGISTRY_ENROLLMENT` | `false` | Enable legacy namespace auto-enrollment |
| `WEBHOOK_MAX_RETRIES` | `3` | Maximum durable delivery attempts before dead-lettering |
| `WEBHOOK_TIMEOUT_SECONDS` | `5.0` | Timeout for each webhook HTTP attempt |
| `WEBHOOK_OUTBOX_POLL_SECONDS` | `0.5` | Idle dispatcher polling interval |
| `WEBHOOK_OUTBOX_BATCH_SIZE` | `20` | Maximum events claimed per dispatcher batch |
| `WEBHOOK_OUTBOX_LEASE_SECONDS` | `30` | Time before an abandoned processing lease can be reclaimed |
| `WEBHOOK_OUTBOX_RETRY_BASE_SECONDS` | `1.0` | Base delay for exponential retry backoff |

### Durable webhook delivery

Message creation, turn advancement, and matching webhook outbox rows commit in one database transaction. The in-process dispatcher leases due rows, revalidates targets against SSRF immediately before connecting, and retries network failures, HTTP 408/429, and 5xx responses. Other 4xx responses are terminal. Exhausted events remain in `webhook_outbox` with `status='dead'` and the last error for operational inspection.

Delivery is **at least once** because a worker can crash after the receiver accepts an event but before the success state commits. Receivers should persist and deduplicate the `X-Agent-Relay-Event-ID` header. `X-Agent-Relay-Attempt` reports the current attempt number.

### Agent Relay Config File

The CLI creates `.agent-relay.json` in your project directory:

```json
{
  "version": 1,
  "server": "http://localhost:8000",
  "relays": {
    "default": {
      "relay_id": "relay-abc",
      "token": "your-participant-token",
      "my_agent": "alice"
    }
  }
}
```

This file is auto-read by the SDK (`AgentRelayClient.from_config()`) and MCP server.

## Upgrading from legacy pairing

This release changes authentication defaults and database constraints. Before upgrading a production installation:

1. Take a database snapshot and audit duplicate participant credentials with `SELECT relay_id, agent_name, COUNT(*) FROM agent_tokens GROUP BY relay_id, agent_name HAVING COUNT(*) > 1`.
2. Upgrade SDK, CLI, MCP, and browser clients so private reads use bearer tokens and new participants redeem named invitations.
3. If a staged transition is required, temporarily set `ALLOW_LEGACY_SHARED_PAIRING=true` and/or `ALLOW_UNAUTHENTICATED_REGISTRY_ENROLLMENT=true`; remove both flags after issuing participant credentials.
4. Run `alembic upgrade head`. This also creates the webhook outbox. Duplicate credential rows removed to enforce one credential per participant are retained, hashed, in `agent_token_dedup_backup` for rollback recovery. Plaintext bearer credentials are never retained.
5. Issue new named invitations for any participant that cannot authenticate, then verify private state, history, SSE, WebSocket, and message sends before completing rollout.

For an application rollback, record `fly releases --app agent-relay-api` before deployment. Restore the pre-upgrade database snapshot, then run `fly releases rollback <release-version> --app agent-relay-api`. To roll back only the outbox release before rolling back the application, first stop message writes and inspect or drain pending rows, then run `fly ssh console --app agent-relay-api -C "alembic downgrade 012"`. Downgrading drops all outbox state, so a database snapshot is required if pending deliveries must be retained.

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

# MCP tests
cd mcp-server && pytest tests/ -v

# Frontend lint and production build
cd frontend && npm run lint && npm run build
```

## License

MIT
