"""
Database models for Agent Relay
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Index, Integer, String, Text, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Relay(Base):
    """A relay manages turn-based communication between agents"""
    __tablename__ = "relays"

    id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    current_turn = Column(Integer, default=0)  # Index of agent whose turn it is
    agent_count = Column(Integer, default=2)
    agent_names = Column(JSON)  # List of agent names
    is_public = Column(Boolean, default=False)  # Privacy control
    owner_id = Column(String, nullable=True)  # Owner identifier for access control
    api_key_hash = Column(String, nullable=True)  # SHA-256 hash of API key
    turn_timeout = Column(Integer, nullable=True)  # Seconds per turn, None = no timeout
    turn_started_at = Column(DateTime, nullable=True)  # When the current turn began

    # Relationships
    messages = relationship("Message", back_populates="relay", cascade="all, delete-orphan")
    webhooks = relationship("Webhook", back_populates="relay", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Relay {self.id}>"


class Message(Base):
    """A message sent by an agent in a relay"""
    __tablename__ = "messages"
    __table_args__ = (
        Index('ix_messages_relay_created', 'relay_id', 'created_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    relay_id = Column(String, ForeignKey("relays.id"), nullable=False)
    agent_index = Column(Integer, nullable=False)  # 0 or 1 (or more for multi-agent)
    agent_name = Column(String, nullable=False)
    content = Column(Text, nullable=True)  # Plain text message
    data = Column(JSON, nullable=True)  # Structured data
    type = Column(String, default="text")  # 'text' or 'structured'
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    relay = relationship("Relay", back_populates="messages")

    def __repr__(self):
        return f"<Message {self.id} from {self.agent_name}>"


class Webhook(Base):
    """Webhook registration for receiving real-time updates"""
    __tablename__ = "webhooks"
    __table_args__ = (
        Index('ix_webhooks_relay_agent', 'relay_id', 'agent_index'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    relay_id = Column(String, ForeignKey("relays.id"), nullable=False)
    agent_index = Column(Integer, nullable=False)  # Which agent this webhook belongs to
    agent_name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    relay = relationship("Relay", back_populates="webhooks")
    deliveries = relationship("WebhookDelivery", back_populates="webhook", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Webhook {self.id} for {self.agent_name}>"


class WebhookDelivery(Base):
    """Log of webhook delivery attempts"""
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    status = Column(String, nullable=False)  # 'success' or 'failed'
    attempts = Column(Integer, default=1)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    webhook = relationship("Webhook", back_populates="deliveries")

    def __repr__(self):
        return f"<WebhookDelivery {self.id} status={self.status}>"
