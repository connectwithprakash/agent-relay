"""
Agent registry endpoints for cross-device discovery
"""
import random
import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AgentRegistration, AgentToken, Relay
from ..rate_limit import limiter
from ..services import RelayService

router = APIRouter()


def _parse_capabilities(capabilities: Optional[str]) -> Optional[list]:
    """Parse a comma-separated capabilities string into a list."""
    if not capabilities:
        return None
    return [c.strip() for c in capabilities.split(",") if c.strip()]


def _agent_to_dict(r: AgentRegistration) -> dict:
    """Serialize an AgentRegistration to a dict with profile fields."""
    return {
        "agent_name": r.agent_name,
        "namespace": r.namespace,
        "description": r.description,
        "capabilities": r.capabilities,
        "status": r.status,
        "relay_id": r.relay_id,
        "last_heartbeat": r.last_heartbeat.isoformat() if r.last_heartbeat else None,
    }


@router.get("/agents/search")
@limiter.limit("30/minute")
async def search_agents(
    request: Request,
    capability: Optional[str] = None,
    namespace: Optional[str] = None,
    status: str = "ready",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Search for agents by capability across all namespaces."""
    query = db.query(AgentRegistration)
    if namespace:
        query = query.filter(AgentRegistration.namespace == namespace)
    if status:
        query = query.filter(AgentRegistration.status == status)

    # Filter by capability (JSON array contains) - must load all for in-memory filter
    if capability:
        all_results = query.all()
        filtered = [r for r in all_results if r.capabilities and capability in r.capabilities]
        total = len(filtered)
        results = filtered[offset : offset + limit]
    else:
        total = query.count()
        results = query.offset(offset).limit(limit).all()

    return {
        "agents": [_agent_to_dict(r) for r in results],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/agents/register")
@limiter.limit("10/minute")
async def register_agent(
    request: Request,
    namespace: str,
    agent_name: str,
    device_id: str = None,
    description: str = None,
    capabilities: str = None,
    db: Session = Depends(get_db),
):
    """Register an agent in a namespace for cross-device discovery.

    When two or more agents register with the same namespace, a relay is
    automatically created and all waiting agents are joined to it.
    """
    # Validate agent_name length
    if not agent_name or len(agent_name) > 100:
        raise HTTPException(
            status_code=422,
            detail="agent_name must be between 1 and 100 characters",
        )

    if not device_id:
        device_id = secrets.token_urlsafe(8)

    caps_list = _parse_capabilities(capabilities)

    # Check if this agent+device is already registered in this namespace
    existing_reg = db.query(AgentRegistration).filter(
        AgentRegistration.namespace == namespace,
        AgentRegistration.agent_name == agent_name,
        AgentRegistration.device_id == device_id,
    ).first()

    if existing_reg and existing_reg.relay_id:
        # Already registered and has a relay - update profile fields
        relay = db.query(Relay).filter(Relay.id == existing_reg.relay_id).first()
        existing_reg.last_heartbeat = datetime.now(timezone.utc)
        existing_reg.status = "ready"
        if description is not None:
            existing_reg.description = description
        if caps_list is not None:
            existing_reg.capabilities = caps_list
        db.commit()

        # Get or create token for this agent
        existing_token = db.query(AgentToken).filter(
            AgentToken.relay_id == relay.id,
            AgentToken.agent_name == agent_name,
        ).first()
        token_str = existing_token.token if existing_token else RelayService.create_agent_token(
            db, relay.id, agent_name
        )
        db.commit()

        return {
            "status": "joined",
            "relay_id": relay.id,
            "token": token_str,
            "agent_name": agent_name,
            "device_id": device_id,
            "agents": relay.agent_names,
            "namespace": namespace,
        }

    # Check if a relay already exists for this namespace
    existing = db.query(AgentRegistration).filter(
        AgentRegistration.namespace == namespace,
        AgentRegistration.relay_id != None,  # noqa: E711
    ).first()

    if existing:
        # Relay exists - join it
        relay = db.query(Relay).filter(Relay.id == existing.relay_id).first()
        if not relay:
            raise HTTPException(status_code=500, detail="Relay referenced but not found")

        # Add this agent to the relay if not already in it
        if agent_name not in relay.agent_names:
            relay.agent_names = relay.agent_names + [agent_name]
            relay.agent_count = len(relay.agent_names)

        # Register this agent
        reg = AgentRegistration(
            namespace=namespace,
            agent_name=agent_name,
            device_id=device_id,
            description=description,
            capabilities=caps_list,
            relay_id=relay.id,
            status="ready",
        )
        db.add(reg)

        # Create token for this agent
        token_str = RelayService.create_agent_token(db, relay.id, agent_name)
        db.commit()

        return {
            "status": "joined",
            "relay_id": relay.id,
            "token": token_str,
            "agent_name": agent_name,
            "device_id": device_id,
            "agents": relay.agent_names,
            "namespace": namespace,
        }
    else:
        # No relay yet - register and wait
        if existing_reg:
            # Re-use existing registration
            existing_reg.last_heartbeat = datetime.now(timezone.utc)
            existing_reg.status = "waiting"
            if description is not None:
                existing_reg.description = description
            if caps_list is not None:
                existing_reg.capabilities = caps_list
            db.commit()
        else:
            reg = AgentRegistration(
                namespace=namespace,
                agent_name=agent_name,
                device_id=device_id,
                description=description,
                capabilities=caps_list,
                status="waiting",
            )
            db.add(reg)
            db.commit()

        # Check if enough agents are waiting to form a relay
        waiting = db.query(AgentRegistration).filter(
            AgentRegistration.namespace == namespace,
            AgentRegistration.status == "waiting",
        ).all()

        if len(waiting) >= 2:
            # Create relay with all waiting agents
            agent_names = [w.agent_name for w in waiting]

            join_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            relay = Relay(
                id=f"relay-{secrets.token_urlsafe(8)}",
                agent_names=agent_names,
                agent_count=len(agent_names),
                current_turn=0,
                is_public=True,
                join_code=join_code,
                turn_started_at=datetime.now(timezone.utc),
            )
            db.add(relay)

            for w in waiting:
                w.relay_id = relay.id
                w.status = "ready"

            # Create token for the creator (current agent)
            token_str = RelayService.create_agent_token(
                db, relay.id, agent_name, is_creator=True
            )
            db.commit()

            return {
                "status": "created",
                "relay_id": relay.id,
                "token": token_str,
                "agent_name": agent_name,
                "device_id": device_id,
                "agents": agent_names,
                "namespace": namespace,
            }
        else:
            return {
                "status": "waiting",
                "agent_name": agent_name,
                "device_id": device_id,
                "namespace": namespace,
                "waiting_count": len(waiting),
                "message": (
                    "Waiting for more agents to join this namespace. "
                    "Other agents should register with the same namespace."
                ),
            }


@router.get("/agents/discover/{namespace}")
@limiter.limit("30/minute")
async def discover_agents(
    namespace: str,
    request: Request,
    include_device_id: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Discover all agents and relays in a namespace.

    By default, device_id is omitted from responses for privacy.
    Pass include_device_id=true (for admin use) to include it.
    """
    base_query = db.query(AgentRegistration).filter(
        AgentRegistration.namespace == namespace,
    )
    total = base_query.count()
    registrations = base_query.offset(offset).limit(limit).all()

    # Get the relay_id from any registration in this namespace (not just paginated results)
    first_with_relay = db.query(AgentRegistration.relay_id).filter(
        AgentRegistration.namespace == namespace,
        AgentRegistration.relay_id != None,  # noqa: E711
    ).first()

    agents_list = []
    for r in registrations:
        agent_data = {
            "agent_name": r.agent_name,
            "description": r.description,
            "capabilities": r.capabilities,
            "relay_id": r.relay_id,
            "status": r.status,
            "last_heartbeat": r.last_heartbeat.isoformat() if r.last_heartbeat else None,
        }
        if include_device_id:
            agent_data["device_id"] = r.device_id
        agents_list.append(agent_data)

    return {
        "namespace": namespace,
        "agents": agents_list,
        "relay_id": first_with_relay[0] if first_with_relay else None,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/agents/{namespace}/{agent_name}")
async def get_agent_profile(
    namespace: str,
    agent_name: str,
    db: Session = Depends(get_db),
):
    """Get a specific agent's profile and capabilities."""
    reg = db.query(AgentRegistration).filter(
        AgentRegistration.namespace == namespace,
        AgentRegistration.agent_name == agent_name,
    ).first()
    if not reg:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_to_dict(reg)


@router.get("/relays/code/{join_code}")
async def get_relay_by_code(join_code: str, db: Session = Depends(get_db)):
    """Look up a relay by its short join code."""
    relay = db.query(Relay).filter(Relay.join_code == join_code.upper()).first()
    if not relay:
        raise HTTPException(status_code=404, detail="Invalid join code")
    agent_names = relay.agent_names or []
    current_turn = (
        agent_names[relay.current_turn]
        if agent_names and relay.current_turn < len(agent_names)
        else None
    )
    return {
        "relay_id": relay.id,
        "agent_names": agent_names,
        "current_turn": current_turn,
        "join_code": relay.join_code,
    }


@router.post("/relays/join/{join_code}")
async def join_by_code(
    join_code: str,
    agent_name: str,
    db: Session = Depends(get_db),
):
    """Join a relay using a short join code. Returns relay info and a token.

    The join code acts as authorization -- knowing the code grants access.
    """
    # Validate agent_name length
    if not agent_name or len(agent_name) > 100:
        raise HTTPException(
            status_code=422,
            detail="agent_name must be between 1 and 100 characters",
        )

    relay = db.query(Relay).filter(Relay.join_code == join_code.upper()).first()
    if not relay:
        raise HTTPException(status_code=404, detail="Invalid join code")

    agent_names = relay.agent_names or []

    # Add agent to relay if not already present
    if agent_name not in agent_names:
        relay.agent_names = agent_names + [agent_name]
        relay.agent_count = len(relay.agent_names)
        # Start turn timer if this is transitioning from open to active
        if not agent_names and relay.turn_started_at is None:
            relay.turn_started_at = datetime.now(timezone.utc)
        db.commit()
        agent_names = relay.agent_names

    # Check if a token already exists for this agent in this relay
    existing_token = db.query(AgentToken).filter(
        AgentToken.relay_id == relay.id,
        AgentToken.agent_name == agent_name,
    ).first()

    if existing_token:
        token_str = existing_token.token
    else:
        token_str = RelayService.create_agent_token(db, relay.id, agent_name)
        db.commit()

    current_turn = (
        agent_names[relay.current_turn]
        if agent_names and relay.current_turn < len(agent_names)
        else None
    )

    return {
        "relay_id": relay.id,
        "join_code": relay.join_code,
        "agent_names": agent_names,
        "current_turn": current_turn,
        "token": token_str,
    }


@router.post("/agents/heartbeat")
async def agent_heartbeat(
    namespace: str,
    agent_name: str,
    device_id: str,
    db: Session = Depends(get_db),
):
    """Update agent heartbeat to mark the agent as online."""
    reg = db.query(AgentRegistration).filter(
        AgentRegistration.namespace == namespace,
        AgentRegistration.agent_name == agent_name,
        AgentRegistration.device_id == device_id,
    ).first()
    if not reg:
        raise HTTPException(status_code=404, detail="Agent not registered")
    reg.last_heartbeat = datetime.now(timezone.utc)
    reg.status = "ready"
    db.commit()
    return {"status": "ok"}
