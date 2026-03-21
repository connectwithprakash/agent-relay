"""
WebSocket endpoint tests for Agent Relay
"""
import pytest
from starlette.websockets import WebSocketDisconnect


class TestWebSocketConnect:
    """Test WebSocket connection behaviors."""

    def test_websocket_connect_success(self, client, sample_relay):
        """Valid relay + agent connects successfully via WebSocket."""
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        with client.websocket_connect(
            f"/relays/{relay_id}/ws?agent=alice&api_key={api_key}"
        ) as ws:
            # Connection accepted; close cleanly from client side
            ws.close()

    def test_websocket_invalid_relay(self, client):
        """WebSocket returns 4004 close code for non-existent relay."""
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/relays/nonexistent-relay/ws?agent=alice"
            ):
                pass
        assert exc_info.value.code == 4004

    def test_websocket_unknown_agent(self, client, sample_relay):
        """WebSocket returns 4003 close code for unknown agent."""
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/relays/{relay_id}/ws?agent=charlie&api_key={api_key}"
            ):
                pass
        assert exc_info.value.code == 4003

    def test_websocket_receives_broadcast(self, client, sample_relay):
        """Two WebSocket clients both receive a message sent via POST."""
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]

        with client.websocket_connect(
            f"/relays/{relay_id}/ws?agent=alice&api_key={api_key}"
        ) as ws1:
            with client.websocket_connect(
                f"/relays/{relay_id}/ws?agent=bob&api_key={api_key}"
            ) as ws2:
                # Send a message via the HTTP API
                resp = client.post(
                    f"/relays/{relay_id}/messages",
                    json={"content": "Hello from alice", "agent": "alice"},
                    headers={"X-API-Key": api_key},
                )
                assert resp.status_code == 200

                # Both clients should receive the broadcast
                msg1 = ws1.receive_json()
                msg2 = ws2.receive_json()

                assert msg1["agent"] == "alice"
                assert msg1["content"] == "Hello from alice"
                assert msg1["next_turn"] == "bob"

                assert msg2["agent"] == "alice"
                assert msg2["content"] == "Hello from alice"
                assert msg2["next_turn"] == "bob"

    def test_websocket_auth_required(self, client, sample_relay):
        """WebSocket returns 4001 when relay has API key but none provided."""
        relay_id = sample_relay["relay_id"]
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/relays/{relay_id}/ws?agent=alice"
            ):
                pass
        assert exc_info.value.code == 4001

    def test_websocket_invalid_api_key(self, client, sample_relay):
        """WebSocket returns 4001 when invalid API key is provided."""
        relay_id = sample_relay["relay_id"]
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/relays/{relay_id}/ws?agent=alice&api_key=wrong-key"
            ):
                pass
        assert exc_info.value.code == 4001
