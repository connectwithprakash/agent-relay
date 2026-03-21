"""
Agent registry endpoints for cross-device discovery
"""
import hashlib
import random
import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AgentRegistration, Relay

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
async def search_agents(
    capability: Optional[str] = None,
    namespace: Optional[str] = None,
    status: str = "ready",
    db: Session = Depends(get_db),
):
    """Search for agents by capability across all namespaces."""
    query = db.query(AgentRegistration)
    if namespace:
        query = query.filter(AgentRegistration.namespace == namespace)
    if status:
        query = query.filter(AgentRegistration.status == status)

    results = query.all()

    # Filter by capability (JSON array contains)
    if capability:
        results = [r for r in results if r.capabilities and capability in r.capabilities]

    return {
        "agents": [_agent_to_dict(r) for r in results],
    }


@router.post("/agents/register")
async def register_agent(
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
        return {
            "status": "joined",
            "relay_id": relay.id,
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
        db.commit()

        return {
            "status": "joined",
            "relay_id": relay.id,
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
            api_key = secrets.token_urlsafe(32)
            api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()

            join_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            relay = Relay(
                id=f"relay-{secrets.token_urlsafe(8)}",
                agent_names=agent_names,
                agent_count=len(agent_names),
                current_turn=0,
                is_public=True,
                api_key_hash=api_key_hash,
                join_code=join_code,
                turn_started_at=datetime.now(timezone.utc),
            )
            db.add(relay)

            for w in waiting:
                w.relay_id = relay.id
                w.status = "ready"
            db.commit()

            return {
                "status": "created",
                "relay_id": relay.id,
                "api_key": api_key,
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
async def discover_agents(namespace: str, db: Session = Depends(get_db)):
    """Discover all agents and relays in a namespace."""
    registrations = db.query(AgentRegistration).filter(
        AgentRegistration.namespace == namespace,
    ).all()

    return {
        "namespace": namespace,
        "agents": [
            {
                "agent_name": r.agent_name,
                "device_id": r.device_id,
                "description": r.description,
                "capabilities": r.capabilities,
                "relay_id": r.relay_id,
                "status": r.status,
                "last_heartbeat": r.last_heartbeat.isoformat() if r.last_heartbeat else None,
            }
            for r in registrations
        ],
        "relay_id": (
            registrations[0].relay_id
            if registrations and registrations[0].relay_id
            else None
        ),
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
    return {
        "relay_id": relay.id,
        "agent_names": relay.agent_names,
        "current_turn": relay.agent_names[relay.current_turn],
        "join_code": relay.join_code,
    }


@router.post("/relays/join/{join_code}")
async def join_by_code(
    join_code: str,
    agent_name: str,
    db: Session = Depends(get_db),
):
    """Join a relay using a short join code. Returns relay info and API key.

    The join code acts as authorization -- knowing the code grants access.
    """
    relay = db.query(Relay).filter(Relay.join_code == join_code.upper()).first()
    if not relay:
        raise HTTPException(status_code=404, detail="Invalid join code")

    # Add agent to relay if not already present
    if agent_name not in relay.agent_names:
        relay.agent_names = relay.agent_names + [agent_name]
        relay.agent_count = len(relay.agent_names)
        db.commit()

    return {
        "relay_id": relay.id,
        "join_code": relay.join_code,
        "agent_names": relay.agent_names,
        "current_turn": relay.agent_names[relay.current_turn],
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
