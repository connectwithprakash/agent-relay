"""
Tests for the non-blocking /relays/{relay_id}/listen endpoint
"""
import time

import pytest


@pytest.fixture
def relay_with_tokens(client):
    """Create a relay and return relay info + per-agent tokens."""
    r = client.post(
        "/relays",
        json={"agent_names": ["alice", "bob"], "is_public": True},
    )
    assert r.status_code == 200
    data = r.json()
    relay_id = data["relay_id"]
    join_code = data["join_code"]
    alice_token = data["token"]

    bob_resp = client.post(f"/relays/join/{join_code}?agent_name=bob")
    bob_token = bob_resp.json()["token"]

    return {
        "relay_id": relay_id,
        "tokens": {"alice": alice_token, "bob": bob_token},
    }


def _send(client, relay_id, agent, content, token):
    """Helper to send a message and assert success."""
    resp = client.post(
        f"/relays/{relay_id}/messages",
        json={"content": content, "agent": agent},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestListenEndpoint:
    """Tests for GET /relays/{relay_id}/listen"""

    def test_listen_returns_immediately(self, client, sample_relay):
        """Listen should return in under 100ms - it must never block."""
        relay_id = sample_relay["relay_id"]
        start = time.monotonic()
        response = client.get(f"/relays/{relay_id}/listen")
        elapsed = time.monotonic() - start
        assert response.status_code == 200
        assert elapsed < 0.1, f"listen took {elapsed:.3f}s, expected < 0.1s"

    def test_listen_no_new_messages(self, client, sample_relay):
        """With no messages, listen returns empty results."""
        relay_id = sample_relay["relay_id"]
        response = client.get(f"/relays/{relay_id}/listen")
        assert response.status_code == 200
        data = response.json()
        assert data["new_messages"] == 0
        assert data["messages"] == []
        assert data["last_id"] == 0
        assert data["total_messages"] == 0
        assert data["agent_count"] == 2
        assert data["current_turn"] == "alice"

    def test_listen_with_since_id_filters(self, client, relay_with_tokens):
        """Messages with id <= since_id should be excluded."""
        relay_id = relay_with_tokens["relay_id"]
        tokens = relay_with_tokens["tokens"]

        # Send two messages: alice then bob (proper turn order)
        r1 = _send(client, relay_id, "alice", "Message 1", tokens["alice"])
        msg1_id = r1["message_id"]

        r2 = _send(client, relay_id, "bob", "Message 2", tokens["bob"])
        msg2_id = r2["message_id"]

        # Listen with since_id=0: should get both messages
        response = client.get(f"/relays/{relay_id}/listen?since_id=0")
        data = response.json()
        assert data["new_messages"] == 2
        assert len(data["messages"]) == 2
        assert data["last_id"] == msg2_id
        assert data["total_messages"] == 2

        # Listen with since_id=msg1_id: should only get message 2
        response = client.get(f"/relays/{relay_id}/listen?since_id={msg1_id}")
        data = response.json()
        assert data["new_messages"] == 1
        assert len(data["messages"]) == 1
        assert data["messages"][0]["id"] == msg2_id
        assert data["messages"][0]["content"] == "Message 2"
        assert data["last_id"] == msg2_id

        # Listen with since_id=msg2_id: should get nothing new
        response = client.get(f"/relays/{relay_id}/listen?since_id={msg2_id}")
        data = response.json()
        assert data["new_messages"] == 0
        assert data["messages"] == []
        assert data["last_id"] == msg2_id

    def test_listen_includes_your_turn(self, client, sample_relay):
        """When agent param is provided, your_turn should reflect turn state."""
        relay_id = sample_relay["relay_id"]

        # Alice's turn initially
        response = client.get(f"/relays/{relay_id}/listen?agent=alice")
        data = response.json()
        assert data["your_turn"] is True
        assert data["current_turn"] == "alice"

        # Bob should see your_turn=False
        response = client.get(f"/relays/{relay_id}/listen?agent=bob")
        data = response.json()
        assert data["your_turn"] is False

    def test_listen_your_turn_none_without_agent(self, client, sample_relay):
        """Without agent param, your_turn should be None."""
        relay_id = sample_relay["relay_id"]
        response = client.get(f"/relays/{relay_id}/listen")
        data = response.json()
        assert data["your_turn"] is None

    def test_listen_relay_not_found(self, client):
        """Listen on nonexistent relay should return 404."""
        response = client.get("/relays/nonexistent/listen")
        assert response.status_code == 404

    def test_listen_respects_limit(self, client, relay_with_tokens):
        """Limit parameter should cap the number of returned messages."""
        relay_id = relay_with_tokens["relay_id"]
        tokens = relay_with_tokens["tokens"]

        # Send 3 messages in proper turn order
        _send(client, relay_id, "alice", "Msg 0", tokens["alice"])
        _send(client, relay_id, "bob", "Msg 1", tokens["bob"])
        _send(client, relay_id, "alice", "Msg 2", tokens["alice"])

        response = client.get(f"/relays/{relay_id}/listen?limit=2")
        data = response.json()
        assert data["new_messages"] == 2
        assert len(data["messages"]) == 2
        # total_messages should still reflect all messages
        assert data["total_messages"] == 3

    def test_listen_message_schema(self, client, sample_message):
        """Returned messages should have correct schema fields."""
        relay = sample_message["relay"]
        relay_id = relay["relay_id"]

        response = client.get(f"/relays/{relay_id}/listen")
        data = response.json()
        assert data["new_messages"] == 1
        msg = data["messages"][0]
        assert "id" in msg
        assert msg["agent"] == "alice"
        assert msg["content"] == "Hello from Alice"
        assert "created_at" in msg
        assert msg["type"] == "text"
