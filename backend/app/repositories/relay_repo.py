"""
Relay repository - Database operations for relays
"""
<<<<<<< HEAD
from typing import Optional, List
=======
from typing import List, Optional
>>>>>>> fix/performance
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

    def list_public(self, limit: int = 20, offset: int = 0) -> List[Relay]:
        """List public relays with pagination"""
        return (
            self.db.query(Relay)
            .filter(Relay.is_public == True)
            .order_by(Relay.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count_public(self) -> int:
        """Count public relays"""
<<<<<<< HEAD
        return self.db.query(Relay).filter(Relay.is_public == True).count()
=======
        return (
            self.db.query(Relay)
            .filter(Relay.is_public == True)
            .count()
        )
>>>>>>> fix/performance
