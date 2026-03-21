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
) -> Optional[str]:
    """Extract API key from Authorization Bearer header or X-API-Key header."""
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return x_api_key


async def require_relay_auth(
    relay_id: str,
    api_key: Optional[str] = Depends(get_api_key),
    db: Session = Depends(get_db),
) -> Relay:
    """Verify API key for relay write operations."""
    repo = RelayRepository(db)
    relay = repo.get_by_id(relay_id)
    if not relay:
        raise HTTPException(status_code=404, detail=f"Relay {relay_id} not found")

    # Legacy relays without api_key_hash allow access without a key
    if relay.api_key_hash is None:
        return relay

    if api_key is None:
        raise HTTPException(status_code=401, detail="API key required")

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    if key_hash != relay.api_key_hash:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return relay
