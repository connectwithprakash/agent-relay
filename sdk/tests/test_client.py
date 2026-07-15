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
    "version": 1,
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
    def test_send_message_forwards_reliability_controls(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            return _json_response(SEND_MESSAGE_RESPONSE)

        client = AgentRelayClient(base_url="http://test", token="client-key")
        client._client = httpx.Client(
            transport=_mock_transport(handler), base_url="http://test"
        )
        client.send_message(
            "r1", "hi", idempotency_key="send-1", expected_version=7
        )

        assert captured["idempotency_key"] == "send-1"
        assert captured["expected_version"] == 7
        client.close()

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

    def test_send_message_does_not_retry_gateway_failure(self, monkeypatch):
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return _json_response({"detail": "temporary gateway failure"}, 503)

        monkeypatch.setattr("agent_relay.client.time.sleep", lambda _: None)
        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")

        with pytest.raises(AgentRelayError):
            client.send_message("r1", "hi")

        assert attempts == 1
        client.close()

    def test_send_message_does_not_retry_transport_error(self):
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectError("tunnel reconnecting", request=request)

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")

        with pytest.raises(httpx.ConnectError):
            client.send_message("r1", "hi")

        assert attempts == 1
        client.close()

    def test_send_message_retries_rate_limit(self, monkeypatch):
        attempts = 0
        delays = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(
                    429,
                    json={"detail": "rate limited"},
                    headers={"Retry-After": "2.5"},
                )
            return _json_response(SEND_MESSAGE_RESPONSE)

        monkeypatch.setattr("agent_relay.client.time.sleep", delays.append)
        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")

        result = client.send_message("r1", "hi")

        assert result.status == "ok"
        assert attempts == 2
        assert delays == [2.5]
        client.close()


# ---------------------------------------------------------------------------
# Tests: get_relay / get_history / health
# ---------------------------------------------------------------------------

class TestPairingInvitations:
    def test_create_invitation_uses_creator_token(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["authorization"] = request.headers.get("authorization")
            return _json_response({"invitation": "invite-bob", "agent_name": "bob"})

        client = AgentRelayClient(base_url="http://test", token="creator-token")
        client._client = httpx.Client(
            transport=_mock_transport(handler),
            base_url="http://test",
            headers=client._headers(),
        )
        result = client.create_invitation("r1", "bob")

        assert "/relays/r1/invitations" in captured["url"]
        assert captured["authorization"] == "Bearer creator-token"
        assert result["invitation"] == "invite-bob"
        client.close()

    def test_redeem_invitation_stores_participant_token(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _json_response(
                {"relay_id": "r1", "agent_name": "bob", "token": "token-bob"}
            )

        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(
            transport=_mock_transport(handler), base_url="http://test"
        )
        client.redeem_invitation("invite-bob")

        assert client._token == "token-bob"
        assert client._client.headers["authorization"] == "Bearer token-bob"
        client.close()


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

    def test_get_relay_retries_transient_transport_error(self, monkeypatch):
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ConnectError("tunnel reconnecting", request=request)
            return _json_response(RELAY_STATE_RESPONSE)

        monkeypatch.setattr("agent_relay.client.time.sleep", lambda _: None)
        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")

        state = client.get_relay("test-relay-123")

        assert state.relay_id == "test-relay-123"
        assert attempts == 2
        client.close()

    def test_get_relay_retries_transient_gateway_response(self, monkeypatch):
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return _json_response({"detail": "tunnel reconnecting"}, 503)
            return _json_response(RELAY_STATE_RESPONSE)

        monkeypatch.setattr("agent_relay.client.time.sleep", lambda _: None)
        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")

        state = client.get_relay("test-relay-123")

        assert state.relay_id == "test-relay-123"
        assert attempts == 2
        client.close()

    def test_get_relay_gateway_retry_ignores_retry_after(self, monkeypatch):
        attempts = 0
        delays = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(
                    503,
                    json={"detail": "tunnel reconnecting"},
                    headers={"Retry-After": "3600"},
                )
            return _json_response(RELAY_STATE_RESPONSE)

        monkeypatch.setattr("agent_relay.client.time.sleep", delays.append)
        client = AgentRelayClient(base_url="http://test")
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")

        state = client.get_relay("test-relay-123")

        assert state.relay_id == "test-relay-123"
        assert attempts == 2
        assert delays == [0.5]
        client.close()

    def test_get_relay_rate_limit_exhaustion(self, monkeypatch):
        attempts = 0
        delays = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return httpx.Response(
                429,
                json={"detail": "rate limited"},
                headers={"Retry-After": "1.5"},
            )

        monkeypatch.setattr("agent_relay.client.time.sleep", delays.append)
        client = AgentRelayClient(base_url="http://test", max_retries=2)
        client._client = httpx.Client(transport=_mock_transport(handler), base_url="http://test")

        with pytest.raises(AgentRelayError) as exc_info:
            client.get_relay("test-relay-123")

        assert exc_info.value.status_code == 429
        assert attempts == 2
        assert delays == [1.5]
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
