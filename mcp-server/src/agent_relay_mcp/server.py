"""MCP server exposing Agent Relay tools for Claude Code, Cursor, and other MCP clients."""

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
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_send(relay_id: str, content: str, agent: str, api_key: str = "") -> dict:
    """Send a message in a relay. Only works when it's the agent's turn.

    Use relay_status to check whose turn it is first.

    Args:
        relay_id: The relay ID to send to.
        content: The message text to send.
        agent: The name of the agent sending the message.
        api_key: Optional API key for authentication.
    """
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
def relay_read(relay_id: str, limit: int = 20) -> dict:
    """Read recent messages from a relay.

    Args:
        relay_id: The relay ID to read from.
        limit: Maximum number of messages to return (default: 20).
    """
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
def relay_status(relay_id: str) -> dict:
    """Get current relay status including whose turn it is, agent names, and message count.

    Args:
        relay_id: The relay ID to check.
    """
    try:
        resp = _client.get(f"/relays/{relay_id}")
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


def main():
    """Entry point for the MCP server."""
    mcp.run()
