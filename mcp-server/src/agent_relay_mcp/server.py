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
# Allows subsequent tool calls to omit relay_id, token, and agent.
_session: dict = {}


def _save_config_file(server: str, relay_id: str, token: str, agent: str) -> None:
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
        "token": token,
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
        return {"error": "Authentication failed. Provide a valid token or join the relay first."}
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
        _session["token"] = result.get("token")
        _session["agent"] = agent_names[0] if agent_names else None

        # Persist to .agent-relay.json for cross-session discovery.
        try:
            _save_config_file(
                server=RELAY_URL,
                relay_id=_session["relay_id"],
                token=_session.get("token", ""),
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
    relay_id: str = "", content: str = "", agent: str = "", token: str = ""
) -> dict:
    """Send a message in a relay. Only works when it's the agent's turn.

    Use relay_status to check whose turn it is first.
    All arguments default to session values from the last relay_create call.

    Args:
        relay_id: The relay ID to send to (defaults to session relay).
        content: The message text to send.
        agent: The name of the agent sending the message (defaults to session agent, optional with token auth).
        token: Optional token for authentication (defaults to session token).
    """
    relay_id = relay_id or _session.get("relay_id", "")
    agent = agent or _session.get("agent", "")
    token = token or _session.get("token", "")

    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}
    if not content:
        return {"error": "Message content is required."}

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # If no token, try join code from session as fallback
    join_code = _session.get("join_code", "")
    if not token and join_code:
        headers["X-Join-Code"] = join_code

    body = {"content": content, "type": "text"}
    if agent:
        body["agent"] = agent

    try:
        resp = _client.post(
            f"/relays/{relay_id}/messages",
            json=body,
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
def relay_join_code(join_code: str, agent_name: str) -> dict:
    """Join a relay using a short join code from another device.

    Share a 6-character code (e.g. ABC123) instead of a full relay ID.
    The code is generated when a relay is created.

    Args:
        join_code: The 6-character join code.
        agent_name: Your agent's name.
    """
    try:
        resp = _client.post(
            f"/relays/join/{join_code}",
            params={"agent_name": agent_name},
        )
        resp.raise_for_status()
        result = resp.json()

        _session["relay_id"] = result["relay_id"]
        _session["agent"] = agent_name
        _session["join_code"] = join_code.upper()
        if result.get("token"):
            _session["token"] = result["token"]

        # Persist config for cross-session use
        try:
            _save_config_file(
                server=RELAY_URL,
                relay_id=result["relay_id"],
                token=result.get("token", ""),
                agent=agent_name,
            )
            result["config_saved"] = True
        except OSError:
            result["config_saved"] = False

        return result
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_register(
    namespace: str, agent_name: str, description: str = "", capabilities: str = ""
) -> dict:
    """Register this agent for cross-device discovery with a description and capabilities.

    All agents using the same namespace will auto-discover each other.
    When 2+ agents register, a relay is automatically created.

    Args:
        namespace: Shared name (e.g. project name, team name).
            All agents with same namespace find each other.
        agent_name: Your agent's name.
        description: What this agent does (e.g. "Reviews Python code for bugs").
        capabilities: Comma-separated skills (e.g. "code_review,python,security").
    """
    try:
        params = {"namespace": namespace, "agent_name": agent_name}
        if description:
            params["description"] = description
        if capabilities:
            params["capabilities"] = capabilities
        resp = _client.post(
            "/agents/register",
            params=params,
        )
        resp.raise_for_status()
        result = resp.json()

        if result["status"] in ("joined", "created"):
            _session["relay_id"] = result["relay_id"]
            _session["agent"] = agent_name
            if result.get("token"):
                _session["token"] = result["token"]

            # Persist config for cross-session use
            try:
                _save_config_file(
                    server=RELAY_URL,
                    relay_id=result["relay_id"],
                    token=result.get("token", ""),
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
    """Discover all agents in a namespace. Shows who's online, their capabilities, and if a relay exists.

    Args:
        namespace: The namespace to search for agents in.
    """
    try:
        resp = _client.get(f"/agents/discover/{namespace}")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_search_agents(capability: str = "", namespace: str = "") -> dict:
    """Search for agents by capability. Find agents that can do what you need.

    Args:
        capability: Skill to search for (e.g. "code_review", "testing", "deployment").
        namespace: Optional namespace to limit search.
    """
    try:
        params = {}
        if capability:
            params["capability"] = capability
        if namespace:
            params["namespace"] = namespace
        resp = _client.get("/agents/search", params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


def main():
    """Entry point for the MCP server."""
    mcp.run()
