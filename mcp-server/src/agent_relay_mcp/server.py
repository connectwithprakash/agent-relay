"""MCP server exposing Agent Relay tools for Claude Code, Cursor, and other MCP clients."""

import json
import os
import tempfile

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

# Session state populated on relay_create/relay_join_code and persisted
# to .agent-relay.json.  On MCP restart, reload from disk so agents
# can resume without re-joining.

def _load_config_file() -> dict:
    """Load session state from .agent-relay.json if it exists."""
    config_path = os.path.join(os.getcwd(), ".agent-relay.json")
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path) as f:
            data = json.load(f)
        default = data.get("relays", {}).get("default", {})
        if default.get("relay_id"):
            return {
                "relay_id": default["relay_id"],
                "token": default.get("token", ""),
                "agent": default.get("my_agent", ""),
            }
    except (json.JSONDecodeError, KeyError, OSError):
        pass
    return {}

_session: dict = _load_config_file()


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

    fd, temporary_path = tempfile.mkstemp(prefix=".agent-relay.", dir=os.path.dirname(config_path) or ".")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, config_path)
        os.chmod(config_path, 0o600)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


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


def _auth_headers(token: str = "") -> dict[str, str]:
    token = token or _session.get("token", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _session_agent_for(relay_id: str, token: str = "") -> str:
    """Return session identity only for the session relay and credential."""
    session_token = _session.get("token", "")
    if relay_id != _session.get("relay_id"):
        return ""
    if token and token != session_token:
        return ""
    return _session.get("agent", "")


def _send_heartbeat(
    relay_id: str = "",
    agent: str = "",
    status: str = "active",
    message: str = "",
    token: str = "",
) -> None:
    """Send a heartbeat to the relay server (best-effort, errors ignored)."""
    rid = relay_id or _session.get("relay_id", "")
    ag = agent or _session_agent_for(rid, token)
    if not rid or not ag:
        return
    try:
        params = {"agent": ag, "status": status}
        if message:
            params["status_message"] = message
        _client.post(
            f"/relays/{rid}/heartbeat",
            params=params,
            headers=_auth_headers(token),
        )
    except Exception:
        pass  # Best-effort, never block the caller


@mcp.tool()
def relay_heartbeat(
    status: str = "active",
    message: str = "",
    relay_id: str = "",
    agent: str = "",
    token: str = "",
) -> dict:
    """Send heartbeat to let others know you're still connected.
    Call this periodically (every 10-15 seconds) during long operations.

    Args:
        status: Your current status - "active", "composing", "idle"
        message: Brief description of what you're doing (e.g. "reviewing architecture.svg", "running tests").
        relay_id: The relay ID (defaults to session relay).
        agent: Your agent name (defaults to session agent).
        token: Participant token for this relay (defaults to session token).
    """
    relay_id = relay_id or _session.get("relay_id", "")
    agent = agent or _session.get("agent", "")

    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}
    if not agent:
        return {"error": "No agent name provided and no active session."}

    try:
        params = {"agent": agent, "status": status}
        if message:
            params["status_message"] = message
        resp = _client.post(
            f"/relays/{relay_id}/heartbeat",
            params=params,
            headers=_auth_headers(token),
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


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
    relay_id: str = "",
    message: str = "",
    agent: str = "",
    token: str = "",
    type: str = "text",
    reply_to: int = 0,
    idempotency_key: str = "",
    expected_version: int = -1,
) -> dict:
    """Send a message in a relay. Only works when it's the agent's turn.

    Use relay_status to check whose turn it is first.
    All arguments default to session values from the last relay_create call.

    Args:
        relay_id: The relay ID to send to (defaults to session relay).
        message: The message text to send.
        agent: The name of the agent sending the message (defaults to session agent, optional with token auth).
        token: Optional token for authentication (defaults to session token).
        type: Message type - text, question, action-item, decision, bug-report, code.
        reply_to: Message ID to reply to (for threading). Use 0 for no reply.
        idempotency_key: Stable key reused for retries of the same logical send.
        expected_version: Relay version observed before sending; -1 disables the check.
    """
    relay_id = relay_id or _session.get("relay_id", "")
    agent = agent or _session.get("agent", "")
    token = token or _session.get("token", "")

    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}
    if not message:
        return {"error": "Message is required. Use the 'message' parameter."}
    # Agent is optional when token auth is available (server resolves identity)
    if not agent and not token:
        return {"error": "Either 'agent' or 'token' is required so the server knows who you are."}

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # If no token, try join code from session as fallback
    join_code = _session.get("join_code", "")
    if not token and join_code:
        headers["X-Join-Code"] = join_code

    # Auto-send heartbeat before sending a message
    _send_heartbeat(relay_id, agent, "active", token=token)

    body: dict = {"content": message, "type": type, "message_type": type}
    if agent:
        body["agent"] = agent
    if reply_to:
        body["reply_to"] = reply_to
    if idempotency_key:
        body["idempotency_key"] = idempotency_key
    if expected_version >= 0:
        body["expected_version"] = expected_version

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
def relay_read(
    relay_id: str = "", limit: int = 20, type: str = "", token: str = ""
) -> dict:
    """Read recent messages from a relay. Optionally filter by message type.

    Args:
        relay_id: The relay ID to read from (defaults to session relay).
        limit: Maximum number of messages to return (default: 20).
        type: Filter by message type (text, question, action-item, decision, bug-report, code). Empty = all.
    """
    relay_id = relay_id or _session.get("relay_id", "")
    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}

    params: dict = {"limit": limit}
    if type:
        params["message_type"] = type

    try:
        resp = _client.get(
            f"/relays/{relay_id}/history",
            params=params,
            headers=_auth_headers(token),
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_status(relay_id: str = "", token: str = "") -> dict:
    """Get current relay status: whose turn, all agents with turn order, presence info, message count, and description.

    Args:
        relay_id: The relay ID to check (defaults to session relay).
    """
    relay_id = relay_id or _session.get("relay_id", "")
    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}

    # Auto-send heartbeat when checking status
    _send_heartbeat(relay_id, token=token)

    try:
        resp = _client.get(f"/relays/{relay_id}", headers=_auth_headers(token))
        resp.raise_for_status()
        result = resp.json()

        # Indicate whether it's the caller's turn
        current = result.get("current_turn")
        my_agent = _session_agent_for(relay_id, token)
        if my_agent and current:
            result["your_turn"] = current == my_agent

        # Add turn order info with presence status for clarity
        agents = result.get("agent_names", [])
        presence_list = result.get("agents_presence", [])
        presence_map = {p["agent"]: p for p in presence_list} if presence_list else {}

        if agents and current:
            turn_order = []
            for i, a in enumerate(agents):
                marker = " <- current turn" if a == current else ""
                you = " (you)" if a == my_agent else ""
                p = presence_map.get(a)
                if p:
                    status_msg = f" - {p['status_message']}" if p.get('status_message') else ""
                    presence_info = f" [{p['status']}, {p['last_seen']}{status_msg}]"
                else:
                    presence_info = " [unknown]"
                turn_order.append(f"  {i+1}. {a}{you}{marker}{presence_info}")
            result["turn_order"] = "\n".join(turn_order)

        return result
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_info(relay_id: str = "", token: str = "") -> dict:
    """Get relay details: description, instructions, agents, and turn order.
    Call this after joining to understand the relay's purpose and your role.

    Args:
        relay_id: The relay ID to inspect (defaults to session relay).
    """
    relay_id = relay_id or _session.get("relay_id", "")
    agent_name = _session_agent_for(relay_id, token)
    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}

    result: dict = {}
    try:
        resp = _client.get(f"/relays/{relay_id}", headers=_auth_headers(token))
        resp.raise_for_status()
        status = resp.json()
        result["relay_id"] = relay_id
        result["description"] = status.get("description")
        result["agent_names"] = status.get("agent_names", [])
        result["current_turn"] = status.get("current_turn")
        result["message_count"] = status.get("message_count")

        if agent_name:
            result["your_turn"] = status.get("current_turn") == agent_name

        # Build turn order display
        agents = status.get("agent_names", [])
        current = status.get("current_turn")
        turn_info = []
        for i, a in enumerate(agents):
            marker = " <- current" if a == current else ""
            you = " (you)" if a == agent_name else ""
            turn_info.append(f"{i+1}. {a}{you}{marker}")
        result["turn_order"] = turn_info
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)

    # Fetch instructions if agent identity is known
    if agent_name:
        try:
            instr_resp = _client.get(
                f"/relays/{relay_id}/instructions",
                params={"agent": agent_name},
                headers=_auth_headers(token),
            )
            if instr_resp.status_code == 200:
                instr = instr_resp.json()
                if instr.get("your_instructions"):
                    result["your_instructions"] = instr["your_instructions"]
        except Exception:
            pass  # Non-critical

    return result


@mcp.tool()
def relay_listen(relay_id: str = "", since_id: int = 0, token: str = "") -> dict:
    """Check for new messages instantly (non-blocking).

    Returns immediately with any new messages since last check.
    Use this between other work to stay updated without blocking.

    Args:
        relay_id: Relay to check (defaults to session relay).
        since_id: Only return messages after this ID. Pass the last_id from previous call.
    """
    relay_id = relay_id or _session.get("relay_id", "")
    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}

    # Use tracked last_id if caller didn't provide since_id
    if since_id == 0:
        since_id = _session.get("last_id", 0)

    agent = _session.get("agent", "")
    params: dict = {"since_id": since_id}
    if agent:
        params["agent"] = agent

    try:
        resp = _client.get(
            f"/relays/{relay_id}/listen",
            params=params,
            headers=_auth_headers(token),
        )
        resp.raise_for_status()
        result = resp.json()

        # Track last_id in session so subsequent calls auto-increment
        if result.get("last_id", 0) > 0:
            _session["last_id"] = result["last_id"]

        return result
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_watch(relay_id: str = "", duration: int = 5, token: str = "") -> dict:
    """Watch a relay for new messages. Returns any messages received within the duration.

    This is a short poll (default 5 seconds). For reading existing history, use relay_read instead.

    Args:
        relay_id: The relay ID to watch (defaults to session relay).
        duration: Seconds to wait for new messages (default 5, max 30).
    """
    import time

    relay_id = relay_id or _session.get("relay_id", "")
    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}

    duration = min(duration, 30)
    messages = []
    try:
        with _client.stream(
            "GET",
            f"/relays/{relay_id}/watch",
            headers=_auth_headers(token),
            timeout=duration + 2,
        ) as response:
            response.raise_for_status()
            deadline = time.monotonic() + duration
            for line in response.iter_lines():
                if time.monotonic() > deadline:
                    break
                if line.startswith("data:") and line.strip() != "data:":
                    messages.append(json.loads(line[5:].strip()))
    except (httpx.HTTPStatusError,) as exc:
        return _handle_http_error(exc)
    except (httpx.ReadTimeout, httpx.ConnectTimeout):
        pass  # Normal - no new messages within duration
    return {"messages": messages, "count": len(messages)}


@mcp.tool()
def relay_create_invitation(
    agent_name: str,
    relay_id: str = "",
    expires_in_seconds: int = 900,
    token: str = "",
) -> dict:
    """Create a one-time, participant-bound invitation as the relay creator."""
    relay_id = relay_id or _session.get("relay_id", "")
    if not relay_id:
        return {"error": "No relay_id provided and no active session."}
    try:
        response = _client.post(
            f"/relays/{relay_id}/invitations",
            params={
                "agent_name": agent_name,
                "expires_in_seconds": expires_in_seconds,
            },
            headers=_auth_headers(token),
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_redeem_invitation(invitation: str) -> dict:
    """Redeem a named one-time invitation and persist the issued credential."""
    try:
        response = _client.post(f"/pairing-invitations/{invitation}/redeem")
        response.raise_for_status()
        result = response.json()
        _session["relay_id"] = result["relay_id"]
        _session["agent"] = result["agent_name"]
        _session["token"] = result["token"]
        _session["last_id"] = 0
        try:
            _save_config_file(
                server=RELAY_URL,
                relay_id=result["relay_id"],
                token=result["token"],
                agent=result["agent_name"],
            )
            result["config_saved"] = True
        except OSError:
            result["config_saved"] = False
        return result
    except httpx.HTTPStatusError as exc:
        return _handle_http_error(exc)


@mcp.tool()
def relay_join_code(join_code: str, agent_name: str) -> dict:
    """Join using legacy relay-wide compatibility pairing material.
    The code is generated when a relay is created.

    Args:
        join_code: The relay-wide compatibility pairing secret.
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

        # Fetch relay status and instructions so the joining agent has full context
        try:
            status_resp = _client.get(f"/relays/{result['relay_id']}", headers=_auth_headers())
            if status_resp.status_code == 200:
                status = status_resp.json()
                result["description"] = status.get("description")
                result["message_count"] = status.get("message_count")
                result["your_turn"] = status.get("current_turn") == agent_name

                # Add turn order
                agents = result.get("agent_names", [])
                turn_info = []
                for i, a in enumerate(agents):
                    marker = " <- current" if a == status.get("current_turn") else ""
                    you = " (you)" if a == agent_name else ""
                    turn_info.append(f"{i+1}. {a}{you}{marker}")
                result["turn_order"] = turn_info
        except Exception:
            pass  # Non-critical; join already succeeded

        # Try to get instructions
        try:
            instr_resp = _client.get(
                f"/relays/{result['relay_id']}/instructions",
                params={"agent": agent_name},
                headers=_auth_headers(),
            )
            if instr_resp.status_code == 200:
                instr = instr_resp.json()
                if instr.get("your_instructions"):
                    result["your_instructions"] = instr["your_instructions"]
        except Exception:
            pass  # Non-critical; join already succeeded

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
def relay_skip_turn(relay_id: str = "", force: bool = False, token: str = "") -> dict:
    """Skip the current agent's turn. Use when an agent appears disconnected or unresponsive.

    Args:
        relay_id: Relay ID (defaults to session relay).
        force: Force skip even without timeout. Use when agent is unresponsive.
        token: Optional auth token (defaults to session token).
    """
    relay_id = relay_id or _session.get("relay_id", "")
    token = token or _session.get("token", "")

    if not relay_id:
        return {"error": "No relay_id provided and no active session. Use relay_create first."}

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = _client.post(
            f"/relays/{relay_id}/skip-turn",
            params={"force": str(force).lower()},
            headers=headers,
        )
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
