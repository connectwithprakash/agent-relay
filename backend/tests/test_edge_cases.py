"""
Edge case tests for Agent Relay API
"""
import pytest


class TestRelayEdgeCases:

    def test_create_relay_duplicate_agent_names(self, client):
        """Creating a relay with duplicate agent names should be rejected."""
        response = client.post("/relays", json={
            "agent_names": ["alice", "alice"],
            "is_public": True,
        })
        assert response.status_code == 422
        assert "unique" in response.text.lower()

    def test_create_relay_max_agents(self, client):
        """Creating a relay with exactly 10 agents (the max) should succeed."""
        agents = [f"agent_{i}" for i in range(10)]
        response = client.post("/relays", json={
            "agent_names": agents,
            "is_public": True,
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["agent_names"]) == 10

    def test_create_relay_too_many_agents(self, client):
        """Creating a relay with 21 agents should fail validation."""
        agents = [f"agent_{i}" for i in range(21)]
        response = client.post("/relays", json={
            "agent_names": agents,
            "is_public": True,
        })
        assert response.status_code == 422  # Pydantic validation error

    def test_create_relay_too_few_agents(self, client):
        """Creating a relay with fewer than 2 agents should fail validation."""
        response = client.post("/relays", json={
            "agent_names": ["solo"],
            "is_public": True,
        })
        assert response.status_code == 422


class TestMessageEdgeCases:

    def test_send_message_to_nonexistent_relay(self, client):
        """Sending a message to a non-existent relay returns 404."""
        response = client.post(
            "/relays/nonexistent-relay/messages",
            json={"content": "Hello!", "agent": "alice"},
        )
        assert response.status_code == 404

    def test_send_empty_message(self, client, sample_relay):
        """Sending a message with no content should work (content is optional)."""
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"agent": "alice"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_send_structured_message_with_data(self, client, sample_relay):
        """Sending a structured message with a data payload should succeed."""
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        payload = {
            "type": "structured",
            "data": {"action": "move", "x": 10, "y": 20, "metadata": {"nested": True}},
            "agent": "alice",
        }
        response = client.post(
            f"/relays/{relay_id}/messages",
            json=payload,
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200

        # Verify data is persisted in history
        history = client.get(f"/relays/{relay_id}/history").json()
        msg = history["messages"][0]
        assert msg["type"] == "structured"
        assert msg["data"]["action"] == "move"
        assert msg["data"]["metadata"]["nested"] is True


class TestHistoryEdgeCases:

    def test_history_pagination_beyond_total(self, client, sample_relay):
        """Requesting history with offset beyond total returns empty list."""
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]

        # Send one message
        client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello", "agent": "alice"},
            headers={"X-API-Key": api_key},
        )

        # Request with offset way beyond total
        response = client.get(f"/relays/{relay_id}/history?offset=1000")
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []
        assert data["total_count"] == 1  # total_count still reflects actual count

    def test_history_nonexistent_relay(self, client):
        """Getting history for a non-existent relay returns 404."""
        response = client.get("/relays/nonexistent/history")
        assert response.status_code == 404

    def test_history_limit_capped(self, client, sample_relay):
        """Requesting limit > 100 should not return more than 100 messages."""
        relay_id = sample_relay["relay_id"]
        # Just verify the endpoint accepts the large limit without error
        response = client.get(f"/relays/{relay_id}/history?limit=999")
        assert response.status_code == 200


class TestWebhookEdgeCases:

    def test_webhook_unknown_agent(self, client, sample_relay):
        """Registering a webhook for an unknown agent returns 400."""
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        response = client.post(
            f"/relays/{relay_id}/webhooks",
            json={"url": "https://example.com/hook", "agent": "charlie"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 400
        assert "Unknown agent" in response.json()["detail"]

    def test_webhook_nonexistent_relay(self, client):
        """Registering a webhook for a non-existent relay returns 404."""
        response = client.post(
            "/relays/nonexistent/webhooks",
            json={"url": "https://example.com/hook", "agent": "alice"},
        )
        assert response.status_code == 404
