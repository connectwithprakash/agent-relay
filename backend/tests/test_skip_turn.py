"""
Tests for skip-turn endpoint with force-skip support for crash recovery.
"""
import pytest


class TestForceSkipTurn:
    """Test force-skip functionality for recovering from disconnected agents."""

    def test_force_skip_works_without_timeout(self, client):
        """Force skip should work even when no turn_timeout is configured."""
        # Create relay without turn_timeout
        resp = client.post("/relays", json={
            "agent_names": ["alice", "bob", "charlie"],
            "is_public": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        relay_id = data["relay_id"]
        token = data["token"]

        # Verify alice has the first turn
        state = client.get(f"/relays/{relay_id}").json()
        assert state["current_turn"] == "alice"
        assert state["version"] == 0

        # Force skip alice's turn (no timeout configured)
        resp = client.post(
            f"/relays/{relay_id}/skip-turn?force=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["status"] == "ok"
        assert result["skipped_agent"] == "alice"
        assert result["next_turn"] == "bob"
        assert result["forced"] is True
        state = client.get(f"/relays/{relay_id}").json()
        assert state["version"] == 1

    def test_skip_returns_who_was_skipped(self, client):
        """Skip response should identify the skipped agent and next agent."""
        resp = client.post("/relays", json={
            "agent_names": ["session1", "session2", "session3"],
            "is_public": True,
        })
        data = resp.json()
        relay_id = data["relay_id"]
        token = data["token"]

        # Force skip session1
        resp = client.post(
            f"/relays/{relay_id}/skip-turn?force=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        result = resp.json()
        assert result["skipped_agent"] == "session1"
        assert result["next_turn"] == "session2"

        # Force skip session2
        resp = client.post(
            f"/relays/{relay_id}/skip-turn?force=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        result = resp.json()
        assert result["skipped_agent"] == "session2"
        assert result["next_turn"] == "session3"

    def test_normal_skip_requires_timeout(self, client):
        """Without force=true, skip should fail if no turn_timeout is set."""
        resp = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
        })
        data = resp.json()
        relay_id = data["relay_id"]
        token = data["token"]

        # Try to skip without force and without timeout configured
        resp = client.post(
            f"/relays/{relay_id}/skip-turn",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "force=true" in resp.json()["detail"]

    def test_skip_advances_correctly(self, client):
        """Force skip should wrap around to the first agent after the last."""
        resp = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
        })
        data = resp.json()
        relay_id = data["relay_id"]
        token = data["token"]

        # Skip alice -> bob
        resp = client.post(
            f"/relays/{relay_id}/skip-turn?force=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json()["next_turn"] == "bob"

        # Skip bob -> alice (wrap around)
        resp = client.post(
            f"/relays/{relay_id}/skip-turn?force=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json()["next_turn"] == "alice"

    def test_force_skip_then_send_message(self, client):
        """After force-skipping, the next agent should be able to send."""
        resp = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
        })
        data = resp.json()
        relay_id = data["relay_id"]
        token = data["token"]  # This token is for alice (creator)

        # Force skip alice -> bob's turn now
        resp = client.post(
            f"/relays/{relay_id}/skip-turn?force=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json()["next_turn"] == "bob"

        # Verify relay state confirms it is bob's turn
        state = client.get(f"/relays/{relay_id}").json()
        assert state["current_turn"] == "bob"

        # Skip bob -> back to alice, then alice (with her token) can send
        resp = client.post(
            f"/relays/{relay_id}/skip-turn?force=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json()["next_turn"] == "alice"

        # Alice sends a message on her turn
        resp = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Back in action!", "agent": "alice"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["next_turn"] == "bob"

    def test_timeout_skip_returns_forced_false(self, client):
        """Timeout-based skip should set forced=false in response."""
        resp = client.post("/relays", json={
            "agent_names": ["alice", "bob"],
            "is_public": True,
            "turn_timeout": 1,
        })
        data = resp.json()
        relay_id = data["relay_id"]
        token = data["token"]

        # Wait for timeout to expire, then do a normal skip
        import time
        time.sleep(1.1)

        resp = client.post(
            f"/relays/{relay_id}/skip-turn",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["skipped_agent"] == "alice"
        assert result["next_turn"] == "bob"
        assert result["forced"] is False

    def test_multiple_force_skips_cycle_through_agents(self, client):
        """Multiple force skips should cycle through all agents in order."""
        resp = client.post("/relays", json={
            "agent_names": ["a", "b", "c", "d"],
            "is_public": True,
        })
        data = resp.json()
        relay_id = data["relay_id"]
        token = data["token"]

        expected = ["b", "c", "d", "a"]
        for expected_next in expected:
            resp = client.post(
                f"/relays/{relay_id}/skip-turn?force=true",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            assert resp.json()["next_turn"] == expected_next
