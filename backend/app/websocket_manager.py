"""
WebSocket connection manager, SSE spectator support, and per-relay locks
"""
import asyncio
import logging
import threading
from typing import Dict, List

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # relay_id -> list of (agent_name, websocket)
        self.active_connections: Dict[str, List[tuple[str, WebSocket]]] = {}
        # relay_id -> list of asyncio.Queue (one per SSE spectator)
        self.spectators: Dict[str, List[asyncio.Queue]] = {}

    async def connect(self, relay_id: str, agent_name: str, websocket: WebSocket):
        await websocket.accept()
        if relay_id not in self.active_connections:
            self.active_connections[relay_id] = []
        self.active_connections[relay_id].append((agent_name, websocket))

    def disconnect(self, relay_id: str, agent_name: str, websocket: WebSocket):
        if relay_id in self.active_connections:
            self.active_connections[relay_id] = [
                (name, ws) for name, ws in self.active_connections[relay_id]
                if ws != websocket
            ]
            # Clean up empty relay entries to prevent unbounded memory growth
            if not self.active_connections[relay_id]:
                del self.active_connections[relay_id]

    def cleanup_relay(self, relay_id: str):
        """Remove per-relay lock when a relay has no connections and no spectators."""
        has_connections = relay_id in self.active_connections
        has_spectators = relay_id in self.spectators
        if not has_connections and not has_spectators:
            with _relay_locks_guard:
                _relay_locks.pop(relay_id, None)

    def add_spectator(self, relay_id: str, queue: asyncio.Queue):
        """Register a spectator queue for SSE streaming."""
        if relay_id not in self.spectators:
            self.spectators[relay_id] = []
        self.spectators[relay_id].append(queue)

    def remove_spectator(self, relay_id: str, queue: asyncio.Queue):
        """Unregister a spectator queue."""
        if relay_id in self.spectators:
            self.spectators[relay_id] = [
                q for q in self.spectators[relay_id] if q is not queue
            ]
            if not self.spectators[relay_id]:
                del self.spectators[relay_id]

    def spectator_count(self, relay_id: str) -> int:
        """Return the number of active spectators for a relay."""
        return len(self.spectators.get(relay_id, []))

    async def broadcast_message(self, relay_id: str, message: dict):
        """Broadcast message to all connected WebSockets and SSE spectators for this relay"""
        # WebSocket broadcast
        if relay_id in self.active_connections:
            disconnected = []
            for agent_name, websocket in self.active_connections[relay_id]:
                try:
                    await websocket.send_json(message)
                except Exception:
                    disconnected.append((agent_name, websocket))

            # Clean up disconnected websockets
            for agent_name, websocket in disconnected:
                self.disconnect(relay_id, agent_name, websocket)

        # SSE spectator broadcast
        if relay_id in self.spectators:
            for queue in self.spectators[relay_id]:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    logger.warning(
                        "Dropped message for slow spectator on relay %s (queue full)",
                        relay_id,
                    )


# Singleton instance
manager = ConnectionManager()

# Per-relay locks to prevent race conditions in send_message
_relay_locks: dict[str, threading.Lock] = {}
_relay_locks_guard = threading.Lock()


def get_relay_lock(relay_id: str) -> threading.Lock:
    """Get or create a per-relay threading lock."""
    with _relay_locks_guard:
        if relay_id not in _relay_locks:
            _relay_locks[relay_id] = threading.Lock()
        return _relay_locks[relay_id]
