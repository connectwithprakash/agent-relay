"""
WebSocket endpoint for real-time message updates
"""
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from loguru import logger

from ..database import SessionLocal
from ..models import AgentToken
from ..security import digest
from ..repositories import RelayRepository
from ..websocket_manager import manager

router = APIRouter()


@router.websocket("/relays/{relay_id}/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    relay_id: str,
    agent: str,
    token: Optional[str] = Query(default=None),
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

        # Authenticate WebSocket connection using token
        # Check if any tokens exist for this relay (if so, auth is required)
        has_tokens = db.query(AgentToken).filter(AgentToken.relay_id == relay_id).first() is not None

        if has_tokens:
            if token:
                logger.warning(
                    "Token passed via query parameter for relay {}. "
                    "Prefer the Sec-WebSocket-Protocol header for credentials.",
                    relay_id,
                )
            # Also accept token from subprotocol header
            subprotocol_token: Optional[str] = None
            for proto in (websocket.headers.get("sec-websocket-protocol") or "").split(","):
                proto = proto.strip()
                if proto.startswith("token-"):
                    subprotocol_token = proto[len("token-"):]
                    break

            effective_token = token or subprotocol_token

            if not effective_token:
                await websocket.close(code=4001, reason="Authentication required")
                return

            agent_token = db.query(AgentToken).filter(
                AgentToken.token_hash == digest(effective_token)
            ).first()

            if (
                not agent_token
                or agent_token.relay_id != relay_id
                or agent_token.agent_name != agent
            ):
                await websocket.close(code=4001, reason="Invalid token")
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
