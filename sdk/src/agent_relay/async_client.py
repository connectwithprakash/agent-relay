"""Asynchronous client for Agent Relay API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

import httpx
import websockets
import websockets.exceptions

from .exceptions import (
    AgentRelayError,
    AuthenticationError,
    NotYourTurnError,
    RateLimitError,
    RelayNotFoundError,
)
from .models import MessageHistory, MessageInfo, RelayInfo, RelayState, SendResult

logger = logging.getLogger(__name__)


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


class AsyncAgentRelayClient:
    """Asynchronous Python client for the Agent Relay API.

    Usage::

        async with AsyncAgentRelayClient("http://localhost:8000") as client:
            relay = await client.create_relay(["alice", "bob"])
            result = await client.send_message(relay.relay_id, "hello", "alice")
    """

    def __init__(self, base_url: str = "http://localhost:8000", api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=self._headers())

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    # -- Relay operations --

    async def create_relay(self, agent_names: list[str], is_public: bool = False) -> RelayInfo:
        """Create a new relay for agent communication."""
        resp = await self._client.post(
            "/relays",
            json={"agent_names": agent_names, "is_public": is_public},
        )
        _raise_for_status(resp)
        return RelayInfo(**resp.json())

    async def get_relay(self, relay_id: str) -> RelayState:
        """Get the current state of a relay."""
        resp = await self._client.get(f"/relays/{relay_id}")
        _raise_for_status(resp)
        return RelayState(**resp.json())

    # -- Message operations --

    async def send_message(
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
        resp = await self._client.post(
            f"/relays/{relay_id}/messages",
            json={"content": content, "type": "text", "agent": agent},
            headers=headers,
        )
        _raise_for_status(resp)
        return SendResult(**resp.json())

    async def get_history(
        self, relay_id: str, limit: int = 50, offset: int = 0
    ) -> list[MessageInfo]:
        """Get message history for a relay."""
        resp = await self._client.get(
            f"/relays/{relay_id}/history",
            params={"limit": limit, "offset": offset},
        )
        _raise_for_status(resp)
        history = MessageHistory(**resp.json())
        return history.messages

    # -- WebSocket listener --

    async def listen(
        self,
        relay_id: str,
        agent: str,
        on_message: Callable[[dict], Awaitable[None]],
        on_connect: Callable[[], Awaitable[None]] | None = None,
        on_disconnect: Callable[[], Awaitable[None]] | None = None,
        reconnect: bool = True,
        max_retries: int = 5,
    ) -> None:
        """Listen for messages via WebSocket with optional auto-reconnect.

        Args:
            relay_id: The relay to listen on.
            agent: The agent name to connect as.
            on_message: Async callback invoked with each incoming message dict.
            on_connect: Optional async callback invoked on successful connection.
            on_disconnect: Optional async callback invoked on disconnection.
            reconnect: Whether to automatically reconnect on failure.
            max_retries: Maximum consecutive reconnect attempts before giving up.
        """
        ws_scheme = "wss" if self.base_url.startswith("https") else "ws"
        host = self.base_url.replace("https://", "").replace("http://", "")
        ws_url = f"{ws_scheme}://{host}/relays/{relay_id}/ws?agent={agent}"

        retries = 0
        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    retries = 0
                    if on_connect:
                        await on_connect()
                    async for raw in ws:
                        import json

                        msg = json.loads(raw)
                        await on_message(msg)
            except (
                websockets.exceptions.ConnectionClosed,
                ConnectionError,
                OSError,
            ):
                if on_disconnect:
                    await on_disconnect()
                if not reconnect:
                    break
                retries += 1
                if retries > max_retries:
                    logger.error("Max reconnect retries (%d) exceeded", max_retries)
                    break
                wait = min(2**retries, 30)
                logger.info("Reconnecting in %ds (attempt %d/%d)", wait, retries, max_retries)
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                break

    # -- Utility --

    async def health(self) -> dict:
        """Check API health."""
        resp = await self._client.get("/health")
        _raise_for_status(resp)
        return resp.json()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> AsyncAgentRelayClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
