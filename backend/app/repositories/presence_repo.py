"""
Repository for agent presence/heartbeat operations
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models import AgentPresence


class PresenceRepository:
    """Database operations for agent presence tracking"""

    def __init__(self, db: Session):
        self.db = db

    def upsert(self, relay_id: str, agent_name: str, status: str = "active") -> AgentPresence:
        """Create or update a presence record for an agent in a relay."""
        presence = (
            self.db.query(AgentPresence)
            .filter(
                AgentPresence.relay_id == relay_id,
                AgentPresence.agent_name == agent_name,
            )
            .first()
        )
        if presence:
            presence.last_seen = datetime.now(timezone.utc)
            presence.status = status
        else:
            presence = AgentPresence(
                relay_id=relay_id,
                agent_name=agent_name,
                last_seen=datetime.now(timezone.utc),
                status=status,
            )
            self.db.add(presence)
        self.db.commit()
        self.db.refresh(presence)
        return presence

    def get_for_relay(self, relay_id: str) -> list[AgentPresence]:
        """Get all presence records for a relay."""
        return (
            self.db.query(AgentPresence)
            .filter(AgentPresence.relay_id == relay_id)
            .all()
        )

    def get_agent_presence(self, relay_id: str, agent_name: str) -> Optional[AgentPresence]:
        """Get presence record for a specific agent in a relay."""
        return (
            self.db.query(AgentPresence)
            .filter(
                AgentPresence.relay_id == relay_id,
                AgentPresence.agent_name == agent_name,
            )
            .first()
        )
