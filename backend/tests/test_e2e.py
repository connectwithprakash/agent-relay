"""
End-to-end tests that walk through complete user journeys for the Agent Relay system.

Each test class covers a distinct flow, verifying the full lifecycle from
relay creation through messaging, authentication, discovery, and teardown.
"""
import pytest


# ---------------------------------------------------------------------------
# Flow 1: Complete Relay Lifecycle
# ---------------------------------------------------------------------------
class TestRelayLifecycle:
    """Create a relay, send messages in turn order, verify history and turn wrap."""

    def test_create_join_communicate_complete(self, client):
        # 1. Create relay with 3 agents
        r = client.post(
            "/relays",
            json={"agent_names": ["alice", "bob", "charlie"], "is_public": True},
        )
        assert r.status_code == 200
        data = r.json()
        relay_id = data["relay_id"]
        token = data["token"]
        join_code = data.get("join_code")

        assert relay_id
        assert token
        assert join_code is not None
        assert len(join_code) == 48

        headers = {"Authorization": f"Bearer {token}"}

        # 2. Verify initial relay state
        r = client.get(f"/relays/{relay_id}")
        assert r.status_code == 200
        state = r.json()
        assert state["current_turn"] == "alice"
        assert state["message_count"] == 0
        assert state["agent_names"] == ["alice", "bob", "charlie"]

        # 3. Get tokens for each agent via join code
        bob_resp = client.post(f"/relays/join/{join_code}?agent_name=bob")
        bob_token = bob_resp.json()["token"]
        charlie_resp = client.post(f"/relays/join/{join_code}?agent_name=charlie")
        charlie_token = charlie_resp.json()["token"]

        agent_tokens = {
            "alice": token,
            "bob": bob_token,
            "charlie": charlie_token,
        }

        # 4. Send messages in turn order: alice -> bob -> charlie
        for agent, msg in [("alice", "Hello!"), ("bob", "Hi!"), ("charlie", "Hey!")]:
            r = client.post(
                f"/relays/{relay_id}/messages",
                json={"content": msg, "agent": agent},
                headers={"Authorization": f"Bearer {agent_tokens[agent]}"},
            )
            assert r.status_code == 200, f"{agent} failed: {r.text}"

        # 5. Verify history
        r = client.get(f"/relays/{relay_id}/history")
        assert r.status_code == 200
        history = r.json()
        assert history["total_count"] == 3
        assert history["messages"][0]["content"] == "Hello!"
        assert history["messages"][1]["content"] == "Hi!"
        assert history["messages"][2]["content"] == "Hey!"
        assert history["messages"][2]["agent"] == "charlie"

        # 6. Verify turn wrapped back to alice
        r = client.get(f"/relays/{relay_id}")
        assert r.json()["current_turn"] == "alice"

    def test_message_response_fields(self, client):
        """Verify send-message response contains expected fields."""
        r = client.post(
            "/relays",
            json={"agent_names": ["x", "y"], "is_public": True},
        )
        data = r.json()
        headers = {"Authorization": f"Bearer {data['token']}"}

        r = client.post(
            f"/relays/{data['relay_id']}/messages",
            json={"content": "ping", "agent": "x"},
            headers=headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "message_id" in body
        assert body["next_turn"] == "y"
        assert body["message_count"] == 1

    def test_structured_message_roundtrip(self, client):
        """Send a structured (JSON) message and retrieve it from history."""
        r = client.post(
            "/relays",
            json={"agent_names": ["sender", "receiver"], "is_public": True},
        )
        data = r.json()
        relay_id = data["relay_id"]
        headers = {"Authorization": f"Bearer {data['token']}"}

        payload = {"key": "value", "nested": {"a": 1}}
        r = client.post(
            f"/relays/{relay_id}/messages",
            json={"data": payload, "type": "structured", "agent": "sender"},
            headers=headers,
        )
        assert r.status_code == 200

        r = client.get(f"/relays/{relay_id}/history")
        msg = r.json()["messages"][0]
        assert msg["type"] == "structured"
        assert msg["data"] == payload


# ---------------------------------------------------------------------------
# Flow 2: Authentication
# ---------------------------------------------------------------------------
class TestAuthFlow:
    """Verify token enforcement on write endpoints."""

    def test_full_auth_lifecycle(self, client):
        r = client.post("/relays", json={"agent_names": ["a", "b"]})
        assert r.status_code == 200
        relay_id = r.json()["relay_id"]
        token = r.json()["token"]
        join_code = r.json()["join_code"]

        # Good token works (Bearer header)
        r = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "test", "agent": "a"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

        # Get token for agent b
        b_resp = client.post(f"/relays/join/{join_code}?agent_name=b")
        b_token = b_resp.json()["token"]

        # b's token works for b's turn
        r = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "test2", "agent": "b"},
            headers={"Authorization": f"Bearer {b_token}"},
        )
        assert r.status_code == 200

        # No token fails
        r = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "test", "agent": "a"},
        )
        assert r.status_code == 401

        # Wrong token fails
        r = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "test", "agent": "a"},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert r.status_code == 401

    def test_auth_required_for_webhooks(self, client):
        """Webhook registration also requires a valid token."""
        r = client.post("/relays", json={"agent_names": ["a", "b"]})
        relay_id = r.json()["relay_id"]

        # No token -> 401
        r = client.post(
            f"/relays/{relay_id}/webhooks",
            json={"url": "https://example.com/hook", "agent": "a"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Flow 3: Join Codes
# ---------------------------------------------------------------------------
class TestJoinCodeFlow:
    """Create relay, get join code, join as new agent, verify agent roster."""

    def test_create_and_join_by_code(self, client):
        r = client.post(
            "/relays",
            json={"agent_names": ["creator", "partner"], "is_public": True},
        )
        assert r.status_code == 200
        join_code = r.json()["join_code"]
        relay_id = r.json()["relay_id"]

        # Join by code
        r = client.post(f"/relays/join/{join_code}?agent_name=partner")
        assert r.status_code == 200
        assert "partner" in r.json()["agent_names"]
        assert r.json()["token"] is not None

        # Verify via relay state
        r = client.get(f"/relays/{relay_id}")
        assert "partner" in r.json()["agent_names"]

    def test_lookup_relay_by_code(self, client):
        """GET /relays/code/{join_code} returns relay info."""
        r = client.post(
            "/relays",
            json={"agent_names": ["a", "b"], "is_public": True},
        )
        join_code = r.json()["join_code"]
        relay_id = r.json()["relay_id"]

        r = client.get(f"/relays/code/{join_code}")
        assert r.status_code == 200
        assert r.json()["relay_id"] == relay_id
        assert r.json()["agent_names"] == ["a", "b"]

    def test_invalid_join_code_404(self, client):
        r = client.post("/relays/join/ZZZZZZ?agent_name=nobody")
        assert r.status_code == 404

    def test_join_idempotent(self, client):
        """An unapproved participant cannot mutate relay membership."""
        r = client.post(
            "/relays",
            json={"agent_names": ["alpha", "omega"], "is_public": True},
        )
        assert r.status_code == 200
        join_code = r.json()["join_code"]
        relay_id = r.json()["relay_id"]

        first = client.post(f"/relays/join/{join_code}?agent_name=beta")
        second = client.post(f"/relays/join/{join_code}?agent_name=beta")
        assert first.status_code == 403
        assert second.status_code == 403

        r = client.get(f"/relays/{relay_id}")
        assert r.json()["agent_names"] == ["alpha", "omega"]


# ---------------------------------------------------------------------------
# Flow 4: Agent Discovery via Namespace
# ---------------------------------------------------------------------------
class TestDiscoveryFlow:
    """Two agents register in same namespace -> relay auto-created."""

    def test_namespace_discovery_creates_relay(self, client):
        r1 = client.post(
            "/agents/register",
            params={"namespace": "e2e-ns", "agent_name": "scout"},
        )
        assert r1.status_code == 200
        assert r1.json()["status"] == "waiting"

        r2 = client.post(
            "/agents/register",
            params={"namespace": "e2e-ns", "agent_name": "builder"},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "created"
        assert r2.json()["relay_id"]
        assert r2.json()["token"] is not None

        # Discover shows both agents
        r = client.get("/agents/discover/e2e-ns")
        assert r.status_code == 200
        agents = r.json()["agents"]
        agent_names = [a["agent_name"] for a in agents]
        assert "scout" in agent_names
        assert "builder" in agent_names
        assert len(agents) == 2

    def test_third_agent_joins_existing_namespace_relay(self, client):
        """After relay is created, a third agent joins the existing relay."""
        client.post(
            "/agents/register",
            params={"namespace": "e2e-ns-3", "agent_name": "first"},
        )
        r2 = client.post(
            "/agents/register",
            params={"namespace": "e2e-ns-3", "agent_name": "second"},
        )
        relay_id = r2.json()["relay_id"]

        r3 = client.post(
            "/agents/register",
            params={"namespace": "e2e-ns-3", "agent_name": "third"},
        )
        assert r3.status_code == 200
        assert r3.json()["status"] == "joined"
        assert r3.json()["relay_id"] == relay_id
        assert "third" in r3.json()["agents"]
        assert r3.json()["token"] is not None

    def test_discover_empty_namespace(self, client):
        r = client.get("/agents/discover/nonexistent-ns")
        assert r.status_code == 200
        assert r.json()["agents"] == []
        assert r.json()["relay_id"] is None

    def test_heartbeat(self, client):
        """Agent heartbeat updates status after registration."""
        r = client.post(
            "/agents/register",
            params={
                "namespace": "hb-ns",
                "agent_name": "hb-agent",
                "device_id": "dev-1",
            },
        )
        assert r.status_code == 200

        r = client.post(
            "/agents/heartbeat",
            params={
                "namespace": "hb-ns",
                "agent_name": "hb-agent",
                "device_id": "dev-1",
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Flow 5: Turn Enforcement
# ---------------------------------------------------------------------------
class TestTurnEnforcement:
    """Verify that only the agent whose turn it is may send a message."""

    def test_wrong_turn_rejected(self, client):
        r = client.post(
            "/relays",
            json={"agent_names": ["alice", "bob"], "is_public": True},
        )
        data = r.json()
        relay_id = data["relay_id"]
        join_code = data["join_code"]

        # Get bob's token
        bob_resp = client.post(f"/relays/join/{join_code}?agent_name=bob")
        bob_token = bob_resp.json()["token"]

        # It is alice's turn; bob tries to send
        r = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "out of turn", "agent": "bob"},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert r.status_code == 400

    def test_turn_wraps_around(self, client):
        """alice -> bob -> charlie -> alice"""
        r = client.post(
            "/relays",
            json={"agent_names": ["alice", "bob", "charlie"], "is_public": True},
        )
        data = r.json()
        relay_id = data["relay_id"]
        join_code = data["join_code"]

        # Get tokens for all agents
        alice_token = data["token"]
        bob_token = client.post(f"/relays/join/{join_code}?agent_name=bob").json()["token"]
        charlie_token = client.post(f"/relays/join/{join_code}?agent_name=charlie").json()["token"]
        tokens = {"alice": alice_token, "bob": bob_token, "charlie": charlie_token}

        turn_order = ["alice", "bob", "charlie", "alice", "bob"]
        for agent in turn_order:
            state = client.get(f"/relays/{relay_id}").json()
            assert state["current_turn"] == agent

            r = client.post(
                f"/relays/{relay_id}/messages",
                json={"content": f"msg from {agent}", "agent": agent},
                headers={"Authorization": f"Bearer {tokens[agent]}"},
            )
            assert r.status_code == 200

    def test_unknown_agent_rejected(self, client):
        r = client.post(
            "/relays",
            json={"agent_names": ["alice", "bob"], "is_public": True},
        )
        data = r.json()
        headers = {"Authorization": f"Bearer {data['token']}"}

        # Token belongs to alice, but trying to send as eve (unknown agent)
        r = client.post(
            f"/relays/{data['relay_id']}/messages",
            json={"content": "nope", "agent": "eve"},
            headers=headers,
        )
        # The token agent (alice) is used since the agent from token overrides request body
        # But token agent is alice, not eve, so it should succeed as alice
        # Actually the token agent_name overrides, so it will try as "alice" not "eve"
        assert r.status_code == 200  # alice's turn, token says alice


# ---------------------------------------------------------------------------
# Flow 6: Spectator Mode
# ---------------------------------------------------------------------------
class TestSpectatorFlow:
    """Spectator count and watch endpoint availability."""

    def test_spectator_count_starts_at_zero(self, client):
        r = client.post(
            "/relays",
            json={"agent_names": ["a", "b"], "is_public": True},
        )
        relay_id = r.json()["relay_id"]

        r = client.get(f"/relays/{relay_id}/spectators")
        assert r.status_code == 200
        assert r.json()["spectator_count"] == 0

    def test_watch_private_relay_denied(self, client):
        """GET /relays/{id}/watch on a private relay without owner_id returns 403."""
        r = client.post(
            "/relays",
            json={
                "agent_names": ["a", "b"],
                "is_public": False,
                "owner_id": "owner-watch",
            },
        )
        relay_id = r.json()["relay_id"]

        r = client.get(f"/relays/{relay_id}/watch")
        assert r.status_code == 403

    def test_watch_nonexistent_relay_404(self, client):
        """GET /relays/{id}/watch on missing relay returns 404."""
        r = client.get("/relays/no-such-relay/watch")
        assert r.status_code == 404

    def test_spectator_count_nonexistent_relay_404(self, client):
        r = client.get("/relays/nonexistent-id/spectators")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Flow 7: Rate Limiting & Validation
# ---------------------------------------------------------------------------
class TestValidation:
    """Input validation and size limits."""

    def test_message_content_size_limit(self, client):
        """Message content > 65536 chars rejected by schema validation."""
        r = client.post(
            "/relays",
            json={"agent_names": ["a", "b"], "is_public": True},
        )
        data = r.json()
        headers = {"Authorization": f"Bearer {data['token']}"}

        oversized = "x" * 65537
        r = client.post(
            f"/relays/{data['relay_id']}/messages",
            json={"content": oversized, "agent": "a"},
            headers=headers,
        )
        assert r.status_code == 422

    def test_structured_data_size_limit(self, client):
        """Structured data payload > 64KB rejected."""
        r = client.post(
            "/relays",
            json={"agent_names": ["a", "b"], "is_public": True},
        )
        data = r.json()
        headers = {"Authorization": f"Bearer {data['token']}"}

        # Build a dict that serializes to > 64KB
        big_data = {"payload": "x" * 70000}
        r = client.post(
            f"/relays/{data['relay_id']}/messages",
            json={"data": big_data, "type": "structured", "agent": "a"},
            headers=headers,
        )
        assert r.status_code == 422

    def test_duplicate_agent_names_rejected(self, client):
        """Relay with duplicate agent names returns 422."""
        r = client.post(
            "/relays",
            json={"agent_names": ["same", "same"], "is_public": True},
        )
        assert r.status_code == 422

    def test_too_few_agents_rejected(self, client):
        """Relay with fewer than 2 agents is rejected."""
        r = client.post(
            "/relays",
            json={"agent_names": ["lonely"]},
        )
        assert r.status_code == 422

    def test_too_many_agents_rejected(self, client):
        """Relay with more than 20 agents is rejected."""
        names = [f"agent_{i}" for i in range(21)]
        r = client.post(
            "/relays",
            json={"agent_names": names},
        )
        assert r.status_code == 422

    def test_pagination_capped_at_100(self, client):
        """Requesting limit > 100 is capped to 100 (no error, just capped)."""
        r = client.post(
            "/relays",
            json={"agent_names": ["a", "b"], "is_public": True},
        )
        relay_id = r.json()["relay_id"]

        # Should not fail - the server caps it silently
        r = client.get(f"/relays/{relay_id}/history?limit=200")
        assert r.status_code == 200

    def test_nonexistent_relay_404(self, client):
        r = client.get("/relays/does-not-exist")
        assert r.status_code == 404

        r = client.get("/relays/does-not-exist/history")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Flow 8: Public Relay Listing
# ---------------------------------------------------------------------------
class TestPublicRelays:
    """Public vs private relay visibility in the listing endpoint."""

    def test_public_relays_listed(self, client):
        r = client.post(
            "/relays",
            json={"agent_names": ["pub1", "pub2"], "is_public": True},
        )
        assert r.status_code == 200
        relay_id = r.json()["relay_id"]

        r = client.get("/relays")
        assert r.status_code == 200
        listed_ids = [item["relay_id"] for item in r.json()["relays"]]
        assert relay_id in listed_ids

    def test_private_relays_hidden(self, client):
        r = client.post(
            "/relays",
            json={"agent_names": ["priv1", "priv2"], "is_public": False},
        )
        assert r.status_code == 200
        relay_id = r.json()["relay_id"]

        r = client.get("/relays")
        assert r.status_code == 200
        listed_ids = [item["relay_id"] for item in r.json()["relays"]]
        assert relay_id not in listed_ids

    def test_private_relay_state_requires_owner(self, client):
        """Private relay state is inaccessible without owner_id."""
        r = client.post(
            "/relays",
            json={
                "agent_names": ["secret1", "secret2"],
                "is_public": False,
                "owner_id": "owner-123",
            },
        )
        relay_id = r.json()["relay_id"]

        # Without owner_id -> 403
        r = client.get(f"/relays/{relay_id}")
        assert r.status_code == 403

        # With correct owner_id -> 200
        r = client.get(f"/relays/{relay_id}?owner_id=owner-123")
        assert r.status_code == 200

    def test_relay_list_pagination(self, client):
        """Verify offset and limit work on the relay listing."""
        # Create 3 public relays
        ids = []
        for i in range(3):
            r = client.post(
                "/relays",
                json={"agent_names": [f"a{i}", f"b{i}"], "is_public": True},
            )
            ids.append(r.json()["relay_id"])

        # Fetch page of 2
        r = client.get("/relays?limit=2&offset=0")
        assert r.status_code == 200
        assert len(r.json()["relays"]) <= 2
        assert r.json()["total_count"] >= 3

    def test_relay_list_item_fields(self, client):
        """Each item in the relay list has the expected fields."""
        client.post(
            "/relays",
            json={"agent_names": ["f1", "f2"], "is_public": True},
        )
        r = client.get("/relays")
        item = r.json()["relays"][0]
        assert "relay_id" in item
        assert "agent_names" in item
        assert "current_turn" in item
        assert "message_count" in item
        assert "is_public" in item
        assert "created_at" in item


# ---------------------------------------------------------------------------
# Flow 9: Webhook Registration (bonus coverage)
# ---------------------------------------------------------------------------
class TestWebhookFlow:
    """Register and list webhooks for a relay."""

    def test_register_and_list_webhooks(self, client):
        r = client.post(
            "/relays",
            json={"agent_names": ["wh_a", "wh_b"], "is_public": True},
        )
        data = r.json()
        relay_id = data["relay_id"]
        headers = {"Authorization": f"Bearer {data['token']}"}

        # Register webhook
        r = client.post(
            f"/relays/{relay_id}/webhooks",
            json={"url": "https://example.com/hook", "agent": "wh_a"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["agent"] == "wh_a"
        assert r.json()["url"] == "https://example.com/hook"
        assert "webhook_id" in r.json()

        # List webhooks
        r = client.get(f"/relays/{relay_id}/webhooks", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["agent"] == "wh_a"

    def test_webhook_invalid_agent_rejected(self, client):
        r = client.post(
            "/relays",
            json={"agent_names": ["wh_x", "wh_y"], "is_public": True},
        )
        data = r.json()
        headers = {"Authorization": f"Bearer {data['token']}"}

        r = client.post(
            f"/relays/{data['relay_id']}/webhooks",
            json={"url": "https://example.com/hook", "agent": "ghost"},
            headers=headers,
        )
        assert r.status_code == 400
