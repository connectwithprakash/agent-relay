"""
Agent registry endpoints for cross-device discovery
"""
import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AgentRegistration, Relay

router = APIRouter()


@router.post("/agents/register")
async def register_agent(
    namespace: str,
    agent_name: str,
    device_id: str = None,
    db: Session = Depends(get_db),
):
    """Register an agent in a namespace for cross-device discovery.

    When two or more agents register with the same namespace, a relay is
    automatically created and all waiting agents are joined to it.
    """
    if not device_id:
        device_id = secrets.token_urlsafe(8)

    # Check if this agent+device is already registered in this namespace
    existing_reg = db.query(AgentRegistration).filter(
        AgentRegistration.namespace == namespace,
        AgentRegistration.agent_name == agent_name,
        AgentRegistration.device_id == device_id,
    ).first()

    if existing_reg and existing_reg.relay_id:
        # Already registered and has a relay
        relay = db.query(Relay).filter(Relay.id == existing_reg.relay_id).first()
        existing_reg.last_heartbeat = datetime.now(timezone.utc)
        existing_reg.status = "ready"
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
            db.commit()
        else:
            reg = AgentRegistration(
                namespace=namespace,
                agent_name=agent_name,
                device_id=device_id,
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

            relay = Relay(
                id=f"relay-{secrets.token_urlsafe(8)}",
                agent_names=agent_names,
                agent_count=len(agent_names),
                current_turn=0,
                is_public=True,
                api_key_hash=api_key_hash,
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
