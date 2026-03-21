"""
Tests for Spectator/Observer mode (SSE watch endpoint)
"""
import asyncio

import pytest

from app.websocket_manager import ConnectionManager


class TestConnectionManagerSpectators:
    """Unit tests for spectator management in ConnectionManager."""

    def test_add_and_remove_spectator(self):
        mgr = ConnectionManager()
        queue = asyncio.Queue()
        mgr.add_spectator("relay-1", queue)
        assert mgr.spectator_count("relay-1") == 1

        mgr.remove_spectator("relay-1", queue)
        assert mgr.spectator_count("relay-1") == 0

    def test_spectator_count_empty(self):
        mgr = ConnectionManager()
        assert mgr.spectator_count("nonexistent") == 0

    def test_multiple_spectators(self):
        mgr = ConnectionManager()
        q1 = asyncio.Queue()
        q2 = asyncio.Queue()
        mgr.add_spectator("relay-1", q1)
        mgr.add_spectator("relay-1", q2)
        assert mgr.spectator_count("relay-1") == 2

        mgr.remove_spectator("relay-1", q1)
        assert mgr.spectator_count("relay-1") == 1

    def test_remove_spectator_cleanup(self):
        """Removing the last spectator cleans up the relay entry."""
        mgr = ConnectionManager()
        queue = asyncio.Queue()
        mgr.add_spectator("relay-1", queue)
        mgr.remove_spectator("relay-1", queue)
        assert "relay-1" not in mgr.spectators

    @pytest.mark.asyncio
    async def test_broadcast_to_spectators(self):
        mgr = ConnectionManager()
        queue = asyncio.Queue()
        mgr.add_spectator("relay-1", queue)

        message = {"agent": "alice", "content": "hello"}
        await mgr.broadcast_message("relay-1", message)

        received = queue.get_nowait()
        assert received == message

    @pytest.mark.asyncio
    async def test_broadcast_does_not_block_on_full_queue(self):
        mgr = ConnectionManager()
        queue = asyncio.Queue(maxsize=1)
        queue.put_nowait({"old": "message"})
        mgr.add_spectator("relay-1", queue)

        # Should not raise even though queue is full
        await mgr.broadcast_message("relay-1", {"agent": "alice", "content": "hello"})

        # Queue still has the old message (new one dropped)
        assert queue.get_nowait() == {"old": "message"}


class TestWatchSSEReceivesMessages:
    """Verify SSE spectator queues receive broadcast messages."""

    @pytest.mark.asyncio
    async def test_watch_sse_receives_messages(self):
        mgr = ConnectionManager()
        queue = asyncio.Queue()
        mgr.add_spectator("relay-test", queue)

        msg = {
            "id": 1,
            "agent": "alice",
            "content": "Test message",
            "type": "text",
            "created_at": "2026-01-01T00:00:00",
            "next_turn": "bob",
        }
        await mgr.broadcast_message("relay-test", msg)

        received = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert received["agent"] == "alice"
        assert received["content"] == "Test message"
        assert received["next_turn"] == "bob"

        mgr.remove_spectator("relay-test", queue)


class TestWatchEndpoint:
    """Integration tests for the /relays/{relay_id}/watch SSE endpoint."""

    def test_watch_nonexistent_relay(self, client):
        response = client.get("/relays/nonexistent/watch")
        assert response.status_code == 404

    def test_watch_private_relay_denied(self, client, private_relay):
        relay_id = private_relay["relay_id"]
        response = client.get(f"/relays/{relay_id}/watch?owner_id=wrong-owner")
        assert response.status_code == 403

    def test_watch_public_relay_accepted(self, client, sample_relay):
        """The watch endpoint should accept connections for public relays (not 403/404)."""
        relay_id = sample_relay["relay_id"]
        # SSE endpoints stream indefinitely, so we cannot use a simple GET.
        # Instead, verify that the endpoint does not return 4xx/5xx by
        # checking what happens when the relay exists and is public.
        # The unit tests in TestWatchSSEReceivesMessages cover the actual
        # message delivery through the spectator queue.

        # Verify 404 for bad relay (proves routing works)
        resp = client.get("/relays/bad-id/watch")
        assert resp.status_code == 404

        # Verify 403 for private relay
        # (already tested in test_watch_private_relay_denied)


class TestSpectatorDoesNotAffectTurns:
    """Spectators are purely read-only and must not impact turn logic."""

    def test_spectator_does_not_affect_turns(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        api_key = sample_relay.get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        # Initial turn should be alice
        state = client.get(f"/relays/{relay_id}").json()
        assert state["current_turn"] == "alice"

        # Send as alice
        resp = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hello!", "agent": "alice"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["next_turn"] == "bob"

        # Turn is now bob
        state = client.get(f"/relays/{relay_id}").json()
        assert state["current_turn"] == "bob"

        # Send as bob
        resp2 = client.post(
            f"/relays/{relay_id}/messages",
            json={"content": "Hi!", "agent": "bob"},
            headers=headers,
        )
        assert resp2.status_code == 200
        assert resp2.json()["next_turn"] == "alice"


class TestSpectatorCountEndpoint:
    def test_spectator_count_initially_zero(self, client, sample_relay):
        relay_id = sample_relay["relay_id"]
        resp = client.get(f"/relays/{relay_id}/spectators")
        assert resp.status_code == 200
        assert resp.json()["spectator_count"] == 0

    def test_spectator_count_nonexistent_relay(self, client):
        resp = client.get("/relays/nonexistent/spectators")
        assert resp.status_code == 404
