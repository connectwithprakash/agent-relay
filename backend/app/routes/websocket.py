"""
WebSocket endpoint for real-time message updates
"""
import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from ..database import SessionLocal
from ..repositories import RelayRepository
from ..websocket_manager import manager

logger = logging.getLogger(__name__)

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

        if not relay.agent_names or agent not in relay.agent_names:
            await websocket.close(code=4003, reason="Unknown agent")
            return

        # Authenticate WebSocket connection if relay has an API key
        if relay.api_key_hash is not None:
            if api_key:
                logger.warning(
                    "API key passed via query parameter for relay %s. "
                    "Prefer the Sec-WebSocket-Protocol header for credentials.",
                    relay_id,
                )
            # Also accept api_key from subprotocol header
            subprotocol_key: Optional[str] = None
            for proto in (websocket.headers.get("sec-websocket-protocol") or "").split(","):
                proto = proto.strip()
                if proto.startswith("apikey-"):
                    subprotocol_key = proto[len("apikey-"):]
                    break

            effective_key = api_key or subprotocol_key

            if not effective_key:
                await websocket.close(code=4001, reason="Authentication required")
                return
            provided_hash = hashlib.sha256(effective_key.encode()).hexdigest()
            if provided_hash != relay.api_key_hash:
                await websocket.close(code=4001, reason="Invalid API key")
                return

        await manager.connect(relay_id, agent, websocket)

        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(relay_id, agent, websocket)
            manager.cleanup_relay(relay_id)
    finally:
        db.close()
