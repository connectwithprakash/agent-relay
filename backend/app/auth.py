"""
Authentication dependencies for FastAPI endpoints.

Token-based auth: agents receive a token on relay creation or join.
The token encodes relay_id + agent_name + is_creator.
"""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import AgentToken, Relay
from .repositories import RelayRepository


async def get_current_agent(
    relay_id: str,
    authorization: str = Header(None),
    x_join_code: str = Header(None, alias="X-Join-Code"),
    db: Session = Depends(get_db),
) -> dict:
    """Extract and verify agent token. Returns {relay_id, agent_name, is_creator, token, relay}.

    Falls back to join code header for backward compatibility.
    """
    repo = RelayRepository(db)
    relay = repo.get_by_id(relay_id)
    if not relay:
        raise HTTPException(status_code=404, detail=f"Relay {relay_id} not found")

    # Try Bearer token first
    if authorization and authorization.startswith("Bearer "):
        token_str = authorization[7:]
        agent_token = db.query(AgentToken).filter(AgentToken.token == token_str).first()
        if not agent_token:
            raise HTTPException(status_code=401, detail="Invalid token. Join the relay again.")
        if agent_token.relay_id != relay_id:
            raise HTTPException(status_code=403, detail="Token not valid for this relay")
        return {
            "relay_id": agent_token.relay_id,
            "agent_name": agent_token.agent_name,
            "is_creator": agent_token.is_creator,
            "token": agent_token,
            "relay": relay,
        }

    # Fallback: join code header
    if x_join_code and relay.join_code and x_join_code.upper() == relay.join_code.upper():
        return {
            "relay_id": relay.id,
            "agent_name": None,  # Unknown from join code alone
            "is_creator": False,
            "token": None,
            "relay": relay,
        }

    raise HTTPException(
        status_code=401,
        detail="Token required. Join the relay first.",
    )


async def require_relay_auth(
    agent_info: dict = Depends(get_current_agent),
) -> Relay:
    """Dependency that returns the authenticated Relay object.

    Compatible with existing route signatures that expect a Relay from auth.
    """
    return agent_info["relay"]
