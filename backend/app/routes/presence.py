"""
Presence/heartbeat endpoints for agent liveness tracking
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_agent
from ..repositories import PresenceRepository
from ..rate_limit import limiter
from .relays import get_relay_or_404

router = APIRouter()


@router.post("/relays/{relay_id}/heartbeat")
@limiter.limit("60/minute")
async def heartbeat(
    request: Request,
    relay_id: str,
    status: str = "active",
    status_message: str = None,
    agent_info: dict = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    """Send a heartbeat to update agent presence.

    Args:
        relay_id: The relay to send heartbeat for.
        The authenticated participant is the agent sending the heartbeat.
        status: Current status - active, composing, idle.
        status_message: Brief description of what the agent is currently doing.
    """
    relay = agent_info["relay"]
    agent = agent_info["agent_name"]

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

    # Truncate status_message to 200 chars
    if status_message and len(status_message) > 200:
        status_message = status_message[:200]

    presence_repo = PresenceRepository(db)
    presence = presence_repo.upsert(relay_id, agent, status, status_message=status_message)

    return {
        "status": "ok",
        "agent": presence.agent_name,
        "presence_status": presence.status,
        "status_message": presence.status_message,
        "last_seen": presence.last_seen.isoformat(),
    }
