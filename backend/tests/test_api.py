"""
Integration tests for Agent Relay API endpoints
"""
import pytest


class TestHealthCheck:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestCreateRelay:
    def test_create_relay(self, client):
        response = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["relay_id"].startswith("relay-")
        assert data["agent_names"] == ["alice", "bob"]
        assert data["current_turn"] == "alice"
        assert data["api_key"] is not None
        assert len(data["api_key"]) > 20

    def test_create_relay_default_agents(self, client):
        response = client.post("/relays", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["agent_names"] == ["agent_0", "agent_1"]

    def test_create_relay_three_agents(self, client):
        response = client.post("/relays", json={
            "agent_names": ["a", "b", "c"],
            "is_public": False,
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["agent_names"]) == 3


class TestGetRelayState:
    def test_get_relay_state(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        response = client.get(f"/relays/{relay_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["relay_id"] == relay_id
        assert data["current_turn"] == "alice"
        assert data["message_count"] == 0

    def test_get_relay_not_found(self, client):
        response = client.get("/relays/nonexistent")
        assert response.status_code == 404

    def test_get_private_relay_denied(self, client, private_relay):
        relay_id = private_relay["relay_id"]
        response = client.get(f"/relays/{relay_id}?owner_id=wrong-owner")
        assert response.status_code == 403

    def test_get_private_relay_by_owner(self, client, private_relay):
        relay_id = private_relay["relay_id"]
        response = client.get(f"/relays/{relay_id}?owner_id=test-owner")
        assert response.status_code == 200


class TestSendMessage:
    def test_send_message(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello!", "agent": "alice"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["next_turn"] == "bob"
        assert data["message_count"] == 1

    def test_send_message_wrong_turn(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello!", "agent": "bob"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 400
        assert "Not turn" in response.json()["detail"]

    def test_send_message_with_api_key(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        # Use Bearer auth
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello via Bearer!", "agent": "alice"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert response.status_code == 200

    def test_send_message_without_api_key(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        # No auth header - should fail since relay has api_key_hash
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello!", "agent": "alice"},
        )
        assert response.status_code == 401
        assert "API key required" in response.json()["detail"]

    def test_send_message_invalid_api_key(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello!", "agent": "alice"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]

    def test_send_message_auto_agent(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        # No agent specified - should auto-detect current turn
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Auto agent"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200
        assert response.json()["next_turn"] == "bob"

    def test_send_structured_message(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={
                "data": {"key": "value"},
                "type": "structured",
                "agent": "alice",
            },
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200


class TestMessageHistory:
    def test_get_history(self, client, sample_message):
        relay = sample_message["relay"]
        relay_id = relay["relay_id"]
        response = client.get(f"/relays/{relay_id}/history")
        assert response.status_code == 200
        data = response.json()
        assert data["relay_id"] == relay_id
        assert data["total_count"] == 1
        assert len(data["messages"]) == 1
        assert data["messages"][0]["agent"] == "alice"
        assert data["messages"][0]["content"] == "Hello from Alice"

    def test_get_history_empty(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        response = client.get(f"/relays/{relay_id}/history")
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 0
        assert data["messages"] == []


class TestListRelays:
    def test_list_public_relays(self, client, sample_relay):
        response = client.get("/relays")
        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] >= 1
        assert len(data["relays"]) >= 1
        relay_item = data["relays"][0]
        assert "relay_id" in relay_item
        assert "agent_names" in relay_item
        assert relay_item["is_public"] is True

    def test_list_relays_excludes_private(self, client, sample_relay, private_relay):
        response = client.get("/relays")
        assert response.status_code == 200
        data = response.json()
        relay_ids = [r["relay_id"] for r in data["relays"]]
        assert sample_relay["relay_id"] in relay_ids
        assert private_relay["relay_id"] not in relay_ids

    def test_list_relays_pagination(self, client):
        # Create 3 public relays
        for i in range(3):
            client.post("/relays", json={
                "agent_names": [f"a{i}", f"b{i}"],
                "is_public": True,
            })
        response = client.get("/relays?limit=2&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data["relays"]) == 2
        assert data["total_count"] == 3


class TestWebhooks:
    def test_register_webhook(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        response = client.post(
            f"/relays/{relay_id}/webhooks",
            json={"url": "https://example.com/webhook", "agent": "alice"},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://example.com/webhook"
        assert data["agent"] == "alice"
        assert "webhook_id" in data

    def test_register_webhook_without_api_key(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        response = client.post(
            f"/relays/{relay_id}/webhooks",
            json={"url": "https://example.com/webhook", "agent": "alice"},
        )
        assert response.status_code == 401

    def test_list_webhooks(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay["api_key"]
        # Register a webhook first
        client.post(
            f"/relays/{relay_id}/webhooks",
            json={"url": "https://example.com/webhook", "agent": "bob"},
            headers={"X-API-Key": api_key},
        )
        response = client.get(f"/relays/{relay_id}/webhooks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["agent"] == "bob"
