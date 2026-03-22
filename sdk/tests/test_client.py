"""Unit tests for the Agent Relay Python SDK.

All tests use httpx mock transport so no running server is needed.
"""

import json

import httpx
import pytest

from agent_relay import (
    AgentRelayClient,
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
    def test_create_relay_builds_correct_request(self):
        """Verify request body and returned model."""
        captured_request = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_request["method"] = request.method
            captured_request["url"] = str(request.url)
            captured_request["body"] = json.loads(request.content)
            return _json_response(RELAY_CREATE_RESPONSE)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")

        relay = client.create_relay(["alice", "bob"], is_public=True)

        assert captured_request["method"] == "POST"
        assert captured_request["url"].endswith("/relays")
        assert captured_request["body"] == {
            "agent_names": ["alice", "bob"],
            "is_public": True,
        }
        assert relay.relay_id == "test-relay-123"
        assert relay.agent_names == ["alice", "bob"]
        assert relay.current_turn == "alice"
        client.close()

    def test_create_relay_default_not_public(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return _json_response(RELAY_CREATE_RESPONSE)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")
        client.create_relay(["alice", "bob"])
        assert captured["body"]["is_public"] is False
        client.close()


# ---------------------------------------------------------------------------
# Tests: send_message
# ---------------------------------------------------------------------------

class TestSendMessage:
    def test_send_message_includes_auth_header(self):
        """Verify auth header is sent when token is provided on the call."""
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return _json_response(SEND_MESSAGE_RESPONSE)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")

        result = client.send_message("r1", "hi", "alice", token="secret-key")

        assert captured_headers.get("authorization") == "Bearer secret-key"
        assert result.status == "ok"
        assert result.next_turn == "bob"
        client.close()

    def test_send_message_uses_client_level_auth(self):
        """Verify the client-level token is included by default."""
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return _json_response(SEND_MESSAGE_RESPONSE)

        client = AgentRelayClient(base_url="http://test", token="client-key")
        client._client = httpx.Client(
            transport=_mock_transport(handler),
            base_url="http://test",
            headers=client._headers(),
        )

        client.send_message("r1", "hi", "alice")
        assert captured_headers.get("authorization") == "Bearer client-key"
        client.close()


# ---------------------------------------------------------------------------
# Tests: get_relay / get_history / health
# ---------------------------------------------------------------------------

class TestReadOperations:
    def test_get_relay(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(RELAY_STATE_RESPONSE)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")
        state = client.get_relay("test-relay-123")
        assert state.relay_id == "test-relay-123"
        assert state.current_turn == "alice"
        assert state.message_count == 0
        client.close()

    def test_get_history(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(HISTORY_RESPONSE)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")
        messages = client.get_history("test-relay-123")
        assert len(messages) == 1
        assert messages[0].agent == "alice"
        assert messages[0].content == "hello"
        client.close()

    def test_health(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(HEALTH_RESPONSE)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")
        result = client.health()
        assert result["status"] == "healthy"
        client.close()


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_404_raises_relay_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"detail": "Relay xyz not found"}, 404)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")
        with pytest.raises(RelayNotFoundError):
            client.get_relay("xyz")
        client.close()

    def test_401_raises_authentication_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"detail": "Invalid token"}, 401)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")
        with pytest.raises(AuthenticationError):
            client.send_message("r1", "hi", "alice")
        client.close()

    def test_400_turn_error_raises_not_your_turn(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"detail": "It is not your turn"}, 400)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")
        with pytest.raises(NotYourTurnError):
            client.send_message("r1", "hi", "bob")
        client.close()

    def test_400_generic_raises_agent_relay_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"detail": "Bad request"}, 400)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")
        with pytest.raises(AgentRelayError):
            client.send_message("r1", "hi", "alice")
        client.close()

    def test_500_raises_agent_relay_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response({"detail": "Internal server error"}, 500)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")
        with pytest.raises(AgentRelayError) as exc_info:
            client.health()
        assert exc_info.value.status_code == 500
        client.close()


# ---------------------------------------------------------------------------
# Tests: context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_context_manager(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(HEALTH_RESPONSE)

        with AgentRelayClient(base_url="http://test") as client:
            client._client = httpx.Client(
                transport=_mock_transport(handler), base_url="http://test"
            )
            result = client.health()
            assert result["status"] == "healthy"
