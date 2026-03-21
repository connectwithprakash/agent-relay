"""
SSE spectator endpoints for read-only relay watching
"""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ..database import get_db
from ..services import PrivacyService
from ..websocket_manager import manager, SPECTATOR_QUEUE_MAXSIZE
from .relays import get_relay_or_404

router = APIRouter()

# Seconds to wait for a message before sending a keep-alive comment
SSE_HEARTBEAT_TIMEOUT_SECONDS = 30


@router.get("/relays/{relay_id}/watch")
async def watch_relay(relay_id: str, request: Request, db: Session = Depends(get_db)):
    """Watch relay messages in real-time via Server-Sent Events (read-only spectator mode).

    Public relays can be watched without authentication. Private relays
    require the correct owner_id query parameter.
    """
    relay = get_relay_or_404(db, relay_id)

    # For private relays, require owner_id
    owner_id = request.query_params.get("owner_id")
    if not PrivacyService.check_access(relay, owner_id):
        raise HTTPException(status_code=403, detail="Access denied. This relay is private.")

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue(maxsize=SPECTATOR_QUEUE_MAXSIZE)
        manager.add_spectator(relay_id, queue)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_TIMEOUT_SECONDS)
                    yield {"event": "message", "data": json.dumps(message)}
                except asyncio.TimeoutError:
                    # Send keep-alive comment to prevent connection timeout
                    yield {"comment": "keep-alive"}
        finally:
            manager.remove_spectator(relay_id, queue)

    return EventSourceResponse(event_generator())


@router.get("/relays/{relay_id}/spectators")
async def get_spectator_count(relay_id: str, db: Session = Depends(get_db)):
    """Get the number of active spectators watching a relay."""
    get_relay_or_404(db, relay_id)
    return {"relay_id": relay_id, "spectator_count": manager.spectator_count(relay_id)}
