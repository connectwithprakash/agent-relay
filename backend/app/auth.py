"""Participant-bound bearer authentication."""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session
from .database import get_db
from .models import AgentToken
from .repositories import RelayRepository
from .security import digest

async def get_current_agent(relay_id: str, authorization: str = Header(None), db: Session = Depends(get_db)) -> dict:
    relay = RelayRepository(db).get_by_id(relay_id)
    if not relay:
        raise HTTPException(status_code=404, detail=f"Relay {relay_id} not found")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token required (use Bearer authentication)")
    token = db.query(AgentToken).filter(AgentToken.token_hash == digest(authorization[7:])).first()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid token")
    if token.relay_id != relay_id:
        raise HTTPException(status_code=403, detail="Token not valid for this relay")
    return {"relay_id": token.relay_id, "agent_name": token.agent_name, "is_creator": token.is_creator, "token": token, "relay": relay}

async def require_relay_auth(agent_info: dict = Depends(get_current_agent)):
    return agent_info["relay"]
