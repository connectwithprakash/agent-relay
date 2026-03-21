"""
Message endpoints - send and history
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import require_relay_auth
from ..database import get_db
from ..models import Relay, Message
from ..repositories import MessageRepository
from ..schemas import (
    SendMessageRequest, SendMessageResponse,
    MessageHistory, MessageSchema,
)
from ..services import PrivacyService, RelayService, WebhookService
from ..websocket_manager import manager, get_relay_lock
from ..rate_limit import limiter
from .relays import get_relay_or_404, _check_and_advance_timeout

logger = logging.getLogger("agent_relay.app")

router = APIRouter()


@router.post("/relays/{relay_id}/messages", response_model=SendMessageResponse)
@limiter.limit("30/minute")
async def send_message(
    request: Request,
    req: SendMessageRequest,
    relay: Relay = Depends(require_relay_auth),
    db: Session = Depends(get_db),
):
    """Send a message (only if your turn). Requires API key for authenticated relays."""
    relay_id = relay.id

    # Use per-relay lock to prevent race conditions between
    # turn validation, message creation, and turn advancement
    lock = get_relay_lock(relay_id)
    with lock:
        # Re-read relay inside lock to get fresh state
        db.refresh(relay)

        # Auto-advance if turn has timed out
        _check_and_advance_timeout(db, relay)

        # Validate agent and turn using service
        try:
            agent, agent_index = RelayService.validate_agent(relay, req.agent)
            RelayService.validate_turn(relay, agent_index)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Create message
        message_repo = MessageRepository(db)
        message = Message(
            relay_id=relay_id,
            agent_index=agent_index,
            agent_name=agent,
            content=req.content,
            data=req.data,
            type=req.type
        )
        message = message_repo.create(message)

        # Switch turn
        next_turn = RelayService.advance_turn(db, relay, getattr(req, 'next_agent', None))
        message_count = message_repo.count_by_relay_id(relay_id)

    # Prepare broadcast payload (outside lock)
    message_dict = {
        "id": message.id,
        "agent": message.agent_name,
        "content": message.content,
        "data": message.data,
        "type": message.type,
        "created_at": message.created_at.isoformat(),
        "next_turn": next_turn
    }

    # Broadcast via WebSocket and trigger webhooks
    asyncio.create_task(manager.broadcast_message(relay_id, message_dict))
    asyncio.create_task(WebhookService.trigger_webhooks(db, relay, message, relay.current_turn))

    return SendMessageResponse(
        status="ok",
        message_id=message.id,
        next_turn=next_turn,
        message_count=message_count
    )


@router.post("/relays/{relay_id}/skip-turn")
@limiter.limit("10/minute")
async def skip_turn(
    request: Request,
    relay: Relay = Depends(require_relay_auth),
    db: Session = Depends(get_db),
):
    """Skip the current turn if the turn timeout has elapsed.

    Only succeeds when the relay has a turn_timeout configured and the
    current turn's time has been exceeded.
    """
    relay_id = relay.id
    lock = get_relay_lock(relay_id)
    with lock:
        db.refresh(relay)

        if relay.turn_timeout is None:
            raise HTTPException(
                status_code=400,
                detail="This relay has no turn timeout configured."
            )

        if relay.turn_started_at is None:
            raise HTTPException(
                status_code=400,
                detail="Turn has not started yet."
            )

        now = datetime.now(timezone.utc)
        started = relay.turn_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed = (now - started).total_seconds()

        if elapsed < relay.turn_timeout:
            remaining = relay.turn_timeout - elapsed
            raise HTTPException(
                status_code=400,
                detail=f"Turn has not timed out yet. {remaining:.0f}s remaining."
            )

        agent_names = relay.agent_names or []
        if not agent_names:
            raise HTTPException(
                status_code=400,
                detail="Cannot skip turn: relay has no agents."
            )
        skipped_agent = agent_names[relay.current_turn]
        next_turn = RelayService.advance_turn(db, relay)

    return {
        "status": "ok",
        "skipped_agent": skipped_agent,
        "next_turn": next_turn,
    }


@router.get("/relays/{relay_id}/history", response_model=MessageHistory)
@limiter.limit("60/minute")
async def get_message_history(
    request: Request,
    relay_id: str,
    limit: int = 50,
    offset: int = 0,
    owner_id: str = None,
    db: Session = Depends(get_db)
):
    """Get message history"""
    relay = get_relay_or_404(db, relay_id)

    if not PrivacyService.check_access(relay, owner_id):
        raise HTTPException(status_code=403, detail="Access denied. This relay is private.")

    # Cap limit to prevent excessive queries
    limit = min(limit, 100)

    message_repo = MessageRepository(db)
    messages = message_repo.get_by_relay_id(relay_id, limit, offset)
    total_count = message_repo.count_by_relay_id(relay_id)

    return MessageHistory(
        relay_id=relay_id,
        messages=[
            MessageSchema(
                id=msg.id,
                agent=msg.agent_name,
                content=msg.content,
                data=msg.data,
                type=msg.type,
                created_at=msg.created_at.isoformat()
            )
            for msg in messages
        ],
        total_count=total_count
    )
