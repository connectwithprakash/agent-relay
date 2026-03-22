"""Unit tests for the async Agent Relay Python SDK client.

All tests use httpx MockTransport so no running server is needed.
"""

import json

import httpx
import pytest
import pytest_asyncio

from agent_relay import (
    AsyncAgentRelayClient,
    AgentRelayError,
    AuthenticationError,
    NotYourTurnError,
    RelayNotFoundError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_transport(handler):
    """Create an httpx.MockTransport from a handler function."""
    return httpx.MockTransport(handler)


def _json_response(data: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=data,
        headers={"Content-Type": "application/json"},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RELAY_CREATE_RESPONSE = {
    "relay_id": "test-relay-123",
    "agent_names": ["alice", "bob"],
    "current_turn": "alice",
}

RELAY_STATE_RESPONSE = {
    "relay_id": "test-relay-123",
    "current_turn": "alice",
    "agent_names": ["alice", "bob"],
    "message_count": 0,
    "last_message": None,
    "last_agent": None,
    "created_at": "2025-01-01T00:00:00",
    "is_public": False,
    "owner_id": None,
}

SEND_MESSAGE_RESPONSE = {
    "status": "ok",
    "message_id": 1,
    "next_turn": "bob",
    "message_count": 1,
}

HISTORY_RESPONSE = {
    "relay_id": "test-relay-123",
    "messages": [
        {
            "id": 1,
            "agent": "alice",
            "content": "hello",
            "data": None,
            "type": "text",
            "created_at": "2025-01-01T00:00:01",
        }
    ],
    "total_count": 1,
}

HEALTH_RESPONSE = {"status": "healthy", "version": "2.0.0"}


# ---------------------------------------------------------------------------
# Tests: create_relay
# ---------------------------------------------------------------------------

class TestCreateRelay:
    @pytest.mark.asyncio
    async def test_create_relay(self):
        captured = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return _json_response(RELAY_CREATE_RESPONSE)

        client = AsyncAgentRelayClient(base_url="http://test")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )

        relay = await client.create_relay(["alice", "bob"], is_public=True)

        assert captured["method"] == "POST"
        assert captured["url"].endswith("/relays")
        assert captured["body"] == {"agent_names": ["alice", "bob"], "is_public": True}
        assert relay.relay_id == "test-relay-123"
        assert relay.agent_names == ["alice", "bob"]
        assert relay.current_turn == "alice"
        await client.close()


# ---------------------------------------------------------------------------
# Tests: send_message
# ---------------------------------------------------------------------------

class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_message_with_auth(self):
        captured_headers = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return _json_response(SEND_MESSAGE_RESPONSE)

        client = AsyncAgentRelayClient(base_url="http://test")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )

        result = await client.send_message("r1", "hi", "alice", token="secret-key")
        assert captured_headers.get("authorization") == "Bearer secret-key"
        assert result.status == "ok"
        assert result.next_turn == "bob"
        await client.close()

    @pytest.mark.asyncio
    async def test_send_message_client_level_auth(self):
        captured_headers = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return _json_response(SEND_MESSAGE_RESPONSE)

        client = AsyncAgentRelayClient(base_url="http://test", token="client-key")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="http://test",
            headers=client._headers(),
        )

        await client.send_message("r1", "hi", "alice")
        assert captured_headers.get("authorization") == "Bearer client-key"
        await client.close()


# ---------------------------------------------------------------------------
# Tests: get_relay / get_history / health
# ---------------------------------------------------------------------------

class TestReadOperations:
    @pytest.mark.asyncio
    async def test_get_relay(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(RELAY_STATE_RESPONSE)

        client = AsyncAgentRelayClient(base_url="http://test")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )
        state = await client.get_relay("test-relay-123")
        assert state.relay_id == "test-relay-123"
        assert state.current_turn == "alice"
        assert state.message_count == 0
        await client.close()

    @pytest.mark.asyncio
    async def test_get_history(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(HISTORY_RESPONSE)

        client = AsyncAgentRelayClient(base_url="http://test")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )
        messages = await client.get_history("test-relay-123")
        assert len(messages) == 1
        assert messages[0].agent == "alice"
        assert messages[0].content == "hello"
        await client.close()

    @pytest.mark.asyncio
    async def test_health(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(HEALTH_RESPONSE)

        client = AsyncAgentRelayClient(base_url="http://test")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )
        result = await client.health()
        assert result["status"] == "healthy"
        await client.close()


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_404_raises_relay_not_found(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"detail": "Relay xyz not found"}, 404)

        client = AsyncAgentRelayClient(base_url="http://test")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )
        with pytest.raises(RelayNotFoundError):
            await client.get_relay("xyz")
        await client.close()

    @pytest.mark.asyncio
    async def test_401_raises_authentication_error(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"detail": "Invalid token"}, 401)

        client = AsyncAgentRelayClient(base_url="http://test")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )
        with pytest.raises(AuthenticationError):
            await client.send_message("r1", "hi", "alice")
        await client.close()

    @pytest.mark.asyncio
    async def test_400_turn_error_raises_not_your_turn(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"detail": "It is not your turn"}, 400)

        client = AsyncAgentRelayClient(base_url="http://test")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )
        with pytest.raises(NotYourTurnError):
            await client.send_message("r1", "hi", "bob")
        await client.close()

    @pytest.mark.asyncio
    async def test_400_generic_raises_agent_relay_error(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"detail": "Bad request"}, 400)

        client = AsyncAgentRelayClient(base_url="http://test")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://test"
        )
        with pytest.raises(AgentRelayError):
            await client.send_message("r1", "hi", "alice")
        await client.close()


# ---------------------------------------------------------------------------
# Tests: context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(HEALTH_RESPONSE)

        async with AsyncAgentRelayClient(base_url="http://test") as client:
            client._client = httpx.AsyncClient(
                transport=httpx.MockTransport(handler), base_url="http://test"
            )
            result = await client.health()
            assert result["status"] == "healthy"
