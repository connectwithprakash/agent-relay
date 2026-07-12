"""
Relay CRUD endpoints
"""
from datetime import datetime, timedelta, timezone
import uuid

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from ..database import get_db
from ..models import AgentToken, PairingInvitation, Relay
from ..security import digest
from ..auth import get_current_agent
from ..security import generate_secret, prefix
from ..repositories import RelayRepository, MessageRepository
from ..schemas import (
    CreateRelayRequest, CreateRelayResponse,
    RelayState, RelayListResponse, RelayListItem,
)
from ..services import PrivacyService, RelayService
from ..rate_limit import limiter

router = APIRouter()


@router.post("/relays/{relay_id}/invitations")
async def create_pairing_invitation(
    relay_id: str,
    agent_name: str,
    expires_in_seconds: int = 900,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Creator-only, one-time credential invitation for a named participant."""
    if not agent_info["is_creator"]:
        raise HTTPException(status_code=403, detail="Only the relay creator may issue invitations")
    relay = agent_info["relay"]
    if agent_name not in (relay.agent_names or []):
        raise HTTPException(status_code=400, detail="Invitation target is not a relay participant")
    if db.query(AgentToken).filter(AgentToken.relay_id == relay_id, AgentToken.agent_name == agent_name).first():
        raise HTTPException(status_code=409, detail="Participant already has a credential")
    secret = generate_secret()
    invitation = PairingInvitation(
        id=str(uuid.uuid4()), relay_id=relay_id, agent_name=agent_name,
        secret_hash=digest(secret), expires_at=datetime.now(timezone.utc) + timedelta(seconds=min(max(expires_in_seconds, 60), 86400)),
    )
    db.query(PairingInvitation).filter(PairingInvitation.relay_id == relay_id, PairingInvitation.agent_name == agent_name).delete()
    db.add(invitation); db.commit()
    return {"invitation": secret, "agent_name": agent_name, "expires_at": invitation.expires_at.isoformat()}


@router.post("/pairing-invitations/{secret}/redeem")
async def redeem_pairing_invitation(secret: str, db: Session = Depends(get_db)):
    invitation = db.query(PairingInvitation).filter(PairingInvitation.secret_hash == digest(secret)).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation is invalid, expired, or already redeemed")
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if expires_at < now:
        raise HTTPException(status_code=404, detail="Invitation is invalid, expired, or already redeemed")
    claimed = db.execute(
        update(PairingInvitation)
        .where(PairingInvitation.id == invitation.id, PairingInvitation.redeemed_at.is_(None))
        .values(redeemed_at=now)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=404, detail="Invitation is invalid, expired, or already redeemed")
    raw_token = generate_secret()
    try:
        db.add(AgentToken(token_hash=digest(raw_token), token_prefix=prefix(raw_token), relay_id=invitation.relay_id, agent_name=invitation.agent_name))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Participant already has a credential")
    return {"relay_id": invitation.relay_id, "agent_name": invitation.agent_name, "token": raw_token}


def get_relay_or_404(db: Session, relay_id: str) -> Relay:
    """Get relay by ID or raise 404"""
    repo = RelayRepository(db)
    relay = repo.get_by_id(relay_id)
    if not relay:
        raise HTTPException(status_code=404, detail=f"Relay {relay_id} not found")
    return relay


def _authorize_private_read(db: Session, relay: Relay, authorization: str | None) -> None:
    if relay.is_public:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token required for private relay")
    token = db.query(AgentToken).filter(
        AgentToken.relay_id == relay.id,
        AgentToken.token_hash == digest(authorization[7:]),
    ).first()
    if not token:
        raise HTTPException(status_code=403, detail="Token is not valid for this relay")


def _check_and_advance_timeout(db: Session, relay: Relay) -> None:
    """If the relay has a turn timeout and it has elapsed, auto-advance the turn."""
    if relay.turn_timeout is None or relay.turn_started_at is None:
        return
    if not relay.agent_names or relay.agent_count == 0:
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
    relay, token = RelayService.create_relay(db, req)
    return CreateRelayResponse(
        relay_id=relay.id,
        agent_names=relay.agent_names,
        current_turn=relay.agent_names[0] if relay.agent_names else None,
        token=token,
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
            current_turn=relay.agent_names[relay.current_turn] if relay.agent_names else None,
            message_count=counts.get(relay.id, 0),
            is_public=relay.is_public,
            created_at=relay.created_at.isoformat(),
            description=relay.description,
            status="open" if not relay.agent_names else "active",
        ))

    return RelayListResponse(relays=items, total_count=total_count)


@router.get("/relays/{relay_id}", response_model=RelayState)
async def get_relay_state(relay_id: str, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Get current relay state; private relays require a participant token."""
    relay = get_relay_or_404(db, relay_id)
    _authorize_private_read(db, relay, authorization)

    # Auto-advance if turn has timed out
    _check_and_advance_timeout(db, relay)

    return RelayService.get_relay_state(db, relay)


@router.get("/relays/{relay_id}/instructions")
async def get_relay_instructions(
    relay_id: str,
    agent: Optional[str] = None,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Get relay purpose and agent-specific instructions."""
    relay = get_relay_or_404(db, relay_id)
    _authorize_private_read(db, relay, authorization)
    result = {
        "relay_id": relay_id,
        "description": relay.description,
        "agent_names": relay.agent_names or [],
        "current_turn": (
            relay.agent_names[relay.current_turn]
            if relay.agent_names and 0 <= relay.current_turn < len(relay.agent_names)
            else None
        ),
    }
    if relay.agent_instructions:
        result["all_instructions"] = relay.agent_instructions
        if agent:
            result["your_instructions"] = relay.agent_instructions.get(
                agent, "No specific instructions."
            )
    return result
