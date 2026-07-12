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
        assert data["token"] is not None
        assert len(data["token"]) > 20

    def test_create_relay_open(self, client):
        """Creating a relay without agent_names creates an open relay."""
        response = client.post("/relays", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["agent_names"] == []
        assert data["current_turn"] is None
        assert data["status"] == "open"
        assert data["join_code"] is not None

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
        assert "join_code" not in data

    def test_get_relay_not_found(self, client):
        response = client.get("/relays/nonexistent")
        assert response.status_code == 404

    def test_get_private_relay_denied(self, client, private_relay):
        relay_id = private_relay["relay_id"]
        response = client.get(f"/relays/{relay_id}?owner_id=wrong-owner")
        assert response.status_code == 401

    def test_get_private_relay_by_owner(self, client, private_relay):
        relay_id = private_relay["relay_id"]
        response = client.get(f"/relays/{relay_id}", headers={"Authorization": f"Bearer {private_relay['token']}"})
        assert response.status_code == 200


class TestSendMessage:
    def test_send_message_rejects_stale_relay_version(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        headers = {"Authorization": f"Bearer {sample_relay['token']}"}
        first = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "first", "expected_version": 0},
            headers=headers,
        )
        assert first.status_code == 200
        stale = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "stale", "expected_version": 0},
            headers=headers,
        )
        assert stale.status_code == 409

    def test_idempotent_retry_wins_over_stale_expected_version(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        headers = {"Authorization": f"Bearer {sample_relay['token']}"}
        payload = {
            "content": "retry-safe",
            "expected_version": 0,
            "idempotency_key": "retry-safe-1",
        }

        first = client.post(f"/relays/{relay_id}/messages", json=payload, headers=headers)
        retry = client.post(f"/relays/{relay_id}/messages", json=payload, headers=headers)

        assert first.status_code == 200
        assert retry.status_code == 200
        assert retry.json() == first.json()

    def test_send_message(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello!", "agent": "alice"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["next_turn"] == "bob"
        assert data["message_count"] == 1

    def test_send_message_wrong_turn(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        # Join as bob to get bob's token
        join_code = sample_relay["join_code"]
        join_resp = client.post(
            f"/relays/join/{join_code}",
            params={"agent_name": "bob"},
        )
        bob_token = join_resp.json()["token"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello!", "agent": "bob"},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert response.status_code == 400
        assert "Not turn" in response.json()["detail"]

    def test_send_message_with_bearer_token(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]
        # Use Bearer auth
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello via Bearer!", "agent": "alice"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    def test_send_message_without_token(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        # No auth header - should fail since relay has tokens
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello!", "agent": "alice"},
        )
        assert response.status_code == 401
        assert "Token required" in response.json()["detail"]

    def test_send_message_invalid_token(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello!", "agent": "alice"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401
        assert "Invalid token" in response.json()["detail"]

    def test_send_message_auto_agent(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]
        # No agent specified - should use agent from token (alice = creator)
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Auto agent"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["next_turn"] == "bob"

    def test_send_structured_message(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]
        response = client.post(
            f"/relays/{relay_id}/messages",
            json={
                "data": {"key": "value"},
                "type": "structured",
                "agent": "alice",
            },
            headers={"Authorization": f"Bearer {token}"},
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

    def test_public_reads_ignore_stale_bearer_token(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        headers = {"Authorization": "Bearer stale-token"}

        history = client.get(f"/relays/{relay_id}/history", headers=headers)
        listen = client.get(f"/relays/{relay_id}/listen", headers=headers)

        assert history.status_code == 200
        assert listen.status_code == 200
        assert listen.json()["your_turn"] is None


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


class TestRelayInstructions:
    def test_get_instructions_no_instructions(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        response = client.get(f"/relays/{relay_id}/instructions")
        assert response.status_code == 200
        data = response.json()
        assert data["relay_id"] == relay_id
        assert data["agent_names"] == ["alice", "bob"]
        assert data["current_turn"] == "alice"
        assert "all_instructions" not in data

    def test_get_instructions_with_instructions(self, client):
        response = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
            "agent_instructions": {
                "alice": "You are a helpful coder.",
                "bob": "You are a code reviewer.",
            },
        })
        assert response.status_code == 200
        relay_id = response.json()["relay_id"]

        resp = client.get(f"/relays/{relay_id}/instructions?agent=alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["all_instructions"]["alice"] == "You are a helpful coder."
        assert data["your_instructions"] == "You are a helpful coder."

    def test_get_instructions_unknown_agent(self, client):
        response = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
            "agent_instructions": {
                "alice": "You are a helpful coder.",
            },
        })
        assert response.status_code == 200
        relay_id = response.json()["relay_id"]

        resp = client.get(f"/relays/{relay_id}/instructions?agent=charlie")
        assert resp.status_code == 200
        data = resp.json()
        assert data["your_instructions"] == "No specific instructions."

    def test_get_instructions_not_found(self, client):
        response = client.get("/relays/nonexistent/instructions")
        assert response.status_code == 404

    def test_private_instructions_require_participant_token(self, client, private_relay):
        relay_id = private_relay["relay_id"]
        unauthorized = client.get(f"/relays/{relay_id}/instructions")
        assert unauthorized.status_code == 401

        authorized = client.get(
            f"/relays/{relay_id}/instructions",
            headers={"Authorization": f"Bearer {private_relay['token']}"},
        )
        assert authorized.status_code == 200
        assert authorized.json()["relay_id"] == relay_id


class TestWebhooks:
    def test_register_webhook(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]
        response = client.post(
            f"/relays/{relay_id}/webhooks",
            json={"url": "https://example.com/webhook", "agent": "alice"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://example.com/webhook"
        assert data["agent"] == "alice"
        assert "webhook_id" in data

    def test_register_webhook_without_token(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        response = client.post(
            f"/relays/{relay_id}/webhooks",
            json={"url": "https://example.com/webhook", "agent": "alice"},
        )
        assert response.status_code == 401

    def test_list_webhooks(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        token = sample_relay["token"]
        # Register a webhook first
        client.post(
            f"/relays/{relay_id}/webhooks",
            json={"url": "https://example.com/webhook", "agent": "alice"},
            headers={"Authorization": f"Bearer {token}"},
        )
        response = client.get(
            f"/relays/{relay_id}/webhooks",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["agent"] == "alice"
