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


@mcp.tool()
def relay_create(agent_names: list[str], is_public: bool = False) -> dict:
    """Create a new relay for turn-based agent communication.

    Returns relay_id and agent_names. Share the relay_id with other agents to join.

    Args:
        agent_names: List of agent names (2-10 agents). Turn order follows list order.
        is_public: If True, anyone can read the relay. If False, only the owner can.
    """
    with httpx.Client() as client:
        resp = client.post(
            f"{RELAY_URL}/relays",
            json={"agent_names": agent_names, "is_public": is_public},
        )
        resp.raise_for_status()
        return resp.json()


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
    with httpx.Client() as client:
        resp = client.post(
            f"{RELAY_URL}/relays/{relay_id}/messages",
            json={"content": content, "type": "text", "agent": agent},
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
def relay_read(relay_id: str, limit: int = 20) -> dict:
    """Read recent messages from a relay.

    Args:
        relay_id: The relay ID to read from.
        limit: Maximum number of messages to return (default: 20).
    """
    with httpx.Client() as client:
        resp = client.get(
            f"{RELAY_URL}/relays/{relay_id}/history",
            params={"limit": limit},
        )
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
def relay_status(relay_id: str) -> dict:
    """Get current relay status including whose turn it is, agent names, and message count.

    Args:
        relay_id: The relay ID to check.
    """
    with httpx.Client() as client:
        resp = client.get(f"{RELAY_URL}/relays/{relay_id}")
        resp.raise_for_status()
        return resp.json()


def main():
    """Entry point for the MCP server."""
    mcp.run()
