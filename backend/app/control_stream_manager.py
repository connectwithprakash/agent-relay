"""Best-effort live streams for one managed harness session."""
from collections import defaultdict


class ControlStreamManager:
    def __init__(self):
        self._connections = defaultdict(list)

    async def connect(self, key, role, websocket, subprotocol=None):
        await websocket.accept(subprotocol=subprotocol)
        self._connections[key].append((role, websocket))

    def disconnect(self, key, websocket):
        self._connections[key] = [entry for entry in self._connections[key] if entry[1] is not websocket]
        if not self._connections[key]:
            self._connections.pop(key, None)

    async def send_to_role(self, key, role, frame, exclude=None):
        disconnected = []
        for peer_role, websocket in list(self._connections.get(key, [])):
            if peer_role != role or websocket is exclude:
                continue
            try:
                await websocket.send_json(frame)
            except Exception:
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(key, websocket)


manager = ControlStreamManager()
