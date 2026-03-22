"""
Authentication dependencies for FastAPI endpoints
"""
import hashlib
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .database import get_db
from .models import Relay
from .repositories import RelayRepository


async def get_api_key(
    authorization: str = Header(None),
    x_api_key: str = Header(None, alias="X-API-Key"),
    x_join_code: str = Header(None, alias="X-Join-Code"),
) -> dict:
    """Extract API key or join code from headers."""
    api_key = None
    if authorization and authorization.startswith("Bearer "):
        api_key = authorization[7:]
    elif x_api_key:
        api_key = x_api_key
    return {"api_key": api_key, "join_code": x_join_code}


async def require_relay_auth(
    relay_id: str,
    auth: dict = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Relay:
    """Verify API key or join code for relay write operations."""
    repo = RelayRepository(db)
    relay = repo.get_by_id(relay_id)
    if not relay:
        raise HTTPException(status_code=404, detail=f"Relay {relay_id} not found")

    # Legacy relays without api_key_hash allow access without a key
    if relay.api_key_hash is None:
        return relay

    api_key = auth.get("api_key")
    join_code = auth.get("join_code")

    # If join code matches, allow access (knowing the code = authorized)
    if join_code and relay.join_code and join_code.upper() == relay.join_code.upper():
        return relay

    # Otherwise require API key
    if api_key is None:
        raise HTTPException(status_code=401, detail="API key required. Pass via Authorization header or X-Join-Code header.")

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    if key_hash != relay.api_key_hash:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return relay
