"""
Message repository - Database operations for messages
"""
from typing import List, Optional
from sqlalchemy.orm import Session

from ..models import Message


class MessageRepository:
    """Repository for message database operations"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_by_relay_id(
        self,
        relay_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Message]:
        """Get messages for a relay with pagination"""
        return (
            self.db.query(Message)
            .filter(Message.relay_id == relay_id)
            .order_by(Message.created_at.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
    
    def count_by_relay_id(self, relay_id: str) -> int:
        """Count messages for a relay"""
        return (
            self.db.query(Message)
            .filter(Message.relay_id == relay_id)
            .count()
        )
    
    def get_last_message(self, relay_id: str) -> Optional[Message]:
        """Get the most recent message for a relay"""
        return (
            self.db.query(Message)
            .filter(Message.relay_id == relay_id)
            .order_by(Message.created_at.desc())
            .first()
        )
    
    def create(self, message: Message) -> Message:
        """Create a new message"""
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message
