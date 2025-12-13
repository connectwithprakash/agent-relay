"""
Relay repository - Database operations for relays
"""
from typing import Optional
from sqlalchemy.orm import Session

from ..models import Relay


class RelayRepository:
    """Repository for relay database operations"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_by_id(self, relay_id: str) -> Optional[Relay]:
        """Get relay by ID"""
        return self.db.query(Relay).filter(Relay.id == relay_id).first()
    
    def create(self, relay: Relay) -> Relay:
        """Create a new relay"""
        self.db.add(relay)
        self.db.commit()
        self.db.refresh(relay)
        return relay
    
    def update(self, relay: Relay) -> Relay:
        """Update an existing relay"""
        self.db.commit()
        self.db.refresh(relay)
        return relay
    
    def delete(self, relay: Relay) -> None:
        """Delete a relay"""
        self.db.delete(relay)
        self.db.commit()
