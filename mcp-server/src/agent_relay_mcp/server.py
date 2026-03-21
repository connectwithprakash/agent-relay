"""MCP server exposing Agent Relay tools for Claude Code, Cursor, and other MCP clients."""

import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

RELAY_URL = os.environ.get("RELAY_URL", "http://localhost:8000")

mcp = FastMCP(
    "Agent Relay",
    instructions="Turn-based agent-to-agent communication. "
    "Create relays, send messages, read history, and check relay status.",
)

# Persistent HTTP client reused across all tool calls to avoid
# creating and tearing down TCP connections on every request.
_client = httpx.Client(base_url=RELAY_URL, timeout=10.0)

# Ephemeral session state populated on relay_create.
# Allows subsequent tool calls to omit relay_id, api_key, and agent.
_session: dict = {}


def _save_config_file(server: str, relay_id: str, api_key: str, agent: str) -> None:
    """Write .agent-relay.json to the current working directory."""
    config_path = os.path.join(os.getcwd(), ".agent-relay.json")

    if os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
    else:
        data = {"version": 1, "server": server, "relays": {}}

    data["server"] = server
    data["relays"]["default"] = {
        "relay_id": relay_id,
        "api_key": api_key,
        "my_agent": agent,
    }

    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)


def _handle_http_error(exc: httpx.HTTPStatusError) -> dict:
    """Convert an HTTP error into a user-friendly error dict."""
    status = exc.response.status_code
    detail = ""
    try:
        detail = exc.response.json().get("detail", "")
    except Exception:
        detail = exc.response.text

    if status == 400 and "turn" in detail.lower():
        return {"error": "Not your turn. Use relay_status to check whose turn it is."}
    if status == 400:
        return {"error": f"Bad request: {detail}"}
    if status == 401 or status == 403:
        return {"error": "Authentication failed. Provide a valid api_key."}
    if status == 404:
        return {"error": "Relay not found. Check the relay_id."}
    if status == 429:
        return {"error": "Rate limit exceeded. Wait before retrying."}
    return {"error": f"Request failed ({status}): {detail}"}


@mcp.tool()
def relay_create(agent_names: list[str], is_public: bool = False) -> dict:
    """Create a new relay for turn-based agent communication.

    Returns relay_id and agent_names. Share the relay_id with other agents to join.

    Args:
        agent_names: List of agent names (2-10 agents). Turn order follows list order.
        is_public: If True, the relay appears in public listings and anyone with the
            relay_id can read messages. If False, only the creator can access it.
    """
    try:
        resp = _client.post(
            "/relays",
            json={"agent_names": agent_names, "is_public": is_public},
        )
        resp.raise_for_status()
        result = resp.json()

        # Auto-populate session state so subsequent calls can omit args.
        _session["relay_id"] = result.get("relay_id")
        _session["api_key"] = result.get("api_key")
        _session["agent"] = agent_names[0] if agent_names else None

        # Persist to .agent-relay.json for cross-session discovery.
        try:
            _save_config_file(
                server=RELAY_URL,
                relay_id=_session["relay_id"],
                api_key=_session.get("api_key", ""),
                agent=_session.get("agent", ""),
            )
            result["config_saved"] = True
        except OSError:
            result["config_saved"] = False

        return result
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_send(
    relay_id: str = "", content: str = "", agent: str = "", api_key: str = ""
) -> dict:
    """Send a message in a relay. Only works when it's the agent's turn.

    Use relay_status to check whose turn it is first.
    All arguments default to session values from the last relay_create call.

    Args:
        relay_id: The relay ID to send to (defaults to session relay).
        content: The message text to send.
        agent: The name of the agent sending the message (defaults to session agent).
        api_key: Optional API key for authentication (defaults to session key).
    """
    relay_id = relay_id or _session.get("relay_id", "")
    agent = agent or _session.get("agent", "")
    api_key = api_key or _session.get("api_key", "")

    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}
    if not content:
        return {"error": "Message content is required."}
    if not agent:
        return {"error": "No agent name provided and no active session."}

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = _client.post(
            f"/relays/{relay_id}/messages",
            json={"content": content, "type": "text", "agent": agent},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_read(relay_id: str = "", limit: int = 20) -> dict:
    """Read recent messages from a relay.

    Args:
        relay_id: The relay ID to read from (defaults to session relay).
        limit: Maximum number of messages to return (default: 20).
    """
    relay_id = relay_id or _session.get("relay_id", "")
    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}

    try:
        resp = _client.get(
            f"/relays/{relay_id}/history",
            params={"limit": limit},
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_status(relay_id: str = "") -> dict:
    """Get current relay status including whose turn it is, agent names, and message count.

    Args:
        relay_id: The relay ID to check (defaults to session relay).
    """
    relay_id = relay_id or _session.get("relay_id", "")
    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}

    try:
        resp = _client.get(f"/relays/{relay_id}")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_watch(relay_id: str = "", duration: int = 30) -> dict:
    """Watch a relay for new messages using Server-Sent Events.
    Returns messages received during the watch period.

    Args:
        relay_id: The relay ID to watch (defaults to session relay).
        duration: How many seconds to watch (default 30, max 120).
    """
    import time

    relay_id = relay_id or _session.get("relay_id", "")
    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}

    duration = min(duration, 120)
    messages = []
    try:
        with _client.stream("GET", f"/relays/{relay_id}/watch") as response:
            response.raise_for_status()
            deadline = time.monotonic() + duration
            for line in response.iter_lines():
                if time.monotonic() > deadline:
                    break
                if line.startswith("data:") and line.strip() != "data:":
                    messages.append(json.loads(line[5:].strip()))
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)
    return {"messages": messages, "count": len(messages)}


@mcp.tool()
def relay_register(namespace: str, agent_name: str) -> dict:
    """Register this agent for cross-device discovery.

    All agents using the same namespace will auto-discover each other.
    When 2+ agents register, a relay is automatically created.

    Args:
        namespace: Shared name (e.g. project name, team name).
            All agents with same namespace find each other.
        agent_name: Your agent's name.
    """
    try:
        resp = _client.post(
            "/agents/register",
            params={"namespace": namespace, "agent_name": agent_name},
        )
        resp.raise_for_status()
        result = resp.json()

        if result["status"] in ("joined", "created"):
            _session["relay_id"] = result["relay_id"]
            _session["agent"] = agent_name
            if result.get("api_key"):
                _session["api_key"] = result["api_key"]

            # Persist config for cross-session use
            try:
                _save_config_file(
                    server=RELAY_URL,
                    relay_id=result["relay_id"],
                    api_key=result.get("api_key", ""),
                    agent=agent_name,
                )
                result["config_saved"] = True
            except OSError:
                result["config_saved"] = False

        return result
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_discover(namespace: str) -> dict:
    """Discover all agents in a namespace. Shows who's online and if a relay exists.

    Args:
        namespace: The namespace to search for agents in.
    """
    try:
        resp = _client.get(f"/agents/discover/{namespace}")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


def main():
    """Entry point for the MCP server."""
    mcp.run()
