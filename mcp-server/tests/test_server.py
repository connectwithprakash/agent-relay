"""Unit tests for the Agent Relay MCP server.

All tests mock the module-level httpx client so no running server is needed.
"""

import json
from unittest.mock import patch, MagicMock

import httpx
import pytest

from agent_relay_mcp.server import (
    _handle_http_error,
    relay_create,
    relay_send,
    relay_read,
    relay_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_status_error(status_code: int, detail: str) -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError with a JSON body."""
    response = httpx.Response(
        status_code,
        json={"detail": detail},
        request=httpx.Request("GET", "http://test"),
    )
    return httpx.HTTPStatusError(
        message=f"HTTP {status_code}",
        request=response.request,
        response=response,
    )


def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status.side_effect = None
    return resp


def _mock_error_response(status_code: int, detail: str) -> MagicMock:
    """Create a mock httpx.Response that raises on raise_for_status."""
    exc = _make_http_status_error(status_code, detail)
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status.side_effect = exc
    return resp


# ---------------------------------------------------------------------------
# Tests: _handle_http_error
# ---------------------------------------------------------------------------

class TestHandleHttpError:
    def test_handle_400_turn_error(self):
        exc = _make_http_status_error(400, "It is not your turn")
        result = _handle_http_error(exc)
        assert "Not your turn" in result["error"]

    def test_handle_400_generic(self):
        exc = _make_http_status_error(400, "Invalid agent name")
        result = _handle_http_error(exc)
        assert "Bad request" in result["error"]
        assert "Invalid agent name" in result["error"]

    def test_handle_401(self):
        exc = _make_http_status_error(401, "Invalid token")
        result = _handle_http_error(exc)
        assert "Authentication failed" in result["error"]

    def test_handle_403(self):
        exc = _make_http_status_error(403, "Forbidden")
        result = _handle_http_error(exc)
        assert "Authentication failed" in result["error"]

    def test_handle_404(self):
        exc = _make_http_status_error(404, "Relay not found")
        result = _handle_http_error(exc)
        assert "Relay not found" in result["error"]

    def test_handle_429(self):
        exc = _make_http_status_error(429, "Too many requests")
        result = _handle_http_error(exc)
        assert "Rate limit exceeded" in result["error"]

    def test_handle_500(self):
        exc = _make_http_status_error(500, "Internal server error")
        result = _handle_http_error(exc)
        assert "500" in result["error"]
        assert "Internal server error" in result["error"]


# ---------------------------------------------------------------------------
# Tests: tool functions
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
}

SEND_MESSAGE_RESPONSE = {
    "status": "ok",
    "message_id": 1,
    "next_turn": "bob",
    "message_count": 1,
}

HISTORY_RESPONSE = {
    "relay_id": "test-relay-123",
    "messages": [{"id": 1, "agent": "alice", "content": "hello"}],
    "total_count": 1,
}


class TestRelayCreate:
    @patch("agent_relay_mcp.server._client")
    def test_relay_create_success(self, mock_client):
        mock_client.post.return_value = _mock_response(RELAY_CREATE_RESPONSE)
        result = relay_create(["alice", "bob"])
        assert result == RELAY_CREATE_RESPONSE
        mock_client.post.assert_called_once_with(
            "/relays",
            json={"agent_names": ["alice", "bob"], "is_public": False},
        )

    @patch("agent_relay_mcp.server._client")
    def test_relay_create_public(self, mock_client):
        mock_client.post.return_value = _mock_response(RELAY_CREATE_RESPONSE)
        relay_create(["alice", "bob"], is_public=True)
        mock_client.post.assert_called_once_with(
            "/relays",
            json={"agent_names": ["alice", "bob"], "is_public": True},
        )


class TestRelaySend:
    @patch("agent_relay_mcp.server._client")
    def test_relay_send_success(self, mock_client):
        mock_client.post.return_value = _mock_response(SEND_MESSAGE_RESPONSE)
        result = relay_send("r1", "hello", "alice")
        assert result["status"] == "ok"

    @patch("agent_relay_mcp.server._client")
    def test_relay_send_with_api_key(self, mock_client):
        mock_client.post.return_value = _mock_response(SEND_MESSAGE_RESPONSE)
        relay_send("r1", "hello", "alice", api_key="secret")
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer secret"

    @patch("agent_relay_mcp.server._client")
    def test_relay_send_error(self, mock_client):
        mock_client.post.return_value = _mock_error_response(400, "It is not your turn")
        result = relay_send("r1", "hello", "bob")
        assert "Not your turn" in result["error"]


class TestRelayRead:
    @patch("agent_relay_mcp.server._client")
    def test_relay_read_success(self, mock_client):
        mock_client.get.return_value = _mock_response(HISTORY_RESPONSE)
        result = relay_read("r1", limit=10)
        assert result == HISTORY_RESPONSE
        mock_client.get.assert_called_once_with(
            "/relays/r1/history",
            params={"limit": 10},
        )


class TestRelayStatus:
    @patch("agent_relay_mcp.server._client")
    def test_relay_status_success(self, mock_client):
        mock_client.get.return_value = _mock_response(RELAY_STATE_RESPONSE)
        result = relay_status("test-relay-123")
        assert result["current_turn"] == "alice"
        mock_client.get.assert_called_once_with("/relays/test-relay-123")
