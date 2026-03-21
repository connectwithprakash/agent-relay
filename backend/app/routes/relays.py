"""
Relay CRUD endpoints
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Relay
from ..repositories import RelayRepository, MessageRepository
from ..schemas import (
    CreateRelayRequest, CreateRelayResponse,
    RelayState, RelayListResponse, RelayListItem,
)
from ..services import PrivacyService, RelayService
from ..rate_limit import limiter

logger = logging.getLogger("agent_relay.app")

router = APIRouter()


def get_relay_or_404(db: Session, relay_id: str) -> Relay:
    """Get relay by ID or raise 404"""
    repo = RelayRepository(db)
    relay = repo.get_by_id(relay_id)
    if not relay:
        raise HTTPException(status_code=404, detail=f"Relay {relay_id} not found")
    return relay


def _check_and_advance_timeout(db: Session, relay: Relay) -> None:
    """If the relay has a turn timeout and it has elapsed, auto-advance the turn."""
    if relay.turn_timeout is None or relay.turn_started_at is None:
        return
    now = datetime.now(timezone.utc)
    started = relay.turn_started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = (now - started).total_seconds()
    if elapsed >= relay.turn_timeout:
        RelayService.advance_turn(db, relay)
        logger.info("Auto-advanced timed-out turn for relay %s", relay.id)


@router.post("/relays", response_model=CreateRelayResponse)
@limiter.limit("5/minute")
async def create_relay(request: Request, req: CreateRelayRequest, db: Session = Depends(get_db)):
    """Create a new relay"""
    relay, api_key = RelayService.create_relay(db, req)
    return CreateRelayResponse(
        relay_id=relay.id,
        agent_names=relay.agent_names,
        current_turn=relay.agent_names[0] if relay.agent_names else None,
        api_key=api_key,
        join_code=relay.join_code,
        description=relay.description,
        status="open" if not relay.agent_names else "active",
    )


@router.get("/relays", response_model=RelayListResponse)
@limiter.limit("30/minute")
async def list_relays(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List public relays with pagination"""
    repo = RelayRepository(db)
    message_repo = MessageRepository(db)
    relays = repo.list_public(limit, offset)
    total_count = repo.count_public()

    # Batch fetch message counts to avoid N+1 queries
    relay_ids = [relay.id for relay in relays]
    counts = message_repo.count_by_relay_ids(relay_ids)

    items = []
    for relay in relays:
        items.append(RelayListItem(
            relay_id=relay.id,
            agent_names=relay.agent_names,
            current_turn=relay.agent_names[relay.current_turn],
            message_count=counts.get(relay.id, 0),
            is_public=relay.is_public,
            created_at=relay.created_at.isoformat(),
        ))

    return RelayListResponse(relays=items, total_count=total_count)


@router.get("/relays/{relay_id}", response_model=RelayState)
async def get_relay_state(relay_id: str, owner_id: str = None, db: Session = Depends(get_db)):
    """Get current relay state"""
    relay = get_relay_or_404(db, relay_id)

    if not PrivacyService.check_access(relay, owner_id):
        raise HTTPException(status_code=403, detail="Access denied. This relay is private.")

    # Auto-advance if turn has timed out
    _check_and_advance_timeout(db, relay)

    return RelayService.get_relay_state(db, relay)
