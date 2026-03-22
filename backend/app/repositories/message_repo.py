"""
Message repository - Database operations for messages
"""
from typing import Dict, List, Optional
from sqlalchemy import func
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
        offset: int = 0,
        message_type: str = None,
    ) -> List[Message]:
        """Get messages for a relay with pagination and optional message_type filter"""
        query = (
            self.db.query(Message)
            .filter(Message.relay_id == relay_id)
        )
        if message_type:
            query = query.filter(Message.message_type == message_type)
        return (
            query
            .order_by(Message.created_at.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count_by_relay_id(self, relay_id: str, message_type: str = None) -> int:
        """Count messages for a relay, optionally filtered by message_type"""
        query = (
            self.db.query(Message)
            .filter(Message.relay_id == relay_id)
        )
        if message_type:
            query = query.filter(Message.message_type == message_type)
        return query.count()

    def count_by_relay_ids(self, relay_ids: List[str]) -> Dict[str, int]:
        """Count messages for multiple relays in a single query using GROUP BY"""
        if not relay_ids:
            return {}
        results = (
            self.db.query(Message.relay_id, func.count(Message.id))
            .filter(Message.relay_id.in_(relay_ids))
            .group_by(Message.relay_id)
            .all()
        )
        return {relay_id: count for relay_id, count in results}
    
    def get_since_id(
        self,
        relay_id: str,
        since_id: int = 0,
        limit: int = 20,
    ) -> List[Message]:
        """Get messages with id > since_id, ordered ascending by id."""
        return (
            self.db.query(Message)
            .filter(Message.relay_id == relay_id, Message.id > since_id)
            .order_by(Message.id.asc())
            .limit(limit)
            .all()
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
