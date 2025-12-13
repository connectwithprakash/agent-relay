"""
Webhook repository - Database operations for webhooks
"""
from typing import List
from sqlalchemy.orm import Session

from ..models import Webhook


class WebhookRepository:
    """Repository for webhook database operations"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_by_relay_id(self, relay_id: str) -> List[Webhook]:
        """Get all webhooks for a relay"""
        return (
            self.db.query(Webhook)
            .filter(Webhook.relay_id == relay_id)
            .all()
        )
    
    def get_by_relay_and_agent(
        self,
        relay_id: str,
        agent_index: int
    ) -> List[Webhook]:
        """Get webhooks for a specific agent in a relay"""
        return (
            self.db.query(Webhook)
            .filter(
                Webhook.relay_id == relay_id,
                Webhook.agent_index == agent_index
            )
            .all()
        )
    
    def create(self, webhook: Webhook) -> Webhook:
        """Create a new webhook"""
        self.db.add(webhook)
        self.db.commit()
        self.db.refresh(webhook)
        return webhook
    
    def delete(self, webhook: Webhook) -> None:
        """Delete a webhook"""
        self.db.delete(webhook)
        self.db.commit()
