"""
Presence/heartbeat endpoints for agent liveness tracking
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..repositories import PresenceRepository
from ..rate_limit import limiter
from .relays import get_relay_or_404

logger = logging.getLogger("agent_relay.app")

router = APIRouter()


@router.post("/relays/{relay_id}/heartbeat")
@limiter.limit("60/minute")
async def heartbeat(
    request: Request,
    relay_id: str,
    agent: str,
    status: str = "active",
    db: Session = Depends(get_db),
):
    """Send a heartbeat to update agent presence.

    Args:
        relay_id: The relay to send heartbeat for.
        agent: The agent name sending the heartbeat.
        status: Current status - active, composing, idle.
    """
    relay = get_relay_or_404(db, relay_id)

    # Validate agent belongs to this relay
    agent_names = relay.agent_names or []
    if agent not in agent_names:
        raise HTTPException(status_code=400, detail=f"Agent '{agent}' is not in this relay")

    # Validate status
    valid_statuses = {"active", "composing", "idle"}
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{status}'. Must be one of: {', '.join(sorted(valid_statuses))}"
        )

    presence_repo = PresenceRepository(db)
    presence = presence_repo.upsert(relay_id, agent, status)

    return {
        "status": "ok",
        "agent": presence.agent_name,
        "presence_status": presence.status,
        "last_seen": presence.last_seen.isoformat(),
    }
