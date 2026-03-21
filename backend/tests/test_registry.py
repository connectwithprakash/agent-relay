"""
Tests for the agent registry (cross-device discovery) endpoints
"""
import pytest


class TestRegisterAgent:
    """Tests for POST /agents/register"""

    def test_register_first_agent_waiting(self, client):
        """First agent to register in a namespace should get 'waiting' status."""
        resp = client.post(
            "/agents/register",
            params={"namespace": "test-project", "agent_name": "alice"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "waiting"
        assert data["agent_name"] == "alice"
        assert data["namespace"] == "test-project"
        assert data["waiting_count"] == 1
        assert "device_id" in data

    def test_register_second_agent_creates_relay(self, client):
        """When a second agent registers, a relay should be created automatically."""
        # First agent
        resp1 = client.post(
            "/agents/register",
            params={"namespace": "test-project", "agent_name": "alice"},
        )
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "waiting"

        # Second agent
        resp2 = client.post(
            "/agents/register",
            params={"namespace": "test-project", "agent_name": "bob"},
        )
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["status"] == "created"
        assert "relay_id" in data
        assert "api_key" in data
        assert set(data["agents"]) == {"alice", "bob"}
        assert data["namespace"] == "test-project"

    def test_register_joins_existing_relay(self, client):
        """A third agent registering should join the existing relay."""
        # Create relay with two agents
        client.post(
            "/agents/register",
            params={"namespace": "team-alpha", "agent_name": "alice"},
        )
        resp2 = client.post(
            "/agents/register",
            params={"namespace": "team-alpha", "agent_name": "bob"},
        )
        assert resp2.json()["status"] == "created"
        relay_id = resp2.json()["relay_id"]

        # Third agent joins
        resp3 = client.post(
            "/agents/register",
            params={"namespace": "team-alpha", "agent_name": "charlie"},
        )
        assert resp3.status_code == 200
        data = resp3.json()
        assert data["status"] == "joined"
        assert data["relay_id"] == relay_id
        assert "charlie" in data["agents"]

    def test_register_with_custom_device_id(self, client):
        """Registration should respect a provided device_id."""
        resp = client.post(
            "/agents/register",
            params={
                "namespace": "ns1",
                "agent_name": "alice",
                "device_id": "my-laptop-123",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["device_id"] == "my-laptop-123"

    def test_register_idempotent_with_relay(self, client):
        """Re-registering an agent that already has a relay should return 'joined'."""
        # Setup: two agents create a relay
        resp1 = client.post(
            "/agents/register",
            params={
                "namespace": "ns-idem",
                "agent_name": "alice",
                "device_id": "dev-1",
            },
        )
        client.post(
            "/agents/register",
            params={
                "namespace": "ns-idem",
                "agent_name": "bob",
                "device_id": "dev-2",
            },
        )

        # Re-register alice with same device_id
        resp3 = client.post(
            "/agents/register",
            params={
                "namespace": "ns-idem",
                "agent_name": "alice",
                "device_id": resp1.json()["device_id"],
            },
        )
        assert resp3.status_code == 200
        assert resp3.json()["status"] == "joined"

    def test_separate_namespaces_independent(self, client):
        """Agents in different namespaces should not see each other."""
        resp1 = client.post(
            "/agents/register",
            params={"namespace": "project-a", "agent_name": "alice"},
        )
        resp2 = client.post(
            "/agents/register",
            params={"namespace": "project-b", "agent_name": "bob"},
        )
        # Both should be waiting since they are in different namespaces
        assert resp1.json()["status"] == "waiting"
        assert resp2.json()["status"] == "waiting"


class TestDiscoverAgents:
    """Tests for GET /agents/discover/{namespace}"""

    def test_discover_namespace(self, client):
        """Should list all agents registered in a namespace."""
        client.post(
            "/agents/register",
            params={"namespace": "disc-ns", "agent_name": "alice", "device_id": "d1"},
        )
        client.post(
            "/agents/register",
            params={"namespace": "disc-ns", "agent_name": "bob", "device_id": "d2"},
        )

        resp = client.get("/agents/discover/disc-ns")
        assert resp.status_code == 200
        data = resp.json()
        assert data["namespace"] == "disc-ns"
        assert len(data["agents"]) == 2
        agent_names = {a["agent_name"] for a in data["agents"]}
        assert agent_names == {"alice", "bob"}
        # Both registered so relay was created
        assert data["relay_id"] is not None

    def test_discover_empty_namespace(self, client):
        """Discovering an empty namespace should return empty results."""
        resp = client.get("/agents/discover/empty-ns")
        assert resp.status_code == 200
        data = resp.json()
        assert data["namespace"] == "empty-ns"
        assert data["agents"] == []
        assert data["relay_id"] is None

    def test_discover_shows_status(self, client):
        """Agent status should be visible in discovery results."""
        client.post(
            "/agents/register",
            params={"namespace": "status-ns", "agent_name": "alice"},
        )
        resp = client.get("/agents/discover/status-ns")
        data = resp.json()
        assert data["agents"][0]["status"] == "waiting"
        assert data["agents"][0]["last_heartbeat"] is not None


class TestHeartbeat:
    """Tests for POST /agents/heartbeat"""

    def test_heartbeat(self, client):
        """Heartbeat should update the agent's last_heartbeat and status."""
        reg = client.post(
            "/agents/register",
            params={
                "namespace": "hb-ns",
                "agent_name": "alice",
                "device_id": "dev-hb",
            },
        )
        assert reg.status_code == 200

        resp = client.post(
            "/agents/heartbeat",
            params={
                "namespace": "hb-ns",
                "agent_name": "alice",
                "device_id": "dev-hb",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_heartbeat_unknown_agent(self, client):
        """Heartbeat for an unregistered agent should return 404."""
        resp = client.post(
            "/agents/heartbeat",
            params={
                "namespace": "hb-ns",
                "agent_name": "ghost",
                "device_id": "dev-x",
            },
        )
        assert resp.status_code == 404
