"""Synchronous client for Agent Relay API."""

from __future__ import annotations

import time

import httpx

from .models import MessageHistory, MessageInfo, RelayInfo, RelayState, SendResult
from ._utils import raise_for_status as _raise_for_status


_DEFAULT_RETRY_AFTER = 5.0


class AgentRelayClient:
    """Synchronous Python client for the Agent Relay API.

    Usage::

        with AgentRelayClient("http://localhost:8000") as client:
            relay = client.create_relay(["alice", "bob"])
            # token is auto-stored from create
            result = client.send_message(relay.relay_id, "hello")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        token: str | None = None,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.max_retries = max_retries
        self._client = httpx.Client(base_url=self.base_url, headers=self._headers())

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _update_auth_header(self) -> None:
        """Update the client's default auth header after token changes."""
        if self._token:
            self._client.headers["Authorization"] = f"Bearer {self._token}"
        elif "Authorization" in self._client.headers:
            del self._client.headers["Authorization"]

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send an HTTP request with automatic retry on 429 Rate Limit responses."""
        for attempt in range(1, self.max_retries + 1):
            resp = self._client.request(method, url, **kwargs)
            if resp.status_code != 429 or attempt == self.max_retries:
                return resp
            retry_after = _DEFAULT_RETRY_AFTER
            if "retry-after" in resp.headers:
                try:
                    retry_after = float(resp.headers["retry-after"])
                except (ValueError, TypeError):
                    pass
            time.sleep(retry_after)
        return resp  # unreachable, but satisfies type checkers

    # -- Relay operations --

    def create_relay(self, agent_names: list[str], is_public: bool = False) -> RelayInfo:
        """Create a new relay for agent communication."""
        resp = self._request(
            "POST", "/relays",
            json={"agent_names": agent_names, "is_public": is_public},
        )
        _raise_for_status(resp)
        result = resp.json()
        # Auto-store the creator token
        if result.get("token"):
            self._token = result["token"]
            self._update_auth_header()
        return RelayInfo(**result)

    def get_relay(self, relay_id: str) -> RelayState:
        """Get the current state of a relay."""
        resp = self._request("GET", f"/relays/{relay_id}")
        _raise_for_status(resp)
        return RelayState(**resp.json())

    # -- Message operations --

    def send_message(
        self,
        relay_id: str,
        content: str,
        agent: str | None = None,
        token: str | None = None,
    ) -> SendResult:
        """Send a message in a relay (only works when it's the agent's turn).

        Args:
            relay_id: The relay ID to send to.
            content: The message text to send.
            agent: Optional agent name. Server derives it from token if omitted.
            token: Per-call token override. If provided, this is used instead
                of the client-level token for this request only.
        """
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = {"content": content, "type": "text"}
        if agent:
            body["agent"] = agent
        resp = self._request(
            "POST", f"/relays/{relay_id}/messages",
            json=body,
            headers=headers,
        )
        _raise_for_status(resp)
        return SendResult(**resp.json())

    def get_history(
        self, relay_id: str, limit: int = 50, offset: int = 0
    ) -> list[MessageInfo]:
        """Get message history for a relay."""
        resp = self._request(
            "GET", f"/relays/{relay_id}/history",
            params={"limit": limit, "offset": offset},
        )
        _raise_for_status(resp)
        history = MessageHistory(**resp.json())
        return history.messages

    # -- Polling helpers --

    def wait_for_turn(
        self,
        relay_id: str,
        agent: str,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> RelayState:
        """Block until it is the specified agent's turn.

        Polls ``get_relay`` at the given interval and returns the relay state
        once ``current_turn`` matches *agent*.

        Args:
            relay_id: The relay to watch.
            agent: The agent name to wait for.
            poll_interval: Seconds between status checks (default 2).
            timeout: Maximum seconds to wait before raising ``TimeoutError`` (default 300).

        Returns:
            The :class:`RelayState` when it becomes the agent's turn.

        Raises:
            TimeoutError: If the agent's turn does not arrive within *timeout* seconds.
        """
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            state = self.get_relay(relay_id)
            if state.current_turn == agent:
                return state
            time.sleep(poll_interval)
        raise TimeoutError(f"Timed out waiting for {agent}'s turn after {timeout}s")

    # -- Join code operations --

    def join_by_code(self, join_code: str, agent_name: str) -> dict:
        """Join a relay using a short join code.

        Args:
            join_code: The 6-character code (e.g. 'ABC123').
            agent_name: Name of the agent joining.

        Returns:
            Dict with relay_id, join_code, agent_names, current_turn, and token.
        """
        resp = self._request(
            "POST",
            f"/relays/join/{join_code}",
            params={"agent_name": agent_name},
        )
        _raise_for_status(resp)
        result = resp.json()
        # Auto-store the token
        if result.get("token"):
            self._token = result["token"]
            self._update_auth_header()
        return result

    def get_relay_by_code(self, join_code: str) -> dict:
        """Look up a relay by its short join code.

        Args:
            join_code: The 6-character code.

        Returns:
            Dict with relay_id, agent_names, current_turn, and join_code.
        """
        resp = self._request("GET", f"/relays/code/{join_code}")
        _raise_for_status(resp)
        return resp.json()

    # -- Discovery operations --

    def register(
        self,
        namespace: str,
        agent_name: str,
        device_id: str | None = None,
        description: str | None = None,
        capabilities: list[str] | str | None = None,
    ) -> dict:
        """Register this agent in a namespace for cross-device discovery.

        Args:
            namespace: The shared namespace to join.
            agent_name: This agent's name.
            device_id: Optional device identifier.
            description: What this agent does (e.g. "Reviews Python code for bugs").
            capabilities: Skills as a list or comma-separated string
                (e.g. ["code_review", "python"] or "code_review,python").

        Returns:
            Relay info if a relay exists or is created, or a 'waiting' status
            if not enough agents have joined yet.
        """
        params: dict[str, str] = {"namespace": namespace, "agent_name": agent_name}
        if device_id:
            params["device_id"] = device_id
        if description:
            params["description"] = description
        if capabilities:
            if isinstance(capabilities, list):
                params["capabilities"] = ",".join(capabilities)
            else:
                params["capabilities"] = capabilities
        resp = self._request("POST", "/agents/register", params=params)
        _raise_for_status(resp)
        result = resp.json()
        # Auto-store the token if relay was created/joined
        if result.get("token"):
            self._token = result["token"]
            self._update_auth_header()
        return result

    def discover(self, namespace: str) -> dict:
        """Discover all agents and relays in a namespace."""
        resp = self._request("GET", f"/agents/discover/{namespace}")
        _raise_for_status(resp)
        return resp.json()

    def search_agents(
        self,
        capability: str | None = None,
        namespace: str | None = None,
        status: str | None = None,
    ) -> dict:
        """Search for agents by capability across all namespaces.

        Args:
            capability: Skill to search for (e.g. "code_review").
            namespace: Optional namespace to limit the search.
            status: Filter by status (default server-side is "ready").

        Returns:
            Dict with an "agents" list of matching agent profiles.
        """
        params: dict[str, str] = {}
        if capability:
            params["capability"] = capability
        if namespace:
            params["namespace"] = namespace
        if status:
            params["status"] = status
        resp = self._request("GET", "/agents/search", params=params)
        _raise_for_status(resp)
        return resp.json()

    def get_agent_profile(self, namespace: str, agent_name: str) -> dict:
        """Get a specific agent's profile and capabilities.

        Args:
            namespace: The agent's namespace.
            agent_name: The agent's name.

        Returns:
            Dict with agent profile including description, capabilities, and status.
        """
        resp = self._request("GET", f"/agents/{namespace}/{agent_name}")
        _raise_for_status(resp)
        return resp.json()

    def wait_for_relay(
        self,
        namespace: str,
        agent_name: str,
        poll_interval: float = 3.0,
        timeout: float = 300.0,
    ) -> dict:
        """Register and poll until a relay is created in this namespace.

        Args:
            namespace: The shared namespace to join.
            agent_name: This agent's name.
            poll_interval: Seconds between discovery checks (default 3).
            timeout: Maximum seconds to wait (default 300).

        Returns:
            Registration result dict with relay info once a relay is ready.

        Raises:
            TimeoutError: If no relay is created within *timeout* seconds.
        """
        result = self.register(namespace, agent_name)
        if result["status"] in ("joined", "created"):
            return result

        device_id = result["device_id"]
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            time.sleep(poll_interval)
            disc = self.discover(namespace)
            if disc.get("relay_id"):
                result = self.register(namespace, agent_name, device_id)
                if result["status"] in ("joined", "created"):
                    return result
        raise TimeoutError(
            f"No relay created in namespace '{namespace}' after {timeout}s"
        )

    # -- Factory methods --

    @classmethod
    def from_config(cls, path=None, relay_name="default"):
        """Create client from .agent-relay.json config file."""
        from .config import load_config
        config = load_config(path, relay_name)
        return cls(base_url=config["server"], token=config.get("token"))

    @classmethod
    def from_env(cls):
        """Create client from AGENT_RELAY_* environment variables."""
        from .config import load_from_env
        config = load_from_env()
        return cls(base_url=config["server"], token=config.get("token"))

    # -- Utility --

    def health(self) -> dict:
        """Check API health."""
        resp = self._request("GET", "/health")
        _raise_for_status(resp)
        return resp.json()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> AgentRelayClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
