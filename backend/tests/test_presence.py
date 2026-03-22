"""Tests for agent presence/heartbeat system"""
from datetime import datetime, timezone, timedelta

from app.models import AgentPresence


class TestHeartbeat:
    """Test heartbeat endpoint updates last_seen"""

    def test_heartbeat_updates_last_seen(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]

        # Send heartbeat for alice
        resp = client.post(
            f"/relays/{relay_id}/heartbeat",
            params={"agent": "alice", "status": "active"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["agent"] == "alice"
        assert data["presence_status"] == "active"
        assert "last_seen" in data

        # Send another heartbeat with different status
        resp2 = client.post(
            f"/relays/{relay_id}/heartbeat",
            params={"agent": "alice", "status": "composing"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["presence_status"] == "composing"
        # last_seen should be updated (equal or later)
        assert data2["last_seen"] >= data["last_seen"]

    def test_heartbeat_invalid_agent(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        resp = client.post(
            f"/relays/{relay_id}/heartbeat",
            params={"agent": "unknown_agent", "status": "active"},
        )
        assert resp.status_code == 400
        assert "not in this relay" in resp.json()["detail"]

    def test_heartbeat_invalid_status(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        resp = client.post(
            f"/relays/{relay_id}/heartbeat",
            params={"agent": "alice", "status": "invalid"},
        )
        assert resp.status_code == 400
        assert "Invalid status" in resp.json()["detail"]

    def test_heartbeat_relay_not_found(self, client):
        resp = client.post(
            "/relays/nonexistent/heartbeat",
            params={"agent": "alice", "status": "active"},
        )
        assert resp.status_code == 404


class TestPresenceInRelayStatus:
    """Test that relay status includes presence info"""

    def test_presence_in_relay_status(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]

        # Send heartbeats for both agents
        client.post(
            f"/relays/{relay_id}/heartbeat",
            params={"agent": "alice", "status": "active"},
        )
        client.post(
            f"/relays/{relay_id}/heartbeat",
            params={"agent": "bob", "status": "composing"},
        )

        # Check relay status
        resp = client.get(f"/relays/{relay_id}")
        assert resp.status_code == 200
        data = resp.json()

        assert "agents_presence" in data
        presence = data["agents_presence"]
        assert len(presence) == 2

        alice_p = next(p for p in presence if p["agent"] == "alice")
        bob_p = next(p for p in presence if p["agent"] == "bob")

        assert alice_p["status"] == "active"
        assert bob_p["status"] == "composing"
        assert "ago" in alice_p["last_seen"] or alice_p["last_seen"] == "never"
        assert "ago" in bob_p["last_seen"] or bob_p["last_seen"] == "never"

    def test_presence_unknown_for_no_heartbeat(self, client, sample_relay):
        """Agents that never sent a heartbeat should show as unknown"""
        relay_id = sample_relay["relay_id"]

        resp = client.get(f"/relays/{relay_id}")
        assert resp.status_code == 200
        data = resp.json()

        presence = data["agents_presence"]
        assert len(presence) == 2
        for p in presence:
            assert p["status"] == "unknown"
            assert p["last_seen"] == "never"


class TestDisconnectedAfter60s:
    """Test that agents are marked disconnected after 120s without heartbeat"""

    def test_disconnected_after_120s(self, client, sample_relay, db_session):
        relay_id = sample_relay["relay_id"]

        # Send heartbeat for alice
        client.post(
            f"/relays/{relay_id}/heartbeat",
            params={"agent": "alice", "status": "active"},
        )

        # Manually backdate alice's last_seen to > 120s ago
        presence = db_session.query(AgentPresence).filter(
            AgentPresence.relay_id == relay_id,
            AgentPresence.agent_name == "alice",
        ).first()
        assert presence is not None
        presence.last_seen = datetime.now(timezone.utc) - timedelta(seconds=150)
        db_session.commit()

        # Check relay status
        resp = client.get(f"/relays/{relay_id}")
        assert resp.status_code == 200
        data = resp.json()

        alice_p = next(p for p in data["agents_presence"] if p["agent"] == "alice")
        assert alice_p["status"] == "disconnected"


class TestAutoSkipDisconnectedAgent:
    """Test that disconnected agents are auto-skipped when holding the turn"""

    def test_auto_skip_disconnected_agent(self, client, sample_relay, db_session):
        relay_id = sample_relay["relay_id"]

        # Send heartbeat for alice (who has the first turn)
        client.post(
            f"/relays/{relay_id}/heartbeat",
            params={"agent": "alice", "status": "active"},
        )

        # Verify alice has the turn
        resp = client.get(f"/relays/{relay_id}")
        assert resp.json()["current_turn"] == "alice"

        # Backdate alice's last_seen to > 2 minutes ago (auto-skip threshold)
        presence = db_session.query(AgentPresence).filter(
            AgentPresence.relay_id == relay_id,
            AgentPresence.agent_name == "alice",
        ).first()
        presence.last_seen = datetime.now(timezone.utc) - timedelta(seconds=150)
        db_session.commit()

        # Check relay status - should auto-skip alice's turn
        resp = client.get(f"/relays/{relay_id}")
        assert resp.status_code == 200
        data = resp.json()

        # Turn should have advanced to bob
        assert data["current_turn"] == "bob"

    def test_no_skip_when_agent_recently_seen(self, client, sample_relay, db_session):
        """Agent with recent heartbeat should NOT be skipped"""
        relay_id = sample_relay["relay_id"]

        # Send fresh heartbeat for alice
        client.post(
            f"/relays/{relay_id}/heartbeat",
            params={"agent": "alice", "status": "active"},
        )

        # Check relay status - alice should still have the turn
        resp = client.get(f"/relays/{relay_id}")
        assert resp.status_code == 200
        assert resp.json()["current_turn"] == "alice"

    def test_no_skip_when_no_heartbeat_sent(self, client, sample_relay):
        """Agent that never sent heartbeat should NOT be skipped (no presence record)"""
        relay_id = sample_relay["relay_id"]

        resp = client.get(f"/relays/{relay_id}")
        assert resp.status_code == 200
        # alice still has turn since no presence record exists at all
        assert resp.json()["current_turn"] == "alice"
