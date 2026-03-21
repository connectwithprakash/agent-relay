"""Asynchronous client for Agent Relay API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

import httpx
import websockets
import websockets.exceptions

from .models import MessageHistory, MessageInfo, RelayInfo, RelayState, SendResult
from ._utils import raise_for_status as _raise_for_status

logger = logging.getLogger(__name__)


_DEFAULT_RETRY_AFTER = 5.0


class AsyncAgentRelayClient:
    """Asynchronous Python client for the Agent Relay API.

    Usage::

        async with AsyncAgentRelayClient("http://localhost:8000") as client:
            relay = await client.create_relay(["alice", "bob"])
            result = await client.send_message(relay.relay_id, "hello", "alice")
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
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=self._headers())

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send an async HTTP request with automatic retry on 429 Rate Limit responses."""
        for attempt in range(1, self.max_retries + 1):
            resp = await self._client.request(method, url, **kwargs)
            if resp.status_code != 429 or attempt == self.max_retries:
                return resp
            retry_after = _DEFAULT_RETRY_AFTER
            if "retry-after" in resp.headers:
                try:
                    retry_after = float(resp.headers["retry-after"])
                except (ValueError, TypeError):
                    pass
            await asyncio.sleep(retry_after)
        return resp  # unreachable, but satisfies type checkers

    # -- Relay operations --

    async def create_relay(self, agent_names: list[str], is_public: bool = False) -> RelayInfo:
        """Create a new relay for agent communication."""
        resp = await self._request(
            "POST", "/relays",
            json={"agent_names": agent_names, "is_public": is_public},
        )
        _raise_for_status(resp)
        return RelayInfo(**resp.json())

    async def get_relay(self, relay_id: str) -> RelayState:
        """Get the current state of a relay."""
        resp = await self._request("GET", f"/relays/{relay_id}")
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
        resp = await self._request(
            "POST", f"/relays/{relay_id}/messages",
            json={"content": content, "type": "text", "agent": agent},
            headers=headers,
        )
        _raise_for_status(resp)
        return SendResult(**resp.json())

    async def get_history(
        self, relay_id: str, limit: int = 50, offset: int = 0
    ) -> list[MessageInfo]:
        """Get message history for a relay."""
        resp = await self._request(
            "GET", f"/relays/{relay_id}/history",
            params={"limit": limit, "offset": offset},
        )
        _raise_for_status(resp)
        history = MessageHistory(**resp.json())
        return history.messages

    # -- Polling helpers --

    async def wait_for_turn(
        self,
        relay_id: str,
        agent: str,
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> RelayState:
        """Async wait until it is the specified agent's turn.

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
        loop = asyncio.get_running_loop()
        start = loop.time()
        while loop.time() - start < timeout:
            state = await self.get_relay(relay_id)
            if state.current_turn == agent:
                return state
            await asyncio.sleep(poll_interval)
        raise TimeoutError(f"Timed out waiting for {agent}'s turn after {timeout}s")

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

    async def health(self) -> dict:
        """Check API health."""
        resp = await self._request("GET", "/health")
        _raise_for_status(resp)
        return resp.json()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> AsyncAgentRelayClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
