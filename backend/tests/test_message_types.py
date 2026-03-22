"""
Tests for message types and threading features
"""
import pytest


class TestMessageTypes:
    def test_send_with_message_type(self, client, sample_relay):
        """Messages can be sent with a categorized message_type."""
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={
                "content": "Is this working?",
                "agent": "alice",
                "message_type": "question",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

        # Verify it appears in history with the correct message_type
        history = client.get(f"/relays/{relay_id}/history").json()
        assert history["messages"][0]["message_type"] == "question"

    def test_send_default_message_type(self, client, sample_relay):
        """Messages without explicit message_type default to 'text'."""
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]
        client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Plain message", "agent": "alice"},
            headers={"Authorization": f"Bearer {token}"},
        )
        history = client.get(f"/relays/{relay_id}/history").json()
        assert history["messages"][0]["message_type"] == "text"

    def test_send_with_invalid_message_type(self, client, sample_relay):
        """Invalid message_type values are rejected."""
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={
                "content": "Bad type",
                "agent": "alice",
                "message_type": "invalid-type",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422

    def test_filter_history_by_type(self, client, sample_relay):
        """History endpoint filters by message_type query parameter."""
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]

        # Send a question from alice
        client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Question?", "agent": "alice", "message_type": "question"},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Join as bob and send an action-item
        join_code = sample_relay["join_code"]
        bob_resp = client.post(
            f"/relays/join/{join_code}", params={"agent_name": "bob"}
        )
        bob_token = bob_resp.json()["token"]
        client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Do this", "agent": "bob", "message_type": "action-item"},
            headers={"Authorization": f"Bearer {bob_token}"},
        )

        # Filter for questions only
        resp = client.get(f"/relays/{relay_id}/history?message_type=question")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1
        assert data["messages"][0]["message_type"] == "question"
        assert data["messages"][0]["content"] == "Question?"

        # Filter for action-items only
        resp = client.get(f"/relays/{relay_id}/history?message_type=action-item")
        data = resp.json()
        assert data["total_count"] == 1
        assert data["messages"][0]["message_type"] == "action-item"

        # No filter returns all
        resp = client.get(f"/relays/{relay_id}/history")
        assert resp.json()["total_count"] == 2


class TestThreading:
    def test_send_with_reply_to(self, client, sample_relay):
        """Messages can reference a parent message via reply_to."""
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]

        # Send original message
        resp1 = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Original", "agent": "alice"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp1.status_code == 200
        original_id = resp1.json()["message_id"]

        # Join as bob and reply
        join_code = sample_relay["join_code"]
        bob_resp = client.post(
            f"/relays/join/{join_code}", params={"agent_name": "bob"}
        )
        bob_token = bob_resp.json()["token"]
        resp2 = client.post(
            f"/relays/{relay_id}/messages",
            json={
                "content": "Reply to original",
                "agent": "bob",
                "reply_to": original_id,
            },
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert resp2.status_code == 200

        # Verify reply_to appears in history
        history = client.get(f"/relays/{relay_id}/history").json()
        reply_msg = history["messages"][1]
        assert reply_msg["reply_to"] == original_id
        assert reply_msg["content"] == "Reply to original"

        # Original has no reply_to
        assert history["messages"][0]["reply_to"] is None

    def test_reply_to_invalid_message_id(self, client, sample_relay):
        """Replying to a non-existent message ID returns an error."""
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={
                "content": "Reply to ghost",
                "agent": "alice",
                "reply_to": 99999,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400
        assert "reply_to" in response.json()["detail"].lower()

    def test_reply_to_message_in_different_relay(self, client, sample_relay):
        """Replying to a message from a different relay is rejected."""
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]

        # Send a message in the first relay
        resp = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "First relay msg", "agent": "alice"},
            headers={"Authorization": f"Bearer {token}"},
        )
        msg_id = resp.json()["message_id"]

        # Create a second relay
        resp2 = client.post(
            "/relays",
            json={"agent_names": ["charlie", "dave"], "is_public": True},
        )
        relay2_id = resp2.json()["relay_id"]
        token2 = resp2.json()["token"]

        # Try to reply to message from first relay in second relay
        response = client.post(
            f"/relays/{relay2_id}/messages",
            json={
                "content": "Cross-relay reply",
                "agent": "charlie",
                "reply_to": msg_id,
            },
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert response.status_code == 400
        assert "reply_to" in response.json()["detail"].lower()
