# Agent Relay Discovery Specification

## 1. Config File: `.agent-relay.json`

Lives in project root (should be gitignored). Created automatically by `agent-relay create` or `relay_create` MCP tool.

```json
{
  "version": 1,
  "server": "http://localhost:8000",
  "relays": {
    "default": {
      "relay_id": "relay-abc",
      "api_key": "key-xyz",
      "my_agent": "alice"
    }
  }
}
```

Multiple named relays supported. `default` is used when no relay name is specified.

## 2. MCP Server Behavior

- Add module-level `_session: dict` to `mcp-server/src/agent_relay_mcp/server.py`.
- On `relay_create`: auto-populate `_session` with relay_id, api_key, agent name AND write `.agent-relay.json` to cwd.
- All tools (`relay_send`, `relay_read`, `relay_status`) default to `_session` values when args are omitted.
- Session is ephemeral (per MCP process); config file provides persistence across sessions.

## 3. SDK Auto-Config

Add `sdk/src/agent_relay/config.py` with:

- `AgentRelayClient.from_config(path=None)` -- walks cwd upward to find `.agent-relay.json`, parses it, returns configured client.
- `AgentRelayClient.from_env()` -- reads environment variables (see section 5), returns configured client.
- Existing explicit constructor remains unchanged for programmatic use.

## 4. CLI Commands

Entry point: `agent-relay` (Click-based, in `sdk/src/agent_relay/cli.py`). Register in `sdk/pyproject.toml` as `[project.scripts] agent-relay = "agent_relay.cli:main"`.

| Command | Description |
|---|---|
| `agent-relay create <agent1> <agent2> ...` | Creates relay with given agents, writes `.agent-relay.json` for first agent, prints join commands for remaining agents |
| `agent-relay join <relay_id> --agent <name> --key <key> [--server URL]` | Writes `.agent-relay.json` locally for the joining agent |
| `agent-relay status [--name <relay-name>]` | Reads config, displays current turn, message count, and agent list |
| `agent-relay send "<message>" [--name <relay-name>]` | Sends message from the configured agent |

## 5. Environment Variables

| Variable | Purpose | Example |
|---|---|---|
| `AGENT_RELAY_SERVER` | Base URL of relay server | `http://localhost:8000` |
| `AGENT_RELAY_ID` | Relay identifier | `relay-NdJhe1gA-M8` |
| `AGENT_RELAY_KEY` | API key for authentication | `stmH3DQYD3pyBywkYnPcFm1fCYoa3FwO1yP1hdFwW0s` |
| `AGENT_RELAY_AGENT` | Agent name for this session | `synthesizer` |

## 6. Multi-Device Sharing

- `agent-relay create` outputs a copy-pasteable join command for each non-local agent, containing relay_id, key, and server URL.
- Each agent receives its own API key, so sharing a join command is safe and scoped.
- No central registry required. The join command IS the sharing mechanism (copy-paste via terminal, chat, etc.).
- For remote servers, replace `localhost` with the host's public address or tunnel URL.

## 7. Priority Order

```
explicit constructor args  >  environment variables  >  .agent-relay.json config  >  built-in defaults
```

Built-in defaults: `server = http://localhost:8000`. All other fields have no defaults and must be provided by at least one layer.

## Files to Create or Modify

| File | Change |
|---|---|
| `sdk/src/agent_relay/config.py` | New: config discovery, parsing, persistence, `from_config()` and `from_env()` |
| `sdk/src/agent_relay/cli.py` | New: Click-based CLI with create, join, status, send commands |
| `mcp-server/src/agent_relay_mcp/server.py` | Modify: add `_session` dict, auto-save `.agent-relay.json` on relay_create |
| `sdk/pyproject.toml` | Modify: add `[project.scripts] agent-relay = "agent_relay.cli:main"` |
