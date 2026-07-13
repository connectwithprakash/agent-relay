"""
Message endpoints - send and history
"""
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from ..auth import get_current_agent
from ..database import get_db
from ..models import AgentToken, Relay, Message
from ..security import digest
from ..repositories import MessageRepository
from ..schemas import (
    SendMessageRequest, SendMessageResponse,
    MessageHistory, MessageSchema, ListenResponse,
)
from ..services import PrivacyService, RelayService, WebhookService
from ..websocket_manager import manager, get_relay_lock
from ..rate_limit import limiter
from .relays import get_relay_or_404, _check_and_advance_timeout

router = APIRouter()

def _read_relay(db: Session, relay_id: str, authorization: str | None) -> tuple[Relay, str | None]:
    relay = get_relay_or_404(db, relay_id)
    if relay.is_public:
        if not authorization or not authorization.startswith("Bearer "):
            return relay, None
        token = db.query(AgentToken).filter(
            AgentToken.token_hash == digest(authorization[7:]),
            AgentToken.relay_id == relay_id,
        ).first()
        return relay, token.agent_name if token else None
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token required for private relay")
    token = db.query(AgentToken).filter(AgentToken.token_hash == digest(authorization[7:]), AgentToken.relay_id == relay_id).first()
    if not token:
        raise HTTPException(status_code=403, detail="Token is not valid for this relay")
    return relay, token.agent_name



@router.post("/relays/{relay_id}/messages", response_model=SendMessageResponse)
@limiter.limit("30/minute")
async def send_message(
    request: Request,
    req: SendMessageRequest,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Send a message (only if your turn). Requires token for authenticated relays."""
    relay = agent_info["relay"]
    relay_id = relay.id

    # Participant identity is derived exclusively from the authenticated token.
    agent_override = agent_info["agent_name"]

    # Use per-relay lock to prevent race conditions between
    # turn validation, message creation, and turn advancement
    lock = get_relay_lock(relay_id)
    with lock:
        # Re-read relay inside lock to get fresh state
        db.refresh(relay)
        observed_version = relay.version

        # Idempotency check: if a message with this key already exists, return it
        message_repo = MessageRepository(db)
        if req.idempotency_key:
            existing = db.query(Message).filter(
                Message.relay_id == relay_id,
                Message.agent_name == agent_override,
                Message.idempotency_key == req.idempotency_key,
            ).first()
            if existing:
                agent_names = relay.agent_names or []
                current_turn = (
                    agent_names[relay.current_turn]
                    if agent_names and 0 <= relay.current_turn < len(agent_names)
                    else "unknown"
                )
                count = message_repo.count_by_relay_id(relay_id)
                return SendMessageResponse(
                    status="ok",
                    message_id=existing.id,
                    next_turn=current_turn,
                    message_count=count,
                    version=relay.version,
                )

        if req.expected_version is not None and req.expected_version != observed_version:
            raise HTTPException(status_code=409, detail="Relay state changed; refresh and retry")

        # Timeout advancement is a separate versioned state change. Make the
        # caller refresh instead of accepting a command against stale ownership.
        try:
            timed_out = _check_and_advance_timeout(db, relay)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if timed_out:
            raise HTTPException(status_code=409, detail="Turn timed out; refresh and retry")

        # Validate agent and turn using service
        try:
            agent, agent_index = RelayService.validate_agent(relay, agent_override)
            RelayService.validate_turn(relay, agent_index)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Validate reply_to if provided
        if req.reply_to is not None:
            parent_msg = db.query(Message).filter(
                Message.id == req.reply_to,
                Message.relay_id == relay_id,
            ).first()
            if parent_msg is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"reply_to message {req.reply_to} not found in this relay",
                )

        # Create message
        message = Message(
            relay_id=relay_id,
            agent_index=agent_index,
            agent_name=agent,
            content=req.content,
            data=req.data,
            type=req.message_type if req.message_type != "text" else req.type,
            message_type=req.message_type if req.message_type != "text" else req.type,
            reply_to=req.reply_to,
            idempotency_key=req.idempotency_key,
        )
        if req.idempotency_key:
            try:
                # The savepoint lets a concurrent idempotency-key winner be read
                # without aborting this request's outer transaction.
                with db.begin_nested():
                    message = message_repo.create(message)
            except IntegrityError:
                existing = db.query(Message).filter(
                    Message.relay_id == relay_id,
                    Message.agent_name == agent,
                    Message.idempotency_key == req.idempotency_key,
                ).first()
                if existing is None:
                    raise
                agent_names = relay.agent_names or []
                current_turn = agent_names[relay.current_turn] if agent_names else "unknown"
                return SendMessageResponse(
                    status="ok", message_id=existing.id, next_turn=current_turn,
                    message_count=message_repo.count_by_relay_id(relay_id),
                    version=relay.version,
                )
        else:
            message = message_repo.create(message)

        # Switch turn and commit the message plus relay state as one command.
        next_turn = RelayService.advance_turn(db, relay, getattr(req, 'next_agent', None), commit=False)
        # Compare-and-swap makes turn ownership safe across worker processes.
        with db.no_autoflush:
            result = db.execute(
                update(Relay)
                .where(Relay.id == relay_id, Relay.version == observed_version)
                .values(
                    current_turn=relay.current_turn,
                    agent_count=relay.agent_count,
                    turns_waited=relay.turns_waited,
                    turn_started_at=relay.turn_started_at,
                    version=observed_version + 1,
                )
            )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Relay state changed; refresh and retry")
        db.expire(relay)
        outbox_count = WebhookService.enqueue_webhooks(
            db, relay, message, relay.current_turn
        )
        db.commit()
        db.refresh(message)
        message_count = message_repo.count_by_relay_id(relay_id)

    # Prepare broadcast payload (outside lock)
    message_dict = {
        "id": message.id,
        "agent": message.agent_name,
        "content": message.content,
        "data": message.data,
        "type": message.type,
        "reply_to": message.reply_to,
        "message_type": message.message_type,
        "created_at": message.created_at.isoformat(),
        "next_turn": next_turn,
        "version": observed_version + 1,
    }

    # WebSocket delivery is best effort; webhook delivery is durable in the outbox.
    asyncio.create_task(manager.broadcast_message(relay_id, message_dict))
    if outbox_count:
        WebhookService.notify_dispatcher()

    return SendMessageResponse(
        status="ok",
        message_id=message.id,
        next_turn=next_turn,
        message_count=message_count,
        version=observed_version + 1,
    )


@router.post("/relays/{relay_id}/skip-turn")
@limiter.limit("10/minute")
async def skip_turn(
    request: Request,
    force: bool = False,
    target_agent: str = None,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Skip an agent's turn.

    Modes:
    1. Timeout-based (default): succeeds only when turn_timeout is configured and expired.
    2. Force skip (force=true): any authenticated agent can skip immediately.

    Args:
        force: Skip immediately without timeout check.
        target_agent: Skip this specific agent. If not provided, skips current turn holder.
    """
    relay = agent_info["relay"]
    if force and not agent_info["is_creator"]:
        raise HTTPException(status_code=403, detail="Only the relay creator may force-skip a turn")
    relay_id = relay.id
    lock = get_relay_lock(relay_id)
    with lock:
        db.refresh(relay)

        agent_names = relay.agent_names or []
        if not agent_names:
            raise HTTPException(
                status_code=400,
                detail="Cannot skip turn: relay has no agents."
            )

        skipped_agent = (
            agent_names[relay.current_turn]
            if 0 <= relay.current_turn < len(agent_names)
            else None
        )

        if force:
            # If target_agent specified, advance turn TO skip past them
            if target_agent and target_agent in agent_names:
                # Set current turn to the target, then advance past them
                relay.current_turn = agent_names.index(target_agent)
                skipped_agent = target_agent
            try:
                next_turn = RelayService.advance_turn(db, relay)
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return {
                "status": "ok",
                "skipped_agent": skipped_agent,
                "next_turn": next_turn,
                "forced": True,
            }

        # Timeout-based skip: requires turn_timeout to be configured
        if relay.turn_timeout is None:
            raise HTTPException(
                status_code=400,
                detail="This relay has no turn timeout configured. Use force=true to skip anyway."
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

        try:
            next_turn = RelayService.advance_turn(db, relay)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "status": "ok",
        "skipped_agent": skipped_agent,
        "next_turn": next_turn,
        "forced": False,
    }


@router.get("/relays/{relay_id}/history", response_model=MessageHistory)
@limiter.limit("60/minute")
async def get_message_history(
    request: Request,
    relay_id: str,
    limit: int = 50,
    offset: int = 0,
    message_type: str = None,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db)
):
    """Get message history. Optionally filter by message_type (e.g. question, action-item)."""
    relay, _ = _read_relay(db, relay_id, authorization)

    # Cap limit to prevent excessive queries
    limit = min(limit, 100)

    message_repo = MessageRepository(db)
    messages = message_repo.get_by_relay_id(relay_id, limit, offset, message_type=message_type)
    total_count = message_repo.count_by_relay_id(relay_id, message_type=message_type)

    return MessageHistory(
        relay_id=relay_id,
        messages=[
            MessageSchema(
                id=msg.id,
                agent=msg.agent_name,
                content=msg.content,
                data=msg.data,
                type=msg.type,
                reply_to=msg.reply_to,
                message_type=msg.message_type,
                created_at=msg.created_at.isoformat()
            )
            for msg in messages
        ],
        total_count=total_count
    )


@router.get("/relays/{relay_id}/listen", response_model=ListenResponse)
@limiter.limit("120/minute")
async def listen_for_messages(
    request: Request,
    relay_id: str,
    since_id: int = 0,
    agent: str | None = None,
    limit: int = 20,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Non-blocking check for new messages since a given message ID.

    Returns immediately with any messages whose id > since_id.
    Designed for agents to poll quickly between other work without blocking.
    """
    relay, authenticated_agent = _read_relay(db, relay_id, authorization)
    if authenticated_agent is not None:
        agent = authenticated_agent

    # Cap limit to prevent excessive queries
    limit = min(limit, 100)

    message_repo = MessageRepository(db)
    messages = message_repo.get_since_id(relay_id, since_id, limit)
    total_count = message_repo.count_by_relay_id(relay_id)

    agent_names = relay.agent_names or []
    current_turn = (
        agent_names[relay.current_turn]
        if agent_names and 0 <= relay.current_turn < len(agent_names)
        else None
    )

    your_turn = None
    if agent and current_turn:
        your_turn = current_turn == agent

    last_id = messages[-1].id if messages else since_id

    return ListenResponse(
        new_messages=len(messages),
        your_turn=your_turn,
        current_turn=current_turn,
        messages=[
            MessageSchema(
                id=msg.id,
                agent=msg.agent_name,
                content=msg.content,
                data=msg.data,
                type=msg.type,
                created_at=msg.created_at.isoformat(),
            )
            for msg in messages
        ],
        last_id=last_id,
        agent_count=len(agent_names),
        total_messages=total_count,
    )
