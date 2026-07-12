"""Unit tests for the Agent Relay MCP server.

All tests mock the module-level httpx client so no running server is needed.
"""

import json
from unittest.mock import call, patch, MagicMock

import httpx
import pytest

from agent_relay_mcp.server import (
    _handle_http_error,
    _session,
    relay_create,
    relay_send,
    relay_read,
    relay_status,
    relay_join_code,
    relay_create_invitation,
    relay_redeem_invitation,
    relay_info,
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
        assert result["relay_id"] == "test-relay-123"
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
    def test_relay_send_forwards_reliability_controls(self, mock_client):
        mock_client.post.return_value = _mock_response(SEND_MESSAGE_RESPONSE)
        relay_send(
            "r1", "hello", "alice",
            idempotency_key="send-1", expected_version=4,
        )
        body = mock_client.post.call_args.kwargs["json"]
        assert body["idempotency_key"] == "send-1"
        assert body["expected_version"] == 4

    @patch("agent_relay_mcp.server._client")
    def test_relay_send_success(self, mock_client):
        mock_client.post.return_value = _mock_response(SEND_MESSAGE_RESPONSE)
        result = relay_send("r1", "hello", "alice")
        assert result["status"] == "ok"

    @patch("agent_relay_mcp.server._client")
    def test_relay_send_with_token(self, mock_client):
        mock_client.post.return_value = _mock_response(SEND_MESSAGE_RESPONSE)
        relay_send("r1", "hello", "alice", token="secret")
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer secret"

    @patch("agent_relay_mcp.server._client")
    def test_relay_send_error(self, mock_client):
        mock_client.post.return_value = _mock_error_response(400, "It is not your turn")
        result = relay_send("r1", "hello", "bob")
        assert "Not your turn" in result["error"]

    def test_relay_send_empty_message_error(self):
        """Fix 3: error message should suggest 'message' parameter."""
        result = relay_send("r1", "", "alice")
        assert "'message'" in result["error"]

    @patch("agent_relay_mcp.server._session", {})
    @patch("agent_relay_mcp.server._client")
    def test_relay_send_agent_optional_with_token(self, mock_client):
        """Fix 2: agent param should be optional when token auth is set."""
        mock_client.post.return_value = _mock_response(SEND_MESSAGE_RESPONSE)
        result = relay_send("r1", "hello", agent="", token="secret")
        assert result["status"] == "ok"
        # Verify agent was NOT included in the body
        call_kwargs = mock_client.post.call_args
        assert "agent" not in call_kwargs.kwargs["json"]

    def test_relay_send_no_agent_no_token_errors(self):
        """Fix 2: without agent or token, should error."""
        _session.clear()
        result = relay_send("r1", "hello", agent="", token="")
        assert "error" in result
        assert "agent" in result["error"].lower() or "token" in result["error"].lower()


class TestRelayRead:
    @patch("agent_relay_mcp.server._client")
    def test_relay_read_success(self, mock_client):
        mock_client.get.return_value = _mock_response(HISTORY_RESPONSE)
        result = relay_read("r1", limit=10)
        assert result == HISTORY_RESPONSE
        mock_client.get.assert_called_once_with(
            "/relays/r1/history",
            params={"limit": 10},
            headers={},
        )

    @patch("agent_relay_mcp.server._client")
    def test_explicit_relay_token_overrides_session_token(self, mock_client):
        mock_client.get.return_value = _mock_response(HISTORY_RESPONSE)
        relay_read("r2", token="token-r2")
        assert mock_client.get.call_args.kwargs["headers"] == {
            "Authorization": "Bearer token-r2"
        }


class TestPairingInvitations:
    @patch("agent_relay_mcp.server._client")
    def test_create_invitation(self, mock_client):
        mock_client.post.return_value = _mock_response({"invitation": "invite-bob"})
        result = relay_create_invitation("bob", relay_id="r1", token="creator")
        assert result["invitation"] == "invite-bob"
        assert mock_client.post.call_args.kwargs["headers"] == {
            "Authorization": "Bearer creator"
        }

    @patch("agent_relay_mcp.server._save_config_file")
    @patch("agent_relay_mcp.server._client")
    def test_redeem_invitation_persists_session(self, mock_client, mock_save):
        mock_client.post.return_value = _mock_response({
            "relay_id": "r1", "agent_name": "bob", "token": "token-bob"
        })
        result = relay_redeem_invitation("invite-bob")
        assert result["config_saved"] is True
        assert _session["token"] == "token-bob"
        mock_save.assert_called_once()
        _session.clear()


class TestRelayStatus:
    @patch("agent_relay_mcp.server._client")
    def test_relay_status_success(self, mock_client):
        mock_client.get.return_value = _mock_response(RELAY_STATE_RESPONSE)
        result = relay_status("test-relay-123")
        assert result["current_turn"] == "alice"
        mock_client.get.assert_called_once_with("/relays/test-relay-123", headers={})

    @patch("agent_relay_mcp.server._session", {"agent": "alice", "relay_id": "test-relay-123"})
    @patch("agent_relay_mcp.server._client")
    def test_relay_status_your_turn_true(self, mock_client):
        """Fix 4: relay_status should show your_turn boolean."""
        mock_client.get.return_value = _mock_response(RELAY_STATE_RESPONSE)
        result = relay_status("test-relay-123")
        assert result["your_turn"] is True

    @patch("agent_relay_mcp.server._session", {"agent": "bob", "relay_id": "test-relay-123"})
    @patch("agent_relay_mcp.server._client")
    def test_relay_status_your_turn_false(self, mock_client):
        """Fix 4: relay_status should show your_turn=False when not your turn."""
        mock_client.get.return_value = _mock_response(RELAY_STATE_RESPONSE)
        result = relay_status("test-relay-123")
        assert result["your_turn"] is False

    @patch(
        "agent_relay_mcp.server._session",
        {"agent": "alice", "relay_id": "session-relay", "token": "session-token"},
    )
    @patch("agent_relay_mcp.server._client")
    def test_cross_relay_token_does_not_reuse_session_identity(self, mock_client):
        response = {
            "relay_id": "test-relay-123",
            "current_turn": "alice",
            "agent_names": ["alice", "bob"],
            "message_count": 0,
        }
        mock_client.get.return_value = _mock_response(response)

        result = relay_status("test-relay-123", token="other-token")

        assert "your_turn" not in result
        assert "(you)" not in result["turn_order"]
        mock_client.post.assert_not_called()


class TestRelayJoinCode:
    @patch("agent_relay_mcp.server._client")
    def test_join_code_returns_full_context(self, mock_client):
        """Fix 1: relay_join_code should return full context after join."""
        join_resp = _mock_response({
            "relay_id": "test-relay-123",
            "agent_names": ["alice", "bob"],
            "token": "tok-123",
        })
        status_resp = _mock_response({
            "description": "Test relay",
            "message_count": 5,
            "current_turn": "bob",
            "agent_names": ["alice", "bob"],
        })
        instr_resp = _mock_response({
            "your_instructions": "Review the code carefully.",
        })

        mock_client.post.return_value = join_resp
        mock_client.get.side_effect = [status_resp, instr_resp]

        result = relay_join_code("ABC123", "bob")

        assert result["relay_id"] == "test-relay-123"
        assert result["description"] == "Test relay"
        assert result["message_count"] == 5
        assert result["your_turn"] is True
        assert result["your_instructions"] == "Review the code carefully."
        assert len(result["turn_order"]) == 2
        assert "(you)" in result["turn_order"][1]
        assert mock_client.get.call_args_list == [
            call("/relays/test-relay-123", headers={"Authorization": "Bearer tok-123"}),
            call(
                "/relays/test-relay-123/instructions",
                params={"agent": "bob"},
                headers={"Authorization": "Bearer tok-123"},
            ),
        ]

    @patch("agent_relay_mcp.server._client")
    def test_join_code_works_when_status_fails(self, mock_client):
        """Join should succeed even if status/instructions fetch fails."""
        join_resp = _mock_response({
            "relay_id": "test-relay-123",
            "agent_names": ["alice", "bob"],
            "token": "tok-123",
        })
        # Status and instructions both fail
        error_resp = _mock_response({}, status_code=500)
        mock_client.post.return_value = join_resp
        mock_client.get.side_effect = Exception("network error")

        result = relay_join_code("ABC123", "bob")
        assert result["relay_id"] == "test-relay-123"


class TestRelayInfo:
    @patch("agent_relay_mcp.server._session", {"relay_id": "r1", "agent": "alice"})
    @patch("agent_relay_mcp.server._client")
    def test_relay_info_success(self, mock_client):
        """Fix 5: relay_info returns description, instructions, turn order."""
        status_resp = _mock_response({
            "description": "Code review relay",
            "agent_names": ["alice", "bob"],
            "current_turn": "alice",
            "message_count": 3,
        })
        instr_resp = _mock_response({
            "your_instructions": "You are the reviewer.",
        })
        mock_client.get.side_effect = [status_resp, instr_resp]

        result = relay_info("r1")

        assert result["description"] == "Code review relay"
        assert result["your_turn"] is True
        assert result["message_count"] == 3
        assert result["your_instructions"] == "You are the reviewer."
        assert len(result["turn_order"]) == 2
        assert mock_client.get.call_args_list == [
            call("/relays/r1", headers={}),
            call("/relays/r1/instructions", params={"agent": "alice"}, headers={}),
        ]

    def test_relay_info_no_relay_id(self):
        _session.clear()
        result = relay_info("")
        assert "error" in result

    @patch("agent_relay_mcp.server._client")
    def test_relay_info_http_error(self, mock_client):
        mock_client.get.return_value = _mock_error_response(404, "Relay not found")
        result = relay_info("bad-id")
        assert "error" in result
