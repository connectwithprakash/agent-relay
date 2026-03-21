"""
WebSocket endpoint for real-time message updates
"""
import hashlib
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from ..database import SessionLocal
from ..repositories import RelayRepository
from ..websocket_manager import manager

router = APIRouter()


@router.websocket("/relays/{relay_id}/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    relay_id: str,
    agent: str,
    api_key: Optional[str] = Query(default=None),
):
    """WebSocket endpoint for real-time message updates"""
    db = SessionLocal()
    try:
        relay_repo = RelayRepository(db)
        relay = relay_repo.get_by_id(relay_id)
        if not relay:
            await websocket.close(code=4004, reason="Relay not found")
            return

        if agent not in relay.agent_names:
            await websocket.close(code=4003, reason="Unknown agent")
            return

        # Authenticate WebSocket connection if relay has an API key
        if hasattr(relay, "api_key_hash") and relay.api_key_hash is not None:
            if not api_key:
                await websocket.close(code=4001, reason="Authentication required")
                return
            provided_hash = hashlib.sha256(api_key.encode()).hexdigest()
            if provided_hash != relay.api_key_hash:
                await websocket.close(code=4001, reason="Invalid API key")
                return

        await manager.connect(relay_id, agent, websocket)

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(relay_id, agent, websocket)
    finally:
        db.close()
