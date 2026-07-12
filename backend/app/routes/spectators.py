"""
SSE spectator endpoints for read-only relay watching
"""
import asyncio
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from ..database import get_db
from ..websocket_manager import manager, SPECTATOR_QUEUE_MAXSIZE
from .relays import _authorize_private_read, get_relay_or_404

router = APIRouter()

# Seconds to wait for a message before sending a keep-alive comment
SSE_HEARTBEAT_TIMEOUT_SECONDS = 30


@router.get("/relays/{relay_id}/watch")
async def watch_relay(
    relay_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Watch relay messages in real-time via Server-Sent Events (read-only spectator mode)."""
    relay = get_relay_or_404(db, relay_id)
    _authorize_private_read(db, relay, authorization)

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
async def get_spectator_count(
    relay_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Get the number of active spectators watching a relay."""
    relay = get_relay_or_404(db, relay_id)
    _authorize_private_read(db, relay, authorization)
    return {"relay_id": relay_id, "spectator_count": manager.spectator_count(relay_id)}
