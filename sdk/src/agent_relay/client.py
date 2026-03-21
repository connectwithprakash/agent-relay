"""Synchronous client for Agent Relay API."""

from __future__ import annotations

import httpx

from .exceptions import (
    AgentRelayError,
    AuthenticationError,
    NotYourTurnError,
    RateLimitError,
    RelayNotFoundError,
)
from .models import MessageHistory, MessageInfo, RelayInfo, RelayState, SendResult


def _raise_for_status(response: httpx.Response) -> None:
    """Convert HTTP error responses into typed SDK exceptions."""
    if response.is_success:
        return

    detail = ""
    try:
        body = response.json()
        detail = body.get("detail", "")
    except Exception:
        detail = response.text

    status = response.status_code
    if status == 400:
        if "turn" in detail.lower():
            raise NotYourTurnError(detail)
        raise AgentRelayError(detail, status_code=status)
    if status == 401 or status == 403:
        raise AuthenticationError(detail)
    if status == 404:
        raise RelayNotFoundError(detail)
    if status == 429:
        raise RateLimitError(detail)
    raise AgentRelayError(detail, status_code=status)


class AgentRelayClient:
    """Synchronous Python client for the Agent Relay API.

    Usage::

        with AgentRelayClient("http://localhost:8000") as client:
            relay = client.create_relay(["alice", "bob"])
            result = client.send_message(relay.relay_id, "hello", "alice")
    """

    def __init__(self, base_url: str = "http://localhost:8000", api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(base_url=self.base_url, headers=self._headers())

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    # -- Relay operations --

    def create_relay(self, agent_names: list[str], is_public: bool = False) -> RelayInfo:
        """Create a new relay for agent communication."""
        resp = self._client.post(
            "/relays",
            json={"agent_names": agent_names, "is_public": is_public},
        )
        _raise_for_status(resp)
        return RelayInfo(**resp.json())

    def get_relay(self, relay_id: str) -> RelayState:
        """Get the current state of a relay."""
        resp = self._client.get(f"/relays/{relay_id}")
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
        """Send a message in a relay (only works when it's the agent's turn)."""
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = self._client.post(
            f"/relays/{relay_id}/messages",
            json={"content": content, "type": "text", "agent": agent},
            headers=headers,
        )
        _raise_for_status(resp)
        return SendResult(**resp.json())

    def get_history(
        self, relay_id: str, limit: int = 50, offset: int = 0
    ) -> list[MessageInfo]:
        """Get message history for a relay."""
        resp = self._client.get(
            f"/relays/{relay_id}/history",
            params={"limit": limit, "offset": offset},
        )
        _raise_for_status(resp)
        history = MessageHistory(**resp.json())
        return history.messages

    # -- Utility --

    def health(self) -> dict:
        """Check API health."""
        resp = self._client.get("/health")
        _raise_for_status(resp)
        return resp.json()

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> AgentRelayClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
