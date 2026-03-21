"""
Tests for the join code cross-device discovery feature
"""
import pytest


class TestCreateRelayHasJoinCode:
    """Verify relays created via POST /relays include a join code."""

    def test_create_relay_has_join_code(self, client):
        """A newly created relay should contain a 6-char join_code."""
        resp = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "join_code" in data
        assert data["join_code"] is not None
        assert len(data["join_code"]) == 6
        assert data["join_code"].isalnum()
        assert data["join_code"] == data["join_code"].upper()


class TestJoinByCode:
    """Tests for POST /relays/join/{join_code}"""

    def test_join_by_code_success(self, client):
        """Joining with a valid code should return relay info."""
        # Create relay
        create_resp = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
        })
        assert create_resp.status_code == 200
        join_code = create_resp.json()["join_code"]
        relay_id = create_resp.json()["relay_id"]

        # Join by code
        resp = client.post(
            f"/relays/join/{join_code}",
            params={"agent_name": "charlie"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["relay_id"] == relay_id
        assert data["join_code"] == join_code
        assert "charlie" in data["agent_names"]

    def test_join_by_code_invalid(self, client):
        """Joining with an invalid code should return 404."""
        resp = client.post(
            "/relays/join/ZZZZZZ",
            params={"agent_name": "alice"},
        )
        assert resp.status_code == 404
        assert "Invalid join code" in resp.json()["detail"]

    def test_join_by_code_adds_agent(self, client):
        """Joining should add the agent to the relay's agent list."""
        create_resp = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
        })
        join_code = create_resp.json()["join_code"]

        # Join as charlie
        resp = client.post(
            f"/relays/join/{join_code}",
            params={"agent_name": "charlie"},
        )
        assert resp.status_code == 200
        assert resp.json()["agent_names"] == ["alice", "bob", "charlie"]

    def test_join_by_code_existing_agent_no_duplicate(self, client):
        """Joining as an already-present agent should not duplicate the name."""
        create_resp = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
        })
        join_code = create_resp.json()["join_code"]

        # Join as alice (already in relay)
        resp = client.post(
            f"/relays/join/{join_code}",
            params={"agent_name": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["agent_names"] == ["alice", "bob"]

    def test_join_code_case_insensitive(self, client):
        """Join codes should be case-insensitive."""
        create_resp = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
        })
        join_code = create_resp.json()["join_code"]
        relay_id = create_resp.json()["relay_id"]

        # Join using lowercase
        resp = client.post(
            f"/relays/join/{join_code.lower()}",
            params={"agent_name": "dave"},
        )
        assert resp.status_code == 200
        assert resp.json()["relay_id"] == relay_id


class TestGetRelayByCode:
    """Tests for GET /relays/code/{join_code}"""

    def test_get_relay_by_code(self, client):
        """Looking up a valid code should return relay info."""
        create_resp = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
        })
        join_code = create_resp.json()["join_code"]
        relay_id = create_resp.json()["relay_id"]

        resp = client.get(f"/relays/code/{join_code}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["relay_id"] == relay_id
        assert data["join_code"] == join_code
        assert data["agent_names"] == ["alice", "bob"]

    def test_get_relay_by_code_invalid(self, client):
        """Looking up an invalid code should return 404."""
        resp = client.get("/relays/code/XXXXXX")
        assert resp.status_code == 404

    def test_get_relay_by_code_case_insensitive(self, client):
        """Code lookup should be case-insensitive."""
        create_resp = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
        })
        join_code = create_resp.json()["join_code"]

        resp = client.get(f"/relays/code/{join_code.lower()}")
        assert resp.status_code == 200
        assert resp.json()["join_code"] == join_code
