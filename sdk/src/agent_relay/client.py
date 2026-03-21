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
            result = client.send_message(relay.relay_id, "hello", "alice")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_retries = max_retries
        self._client = httpx.Client(base_url=self.base_url, headers=self._headers())

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

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
        return RelayInfo(**resp.json())

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
        agent: str,
        api_key: str | None = None,
    ) -> SendResult:
        """Send a message in a relay (only works when it's the agent's turn).

        Args:
            relay_id: The relay ID to send to.
            content: The message text to send.
            agent: The name of the agent sending the message.
            api_key: Per-call API key override. If provided, this is used instead
                of the client-level ``api_key`` for this request only.
        """
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = self._request(
            "POST", f"/relays/{relay_id}/messages",
            json={"content": content, "type": "text", "agent": agent},
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

    # -- Factory methods --

    @classmethod
    def from_config(cls, path=None, relay_name="default"):
        """Create client from .agent-relay.json config file."""
        from .config import load_config
        config = load_config(path, relay_name)
        return cls(base_url=config["server"], api_key=config.get("api_key"))

    @classmethod
    def from_env(cls):
        """Create client from AGENT_RELAY_* environment variables."""
        from .config import load_from_env
        config = load_from_env()
        return cls(base_url=config["server"], api_key=config.get("api_key"))

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
