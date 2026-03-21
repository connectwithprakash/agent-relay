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

    def test_register_with_capabilities(self, client):
        """Registration should accept and store description and capabilities."""
        resp = client.post(
            "/agents/register",
            params={
                "namespace": "cap-ns",
                "agent_name": "reviewer",
                "description": "Reviews Python code for security issues",
                "capabilities": "code_review,security,python",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "waiting"
        assert data["agent_name"] == "reviewer"

        # Verify via profile endpoint
        profile_resp = client.get("/agents/cap-ns/reviewer")
        assert profile_resp.status_code == 200
        profile = profile_resp.json()
        assert profile["description"] == "Reviews Python code for security issues"
        assert profile["capabilities"] == ["code_review", "security", "python"]


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

    def test_discover_includes_capabilities(self, client):
        """Discovery results should include description and capabilities."""
        client.post(
            "/agents/register",
            params={
                "namespace": "disc-caps",
                "agent_name": "tester",
                "device_id": "d1",
                "description": "Runs integration tests",
                "capabilities": "testing,integration",
            },
        )
        client.post(
            "/agents/register",
            params={
                "namespace": "disc-caps",
                "agent_name": "deployer",
                "device_id": "d2",
                "description": "Deploys to production",
                "capabilities": "deployment,docker",
            },
        )

        resp = client.get("/agents/discover/disc-caps")
        assert resp.status_code == 200
        data = resp.json()
        agents_by_name = {a["agent_name"]: a for a in data["agents"]}

        assert agents_by_name["tester"]["description"] == "Runs integration tests"
        assert agents_by_name["tester"]["capabilities"] == ["testing", "integration"]
        assert agents_by_name["deployer"]["description"] == "Deploys to production"
        assert agents_by_name["deployer"]["capabilities"] == ["deployment", "docker"]


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


class TestAgentProfile:
    """Tests for GET /agents/{namespace}/{agent_name}"""

    def test_get_agent_profile(self, client):
        """Should return full agent profile with capabilities."""
        client.post(
            "/agents/register",
            params={
                "namespace": "prof-ns",
                "agent_name": "coder",
                "description": "Writes Python code",
                "capabilities": "coding,python,refactoring",
            },
        )

        resp = client.get("/agents/prof-ns/coder")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "coder"
        assert data["namespace"] == "prof-ns"
        assert data["description"] == "Writes Python code"
        assert data["capabilities"] == ["coding", "python", "refactoring"]
        assert data["status"] == "waiting"
        assert data["last_heartbeat"] is not None

    def test_get_agent_profile_not_found(self, client):
        """Requesting a non-existent agent profile should return 404."""
        resp = client.get("/agents/no-ns/ghost")
        assert resp.status_code == 404

    def test_get_agent_profile_no_capabilities(self, client):
        """Agent registered without capabilities should have null fields."""
        client.post(
            "/agents/register",
            params={"namespace": "plain-ns", "agent_name": "basic"},
        )

        resp = client.get("/agents/plain-ns/basic")
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] is None
        assert data["capabilities"] is None


class TestSearchAgents:
    """Tests for GET /agents/search"""

    def test_search_by_capability(self, client):
        """Should find agents that have the requested capability."""
        # Register agents with different capabilities
        client.post(
            "/agents/register",
            params={
                "namespace": "search-ns",
                "agent_name": "reviewer",
                "device_id": "d1",
                "description": "Code reviewer",
                "capabilities": "code_review,python",
            },
        )
        client.post(
            "/agents/register",
            params={
                "namespace": "search-ns",
                "agent_name": "tester",
                "device_id": "d2",
                "description": "Test runner",
                "capabilities": "testing,python",
            },
        )
        # Both agents are now "ready" (relay created with 2 agents)

        # Search for code_review capability
        resp = client.get("/agents/search", params={"capability": "code_review"})
        assert resp.status_code == 200
        data = resp.json()
        agent_names = [a["agent_name"] for a in data["agents"]]
        assert "reviewer" in agent_names
        assert "tester" not in agent_names

    def test_search_by_capability_python(self, client):
        """Should find all agents with a shared capability."""
        client.post(
            "/agents/register",
            params={
                "namespace": "search-ns2",
                "agent_name": "reviewer",
                "device_id": "d1",
                "capabilities": "code_review,python",
            },
        )
        client.post(
            "/agents/register",
            params={
                "namespace": "search-ns2",
                "agent_name": "tester",
                "device_id": "d2",
                "capabilities": "testing,python",
            },
        )

        resp = client.get("/agents/search", params={"capability": "python"})
        assert resp.status_code == 200
        data = resp.json()
        agent_names = {a["agent_name"] for a in data["agents"]}
        assert agent_names == {"reviewer", "tester"}

    def test_search_with_namespace_filter(self, client):
        """Should limit search to specified namespace."""
        client.post(
            "/agents/register",
            params={
                "namespace": "ns-a",
                "agent_name": "alice",
                "device_id": "d1",
                "capabilities": "python",
            },
        )
        client.post(
            "/agents/register",
            params={
                "namespace": "ns-a",
                "agent_name": "bob",
                "device_id": "d2",
                "capabilities": "python",
            },
        )
        client.post(
            "/agents/register",
            params={
                "namespace": "ns-b",
                "agent_name": "charlie",
                "device_id": "d3",
                "capabilities": "python",
            },
        )
        client.post(
            "/agents/register",
            params={
                "namespace": "ns-b",
                "agent_name": "dave",
                "device_id": "d4",
                "capabilities": "python",
            },
        )

        resp = client.get(
            "/agents/search",
            params={"capability": "python", "namespace": "ns-a"},
        )
        assert resp.status_code == 200
        data = resp.json()
        agent_names = {a["agent_name"] for a in data["agents"]}
        assert agent_names == {"alice", "bob"}

    def test_search_no_results(self, client):
        """Search with no matching capability should return empty list."""
        resp = client.get("/agents/search", params={"capability": "nonexistent"})
        assert resp.status_code == 200
        assert resp.json()["agents"] == []

    def test_search_without_capability(self, client):
        """Search without capability filter should return all ready agents."""
        client.post(
            "/agents/register",
            params={
                "namespace": "all-ns",
                "agent_name": "a1",
                "device_id": "d1",
            },
        )
        client.post(
            "/agents/register",
            params={
                "namespace": "all-ns",
                "agent_name": "a2",
                "device_id": "d2",
            },
        )

        resp = client.get("/agents/search")
        assert resp.status_code == 200
        data = resp.json()
        agent_names = {a["agent_name"] for a in data["agents"]}
        assert "a1" in agent_names
        assert "a2" in agent_names
